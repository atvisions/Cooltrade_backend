from django.urls import path
from .views import TokenDataAPIView
from .views_report import CryptoReportAPIView
from .views_indicators_data import TechnicalIndicatorsDataAPIView
from .views_technical_indicators import TechnicalIndicatorsAPIView
from .views_search import AssetSearchAPIView, PopularAssetsAPIView
from .views_favorites import UserFavoritesAPIView, FavoriteStatusAPIView

urlpatterns = [
    # 技术指标数据
    path('technical-indicators-data/<str:symbol>/', TechnicalIndicatorsDataAPIView.as_view(), name='technical_indicators_data'),

    # 技术指标分析 - 支持加密货币和股票
    path('technical-indicators/<str:symbol>/', TechnicalIndicatorsAPIView.as_view(), name='technical_indicators'),

    # 分析报告API - 支持加密货币和股票
    path('get_report/<str:symbol>/', CryptoReportAPIView.as_view(), name='get_report'),

    # 代币数据
    path('token-data/<str:token_id>/', TokenDataAPIView.as_view(), name='token_data'),

    # 搜索功能
    path('search/', AssetSearchAPIView.as_view(), name='asset_search'),
    path('popular-assets/', PopularAssetsAPIView.as_view(), name='popular_assets'),

    # 收藏功能
    path('favorites/', UserFavoritesAPIView.as_view(), name='user_favorites'),
    path('favorites/status/<str:symbol>/', FavoriteStatusAPIView.as_view(), name='favorite_status'),
]