"""
Technical Indicators API Views - Simplified Synchronous Version
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
import time
import logging
import datetime
import traceback

from .services.technical_analysis import TechnicalAnalysisService
from .services.market_data_service import MarketDataService
from .models import Token, AnalysisReport, TechnicalAnalysis, Chain
from .utils import (
    safe_read_operation, safe_model_operation,
    get_cached_technical_indicators, set_cached_technical_indicators
)

# Configure logging
logger = logging.getLogger(__name__)


class TechnicalIndicatorsAPIView(APIView):
    """Technical Indicators API View"""

    def get(self, request, symbol: str):
        """Synchronous processing of GET requests"""
        try:
            # 获取或创建链记录
            chain, _ = Chain.objects.get_or_create(
                chain=symbol,
                defaults={
                    'is_active': True,
                    'is_testnet': False
                }
            )

            # 获取或创建交易对记录
            token, _ = Token.objects.get_or_create(
                symbol=symbol,
                defaults={
                    'chain': chain,
                    'name': symbol
                }
            )

            # 获取最新的技术分析记录（24小时内）
            time_window = timezone.now() - datetime.timedelta(hours=24)
            latest_analysis = TechnicalAnalysis.objects.filter(
                token=token,
                timestamp__gte=time_window
            ).order_by('-timestamp').first()

            if not latest_analysis:
                return Response({
                    'status': 'error',
                    'message': 'No technical analysis data available'
                }, status=status.HTTP_404_NOT_FOUND)

            # 获取最新的英文报告
            latest_report = AnalysisReport.objects.filter(
                token=token,
                language='en-US',
                technical_analysis=latest_analysis
            ).first()

            if not latest_report:
                return Response({
                    'status': 'error',
                    'message': 'No analysis report available'
                }, status=status.HTTP_404_NOT_FOUND)

            # Get related technical analysis data
            try:
                @safe_read_operation
                def get_technical_analysis():
                    start_time = time.time()
                    ta_qs = TechnicalAnalysis.objects.select_related('token').filter(
                        token=token
                    ).order_by('-timestamp')
                    technical_analysis = ta_qs.first()
                    duration = time.time() - start_time
                    return technical_analysis

                technical_analysis = get_technical_analysis()
                
                if not technical_analysis:
                    error_messages = {
                        'zh-CN': f"未找到代币 {symbol} 的技术分析数据",
                        'en-US': f"Technical analysis data not found for token {symbol}",
                        'ja-JP': f"トークン {symbol} のテクニカル分析データが見つかりません",
                        'ko-KR': f"토큰 {symbol}에 대한 기술적 분석 데이터를 찾을 수 없습니다"
                    }
                    return Response({
                        'status': 'not_found',
                        'message': error_messages.get('en-US', error_messages['en-US']),
                        'needs_refresh': True
                    }, status=status.HTTP_404_NOT_FOUND)
            except Exception as e:
                return Response({
                    'status': 'error',
                    'message': "Error occurred while querying technical analysis data, please try again later"
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # Build response data
            try:
                # Safely convert numeric values
                def safe_float(value, field_name):
                    if value is None:
                        return None
                    try:
                        return float(value)
                    except (ValueError, TypeError) as e:
                        return None

                response_data = {
                    'status': 'success',
                    'data': {
                        'symbol': symbol,
                        'price': safe_float(latest_report.snapshot_price, 'snapshot_price'),
                        'current_price': safe_float(latest_report.snapshot_price, 'snapshot_price'),
                        'snapshot_price': safe_float(latest_report.snapshot_price, 'snapshot_price'),
                        'last_update_time': latest_report.timestamp.isoformat(),
                        'is_stale': False,
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

                # Cache the response data for future requests
                set_cached_technical_indicators(symbol, 'en-US', response_data, timeout=1800)  # 30 minutes cache

                return Response(response_data)

            except Exception as e:
                return Response({
                    'status': 'error',
                    'message': "Error occurred while building response data, please try again later"
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        except Exception as e:
            return Response({
                'status': 'error',
                'message': "Error occurred while processing request, please try again later"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
