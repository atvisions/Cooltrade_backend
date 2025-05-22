"""
技术指标API视图
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
import asyncio
from asgiref.sync import sync_to_async
from django.utils import timezone
import time
import logging
import datetime

from .services.technical_analysis import TechnicalAnalysisService
from .services.market_data_service import MarketDataService
from .models import Token, Chain, AnalysisReport, TechnicalAnalysis

# 配置日志
logger = logging.getLogger(__name__)

class TechnicalIndicatorsAPIView(APIView):
    """技术指标API视图

    处理 /api/crypto/technical-indicators/<str:symbol>/ 接口的请求
    返回指定代币的技术指标分析报告
    """
    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.ta_service = None
        self.market_service = None

    def get(self, request, symbol: str):
        """同步入口点，调用异步处理"""
        return asyncio.run(self.async_get(request, symbol))

    async def async_get(self, request, symbol: str):
        """异步处理 GET 请求"""
        try:
            # 确保服务已初始化
            if self.ta_service is None:
                self.ta_service = TechnicalAnalysisService()
            if self.market_service is None:
                self.market_service = MarketDataService()

            # 获取语言参数
            language = request.GET.get('language', 'zh-CN')
            logger.info(f"请求的语言: {language}")

            # 支持的语言列表
            supported_languages = ['zh-CN', 'en-US', 'ja-JP', 'ko-KR']

            # 验证语言支持
            if language not in supported_languages:
                logger.warning(f"不支持的语言: {language}，使用默认语言 zh-CN")
                language = 'zh-CN'

            # 统一 symbol 格式，去除常见后缀
            clean_symbol = symbol.upper().replace('USDT', '').replace('-PERP', '').replace('_PERP', '').replace('PERP', '')

            # 处理查询
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

                return Response({
                    'status': 'not_found',
                    'message': f"未找到代币 {symbol} 的分析数据",
                    'needs_refresh': True
                }, status=status.HTTP_404_NOT_FOUND)

            # 获取指定语言的最新分析报告
            reports_qs = await sync_to_async(AnalysisReport.objects.filter)(token=token, language=language)
            reports_qs = await sync_to_async(reports_qs.order_by)('-timestamp')
            latest_report = await sync_to_async(reports_qs.first)()

            # 定义报告新鲜度阈值 (12小时)
            freshness_threshold = timezone.now() - datetime.timedelta(hours=12)

            # 如果找不到指定语言的报告，直接返回错误
            if not latest_report or latest_report.timestamp < freshness_threshold:
                # 记录日志
                if not latest_report:
                    logger.warning(f"未找到代币 {symbol} 的 {language} 语言分析报告，返回 404。")
                else:
                    logger.warning(f"代币 {symbol} 的 {language} 语言最新报告 ({latest_report.timestamp}) 已超过 12 小时新鲜度阈值 ({freshness_threshold})，返回 404。")

                return Response({
                    'status': 'not_found',
                    'message': f"未找到代币 {symbol} 的最新 {language} 语言分析数据或数据已过期",
                    'needs_refresh': True
                }, status=status.HTTP_404_NOT_FOUND)

            # 获取相关的技术分析数据
            ta_qs = await sync_to_async(TechnicalAnalysis.objects.filter)(token=token)
            ta_qs = await sync_to_async(ta_qs.order_by)('-timestamp')
            technical_analysis = await sync_to_async(ta_qs.first)()

            if not technical_analysis:
                return Response({
                    'status': 'not_found',
                    'message': f"未找到代币 {symbol} 的技术分析数据",
                    'needs_refresh': True
                }, status=status.HTTP_404_NOT_FOUND)

            # 构建响应数据
            response_data = {
                'status': 'success',
                'data': {
                    'symbol': symbol,
                    'price': float(latest_report.snapshot_price) if latest_report.snapshot_price is not None else None,
                    'trend_analysis': {
                        'probabilities': {
                            'up': latest_report.trend_up_probability,
                            'sideways': latest_report.trend_sideways_probability,
                            'down': latest_report.trend_down_probability
                        },
                        'summary': latest_report.trend_summary
                    },
                    'indicators_analysis': {
                        'RSI': {
                            'value': float(technical_analysis.rsi) if technical_analysis.rsi is not None else None,
                            'analysis': latest_report.rsi_analysis,
                            'support_trend': latest_report.rsi_support_trend
                        },
                        'MACD': {
                            'value': {
                                'line': float(technical_analysis.macd_line) if technical_analysis.macd_line is not None else None,
                                'signal': float(technical_analysis.macd_signal) if technical_analysis.macd_signal is not None else None,
                                'histogram': float(technical_analysis.macd_histogram) if technical_analysis.macd_histogram is not None else None
                            },
                            'analysis': latest_report.macd_analysis,
                            'support_trend': latest_report.macd_support_trend
                        },
                        'BollingerBands': {
                            'value': {
                                'upper': float(technical_analysis.bollinger_upper) if technical_analysis.bollinger_upper is not None else None,
                                'middle': float(technical_analysis.bollinger_middle) if technical_analysis.bollinger_middle is not None else None,
                                'lower': float(technical_analysis.bollinger_lower) if technical_analysis.bollinger_lower is not None else None
                            },
                            'analysis': latest_report.bollinger_analysis,
                            'support_trend': latest_report.bollinger_support_trend
                        },
                        'BIAS': {
                            'value': float(technical_analysis.bias) if technical_analysis.bias is not None else None,
                            'analysis': latest_report.bias_analysis,
                            'support_trend': latest_report.bias_support_trend
                        },
                        'PSY': {
                            'value': float(technical_analysis.psy) if technical_analysis.psy is not None else None,
                            'analysis': latest_report.psy_analysis,
                            'support_trend': latest_report.psy_support_trend
                        },
                        'DMI': {
                            'value': {
                                'plus_di': float(technical_analysis.dmi_plus) if technical_analysis.dmi_plus is not None else None,
                                'minus_di': float(technical_analysis.dmi_minus) if technical_analysis.dmi_minus is not None else None,
                                'adx': float(technical_analysis.dmi_adx) if technical_analysis.dmi_adx is not None else None
                            },
                            'analysis': latest_report.dmi_analysis,
                            'support_trend': latest_report.dmi_support_trend
                        },
                        'VWAP': {
                            'value': float(technical_analysis.vwap) if technical_analysis.vwap is not None else None,
                            'analysis': latest_report.vwap_analysis,
                            'support_trend': latest_report.vwap_support_trend
                        },
                        'FundingRate': {
                            'value': float(technical_analysis.funding_rate) if technical_analysis.funding_rate is not None else None,
                            'analysis': latest_report.funding_rate_analysis,
                            'support_trend': latest_report.funding_rate_support_trend
                        },
                        'ExchangeNetflow': {
                            'value': float(technical_analysis.exchange_netflow) if technical_analysis.exchange_netflow is not None else None,
                            'analysis': latest_report.exchange_netflow_analysis,
                            'support_trend': latest_report.exchange_netflow_support_trend
                        },
                        'NUPL': {
                            'value': float(technical_analysis.nupl) if technical_analysis.nupl is not None else None,
                            'analysis': latest_report.nupl_analysis,
                            'support_trend': latest_report.nupl_support_trend
                        },
                        'MayerMultiple': {
                            'value': float(technical_analysis.mayer_multiple) if technical_analysis.mayer_multiple is not None else None,
                            'analysis': latest_report.mayer_multiple_analysis,
                            'support_trend': latest_report.mayer_multiple_support_trend
                        }
                    },
                    'trading_advice': {
                        'action': latest_report.trading_action,
                        'reason': latest_report.trading_reason,
                        'entry_price': float(latest_report.entry_price) if latest_report.entry_price is not None else None,
                        'stop_loss': float(latest_report.stop_loss) if latest_report.stop_loss is not None else None,
                        'take_profit': float(latest_report.take_profit) if latest_report.take_profit is not None else None
                    },
                    'risk_assessment': {
                        'level': latest_report.risk_level,
                        'score': int(latest_report.risk_score) if latest_report.risk_score is not None else None,
                        'details': latest_report.risk_details
                    },
                    'current_price': float(latest_report.snapshot_price) if latest_report.snapshot_price is not None else None,
                    'snapshot_price': float(latest_report.snapshot_price) if latest_report.snapshot_price is not None else None,
                    'last_update_time': latest_report.timestamp.isoformat()
                }
            }

            return Response(response_data)

        except Exception as e:
            logger.error(f"处理请求时发生错误: {str(e)}")
            return Response({
                'status': 'error',
                'message': f"处理请求失败: {str(e)}",
                'needs_refresh': True
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
