"""
User Favorites API Views
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
import logging
from .models import Asset, MarketType, Exchange, UserFavorite

logger = logging.getLogger(__name__)


class UserFavoritesAPIView(APIView):
    """User Favorites API View"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get user's favorite assets"""
        try:
            user = request.user
            favorites = UserFavorite.objects.filter(user=user).select_related('asset', 'asset__market_type', 'asset__exchange')
            
            results = []
            for favorite in favorites:
                asset = favorite.asset
                results.append({
                    'id': favorite.id,
                    'symbol': asset.symbol,
                    'name': asset.name,
                    'market_type': asset.market_type.name,
                    'exchange': asset.exchange.name if asset.exchange else None,
                    'sector': asset.sector,
                    'added_at': favorite.created_at.isoformat()
                })

            return Response({
                'status': 'success',
                'data': results
            })

        except Exception as e:
            logger.error(f"Get favorites error: {str(e)}")
            return Response({
                'status': 'error',
                'message': 'Failed to get favorites'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request):
        """Add asset to favorites"""
        try:
            user = request.user
            symbol = request.data.get('symbol')
            market_type_name = request.data.get('market_type', 'crypto')
            name = request.data.get('name', symbol)
            exchange_name = request.data.get('exchange')
            sector = request.data.get('sector')

            if not symbol:
                return Response({
                    'status': 'error',
                    'message': 'Symbol is required'
                }, status=status.HTTP_400_BAD_REQUEST)

            with transaction.atomic():
                # Get or create market type
                market_type, _ = MarketType.objects.get_or_create(
                    name=market_type_name,
                    defaults={'description': f'{market_type_name.title()} Market'}
                )

                # Get or create exchange if provided
                exchange = None
                if exchange_name:
                    exchange, _ = Exchange.objects.get_or_create(
                        name=exchange_name,
                        market_type=market_type,
                        defaults={'is_active': True}
                    )

                # Get or create asset
                asset, created = Asset.objects.get_or_create(
                    symbol=symbol,
                    market_type=market_type,
                    defaults={
                        'name': name,
                        'exchange': exchange,
                        'sector': sector,
                        'is_active': True
                    }
                )

                # Update asset info if it already exists but with different data
                if not created:
                    if asset.name != name and name != symbol:
                        asset.name = name
                    if exchange and asset.exchange != exchange:
                        asset.exchange = exchange
                    if sector and asset.sector != sector:
                        asset.sector = sector
                    asset.save()

                # Check if already in favorites
                favorite, created = UserFavorite.objects.get_or_create(
                    user=user,
                    asset=asset
                )

                if not created:
                    return Response({
                        'status': 'info',
                        'message': 'Asset already in favorites',
                        'data': {
                            'id': favorite.id,
                            'symbol': asset.symbol,
                            'name': asset.name,
                            'market_type': asset.market_type.name
                        }
                    })

                return Response({
                    'status': 'success',
                    'message': 'Asset added to favorites',
                    'data': {
                        'id': favorite.id,
                        'symbol': asset.symbol,
                        'name': asset.name,
                        'market_type': asset.market_type.name,
                        'added_at': favorite.created_at.isoformat()
                    }
                }, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"Add favorite error: {str(e)}")
            return Response({
                'status': 'error',
                'message': 'Failed to add favorite'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request):
        """Remove asset from favorites"""
        try:
            user = request.user
            # 兼容 DRF 不自动解析 DELETE body 的问题
            data = request.data
            if not data or 'symbol' not in data:
                import json
                try:
                    data = json.loads(request.body.decode('utf-8'))
                except Exception:
                    data = {}
            symbol = data.get('symbol')
            market_type_name = data.get('market_type', 'crypto')

            if not symbol:
                return Response({
                    'status': 'error',
                    'message': 'Symbol is required'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Find the favorite
            try:
                market_type = MarketType.objects.get(name=market_type_name)
                asset = Asset.objects.get(symbol=symbol, market_type=market_type)
                favorite = UserFavorite.objects.get(user=user, asset=asset)
                favorite.delete()

                return Response({
                    'status': 'success',
                    'message': 'Asset removed from favorites'
                })

            except (MarketType.DoesNotExist, Asset.DoesNotExist, UserFavorite.DoesNotExist):
                return Response({
                    'status': 'error',
                    'message': 'Favorite not found'
                }, status=status.HTTP_404_NOT_FOUND)

        except Exception as e:
            logger.error(f"Remove favorite error: {str(e)}")
            return Response({
                'status': 'error',
                'message': 'Failed to remove favorite'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class FavoriteStatusAPIView(APIView):
    """Check if asset is in user's favorites"""
    permission_classes = [IsAuthenticated]

    def get(self, request, symbol):
        """Check if asset is favorited by user"""
        try:
            user = request.user
            market_type_name = request.GET.get('market_type', 'crypto')

            try:
                market_type = MarketType.objects.get(name=market_type_name)
                asset = Asset.objects.get(symbol=symbol, market_type=market_type)
                is_favorite = UserFavorite.objects.filter(user=user, asset=asset).exists()

                return Response({
                    'status': 'success',
                    'data': {
                        'symbol': symbol,
                        'market_type': market_type_name,
                        'is_favorite': is_favorite
                    }
                })

            except (MarketType.DoesNotExist, Asset.DoesNotExist):
                return Response({
                    'status': 'success',
                    'data': {
                        'symbol': symbol,
                        'market_type': market_type_name,
                        'is_favorite': False
                    }
                })

        except Exception as e:
            logger.error(f"Check favorite status error: {str(e)}")
            return Response({
                'status': 'error',
                'message': 'Failed to check favorite status'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
