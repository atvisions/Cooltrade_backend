"""
Technical Indicators Data API Views - Simplified Synchronous Version
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from datetime import timedelta
import time

from .services.technical_analysis import TechnicalAnalysisService
from .services.market_data_service import MarketDataService
from .models import Token, AnalysisReport, TechnicalAnalysis
from .utils import logger


class TechnicalIndicatorsDataAPIView(APIView):
    """技术指标数据API视图

    处理 /api/crypto/technical-indicators-data/<str:symbol>/ 接口的请求
    返回指定代币的技术指标数据
    """
    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.ta_service = None
        self.market_service = None

    def get(self, request, symbol: str):
        """Synchronous processing of GET requests"""
        try:
            # Ensure services are initialized
            if self.ta_service is None:
                self.ta_service = TechnicalAnalysisService()
            if self.market_service is None:
                self.market_service = MarketDataService()

            # Get technical indicators
            try:
                technical_data = self.ta_service.get_all_indicators(symbol)
                if technical_data['status'] == 'error':
                    return Response(technical_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

                indicators = technical_data['data']['indicators']

            except Exception as e:
                logger.error(f"Failed to get technical indicator data: {str(e)}")
                return Response({
                    'status': 'error',
                    'message': str(e)
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # Clean symbol format
            clean_symbol = symbol.upper().replace('USDT', '').replace('-PERP', '').replace('_PERP', '').replace('PERP', '')

            # Simple synchronous token retrieval
            token = Token.objects.filter(symbol=symbol.upper()).first()
            if not token:
                token = Token.objects.filter(symbol=clean_symbol).first()

            if not token:
                # Log for debugging
                logger.error(f"Token record not found, attempted symbols: {symbol.upper()} and {clean_symbol}")

                # Check what token records exist in database
                all_tokens = list(Token.objects.all())
                token_symbols = [t.symbol for t in all_tokens]
                logger.info(f"Token records in database: {token_symbols}")

                # If no token records in database, try to create one
                if not all_tokens:
                    logger.info(f"No token records in database, trying to create one: {symbol.upper()}")

                    # Create default chain
                    from .models import Chain

                    chain, _ = Chain.objects.get_or_create(
                        chain=symbol.upper(),
                        defaults={
                            'is_active': True,
                            'is_testnet': False
                        }
                    )

                    # Create token record
                    token, _ = Token.objects.get_or_create(
                        symbol=symbol.upper(),
                        defaults={
                            'chain': chain,
                            'name': symbol.upper()
                        }
                    )

                    logger.info(f"Successfully created token record: {token.symbol}")
                else:
                    return Response({
                        'status': 'error',
                        'message': f"Token {symbol} record not found"
                    }, status=status.HTTP_404_NOT_FOUND)

            # 直接使用当前价格，而不依赖于分析报告
            # 从技术指标数据中获取当前价格
            current_price = technical_data.get('data', {}).get('current_price', 0)

            # If no current price in technical indicator data, try to get from Gate API
            if not current_price:
                try:
                    # Ensure ta_service is initialized
                    if self.ta_service is None:
                        self.ta_service = TechnicalAnalysisService()

                    # Get real-time price
                    current_price = self.ta_service.gate_api.get_realtime_price(symbol)

                    # If still unable to get price, use default value
                    if not current_price:
                        current_price = 0
                except Exception as e:
                    logger.error(f"Failed to get real-time price: {str(e)}")
                    current_price = 0

            # 使用当前价格
            price = current_price

            # 格式化指标数据
            formatted_indicators = {
                'rsi': float(indicators.get('RSI', 0)),
                'macd_line': float(indicators.get('MACD', {}).get('line', 0)),
                'macd_signal': float(indicators.get('MACD', {}).get('signal', 0)),
                'macd_histogram': float(indicators.get('MACD', {}).get('histogram', 0)),
                'bollinger_upper': float(indicators.get('BollingerBands', {}).get('upper', 0)),
                'bollinger_middle': float(indicators.get('BollingerBands', {}).get('middle', 0)),
                'bollinger_lower': float(indicators.get('BollingerBands', {}).get('lower', 0)),
                'bias': float(indicators.get('BIAS', 0)),
                'psy': float(indicators.get('PSY', 0)),
                'dmi_plus': float(indicators.get('DMI', {}).get('plus_di', 0)),
                'dmi_minus': float(indicators.get('DMI', {}).get('minus_di', 0)),
                'dmi_adx': float(indicators.get('DMI', {}).get('adx', 0)),
                'vwap': float(indicators.get('VWAP', 0)),
                'funding_rate': float(indicators.get('FundingRate', 0)) * 100,  # 转换为百分比形式，例如 0.0001 -> 0.01%
                'exchange_netflow': float(indicators.get('ExchangeNetflow', 0)),
                'nupl': float(indicators.get('NUPL', 0)),
                'mayer_multiple': float(indicators.get('MayerMultiple', 0))
            }

            # Save technical indicator data to database
            try:
                # Use Django ORM transaction management
                from django.db import transaction

                # Calculate 12-hour segment start point
                now = timezone.now()
                period_hour = (now.hour // 12) * 12
                period_start = now.replace(minute=0, second=0, microsecond=0, hour=period_hour)

                # Use transaction operation
                with transaction.atomic():
                    obj, created = TechnicalAnalysis.objects.get_or_create(
                        asset=token,
                        period_start=period_start,
                        defaults={
                            'timestamp': now,
                            'rsi': formatted_indicators['rsi'],
                            'macd_line': formatted_indicators['macd_line'],
                            'macd_signal': formatted_indicators['macd_signal'],
                            'macd_histogram': formatted_indicators['macd_histogram'],
                            'bollinger_upper': formatted_indicators['bollinger_upper'],
                            'bollinger_middle': formatted_indicators['bollinger_middle'],
                            'bollinger_lower': formatted_indicators['bollinger_lower'],
                            'bias': formatted_indicators['bias'],
                            'psy': formatted_indicators['psy'],
                            'dmi_plus': formatted_indicators['dmi_plus'],
                            'dmi_minus': formatted_indicators['dmi_minus'],
                            'dmi_adx': formatted_indicators['dmi_adx'],
                            'vwap': formatted_indicators['vwap'],
                            'funding_rate': formatted_indicators['funding_rate'],
                            'exchange_netflow': formatted_indicators['exchange_netflow'],
                            'nupl': formatted_indicators['nupl'],
                            'mayer_multiple': formatted_indicators['mayer_multiple']
                        }
                    )
                    if not created:
                        logger.info(f"Technical analysis record already exists within 12 hours, ID: {obj.id}, not creating new one")

                logger.info(f"Successfully saved technical indicator data: {symbol}, ID: {obj.id}")
            except Exception as e:
                logger.error(f"Failed to save technical indicator data: {str(e)}")
                # Even if saving fails, still return data, don't affect API response

            return Response({
                'status': 'success',
                'data': {
                    'symbol': symbol,
                    'price': float(price),
                    'indicators': formatted_indicators
                }
            })

        except Exception as e:
            logger.error(f"Failed to get technical indicator data: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)