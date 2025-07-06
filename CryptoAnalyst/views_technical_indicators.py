"""
Technical Indicators API Views - Simplified Synchronous Version
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.utils import timezone
import time
import logging
import datetime
import traceback

from .services.technical_analysis import TechnicalAnalysisService
from .services.market_data_service import MarketDataService
from .models import Asset, AnalysisReport, TechnicalAnalysis, MarketType
from .utils import (
    safe_read_operation, safe_model_operation,
    get_cached_technical_indicators, set_cached_technical_indicators
)

# Configure logging
logger = logging.getLogger(__name__)


class TechnicalIndicatorsAPIView(APIView):
    """Technical Indicators API View"""
    permission_classes = [AllowAny]

    def get(self, request, symbol: str):
        """Synchronous processing of GET requests"""
        try:
            # 检测市场类型 - 通过请求路径判断
            is_stock_request = '/api/stock/' in request.path
            is_china_request = '/api/china/' in request.path

            if is_china_request:
                market_type_name = 'china'
            elif is_stock_request:
                market_type_name = 'stock'
            else:
                market_type_name = 'crypto'

            # 获取或创建市场类型记录
            market_type, _ = MarketType.objects.get_or_create(
                name=market_type_name,
                defaults={'description': f'{market_type_name.title()} Market'}
            )

            # 获取或创建资产记录
            asset, _ = Asset.objects.get_or_create(
                symbol=symbol,
                market_type=market_type,
                defaults={
                    'name': symbol,
                    'is_active': True
                }
            )

            # 获取最新的技术分析记录（7天内）
            time_window = timezone.now() - datetime.timedelta(days=7)
            latest_analysis = TechnicalAnalysis.objects.filter(
                asset=asset,
                timestamp__gte=time_window
            ).order_by('-timestamp').first()

            if not latest_analysis:
                # 尝试获取任何技术分析数据（不限时间）
                any_analysis = TechnicalAnalysis.objects.filter(asset=asset).order_by('-timestamp').first()
                if any_analysis:
                    print(f"Found analysis for {symbol} but outside time window. Latest: {any_analysis.timestamp}")
                    latest_analysis = any_analysis  # 使用最新的分析数据，不管时间
                else:
                    # 对于股票和A股请求，返回特殊的not_found状态
                    if market_type_name in ['stock', 'china']:
                        market_display = 'stock' if market_type_name == 'stock' else 'A-share'
                        print(f"No technical analysis data for {market_display} symbol: {symbol}")
                        return Response({
                            'status': 'not_found',
                            'message': f'No technical analysis data available for {market_display} {symbol}. Please generate a new report first.',
                            'symbol': symbol,
                            'market_type': market_type_name
                        }, status=status.HTTP_200_OK)  # 返回200状态码，让前端处理
                    else:
                        return Response({
                            'status': 'error',
                            'message': 'No technical analysis data available'
                        }, status=status.HTTP_404_NOT_FOUND)

            # 获取最新的英文报告
            latest_report = AnalysisReport.objects.filter(
                asset=asset,
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
                    ta_qs = TechnicalAnalysis.objects.select_related('asset').filter(
                        asset=asset
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
                        'indicators_analysis': self._build_indicators_analysis(technical_analysis, latest_report, market_type_name),
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

    def _build_indicators_analysis(self, technical_analysis, latest_report, market_type_name):
        """构建指标分析数据，根据市场类型包含不同的指标"""

        # 基础技术指标（所有市场都有）
        indicators = {
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
            }
        }

        # 根据市场类型添加特定指标
        if market_type_name == 'china':
            # A股特有指标 - 从技术分析服务获取基本面数据
            try:
                from .services.technical_analysis import TechnicalAnalysisService
                ta_service = TechnicalAnalysisService()
                china_indicators = ta_service._get_china_stock_basic_indicators(technical_analysis.asset.symbol)

                if china_indicators:
                    # 添加A股基本面指标，包含智能趋势分析
                    indicators.update({
                        'TurnoverRate': {
                            'value': china_indicators.get('TurnoverRate', 0),
                            'analysis': self._analyze_turnover_rate(china_indicators.get('TurnoverRate', 0)),
                            'support_trend': self._get_turnover_rate_trend(china_indicators.get('TurnoverRate', 0))
                        },
                        'VolumeRatio': {
                            'value': china_indicators.get('VolumeRatio', 0),
                            'analysis': self._analyze_volume_ratio(china_indicators.get('VolumeRatio', 0)),
                            'support_trend': self._get_volume_ratio_trend(china_indicators.get('VolumeRatio', 0))
                        },
                        'PE': {
                            'value': china_indicators.get('PE', 0),
                            'analysis': self._analyze_pe_ratio(china_indicators.get('PE', 0)),
                            'support_trend': self._get_pe_trend(china_indicators.get('PE', 0))
                        },
                        'PB': {
                            'value': china_indicators.get('PB', 0),
                            'analysis': self._analyze_pb_ratio(china_indicators.get('PB', 0)),
                            'support_trend': self._get_pb_trend(china_indicators.get('PB', 0))
                        },
                        'PS': {
                            'value': china_indicators.get('PS', 0),
                            'analysis': self._analyze_ps_ratio(china_indicators.get('PS', 0)),
                            'support_trend': self._get_ps_trend(china_indicators.get('PS', 0))
                        },
                        'DividendYield': {
                            'value': china_indicators.get('DividendYield', 0),
                            'analysis': self._analyze_dividend_yield(china_indicators.get('DividendYield', 0)),
                            'support_trend': self._get_dividend_yield_trend(china_indicators.get('DividendYield', 0))
                        }
                    })
            except Exception as e:
                logger.error(f"获取A股基本面指标失败: {str(e)}")

        else:
            # 加密货币和美股特有指标
            indicators.update({
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
            })

        return indicators

    def _analyze_turnover_rate(self, rate):
        """分析换手率"""
        if rate <= 0:
            return "换手率数据不可用"
        elif rate < 1:
            return f"换手率 {rate:.2f}%，交易清淡，市场关注度较低"
        elif rate < 3:
            return f"换手率 {rate:.2f}%，交易温和，属于正常水平"
        elif rate < 7:
            return f"换手率 {rate:.2f}%，交易活跃，市场关注度较高"
        else:
            return f"换手率 {rate:.2f}%，交易异常活跃，可能存在重大消息"

    def _get_turnover_rate_trend(self, rate):
        """获取换手率趋势"""
        if rate <= 0:
            return 'neutral'
        elif rate < 1:
            return 'down'  # 交易清淡，偏空
        elif rate < 3:
            return 'sideways'  # 正常水平
        elif rate < 7:
            return 'up'  # 活跃，偏多
        else:
            return 'sideways'  # 过度活跃，需谨慎

    def _analyze_volume_ratio(self, ratio):
        """分析量比"""
        if ratio <= 0:
            return "量比数据不可用"
        elif ratio < 0.5:
            return f"量比 {ratio:.2f}，成交量萎缩严重，市场观望情绪浓厚"
        elif ratio < 0.8:
            return f"量比 {ratio:.2f}，成交量低于平均水平，交易相对清淡"
        elif ratio < 1.2:
            return f"量比 {ratio:.2f}，成交量接近平均水平，市场表现正常"
        elif ratio < 2.0:
            return f"量比 {ratio:.2f}，成交量放大，市场活跃度提升"
        else:
            return f"量比 {ratio:.2f}，成交量大幅放大，可能有重要消息刺激"

    def _get_volume_ratio_trend(self, ratio):
        """获取量比趋势"""
        if ratio <= 0:
            return 'neutral'
        elif ratio < 0.8:
            return 'down'  # 量能不足，偏空
        elif ratio < 1.2:
            return 'sideways'  # 正常水平
        elif ratio < 2.0:
            return 'up'  # 量能放大，偏多
        else:
            return 'sideways'  # 异常放量，需观察

    def _analyze_pe_ratio(self, pe):
        """分析市盈率"""
        if pe <= 0:
            return "市盈率为负或不可用，公司可能处于亏损状态"
        elif pe < 10:
            return f"市盈率 {pe:.2f}，估值较低，可能存在价值投资机会"
        elif pe < 20:
            return f"市盈率 {pe:.2f}，估值合理，处于正常估值区间"
        elif pe < 30:
            return f"市盈率 {pe:.2f}，估值偏高，需关注业绩增长是否匹配"
        else:
            return f"市盈率 {pe:.2f}，估值较高，投资风险相对较大"

    def _get_pe_trend(self, pe):
        """获取市盈率趋势"""
        if pe <= 0:
            return 'down'  # 亏损，偏空
        elif pe < 15:
            return 'up'  # 低估值，偏多
        elif pe < 25:
            return 'sideways'  # 合理估值
        else:
            return 'down'  # 高估值，偏空

    def _analyze_pb_ratio(self, pb):
        """分析市净率"""
        if pb <= 0:
            return "市净率数据不可用"
        elif pb < 1:
            return f"市净率 {pb:.2f}，股价低于净资产，可能存在价值低估"
        elif pb < 2:
            return f"市净率 {pb:.2f}，估值合理，风险相对较低"
        elif pb < 3:
            return f"市净率 {pb:.2f}，估值偏高，需关注资产质量"
        else:
            return f"市净率 {pb:.2f}，估值较高，投资需谨慎"

    def _get_pb_trend(self, pb):
        """获取市净率趋势"""
        if pb <= 0:
            return 'neutral'
        elif pb < 1:
            return 'up'  # 破净，可能低估
        elif pb < 2.5:
            return 'sideways'  # 合理区间
        else:
            return 'down'  # 高估值，偏空

    def _analyze_ps_ratio(self, ps):
        """分析市销率"""
        if ps <= 0:
            return "市销率数据不可用"
        elif ps < 1:
            return f"市销率 {ps:.2f}，相对营收估值较低"
        elif ps < 3:
            return f"市销率 {ps:.2f}，估值处于合理区间"
        elif ps < 5:
            return f"市销率 {ps:.2f}，估值偏高，需关注盈利能力"
        else:
            return f"市销率 {ps:.2f}，估值较高，投资风险较大"

    def _get_ps_trend(self, ps):
        """获取市销率趋势"""
        if ps <= 0:
            return 'neutral'
        elif ps < 2:
            return 'up'  # 低市销率，偏多
        elif ps < 4:
            return 'sideways'  # 合理区间
        else:
            return 'down'  # 高市销率，偏空

    def _analyze_dividend_yield(self, yield_rate):
        """分析股息率"""
        if yield_rate <= 0:
            return "无分红或股息率数据不可用"
        elif yield_rate < 1:
            return f"股息率 {yield_rate:.2f}%，分红收益较低"
        elif yield_rate < 3:
            return f"股息率 {yield_rate:.2f}%，分红收益一般"
        elif yield_rate < 5:
            return f"股息率 {yield_rate:.2f}%，分红收益较好，适合价值投资"
        else:
            return f"股息率 {yield_rate:.2f}%，分红收益丰厚，但需关注可持续性"

    def _get_dividend_yield_trend(self, yield_rate):
        """获取股息率趋势"""
        if yield_rate <= 0:
            return 'neutral'
        elif yield_rate < 2:
            return 'sideways'  # 分红一般
        elif yield_rate < 6:
            return 'up'  # 高分红，偏多
        else:
            return 'sideways'  # 过高分红，需谨慎


def safe_float(value, field_name):
    """Safely convert value to float"""
    try:
        if value is None:
            return 0.0
        return float(value)
    except (ValueError, TypeError):
        logger.warning(f"Invalid {field_name} value: {value}, using default 0.0")
        return 0.0
