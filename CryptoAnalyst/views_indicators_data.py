"""
技术指标数据API视图
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
import asyncio
from asgiref.sync import sync_to_async
from django.utils import timezone

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

            # 首先尝试使用完整的 symbol 查找代币记录
            token_qs = await sync_to_async(Token.objects.filter)(symbol=symbol.upper())
            token = await sync_to_async(token_qs.first)()

            # 如果找不到，再尝试使用清理后的 symbol 查找
            if not token:
                token_qs = await sync_to_async(Token.objects.filter)(symbol=clean_symbol)
                token = await sync_to_async(token_qs.first)()

            if not token:
                # 记录日志，帮助调试
                logger.error(f"未找到代币记录，尝试查找的符号: {symbol.upper()} 和 {clean_symbol}")

                # 查看数据库中有哪些代币记录
                all_tokens = await sync_to_async(list)(Token.objects.all())
                token_symbols = [t.symbol for t in all_tokens]
                logger.info(f"数据库中的代币记录: {token_symbols}")

                # 如果数据库中没有代币记录，尝试创建一个
                if not all_tokens:
                    logger.info(f"数据库中没有代币记录，尝试创建一个: {symbol.upper()}")

                    # 创建默认链
                    from .models import Chain
                    chain_qs = await sync_to_async(Chain.objects.get_or_create)(
                        chain=symbol.upper(),
                        defaults={
                            'is_active': True,
                            'is_testnet': False
                        }
                    )
                    chain = chain_qs[0]

                    # 创建代币记录
                    token_qs = await sync_to_async(Token.objects.get_or_create)(
                        symbol=symbol.upper(),
                        defaults={
                            'chain': chain,
                            'name': symbol.upper()
                        }
                    )
                    token = token_qs[0]

                    logger.info(f"成功创建代币记录: {token.symbol}")
                else:
                    return Response({
                        'status': 'error',
                        'message': f"未找到代币 {symbol} 的记录"
                    }, status=status.HTTP_404_NOT_FOUND)

            # 直接使用当前价格，而不依赖于分析报告
            # 从技术指标数据中获取当前价格
            current_price = technical_data.get('data', {}).get('current_price', 0)

            # 如果技术指标数据中没有当前价格，尝试从 Gate API 获取
            if not current_price:
                try:
                    # 确保 ta_service 已初始化
                    if self.ta_service is None:
                        self.ta_service = TechnicalAnalysisService()

                    # 获取实时价格
                    current_price = await sync_to_async(self.ta_service.gate_api.get_realtime_price)(symbol)

                    # 如果仍然无法获取价格，使用默认值
                    if not current_price:
                        current_price = 0
                except Exception as e:
                    logger.error(f"获取实时价格失败: {str(e)}")
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

            # 保存技术指标数据到数据库
            try:
                # 定义一个同步函数来创建技术分析记录
                async def create_technical_analysis():
                    # 使用 Django ORM 的事务管理
                    from django.db import transaction

                    # 使用 sync_to_async 包装事务操作
                    @sync_to_async
                    def create_record():
                        with transaction.atomic():
                            # 创建技术分析记录
                            return TechnicalAnalysis.objects.create(
                                token=token,
                                timestamp=timezone.now(),
                                rsi=formatted_indicators['rsi'],
                                macd_line=formatted_indicators['macd_line'],
                                macd_signal=formatted_indicators['macd_signal'],
                                macd_histogram=formatted_indicators['macd_histogram'],
                                bollinger_upper=formatted_indicators['bollinger_upper'],
                                bollinger_middle=formatted_indicators['bollinger_middle'],
                                bollinger_lower=formatted_indicators['bollinger_lower'],
                                bias=formatted_indicators['bias'],
                                psy=formatted_indicators['psy'],
                                dmi_plus=formatted_indicators['dmi_plus'],
                                dmi_minus=formatted_indicators['dmi_minus'],
                                dmi_adx=formatted_indicators['dmi_adx'],
                                vwap=formatted_indicators['vwap'],
                                funding_rate=formatted_indicators['funding_rate'],
                                exchange_netflow=formatted_indicators['exchange_netflow'],
                                nupl=formatted_indicators['nupl'],
                                mayer_multiple=formatted_indicators['mayer_multiple']
                            )

                    # 调用包装后的函数
                    technical_analysis = await create_record()
                    return technical_analysis

                # 执行异步函数
                technical_analysis = await create_technical_analysis()
                logger.info(f"成功保存技术指标数据: {symbol}, ID: {technical_analysis.id}")
            except Exception as e:
                logger.error(f"保存技术指标数据失败: {str(e)}")
                # 即使保存失败，仍然返回数据，不影响 API 响应

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