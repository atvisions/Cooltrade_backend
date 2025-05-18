from django.urls import path
from .views import TokenDataAPIView
from .views_report import CryptoReportAPIView
from .views_indicators_data import TechnicalIndicatorsDataAPIView
from .views_technical_indicators import TechnicalIndicatorsAPIView

urlpatterns = [
    # 技术指标数据
    path('technical-indicators-data/<str:symbol>/', TechnicalIndicatorsDataAPIView.as_view(), name='technical_indicators_data'),

    # 技术指标分析
    path('technical-indicators/<str:symbol>/', TechnicalIndicatorsAPIView.as_view(), name='technical_indicators'),

    # 分析报告API
    path('get_report/<str:symbol>/', CryptoReportAPIView.as_view(), name='get_report'),

    # 代币数据
    path('token-data/<str:token_id>/', TokenDataAPIView.as_view(), name='token_data'),
]