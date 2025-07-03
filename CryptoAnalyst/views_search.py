"""
Asset Search API Views
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q
import logging
import requests
from django.conf import settings
from .models import Asset, MarketType, Exchange

logger = logging.getLogger(__name__)


class AssetSearchAPIView(APIView):
    """Asset Search API View"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Search for assets by symbol or name"""
        try:
            query = request.GET.get('q', '').strip()
            market_type = request.GET.get('market_type', '').strip()
            limit = min(int(request.GET.get('limit', 20)), 50)  # Max 50 results

            if not query:
                return Response({
                    'status': 'error',
                    'message': 'Query parameter is required'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 优先使用外部API获取实时数据
            external_results = self._search_external_apis(query, market_type)
            if external_results:
                return Response({
                    'status': 'success',
                    'data': external_results,
                    'source': 'external'
                })

            # 如果外部API没有结果，再搜索数据库
            search_filters = Q(symbol__icontains=query) | Q(name__icontains=query)

            if market_type and market_type in ['crypto', 'stock']:
                search_filters &= Q(market_type__name=market_type)

            # Search in database
            assets = Asset.objects.filter(search_filters).select_related('market_type', 'exchange')[:limit]

            # Format results
            results = []
            for asset in assets:
                results.append({
                    'symbol': asset.symbol,
                    'name': asset.name,
                    'market_type': asset.market_type.name,
                    'exchange': asset.exchange.name if asset.exchange else None,
                    'sector': asset.sector,
                    'is_active': asset.is_active
                })

            return Response({
                'status': 'success',
                'data': results,
                'source': 'database'
            })

        except Exception as e:
            logger.error(f"Asset search error: {str(e)}")
            return Response({
                'status': 'error',
                'message': 'Search failed'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _search_external_apis(self, query, market_type=None):
        """Search external APIs for assets"""
        results = []
        
        # Search crypto if market_type is crypto or not specified
        if not market_type or market_type == 'crypto':
            crypto_results = self._search_crypto_api(query)
            results.extend(crypto_results)
        
        # Search stocks if market_type is stock or not specified
        if not market_type or market_type == 'stock':
            stock_results = self._search_stock_api(query)
            results.extend(stock_results)
        
        return results[:20]  # Limit to 20 results

    def _search_crypto_api(self, query):
        """Search crypto assets using Gate API"""
        try:
            # Use Gate API to search for crypto symbols
            url = "https://api.gateio.ws/api/v4/spot/currency_pairs"
            response = requests.get(url, timeout=5)

            if response.status_code == 200:
                pairs = response.json()
                results = []
                query_upper = query.upper()

                for pair in pairs:
                    symbol = pair.get('id', '')
                    base = pair.get('base', '')
                    quote = pair.get('quote', '')

                    # 只处理USDT交易对
                    if quote.upper() != 'USDT':
                        continue

                    # Check if query matches symbol or base currency
                    if (query_upper in symbol.upper() or
                        query_upper == base.upper() or
                        query_upper in base.upper()):

                        results.append({
                            'symbol': symbol,
                            'name': base,  # 只使用基础货币名称，避免重复
                            'market_type': 'crypto',
                            'exchange': 'Gate.io',
                            'sector': None,
                            'is_active': True
                        })

                        # 限制结果数量
                        if len(results) >= 10:
                            break

                return results

        except Exception as e:
            logger.error(f"Crypto API search error: {str(e)}")

        return []

    def _search_stock_api(self, query):
        """Search stock assets using Tiingo API"""
        try:
            tiingo_api_key = getattr(settings, 'TIINGO_API_KEY', None)
            if not tiingo_api_key:
                return []
            
            # Search for stock symbols using Tiingo
            url = f"https://api.tiingo.com/tiingo/utilities/search"
            params = {
                'query': query,
                'token': tiingo_api_key,
                'limit': 10
            }
            
            response = requests.get(url, params=params, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                results = []
                
                for item in data:
                    ticker = item.get('ticker', '')
                    name = item.get('name', '')
                    exchange = item.get('exchange', '')
                    asset_type = item.get('assetType', '')
                    
                    # Only include stocks and ETFs
                    if asset_type.lower() in ['stock', 'etf']:
                        results.append({
                            'symbol': ticker,
                            'name': name,
                            'market_type': 'stock',
                            'exchange': exchange,
                            'sector': None,  # Tiingo doesn't provide sector in search
                            'is_active': True
                        })
                
                return results
                
        except Exception as e:
            logger.error(f"Stock API search error: {str(e)}")
        
        return []


class PopularAssetsAPIView(APIView):
    """Popular Assets API View"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get popular assets by market type"""
        try:
            market_type = request.GET.get('market_type', 'crypto')
            
            if market_type == 'crypto':
                # Popular crypto assets
                popular_assets = [
                    {'symbol': 'BTCUSDT', 'name': 'Bitcoin', 'market_type': 'crypto'},
                    {'symbol': 'ETHUSDT', 'name': 'Ethereum', 'market_type': 'crypto'},
                    {'symbol': 'SOLUSDT', 'name': 'Solana', 'market_type': 'crypto'},
                    {'symbol': 'BNBUSDT', 'name': 'BNB', 'market_type': 'crypto'},
                    {'symbol': 'ADAUSDT', 'name': 'Cardano', 'market_type': 'crypto'},
                    {'symbol': 'XRPUSDT', 'name': 'XRP', 'market_type': 'crypto'},
                    {'symbol': 'DOGEUSDT', 'name': 'Dogecoin', 'market_type': 'crypto'},
                    {'symbol': 'AVAXUSDT', 'name': 'Avalanche', 'market_type': 'crypto'}
                ]
            else:  # stock
                # Popular stock assets
                popular_assets = [
                    {'symbol': 'AAPL', 'name': 'Apple Inc.', 'market_type': 'stock', 'sector': 'Technology'},
                    {'symbol': 'MSFT', 'name': 'Microsoft Corporation', 'market_type': 'stock', 'sector': 'Technology'},
                    {'symbol': 'GOOGL', 'name': 'Alphabet Inc.', 'market_type': 'stock', 'sector': 'Technology'},
                    {'symbol': 'AMZN', 'name': 'Amazon.com Inc.', 'market_type': 'stock', 'sector': 'Consumer Discretionary'},
                    {'symbol': 'TSLA', 'name': 'Tesla Inc.', 'market_type': 'stock', 'sector': 'Consumer Discretionary'},
                    {'symbol': 'META', 'name': 'Meta Platforms Inc.', 'market_type': 'stock', 'sector': 'Technology'},
                    {'symbol': 'NVDA', 'name': 'NVIDIA Corporation', 'market_type': 'stock', 'sector': 'Technology'},
                    {'symbol': 'NFLX', 'name': 'Netflix Inc.', 'market_type': 'stock', 'sector': 'Communication Services'}
                ]

            return Response({
                'status': 'success',
                'data': popular_assets
            })

        except Exception as e:
            logger.error(f"Popular assets error: {str(e)}")
            return Response({
                'status': 'error',
                'message': 'Failed to get popular assets'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
