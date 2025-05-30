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
import traceback
from django.db import connection
from django.db.utils import OperationalError

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
            try:
                max_retries = 3
                retry_delay = 1  # 秒

                for attempt in range(max_retries):
                    try:
                        # 首先尝试使用完整的 symbol 查找代币记录
                        token_qs = await sync_to_async(Token.objects.filter)(symbol=symbol.upper())
                        token = await sync_to_async(token_qs.first)()

                        # 如果找不到，再尝试使用清理后的 symbol 查找
                        if not token:
                            token_qs = await sync_to_async(Token.objects.filter)(symbol=clean_symbol)
                            token = await sync_to_async(token_qs.first)()

                        if token:
                            break
                    except OperationalError as e:
                        if attempt < max_retries - 1:
                            logger.warning(f"MySQL连接错误，尝试重连 ({attempt + 1}/{max_retries}): {str(e)}")
                            time.sleep(retry_delay)
                            connection.close()
                            continue
                        else:
                            raise

                if not token:
                    # 记录日志，帮助调试
                    logger.error(f"未找到代币记录，尝试查找的符号: {symbol.upper()} 和 {clean_symbol}")

                    # 查看数据库中有哪些代币记录
                    all_tokens = await sync_to_async(list)(Token.objects.all())
                    token_symbols = [t.symbol for t in all_tokens]
                    logger.info(f"数据库中的代币记录: {token_symbols}")

                    error_messages = {
                        'zh-CN': f"未找到代币 {symbol} 的分析数据",
                        'en-US': f"Analysis data not found for token {symbol}",
                        'ja-JP': f"トークン {symbol} の分析データが見つかりません",
                        'ko-KR': f"토큰 {symbol}에 대한 분석 데이터를 찾을 수 없습니다"
                    }
                    return Response({
                        'status': 'not_found',
                        'message': error_messages.get(language, error_messages['zh-CN']),
                        'needs_refresh': True
                    }, status=status.HTTP_404_NOT_FOUND)
            except Exception as e:
                logger.error(f"查询代币记录时发生错误: {str(e)}")
                logger.error(traceback.format_exc())
                return Response({
                    'status': 'error',
                    'message': "Error occurred while querying token records, please try again later" if language == 'en-US' else "查询代币记录时发生错误，请稍后重试"
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # 获取指定语言的最新分析报告
            try:
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

                    error_messages = {
                        'zh-CN': f"未找到代币 {symbol} 的最新 {language} 语言分析数据或数据已过期",
                        'en-US': f"Latest {language} analysis data not found or expired for token {symbol}",
                        'ja-JP': f"トークン {symbol} の最新の {language} 分析データが見つからないか期限切れです",
                        'ko-KR': f"토큰 {symbol}에 대한 최신 {language} 분석 데이터를 찾을 수 없거나 만료되었습니다"
                    }
                    return Response({
                        'status': 'not_found',
                        'message': error_messages.get(language, error_messages['zh-CN']),
                        'needs_refresh': True
                    }, status=status.HTTP_404_NOT_FOUND)
            except Exception as e:
                logger.error(f"查询分析报告时发生错误: {str(e)}")
                logger.error(traceback.format_exc())
                return Response({
                    'status': 'error',
                    'message': "Error occurred while querying analysis report, please try again later" if language == 'en-US' else "查询分析报告时发生错误，请稍后重试"
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # 获取相关的技术分析数据
            try:
                ta_qs = await sync_to_async(TechnicalAnalysis.objects.filter)(token=token)
                ta_qs = await sync_to_async(ta_qs.order_by)('-timestamp')
                technical_analysis = await sync_to_async(ta_qs.first)()

                if not technical_analysis:
                    error_messages = {
                        'zh-CN': f"未找到代币 {symbol} 的技术分析数据",
                        'en-US': f"Technical analysis data not found for token {symbol}",
                        'ja-JP': f"トークン {symbol} のテクニカル分析データが見つかりません",
                        'ko-KR': f"토큰 {symbol}에 대한 기술적 분석 데이터를 찾을 수 없습니다"
                    }
                    return Response({
                        'status': 'not_found',
                        'message': error_messages.get(language, error_messages['zh-CN']),
                        'needs_refresh': True
                    }, status=status.HTTP_404_NOT_FOUND)
            except Exception as e:
                logger.error(f"查询技术分析数据时发生错误: {str(e)}")
                logger.error(traceback.format_exc())
                return Response({
                    'status': 'error',
                    'message': "Error occurred while querying technical analysis data, please try again later" if language == 'en-US' else "查询技术分析数据时发生错误，请稍后重试"
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # 构建响应数据
            try:
                # 安全地转换数值
                def safe_float(value, field_name):
                    if value is None:
                        return None
                    try:
                        return float(value)
                    except (ValueError, TypeError) as e:
                        logger.error(f"转换字段 {field_name} 的值 {value} 为浮点数时发生错误: {str(e)}")
                        return None

                response_data = {
                    'status': 'success',
                    'data': {
                        'symbol': symbol,
                        'price': safe_float(latest_report.snapshot_price, 'snapshot_price'),
                        'current_price': safe_float(latest_report.snapshot_price, 'snapshot_price'),
                        'snapshot_price': safe_float(latest_report.snapshot_price, 'snapshot_price'),
                        'last_update_time': latest_report.timestamp.isoformat(),
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
                                'value': safe_float(technical_analysis.rsi, 'rsi'),
                                'analysis': latest_report.rsi_analysis,
                                'support_trend': latest_report.rsi_support_trend
                            },
                            'MACD': {
                                'value': {
                                    'line': safe_float(technical_analysis.macd_line, 'macd_line'),
                                    'signal': safe_float(technical_analysis.macd_signal, 'macd_signal'),
                                    'histogram': safe_float(technical_analysis.macd_histogram, 'macd_histogram')
                                },
                                'analysis': latest_report.macd_analysis,
                                'support_trend': latest_report.macd_support_trend
                            },
                            'BollingerBands': {
                                'value': {
                                    'upper': safe_float(technical_analysis.bollinger_upper, 'bollinger_upper'),
                                    'middle': safe_float(technical_analysis.bollinger_middle, 'bollinger_middle'),
                                    'lower': safe_float(technical_analysis.bollinger_lower, 'bollinger_lower')
                                },
                                'analysis': latest_report.bollinger_analysis,
                                'support_trend': latest_report.bollinger_support_trend
                            },
                            'BIAS': {
                                'value': safe_float(technical_analysis.bias, 'bias'),
                                'analysis': latest_report.bias_analysis,
                                'support_trend': latest_report.bias_support_trend
                            },
                            'PSY': {
                                'value': safe_float(technical_analysis.psy, 'psy'),
                                'analysis': latest_report.psy_analysis,
                                'support_trend': latest_report.psy_support_trend
                            },
                            'DMI': {
                                'value': {
                                    'plus_di': safe_float(technical_analysis.dmi_plus, 'dmi_plus'),
                                    'minus_di': safe_float(technical_analysis.dmi_minus, 'dmi_minus'),
                                    'adx': safe_float(technical_analysis.dmi_adx, 'dmi_adx')
                                },
                                'analysis': latest_report.dmi_analysis,
                                'support_trend': latest_report.dmi_support_trend
                            },
                            'VWAP': {
                                'value': safe_float(technical_analysis.vwap, 'vwap'),
                                'analysis': latest_report.vwap_analysis,
                                'support_trend': latest_report.vwap_support_trend
                            },
                            'FundingRate': {
                                'value': safe_float(technical_analysis.funding_rate, 'funding_rate'),
                                'analysis': latest_report.funding_rate_analysis,
                                'support_trend': latest_report.funding_rate_support_trend
                            },
                            'ExchangeNetflow': {
                                'value': safe_float(technical_analysis.exchange_netflow, 'exchange_netflow'),
                                'analysis': latest_report.exchange_netflow_analysis,
                                'support_trend': latest_report.exchange_netflow_support_trend
                            },
                            'NUPL': {
                                'value': safe_float(technical_analysis.nupl, 'nupl'),
                                'analysis': latest_report.nupl_analysis,
                                'support_trend': latest_report.nupl_support_trend
                            },
                            'MayerMultiple': {
                                'value': safe_float(technical_analysis.mayer_multiple, 'mayer_multiple'),
                                'analysis': latest_report.mayer_multiple_analysis,
                                'support_trend': latest_report.mayer_multiple_support_trend
                            }
                        },
                        'trading_advice': {
                            'action': latest_report.trading_action,
                            'reason': latest_report.trading_reason,
                            'entry_price': safe_float(latest_report.entry_price, 'entry_price'),
                            'stop_loss': safe_float(latest_report.stop_loss, 'stop_loss'),
                            'take_profit': safe_float(latest_report.take_profit, 'take_profit'),
                            'risk_level': latest_report.risk_level,
                            'risk_score': latest_report.risk_score,
                            'risk_details': latest_report.risk_details
                        }
                    }
                }

                logger.info(f"成功获取代币 {symbol} 的技术指标数据")
                return Response(response_data)

            except Exception as e:
                logger.error(f"构建响应数据时发生错误: {str(e)}")
                logger.error(traceback.format_exc())
                return Response({
                    'status': 'error',
                    'message': "Error occurred while building response data, please try again later" if language == 'en-US' else "构建响应数据时发生错误，请稍后重试"
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        except Exception as e:
            logger.error(f"处理请求时发生错误: {str(e)}")
            logger.error(traceback.format_exc())
            return Response({
                'status': 'error',
                'message': "Error occurred while processing request, please try again later" if language == 'en-US' else "处理请求时发生错误，请稍后重试"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
