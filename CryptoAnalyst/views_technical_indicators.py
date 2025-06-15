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
from .models import Token, AnalysisReport, TechnicalAnalysis
from .utils import (
    safe_read_operation, safe_model_operation,
    get_cached_technical_indicators, set_cached_technical_indicators
)

# Configure logging
logger = logging.getLogger(__name__)


class TechnicalIndicatorsAPIView(APIView):
    """Technical Indicators API View

    Handles /api/crypto/technical-indicators/<str:symbol>/ endpoint requests
    Returns technical indicator analysis reports for specified tokens
    """
    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.ta_service = None
        self.market_service = None

    def get(self, request, symbol: str):
        """Synchronous processing of GET requests"""
        try:
            # Get request parameters
            language = request.GET.get('language', 'en-US')
            force_refresh = request.GET.get('force_refresh', 'false').lower() == 'true'

            logger.info(f"Requested language: {language}")
            logger.info(f"Force refresh parameter: {force_refresh}")

            # Supported languages list
            supported_languages = ['zh-CN', 'en-US', 'ja-JP', 'ko-KR']

            # Validate language support
            if language not in supported_languages:
                logger.warning(f"Unsupported language: {language}, using default language en-US")
                language = 'en-US'

            # Check cache first (unless force refresh is requested)
            if not force_refresh:
                cached_data = get_cached_technical_indicators(symbol, language)
                if cached_data:
                    logger.info(f"Returning cached technical indicators for {symbol} ({language})")
                    return Response(cached_data)

            # Ensure services are initialized
            if self.ta_service is None:
                self.ta_service = TechnicalAnalysisService()
            if self.market_service is None:
                self.market_service = MarketDataService()

            # Normalize symbol format, remove common suffixes
            clean_symbol = symbol.upper().replace('USDT', '').replace('-PERP', '').replace('_PERP', '').replace('PERP', '')

            # Handle query processing
            try:
                # Simple synchronous token retrieval with robust error handling
                @safe_read_operation
                def get_token():
                    token = Token.objects.filter(symbol=symbol.upper()).first()
                    if not token:
                        token = Token.objects.filter(symbol=clean_symbol).first()
                    return token

                token = get_token()

                if not token:
                    # Log for debugging
                    logger.error(f"Token record not found, attempted symbols: {symbol.upper()} and {clean_symbol}")

                    # Check what token records exist in database
                    @safe_read_operation
                    def get_all_tokens():
                        return list(Token.objects.all())

                    all_tokens = get_all_tokens()
                    token_symbols = [t.symbol for t in all_tokens]
                    logger.info(f"Token records in database: {token_symbols}")

                    error_messages = {
                        'zh-CN': f"未找到代币 {symbol} 的分析数据",
                        'en-US': f"Analysis data not found for token {symbol}",
                        'ja-JP': f"トークン {symbol} の分析データが見つかりません",
                        'ko-KR': f"토큰 {symbol}에 대한 분석 데이터를 찾을 수 없습니다"
                    }
                    return Response({
                        'status': 'not_found',
                        'message': error_messages.get(language, error_messages['en-US']),
                        'needs_refresh': True
                    }, status=status.HTTP_404_NOT_FOUND)
            except Exception as e:
                logger.error(f"Error occurred while querying token record: {str(e)}")
                logger.error(traceback.format_exc())
                return Response({
                    'status': 'error',
                    'message': "Error occurred while querying token records, please try again later"
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # technical-indicators interface only reads local database, does not trigger report generation
            if force_refresh:
                logger.info(f"technical-indicators interface received force_refresh parameter, but this interface only reads local database and does not trigger report generation")

            # Get latest analysis report for specified language
            try:
                @safe_read_operation
                def get_latest_report():
                    start_time = time.time()
                    reports_qs = AnalysisReport.objects.select_related('token').filter(
                        token=token, language=language
                    ).order_by('-timestamp')
                    latest_report = reports_qs.first()
                    duration = time.time() - start_time
                    logger.info(f"Get latest report time cost: {duration:.3f}s")
                    return latest_report

                latest_report = get_latest_report()
                
                if latest_report:
                    logger.info(f"Got latest report ID: {latest_report.id}, time: {latest_report.timestamp}")

                # Define report freshness threshold (12 hours)
                freshness_threshold = timezone.now() - datetime.timedelta(hours=12)

                # If no report found for specified language, return error
                if not latest_report:
                    logger.warning(f"No {language} language analysis report found for token {symbol}, returning 404.")
                    error_messages = {
                        'zh-CN': f"未找到代币 {symbol} 的 {language} 语言分析数据",
                        'en-US': f"{language} analysis data not found for token {symbol}",
                        'ja-JP': f"トークン {symbol} の {language} 分析データが見つかりません",
                        'ko-KR': f"토큰 {symbol}에 대한 {language} 분석 데이터를 찾을 수 없습니다"
                    }
                    return Response({
                        'status': 'not_found',
                        'message': error_messages.get(language, error_messages['en-US']),
                        'needs_refresh': True
                    }, status=status.HTTP_404_NOT_FOUND)

                # Check if report is stale (older than 12 hours)
                is_stale = latest_report.timestamp < freshness_threshold
                if is_stale:
                    logger.info(f"Latest {language} language report for token {symbol} ({latest_report.timestamp}) is older than 12-hour freshness threshold ({freshness_threshold}), but still returning data marked as stale.")
            except Exception as e:
                logger.error(f"Error occurred while querying analysis report: {str(e)}")
                logger.error(traceback.format_exc())
                return Response({
                    'status': 'error',
                    'message': "Error occurred while querying analysis report, please try again later"
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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
                    logger.info(f"Get technical analysis data time cost: {duration:.3f}s")
                    return technical_analysis

                technical_analysis = get_technical_analysis()
                
                if technical_analysis:
                    logger.info(f"Got technical analysis data ID: {technical_analysis.id}, time: {technical_analysis.timestamp}")

                if not technical_analysis:
                    error_messages = {
                        'zh-CN': f"未找到代币 {symbol} 的技术分析数据",
                        'en-US': f"Technical analysis data not found for token {symbol}",
                        'ja-JP': f"トークン {symbol} のテクニカル分析データが見つかりません",
                        'ko-KR': f"토큰 {symbol}에 대한 기술적 분석 데이터를 찾을 수 없습니다"
                    }
                    return Response({
                        'status': 'not_found',
                        'message': error_messages.get(language, error_messages['en-US']),
                        'needs_refresh': True
                    }, status=status.HTTP_404_NOT_FOUND)
            except Exception as e:
                logger.error(f"Error occurred while querying technical analysis data: {str(e)}")
                logger.error(traceback.format_exc())
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
                        logger.error(f"Error converting field {field_name} value {value} to float: {str(e)}")
                        return None

                response_data = {
                    'status': 'success',
                    'data': {
                        'symbol': symbol,
                        'price': safe_float(latest_report.snapshot_price, 'snapshot_price'),
                        'current_price': safe_float(latest_report.snapshot_price, 'snapshot_price'),
                        'snapshot_price': safe_float(latest_report.snapshot_price, 'snapshot_price'),
                        'last_update_time': latest_report.timestamp.isoformat(),
                        'is_stale': is_stale,
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

                logger.info(f"Successfully retrieved technical indicators data for token {symbol}")

                # Cache the response data for future requests
                set_cached_technical_indicators(symbol, language, response_data, timeout=1800)  # 30 minutes cache

                return Response(response_data)

            except Exception as e:
                logger.error(f"Error occurred while building response data: {str(e)}")
                logger.error(traceback.format_exc())
                return Response({
                    'status': 'error',
                    'message': "Error occurred while building response data, please try again later"
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        except Exception as e:
            logger.error(f"Error occurred while processing request: {str(e)}")
            logger.error(traceback.format_exc())

            return Response({
                'status': 'error',
                'message': "Error occurred while processing request, please try again later"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
