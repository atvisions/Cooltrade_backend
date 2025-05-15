"""
技术指标数据API视图
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
import asyncio
from asgiref.sync import sync_to_async

from .services.technical_analysis import TechnicalAnalysisService
from .services.market_data_service import MarketDataService
from .models import Token, AnalysisReport
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

    async def async_get(self, request, symbol: str):
        """异步处理 GET 请求"""
        try:
            # 确保服务已初始化
            if self.ta_service is None:
                self.ta_service = TechnicalAnalysisService()
            if self.market_service is None:
                self.market_service = MarketDataService()

            # 获取技术指标
            technical_data = await sync_to_async(self.ta_service.get_all_indicators)(symbol)
            if technical_data['status'] == 'error':
                return Response(technical_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            indicators = technical_data['data']['indicators']

            # 清理符号格式
            clean_symbol = symbol.upper().replace('USDT', '').replace('-PERP', '').replace('_PERP', '').replace('PERP', '')

            # 查找代币记录
            token_qs = await sync_to_async(Token.objects.filter)(symbol=clean_symbol)
            token = await sync_to_async(token_qs.first)()

            if not token:
                return Response({
                    'status': 'error',
                    'message': f"未找到代币 {clean_symbol} 的记录"
                }, status=status.HTTP_404_NOT_FOUND)

            # 获取最新的分析报告
            reports_qs = await sync_to_async(AnalysisReport.objects.filter)(token=token)
            reports_qs = await sync_to_async(reports_qs.order_by)('-timestamp')
            latest_report = await sync_to_async(reports_qs.first)()

            if not latest_report:
                return Response({
                    'status': 'error',
                    'message': f"未找到代币 {clean_symbol} 的分析报告"
                }, status=status.HTTP_404_NOT_FOUND)

            # 使用报告中的价格
            price = latest_report.snapshot_price

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

            return Response({
                'status': 'success',
                'data': {
                    'symbol': symbol,
                    'price': float(price),
                    'indicators': formatted_indicators
                }
            })

        except Exception as e:
            logger.error(f"获取技术指标数据失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def get(self, request, symbol: str):
        """同步入口点，调用异步处理"""
        return asyncio.run(self.async_get(request, symbol))
