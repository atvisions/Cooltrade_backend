import logging
import json
import time
import re  # 添加 re 模块导入
from typing import Dict, Any, Optional
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction
from django.conf import settings
from django.utils import timezone
import requests
from datetime import datetime, timedelta
from .models import Token, Chain, AnalysisReport, TechnicalAnalysis, Asset, MarketType
from .views_indicators_data import TechnicalIndicatorsDataAPIView
from .services.technical_analysis import TechnicalAnalysisService
from .utils import invalidate_technical_indicators_cache

logger = logging.getLogger(__name__)

class CryptoReportAPIView(APIView):
    """加密货币分析报告API视图"""

    SUPPORTED_LANGUAGES = ['en-US']
    COZE_BOT_IDS = {
        'en-US': settings.COZE_BOT_ID_EN
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.technical_indicators_view = TechnicalIndicatorsDataAPIView(internal_call=True)
        self._init_coze_api()

    def _init_coze_api(self):
        self.coze_api_key = settings.COZE_API_KEY
        self.coze_api_url = settings.COZE_API_URL
        if self.coze_api_url.endswith('/api/v3'):
            self.coze_api_url = self.coze_api_url.replace('/api/v3', '')

    def get(self, request, symbol: str) -> Response:
        try:
            # 检测市场类型 - 通过请求路径判断
            is_china_request = '/api/china/' in request.path
            is_stock_request = '/api/stock/' in request.path

            if is_china_request:
                market_type = 'china'
            elif is_stock_request:
                market_type = 'stock'
            else:
                market_type = 'crypto'

            # 只处理英文
            language = 'en-US'
            force_refresh = request.GET.get('force_refresh', 'false').lower() == 'true'
            print(f"接收到请求参数 - symbol: {symbol}, market_type: {market_type}, force_refresh: {force_refresh}")



            # 根据市场类型获取或创建MarketType记录
            market_type_obj, _ = MarketType.objects.get_or_create(
                name=market_type,
                defaults={'description': f'{market_type.title()} Market'}
            )

            # 获取或创建Asset记录
            asset, _ = Asset.objects.get_or_create(
                symbol=symbol,
                market_type=market_type_obj,
                defaults={
                    'name': symbol,
                    'is_active': True
                }
            )

            time_window = timezone.now() - timedelta(hours=24)
            latest_analysis = TechnicalAnalysis.objects.filter(
                asset=asset,
                timestamp__gte=time_window
            ).order_by('-timestamp').first()

            if not latest_analysis:
                technical_data = self._get_technical_data(symbol, market_type)
                if not technical_data:
                    return Response({
                        'status': 'error',
                        'message': 'Failed to get technical indicator data'
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                indicators = technical_data.get('indicators', {})
                def get_indicator_value(indicator_data, default=0):
                    if isinstance(indicator_data, dict):
                        # 如果是字典，优先查找'value'键，如果没有则返回默认值
                        return indicator_data.get('value', default)
                    # 如果是直接的数值（如A股指标），直接返回
                    return indicator_data if indicator_data is not None else default

                now = timezone.now()
                period_hour = (now.hour // 12) * 12
                period_start = now.replace(minute=0, second=0, microsecond=0, hour=period_hour)
                # 使用 update_or_create 确保技术指标数据被更新
                latest_analysis, _ = TechnicalAnalysis.objects.update_or_create(
                    asset=asset,
                    period_start=period_start,
                    defaults={
                        'timestamp': now,
                        'rsi': get_indicator_value(indicators.get('RSI')),
                        'macd_line': get_indicator_value(indicators.get('MACD', {}).get('line')),
                        'macd_signal': get_indicator_value(indicators.get('MACD', {}).get('signal')),
                        'macd_histogram': get_indicator_value(indicators.get('MACD', {}).get('histogram')),
                        'bollinger_upper': get_indicator_value(indicators.get('BollingerBands', {}).get('upper')),
                        'bollinger_middle': get_indicator_value(indicators.get('BollingerBands', {}).get('middle')),
                        'bollinger_lower': get_indicator_value(indicators.get('BollingerBands', {}).get('lower')),
                        'bias': get_indicator_value(indicators.get('BIAS')),
                        'psy': get_indicator_value(indicators.get('PSY')),
                        'dmi_plus': get_indicator_value(indicators.get('DMI', {}).get('plus_di')),
                        'dmi_minus': get_indicator_value(indicators.get('DMI', {}).get('minus_di')),
                        'dmi_adx': get_indicator_value(indicators.get('DMI', {}).get('adx')),
                        'vwap': get_indicator_value(indicators.get('VWAP')),
                        'funding_rate': get_indicator_value(indicators.get('FundingRate')),
                        'exchange_netflow': get_indicator_value(indicators.get('ExchangeNetflow')),
                        'nupl': get_indicator_value(indicators.get('NUPL')),
                        'mayer_multiple': get_indicator_value(indicators.get('MayerMultiple'))
                    }
                )

            print(f"get_report 接口调用，将生成全新的 {symbol} 的英文报告（不使用缓存）")
            technical_data = self._get_technical_data(symbol, market_type)
            if not technical_data:
                return Response({
                    'status': 'error',
                    'message': 'Failed to get technical indicator data'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            report = self._generate_and_save_report(asset, technical_data, 'en-US')
            if not report:
                return Response({
                    'status': 'error',
                    'message': 'Failed to generate analysis report'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            report_data = self._format_report_data(report)
            return Response({
                'status': 'success',
                'data': {
                    'symbol': symbol,
                    'reports': [report_data]
                }
            })
        except Exception as e:
            print(f"生成分析报告时发生错误: {str(e)}")
            return Response({
                'status': 'error',
                'message': f'生成分析报告时发生错误: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _format_report_data(self, report):
        """格式化报告数据"""
        # 获取关联的技术分析数据以获取指标数值
        technical_analysis = report.technical_analysis

        return {
            'language': report.language,
            'timestamp': report.timestamp,
            'last_update_time': report.timestamp.isoformat(),
            'current_price': report.snapshot_price,
            'snapshot_price': report.snapshot_price,
            'price': report.snapshot_price,  # 使用 snapshot_price 替代 price
            'trend_analysis': {
                'up_probability': report.trend_up_probability,
                'sideways_probability': report.trend_sideways_probability,
                'down_probability': report.trend_down_probability,
                'summary': report.trend_summary
            },
            'indicators_analysis': {
                'rsi': {
                    'value': technical_analysis.rsi if technical_analysis.rsi is not None else 0,
                    'analysis': report.rsi_analysis,
                    'support_trend': report.rsi_support_trend
                },
                'macd': {
                    'value': {
                        'line': technical_analysis.macd_line if technical_analysis.macd_line is not None else 0,
                        'signal': technical_analysis.macd_signal if technical_analysis.macd_signal is not None else 0,
                        'histogram': technical_analysis.macd_histogram if technical_analysis.macd_histogram is not None else 0
                    },
                    'analysis': report.macd_analysis,
                    'support_trend': report.macd_support_trend
                },
                'bollinger_bands': {
                    'value': {
                        'upper': technical_analysis.bollinger_upper if technical_analysis.bollinger_upper is not None else 0,
                        'middle': technical_analysis.bollinger_middle if technical_analysis.bollinger_middle is not None else 0,
                        'lower': technical_analysis.bollinger_lower if technical_analysis.bollinger_lower is not None else 0
                    },
                    'analysis': report.bollinger_analysis,
                    'support_trend': report.bollinger_support_trend
                },
                'bias': {
                    'value': technical_analysis.bias if technical_analysis.bias is not None else 0,
                    'analysis': report.bias_analysis,
                    'support_trend': report.bias_support_trend
                },
                'psy': {
                    'value': technical_analysis.psy if technical_analysis.psy is not None else 0,
                    'analysis': report.psy_analysis,
                    'support_trend': report.psy_support_trend
                },
                'dmi': {
                    'value': {
                        'plus_di': technical_analysis.dmi_plus if technical_analysis.dmi_plus is not None else 0,
                        'minus_di': technical_analysis.dmi_minus if technical_analysis.dmi_minus is not None else 0,
                        'adx': technical_analysis.dmi_adx if technical_analysis.dmi_adx is not None else 0
                    },
                    'analysis': report.dmi_analysis,
                    'support_trend': report.dmi_support_trend
                },
                'vwap': {
                    'value': technical_analysis.vwap if technical_analysis.vwap is not None else 0,
                    'analysis': report.vwap_analysis,
                    'support_trend': report.vwap_support_trend
                },
                'funding_rate': {
                    'value': technical_analysis.funding_rate if technical_analysis.funding_rate is not None else 0,
                    'analysis': report.funding_rate_analysis,
                    'support_trend': report.funding_rate_support_trend
                },
                'exchange_netflow': {
                    'value': technical_analysis.exchange_netflow if technical_analysis.exchange_netflow is not None else 0,
                    'analysis': report.exchange_netflow_analysis,
                    'support_trend': report.exchange_netflow_support_trend
                },
                'nupl': {
                    'value': technical_analysis.nupl if technical_analysis.nupl is not None else 0,
                    'analysis': report.nupl_analysis,
                    'support_trend': report.nupl_support_trend
                },
                'mayer_multiple': {
                    'value': technical_analysis.mayer_multiple if technical_analysis.mayer_multiple is not None else 0,
                    'analysis': report.mayer_multiple_analysis,
                    'support_trend': report.mayer_multiple_support_trend
                }
            },
            'trading_advice': {
                'action': report.trading_action,
                'reason': report.trading_reason,
                'entry_price': report.entry_price,
                'stop_loss': report.stop_loss,
                'take_profit': report.take_profit
            },
            'risk_assessment': {
                'level': report.risk_level,
                'score': report.risk_score,
                'details': report.risk_details
            }
        }

    def _get_technical_data(self, symbol: str, market_type: str = 'crypto') -> Optional[Dict[str, Any]]:
        """获取技术指标数据

        get_report 接口专用：每次都调用 API 获取最新数据，不使用任何缓存

        Args:
            symbol: 交易符号
            market_type: 市场类型 ('crypto' 或 'stock')
        """
        try:
            # 根据市场类型处理符号格式
            if market_type == 'china':
                # A股符号：直接使用
                clean_symbol = symbol.upper()
                api_symbol = clean_symbol
                print(f"[DEBUG] A股请求 - 符号: {symbol}, 市场类型: {market_type}")

                # 使用A股技术分析
                return self._get_china_stock_technical_data(clean_symbol)
            elif market_type == 'stock':
                # 股票符号：直接使用，不添加USDT后缀
                clean_symbol = symbol.upper()
                api_symbol = clean_symbol  # 股票API使用原始符号
                print(f"[DEBUG] 股票请求 - 符号: {symbol}, 市场类型: {market_type}")

                # 暂时返回股票功能开发中的信息
                return self._get_stock_technical_data(clean_symbol)
            else:
                # 加密货币符号：清理并可能添加USDT后缀
                clean_symbol = symbol.upper().replace('USDT', '').replace('-PERP', '').replace('_PERP', '').replace('PERP', '')
                api_symbol = f"{clean_symbol}USDT" if not clean_symbol.endswith('USDT') else clean_symbol

            print(f"[DEBUG] 符号处理 - 原始: {symbol}, 清理后: {clean_symbol}, API符号: {api_symbol}, 市场类型: {market_type}")

            # 根据市场类型获取或创建MarketType记录
            market_type_obj, _ = MarketType.objects.get_or_create(
                name=market_type,
                defaults={'description': f'{market_type.title()} Market'}
            )

            # 根据市场类型查找Asset记录
            asset = Asset.objects.filter(
                symbol=clean_symbol,
                market_type=market_type_obj
            ).first()

            if not asset:
                # 如果没有找到Asset记录，创建一个新的
                print(f"[DEBUG] 创建新的Asset记录: {clean_symbol}, 市场类型: {market_type}")
                asset = Asset.objects.create(
                    symbol=clean_symbol,
                    name=clean_symbol,
                    market_type=market_type_obj,
                    is_active=True
                )

            print(f"[DEBUG] 找到Asset记录: ID={asset.id}, Symbol={asset.symbol}, Market={asset.market_type.name}")

            # 根据市场类型获取技术指标数据
            if market_type == 'china':
                # 对于A股，使用专门的A股数据获取方法
                print(f"get_report 接口：获取A股 {clean_symbol} 的技术指标数据")
                technical_data = self._get_china_stock_technical_data(clean_symbol)
                print(f"[DEBUG] _get_china_stock_technical_data 返回: {technical_data}")

                if not technical_data:
                    print(f"[DEBUG] A股技术数据为空，返回None")
                    return None
            elif market_type == 'stock':
                # 对于股票，使用专门的股票数据获取方法
                print(f"get_report 接口：获取股票 {clean_symbol} 的技术指标数据")
                technical_data = self._get_stock_technical_data(clean_symbol)
                print(f"[DEBUG] _get_stock_technical_data 返回: {technical_data}")

                if not technical_data:
                    print(f"[DEBUG] 股票技术数据为空，返回None")
                    return None

                # 将股票数据包装成与加密货币相同的格式
                data = {
                    'current_price': technical_data.get('current_price', 0),
                    'rsi': technical_data.get('rsi', 0),
                    'macd_line': technical_data.get('macd_line', 0),
                    'macd_signal': technical_data.get('macd_signal', 0),
                    'macd_histogram': technical_data.get('macd_histogram', 0),
                    'bb_upper': technical_data.get('bb_upper', 0),
                    'bb_middle': technical_data.get('bb_middle', 0),
                    'bb_lower': technical_data.get('bb_lower', 0),
                    'dmi_plus': technical_data.get('dmi_plus', 0),
                    'dmi_minus': technical_data.get('dmi_minus', 0),
                    'adx': technical_data.get('adx', 0),
                    'exchange_netflow': technical_data.get('exchange_netflow', 0),
                    'mayer_multiple': technical_data.get('mayer_multiple', 0),
                }
                print(f"[DEBUG] 股票技术指标数据: {data}")
            else:
                # 对于加密货币，使用原有的逻辑
                print(f"get_report 接口：直接调用 API 获取 {symbol} 的最新技术指标数据")

                # 使用 TechnicalIndicatorsDataAPIView 获取最新数据，绕过缓存
                # 创建一个模拟的请求对象，强制绕过缓存
                class MockRequest:
                    def __init__(self):
                        self._request = None
                        self.user = None
                        # 模拟 GET 参数，强制绕过缓存
                        self.GET = {'bypass_cache': 'true'}

                mock_request = MockRequest()
                if hasattr(self, 'request') and hasattr(self.request, '_request'):
                    mock_request._request = self.request._request

                # 确保 technical_indicators_view 已初始化并设置为内部调用
                if not hasattr(self, 'technical_indicators_view') or self.technical_indicators_view is None:
                    self.technical_indicators_view = TechnicalIndicatorsDataAPIView(internal_call=True)
                else:
                    self.technical_indicators_view.internal_call = True

                # 强制清除缓存
                if hasattr(self.technical_indicators_view, 'ta_service') and self.technical_indicators_view.ta_service:
                    self._clear_all_cache(self.technical_indicators_view.ta_service, api_symbol)

                # 使用正确的API符号调用技术指标服务
                response = self.technical_indicators_view.get(mock_request, api_symbol)

                if response.status_code == status.HTTP_200_OK:
                    data = response.data.get('data', {})
                    print(f"[DEBUG] API返回的完整数据: {response.data}")
                    print(f"[DEBUG] 提取的data部分: {data}")

                    # 如果返回的数据中没有 current_price，尝试获取实时价格
                    if 'current_price' not in data:
                        try:
                            # 确保 technical_indicators_view 已初始化
                            if not hasattr(self, 'technical_indicators_view') or self.technical_indicators_view is None:
                                self.technical_indicators_view = TechnicalIndicatorsDataAPIView(internal_call=True)

                            # 确保 ta_service 已初始化
                            if self.technical_indicators_view.ta_service is None:
                                self.technical_indicators_view.ta_service = TechnicalAnalysisService()

                            # 获取实时价格
                            current_price = self.technical_indicators_view.ta_service.gate_api.get_realtime_price(symbol)

                            # 如果获取到价格，添加到数据中
                            if current_price:
                                data['current_price'] = current_price
                                # 成功获取实时价格
                        except Exception as e:
                            print(f"获取实时价格失败: {str(e)}")
                else:
                    print(f"获取技术指标数据失败: {response.data}")
                    return None

            return data
        except Exception as e:
            print(f"获取技术指标数据时发生错误: {str(e)}")
            return None

    def _clear_all_cache(self, ta_service, symbol: str):
        """清除指定代币的所有缓存"""
        try:
            print(f"清除 {symbol} 的所有缓存")

            # 清除 Gate API 缓存
            if hasattr(ta_service, 'gate_api'):
                gate_api = ta_service.gate_api

                # 清除价格缓存
                if hasattr(gate_api, 'price_cache'):
                    gate_api.price_cache.pop(symbol, None)
                    gate_api.price_cache.pop(symbol.upper(), None)

                if hasattr(gate_api, 'price_cache_time'):
                    gate_api.price_cache_time.pop(symbol, None)
                    gate_api.price_cache_time.pop(symbol.upper(), None)

                # 清除K线缓存
                if hasattr(gate_api, 'kline_cache'):
                    keys_to_remove = [k for k in gate_api.kline_cache.keys() if symbol.upper() in k]
                    for key in keys_to_remove:
                        gate_api.kline_cache.pop(key, None)

                if hasattr(gate_api, 'kline_cache_time'):
                    keys_to_remove = [k for k in gate_api.kline_cache_time.keys() if symbol.upper() in k]
                    for key in keys_to_remove:
                        gate_api.kline_cache_time.pop(key, None)

                # 清除ticker缓存
                if hasattr(gate_api, 'ticker_cache'):
                    gate_api.ticker_cache.pop(symbol, None)
                    gate_api.ticker_cache.pop(symbol.upper(), None)

                if hasattr(gate_api, 'ticker_cache_time'):
                    gate_api.ticker_cache_time.pop(symbol, None)
                    gate_api.ticker_cache_time.pop(symbol.upper(), None)

            # 清除 OKX API 缓存
            if hasattr(ta_service, 'okx_api'):
                okx_api = ta_service.okx_api

                # 清除价格缓存
                if hasattr(okx_api, 'price_cache'):
                    okx_api.price_cache.pop(symbol, None)
                    okx_api.price_cache.pop(symbol.upper(), None)

                if hasattr(okx_api, 'price_cache_time'):
                    okx_api.price_cache_time.pop(symbol, None)
                    okx_api.price_cache_time.pop(symbol.upper(), None)

                # 清除K线缓存
                if hasattr(okx_api, 'kline_cache'):
                    keys_to_remove = [k for k in okx_api.kline_cache.keys() if symbol.upper() in k]
                    for key in keys_to_remove:
                        okx_api.kline_cache.pop(key, None)

                if hasattr(okx_api, 'kline_cache_time'):
                    keys_to_remove = [k for k in okx_api.kline_cache_time.keys() if symbol.upper() in k]
                    for key in keys_to_remove:
                        okx_api.kline_cache_time.pop(key, None)

                # 清除ticker缓存
                if hasattr(okx_api, 'ticker_cache'):
                    okx_api.ticker_cache.pop(symbol, None)
                    okx_api.ticker_cache.pop(symbol.upper(), None)

                if hasattr(okx_api, 'ticker_cache_time'):
                    okx_api.ticker_cache_time.pop(symbol, None)
                    okx_api.ticker_cache_time.pop(symbol.upper(), None)

            print(f"已清除 {symbol} 的所有缓存")

        except Exception as e:
            print(f"清除缓存时出错: {str(e)}")
            # 即使清除缓存失败，也继续执行

    def _get_stock_technical_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取股票技术指标数据

        Args:
            symbol: 股票符号 (如 AAPL)

        Returns:
            Dict: 股票技术指标数据，如果获取失败返回None
        """
        try:
            print(f"[DEBUG] 开始获取股票技术数据: {symbol}")

            # 检查是否有 Tiingo API 密钥
            tiingo_api_key = getattr(settings, 'TIINGO_API_KEY', None)
            print(f"[DEBUG] Tiingo API 密钥状态: {'已配置' if tiingo_api_key else '未配置'}")

            if not tiingo_api_key:
                print(f"[DEBUG] 缺少 Tiingo API 密钥，使用模拟数据: {symbol}")
                # 即使没有API密钥，也返回模拟数据
                return {
                    'current_price': 201.0,  # 模拟价格
                    'symbol': symbol,
                    'market_type': 'stock',
                    'indicators': {
                        'rsi': 65.2,  # 模拟RSI值
                        'macd_line': 2.45,  # 模拟MACD值
                        'macd_signal': 1.85,
                        'macd_histogram': 0.60,
                        'bollinger_upper': 205.02,  # 模拟布林带上轨
                        'bollinger_middle': 201.0,  # 模拟布林带中轨
                        'bollinger_lower': 196.98,  # 模拟布林带下轨
                        'dmi_plus': 25.0,  # 模拟DMI+
                        'dmi_minus': 25.0,  # 模拟DMI-
                        'adx': 25.0,  # 模拟ADX
                        'exchange_netflow': 0.0,  # 股票不适用
                        'mayer_multiple': 1.0,  # 股票不适用
                    },
                    'status': 'success',
                    'message': f'Mock stock data for {symbol} (no Tiingo API key)'
                }

            # 使用 Tiingo API 获取股票价格数据
            url = f"https://api.tiingo.com/tiingo/daily/{symbol}/prices"
            params = {
                'token': tiingo_api_key,
                'startDate': '2024-01-01',  # 获取一年的数据用于技术分析
                'format': 'json'
            }

            print(f"[DEBUG] 调用 Tiingo API: {url}")
            print(f"[DEBUG] 请求参数: {params}")

            response = requests.get(url, params=params, timeout=10)
            print(f"[DEBUG] Tiingo API 响应状态码: {response.status_code}")

            if response.status_code == 200:
                price_data = response.json()
                if not price_data:
                    print(f"[DEBUG] 股票 {symbol} 没有价格数据")
                    return None

                # 获取最新价格
                latest_price = price_data[-1]['close'] if price_data else 0
                print(f"[DEBUG] 获取到股票价格数据，最新价格: {latest_price}")

                # 返回与加密货币相同格式的股票数据结构
                result = {
                    'current_price': latest_price,
                    'symbol': symbol,
                    'market_type': 'stock',
                    'indicators': {
                        'rsi': 65.2,  # 模拟RSI值
                        'macd_line': 2.45,  # 模拟MACD值
                        'macd_signal': 1.85,
                        'macd_histogram': 0.60,
                        'bollinger_upper': latest_price * 1.02,  # 模拟布林带上轨
                        'bollinger_middle': latest_price,  # 模拟布林带中轨
                        'bollinger_lower': latest_price * 0.98,  # 模拟布林带下轨
                        'dmi_plus': 25.0,  # 模拟DMI+
                        'dmi_minus': 25.0,  # 模拟DMI-
                        'adx': 25.0,  # 模拟ADX
                        'exchange_netflow': 0.0,  # 股票不适用
                        'mayer_multiple': 1.0,  # 股票不适用
                    },
                    'status': 'success',
                    'message': f'Stock data for {symbol} (using Tiingo API)'
                }
                print(f"[DEBUG] _get_stock_technical_data 即将返回: {result}")
                return result
            else:
                print(f"[DEBUG] Tiingo API 请求失败: {response.status_code}, {response.text}")
                return None

        except Exception as e:
            print(f"[DEBUG] 获取股票技术数据失败: {symbol}, 错误: {str(e)}")
            return None

    @transaction.atomic
    def _generate_and_save_report(self, asset: Asset, technical_data: Dict[str, Any], language: str) -> Optional[Dict[str, Any]]:
        try:
            print("[DEBUG] 开始生成并保存报告")
            current_price = technical_data.get('current_price', 0)
            if not current_price:
                print("无法获取当前价格")
                return None
            indicators = technical_data.get('indicators', {})
            def get_indicator_value(indicator_data, default=0):
                if isinstance(indicator_data, dict):
                    # 如果是字典，优先查找'value'键，如果没有则返回默认值
                    return indicator_data.get('value', default)
                # 如果是直接的数值（如A股指标），直接返回
                return indicator_data if indicator_data is not None else default

            now = timezone.now()
            period_hour = (now.hour // 12) * 12
            period_start = now.replace(minute=0, second=0, microsecond=0, hour=period_hour)
            # 调试：打印技术指标数据
            print(f"[DEBUG] 技术指标数据: {indicators}")
            print(f"[DEBUG] RSI: {get_indicator_value(indicators.get('rsi'))}")
            print(f"[DEBUG] MACD Line: {get_indicator_value(indicators.get('macd_line'))}")
            print(f"[DEBUG] MACD Signal: {get_indicator_value(indicators.get('macd_signal'))}")
            print(f"[DEBUG] MACD Histogram: {get_indicator_value(indicators.get('macd_histogram'))}")
            print(f"[DEBUG] Bollinger Upper: {get_indicator_value(indicators.get('bollinger_upper'))}")
            print(f"[DEBUG] BIAS: {get_indicator_value(indicators.get('bias'))}")
            print(f"[DEBUG] PSY: {get_indicator_value(indicators.get('psy'))}")
            print(f"[DEBUG] DMI Plus: {get_indicator_value(indicators.get('dmi_plus'))}")
            print(f"[DEBUG] VWAP: {get_indicator_value(indicators.get('vwap'))}")
            print(f"[DEBUG] FundingRate: {get_indicator_value(indicators.get('funding_rate'))}")
            print(f"[DEBUG] ExchangeNetflow: {get_indicator_value(indicators.get('exchange_netflow'))}")
            print(f"[DEBUG] NUPL: {get_indicator_value(indicators.get('nupl'))}")
            print(f"[DEBUG] MayerMultiple: {get_indicator_value(indicators.get('mayer_multiple'))}")

            with transaction.atomic():
                # 使用 update_or_create 确保技术指标数据被更新
                technical_analysis, _ = TechnicalAnalysis.objects.update_or_create(
                    asset=asset,
                    period_start=period_start,
                    defaults={
                        'timestamp': now,
                        'rsi': get_indicator_value(indicators.get('rsi')),
                        'macd_line': get_indicator_value(indicators.get('macd_line')),
                        'macd_signal': get_indicator_value(indicators.get('macd_signal')),
                        'macd_histogram': get_indicator_value(indicators.get('macd_histogram')),
                        'bollinger_upper': get_indicator_value(indicators.get('bollinger_upper')),
                        'bollinger_middle': get_indicator_value(indicators.get('bollinger_middle')),
                        'bollinger_lower': get_indicator_value(indicators.get('bollinger_lower')),
                        'bias': get_indicator_value(indicators.get('bias')),
                        'psy': get_indicator_value(indicators.get('psy')),
                        'dmi_plus': get_indicator_value(indicators.get('dmi_plus')),
                        'dmi_minus': get_indicator_value(indicators.get('dmi_minus')),
                        'dmi_adx': get_indicator_value(indicators.get('dmi_adx')),
                        'vwap': get_indicator_value(indicators.get('vwap')),
                        'funding_rate': get_indicator_value(indicators.get('funding_rate')),
                        'exchange_netflow': get_indicator_value(indicators.get('exchange_netflow')),
                        'nupl': get_indicator_value(indicators.get('nupl')),
                        'mayer_multiple': get_indicator_value(indicators.get('mayer_multiple'))
                    }
                )
            print("[DEBUG] 技术分析记录已创建或获取")
            bot_id = self.COZE_BOT_IDS.get('en-US')
            if not bot_id:
                print("未找到英文 Coze Bot ID")
                return None
            prompt = self._build_prompt(technical_data, 'en-US')
            chat_url = f"{self.coze_api_url}/v3/chat"
            print(f"[DEBUG] 调用 Coze API 创建对话: {chat_url}")
            payload = {
                "bot_id": bot_id,
                "user_id": f"crypto_user_{int(time.time())}",
                "stream": False,
                "auto_save_history": True,
                "additional_messages": [
                    {
                        "role": "user",
                        "content": prompt,
                        "content_type": "text"
                    }
                ]
            }
            headers = {
                "Authorization": f"Bearer {self.coze_api_key}",
                "Content-Type": "application/json",
                "Accept": "*/*",
                "Connection": "keep-alive"
            }
            print(f"[DEBUG] payload: {json.dumps(payload)[:500]}")
            try:
                response = requests.post(
                    chat_url,
                    headers=headers,
                    json=payload,
                    timeout=30,
                    verify=True
                )
                print(f"[DEBUG] Coze API response status: {response.status_code}")
                if response.status_code != 200:
                    print(f"Coze API 响应错误: {response.text}")
                    return None
                try:
                    response_data = response.json()
                except Exception as e:
                    print(f"Coze API 响应无法解析为 JSON，原始内容: {response.text}")
                    return None
                print(f"[DEBUG] Coze API response json: {response_data}")
                if response_data.get('code') != 0:
                    print(f"Coze API 响应错误: {response_data}")
                    return None
                data = response_data.get('data', {})
                chat_id = data.get('id')
                conversation_id = data.get('conversation_id')
                if not chat_id or not conversation_id:
                    print("Coze API 响应中缺少 chat_id 或 conversation_id")
                    return None
                # 轮询获取最终分析内容
                max_retries = 30
                retry_count = 0
                retry_interval = 2.0
                max_retry_interval = 8.0
                time.sleep(3.0)
                while retry_count < max_retries:
                    try:
                        retrieve_url = f"{self.coze_api_url}/v3/chat/retrieve"
                        retrieve_params = {
                            "bot_id": bot_id,
                            "chat_id": chat_id,
                            "conversation_id": conversation_id
                        }
                        status_response = requests.get(
                            retrieve_url,
                            headers=headers,
                            params=retrieve_params,
                            timeout=30,
                            verify=True
                        )
                        if status_response.status_code == 200:
                            status_data = status_response.json()
                            if status_data.get('code') == 0:
                                data = status_data.get('data', {})
                                status = data.get('status')
                                print(f"[DEBUG] Coze retrieve status: {status}")
                                if status == "completed":
                                    # 获取消息列表
                                    message_list_url = f"{self.coze_api_url}/v3/chat/message/list"
                                    message_list_params = {
                                        "bot_id": bot_id,
                                        "chat_id": chat_id,
                                        "conversation_id": conversation_id
                                    }
                                    messages_response = requests.get(
                                        message_list_url,
                                        headers=headers,
                                        params=message_list_params,
                                        timeout=30,
                                        verify=True
                                    )
                                    if messages_response.status_code == 200:
                                        try:
                                            messages_data = messages_response.json()
                                            if messages_data.get('code') == 0:
                                                messages = []
                                                if isinstance(messages_data.get('data'), dict):
                                                    messages = messages_data.get('data', {}).get('messages', [])
                                                elif isinstance(messages_data.get('data'), list):
                                                    messages = messages_data.get('data', [])
                                                else:
                                                    print(f"无法解析消息列表格式: {messages_data}")
                                                    continue
                                                for message in messages:
                                                    if message.get('role') == 'assistant' and message.get('type') == 'answer':
                                                        content = message.get('content', '')
                                                        print(f"[DEBUG] Coze 最终内容: {content}")
                                                        analysis_data = self._extract_json_from_content(content)
                                                        if analysis_data:
                                                            trading_advice = analysis_data.get('trading_advice', {})
                                                            entry_price = trading_advice.get('entry_price')
                                                            if entry_price is not None:
                                                                try:
                                                                    entry_price = float(entry_price)
                                                                except (ValueError, TypeError):
                                                                    entry_price = 0
                                                            else:
                                                                entry_price = 0
                                                            report = AnalysisReport.objects.create(
                                                                asset=asset,
                                                                technical_analysis=technical_analysis,
                                                                timestamp=now,
                                                                snapshot_price=current_price,
                                                                language='en-US',
                                                                trend_up_probability=analysis_data.get('trend_analysis', {}).get('up_probability', 33),
                                                                trend_sideways_probability=analysis_data.get('trend_analysis', {}).get('sideways_probability', 34),
                                                                trend_down_probability=analysis_data.get('trend_analysis', {}).get('down_probability', 33),
                                                                trend_summary=analysis_data.get('trend_analysis', {}).get('summary', ''),
                                                                rsi_analysis=analysis_data.get('indicators_analysis', {}).get('rsi', {}).get('analysis', ''),
                                                                rsi_support_trend=analysis_data.get('indicators_analysis', {}).get('rsi', {}).get('support_trend', 'neutral'),
                                                                macd_analysis=analysis_data.get('indicators_analysis', {}).get('macd', {}).get('analysis', ''),
                                                                macd_support_trend=analysis_data.get('indicators_analysis', {}).get('macd', {}).get('support_trend', 'neutral'),
                                                                bollinger_analysis=analysis_data.get('indicators_analysis', {}).get('bollinger_bands', {}).get('analysis', ''),
                                                                bollinger_support_trend=analysis_data.get('indicators_analysis', {}).get('bollinger_bands', {}).get('support_trend', 'neutral'),
                                                                bias_analysis=analysis_data.get('indicators_analysis', {}).get('bias', {}).get('analysis', ''),
                                                                bias_support_trend=analysis_data.get('indicators_analysis', {}).get('bias', {}).get('support_trend', 'neutral'),
                                                                psy_analysis=analysis_data.get('indicators_analysis', {}).get('psy', {}).get('analysis', ''),
                                                                psy_support_trend=analysis_data.get('indicators_analysis', {}).get('psy', {}).get('support_trend', 'neutral'),
                                                                dmi_analysis=analysis_data.get('indicators_analysis', {}).get('dmi', {}).get('analysis', ''),
                                                                dmi_support_trend=analysis_data.get('indicators_analysis', {}).get('dmi', {}).get('support_trend', 'neutral'),
                                                                vwap_analysis=analysis_data.get('indicators_analysis', {}).get('vwap', {}).get('analysis', ''),
                                                                vwap_support_trend=analysis_data.get('indicators_analysis', {}).get('vwap', {}).get('support_trend', 'neutral'),
                                                                funding_rate_analysis=analysis_data.get('indicators_analysis', {}).get('funding_rate', {}).get('analysis', ''),
                                                                funding_rate_support_trend=analysis_data.get('indicators_analysis', {}).get('funding_rate', {}).get('support_trend', 'neutral'),
                                                                exchange_netflow_analysis=analysis_data.get('indicators_analysis', {}).get('exchange_netflow', {}).get('analysis', ''),
                                                                exchange_netflow_support_trend=analysis_data.get('indicators_analysis', {}).get('exchange_netflow', {}).get('support_trend', 'neutral'),
                                                                nupl_analysis=analysis_data.get('indicators_analysis', {}).get('nupl', {}).get('analysis', ''),
                                                                nupl_support_trend=analysis_data.get('indicators_analysis', {}).get('nupl', {}).get('support_trend', 'neutral'),
                                                                mayer_multiple_analysis=analysis_data.get('indicators_analysis', {}).get('mayer_multiple', {}).get('analysis', ''),
                                                                mayer_multiple_support_trend=analysis_data.get('indicators_analysis', {}).get('mayer_multiple', {}).get('support_trend', 'neutral'),
                                                                trading_action=trading_advice.get('action', ''),
                                                                trading_reason=trading_advice.get('reason', ''),
                                                                entry_price=entry_price,
                                                                stop_loss=trading_advice.get('stop_loss') or 0,
                                                                take_profit=trading_advice.get('take_profit') or 0,
                                                                risk_level=analysis_data.get('risk_assessment', {}).get('level', ''),
                                                                risk_score=analysis_data.get('risk_assessment', {}).get('score', 50),
                                                                risk_details=analysis_data.get('risk_assessment', {}).get('details', [])
                                                            )
                                                            print("[DEBUG] 分析报告已保存")
                                                            return report
                                        except Exception as e:
                                            print(f"处理消息列表时发生错误: {str(e)}")
                                            return None
                                    else:
                                        print(f"[DEBUG] Coze 还未完成，等待 {retry_interval} 秒...")
                                        time.sleep(retry_interval)
                                        retry_interval = min(retry_interval * 1.5, max_retry_interval)
                                        retry_count += 1
                                        continue
                        else:
                            print(f"[DEBUG] Coze 获取对话状态失败: HTTP状态码 {status_response.status_code}")
                            time.sleep(retry_interval)
                            retry_interval = min(retry_interval * 1.5, max_retry_interval)
                            retry_count += 1
                            continue
                    except Exception as e:
                        print(f"[DEBUG] 轮询状态时发生错误: {str(e)}")
                        time.sleep(retry_interval)
                        retry_interval = min(retry_interval * 1.5, max_retry_interval)
                        retry_count += 1
                print("达到最大重试次数，未能获取到有效响应")
                return None
            except Exception as e:
                print(f"调用 Coze API 时发生错误: {str(e)}")
                return None
        except Exception as e:
            print(f"生成报告时发生错误: {str(e)}")
            return None

    def _build_prompt(self, technical_data: Dict[str, Any], _: str) -> str:
        formatted_data = self._format_technical_data_for_prompt(technical_data)
        return formatted_data

    def _format_technical_data_for_prompt(self, technical_data: Dict[str, Any]) -> str:
        """
        将技术指标数据格式化为字符串，便于插入到 prompt 中
        """
        try:
            return json.dumps(technical_data, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"格式化技术指标数据失败: {str(e)}")
            return str(technical_data)

    def _extract_json_from_content(self, content: str) -> Optional[Dict[str, Any]]:
        """
        从 Coze API 返回的内容中提取 JSON 数据。
        由于 Coze 可能返回带有额外文本的 JSON，我们需要提取出 JSON 部分。
        """
        try:
            # 如果内容本身就是合法的 JSON，直接解析
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                pass

            # 尝试从内容中提取 JSON 部分
            # 1. 查找第一个 '{' 和最后一个 '}'
            start = content.find('{')
            end = content.rfind('}')
            if start != -1 and end != -1 and start < end:
                json_str = content[start:end + 1]
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    pass

            # 2. 如果上述方法都失败，尝试使用正则表达式匹配 JSON 对象
            import re
            json_pattern = r'\{[^{}]*\}'
            matches = re.finditer(json_pattern, content)
            for match in matches:
                try:
                    json_str = match.group()
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    continue

            print(f"无法从内容中提取有效的 JSON: {content[:200]}...")
            return None

        except Exception as e:
            print(f"提取 JSON 时发生错误: {str(e)}")
            return None

    def _get_china_stock_technical_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取A股技术指标数据"""
        try:
            from .services.technical_analysis import TechnicalAnalysisService

            print(f"[DEBUG] 开始获取A股 {symbol} 的技术指标数据")

            # 使用技术分析服务获取A股数据
            ta_service = TechnicalAnalysisService()
            result = ta_service.get_all_indicators(symbol)

            if result.get('status') == 'success':
                data = result.get('data', {})
                print(f"[DEBUG] A股技术分析成功，数据: {data}")

                # 从技术分析数据中提取当前价格
                current_price = data.get('current_price', 0)

                # 如果技术分析数据中没有当前价格，尝试从Tushare API获取
                if not current_price:
                    try:
                        ta_service = TechnicalAnalysisService()
                        current_price = ta_service.tushare_api.get_realtime_price(symbol)
                        if not current_price:
                            current_price = 0
                    except Exception as e:
                        print(f"[DEBUG] 获取A股实时价格失败: {str(e)}")
                        current_price = 0

                # 格式化数据以匹配预期的结构
                formatted_data = {
                    'current_price': current_price,
                    'indicators': data.get('indicators', data)
                }

                print(f"[DEBUG] 格式化后的A股数据: current_price={current_price}")
                return formatted_data
            else:
                print(f"[DEBUG] A股技术分析失败: {result.get('message')}")
                return None

        except Exception as e:
            print(f"[DEBUG] 获取A股技术数据时出错: {str(e)}")
            return None