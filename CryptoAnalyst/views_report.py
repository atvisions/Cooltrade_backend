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
from .models import Token, Chain, AnalysisReport, TechnicalAnalysis
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
            # 只处理英文
            language = 'en-US'
            force_refresh = request.GET.get('force_refresh', 'false').lower() == 'true'
            print(f"接收到请求参数 - symbol: {symbol}, force_refresh: {force_refresh}")

            # 获取或创建链记录
            chain, _ = Chain.objects.get_or_create(
                chain=symbol,
                defaults={
                    'is_active': True,
                    'is_testnet': False
                }
            )
            token, _ = Token.objects.get_or_create(
                symbol=symbol,
                defaults={
                    'chain': chain,
                    'name': symbol
                }
            )
            time_window = timezone.now() - timedelta(hours=24)
            latest_analysis = TechnicalAnalysis.objects.filter(
                token=token,
                timestamp__gte=time_window
            ).order_by('-timestamp').first()

            if not latest_analysis:
                technical_data = self._get_technical_data(symbol)
                if not technical_data:
                    return Response({
                        'status': 'error',
                        'message': 'Failed to get technical indicator data'
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                indicators = technical_data.get('indicators', {})
                def get_indicator_value(indicator_data, default=0):
                    if isinstance(indicator_data, dict):
                        return indicator_data.get('value', default)
                    return indicator_data if indicator_data is not None else default
                def get_macd_value(macd_data, key, default=0):
                    if isinstance(macd_data, dict):
                        return macd_data.get(key, default)
                    return default
                def get_bollinger_value(bollinger_data, key, default=0):
                    if isinstance(bollinger_data, dict):
                        return bollinger_data.get(key, default)
                    return default
                def get_dmi_value(dmi_data, key, default=0):
                    if isinstance(dmi_data, dict):
                        return dmi_data.get(key, default)
                    return default
                now = timezone.now()
                period_hour = (now.hour // 12) * 12
                period_start = now.replace(minute=0, second=0, microsecond=0, hour=period_hour)
                latest_analysis, _ = TechnicalAnalysis.objects.get_or_create(
                    token=token,
                    period_start=period_start,
                    defaults={
                        'timestamp': now,
                        'rsi': get_indicator_value(indicators.get('rsi')),
                        'macd_line': get_macd_value(indicators.get('macd'), 'macd_line'),
                        'macd_signal': get_macd_value(indicators.get('macd'), 'signal_line'),
                        'macd_histogram': get_macd_value(indicators.get('macd'), 'histogram'),
                        'bollinger_upper': get_bollinger_value(indicators.get('bollinger_bands'), 'upper'),
                        'bollinger_middle': get_bollinger_value(indicators.get('bollinger_bands'), 'middle'),
                        'bollinger_lower': get_bollinger_value(indicators.get('bollinger_bands'), 'lower'),
                        'bias': get_indicator_value(indicators.get('bias')),
                        'psy': get_indicator_value(indicators.get('psy')),
                        'dmi_plus': get_dmi_value(indicators.get('dmi'), 'plus_di'),
                        'dmi_minus': get_dmi_value(indicators.get('dmi'), 'minus_di'),
                        'dmi_adx': get_dmi_value(indicators.get('dmi'), 'adx'),
                        'vwap': get_indicator_value(indicators.get('vwap')),
                        'funding_rate': get_indicator_value(indicators.get('funding_rate')),
                        'exchange_netflow': get_indicator_value(indicators.get('exchange_netflow')),
                        'nupl': get_indicator_value(indicators.get('nupl')),
                        'mayer_multiple': get_indicator_value(indicators.get('mayer_multiple'))
                    }
                )

            print(f"get_report 接口调用，将生成全新的 {symbol} 的英文报告（不使用缓存）")
            technical_data = self._get_technical_data(symbol)
            if not technical_data:
                return Response({
                    'status': 'error',
                    'message': 'Failed to get technical indicator data'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            report = self._generate_and_save_report(token, technical_data, 'en-US')
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
                    'analysis': report.rsi_analysis,
                    'support_trend': report.rsi_support_trend
                },
                'macd': {
                    'analysis': report.macd_analysis,
                    'support_trend': report.macd_support_trend
                },
                'bollinger_bands': {
                    'analysis': report.bollinger_analysis,
                    'support_trend': report.bollinger_support_trend
                },
                'bias': {
                    'analysis': report.bias_analysis,
                    'support_trend': report.bias_support_trend
                },
                'psy': {
                    'analysis': report.psy_analysis,
                    'support_trend': report.psy_support_trend
                },
                'dmi': {
                    'analysis': report.dmi_analysis,
                    'support_trend': report.dmi_support_trend
                },
                'vwap': {
                    'analysis': report.vwap_analysis,
                    'support_trend': report.vwap_support_trend
                },
                'funding_rate': {
                    'analysis': report.funding_rate_analysis,
                    'support_trend': report.funding_rate_support_trend
                },
                'exchange_netflow': {
                    'analysis': report.exchange_netflow_analysis,
                    'support_trend': report.exchange_netflow_support_trend
                },
                'nupl': {
                    'analysis': report.nupl_analysis,
                    'support_trend': report.nupl_support_trend
                },
                'mayer_multiple': {
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

    def _get_technical_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取技术指标数据

        get_report 接口专用：每次都调用 API 获取最新数据，不使用任何缓存
        """
        try:
            # 清理符号格式
            clean_symbol = symbol.upper().replace('USDT', '').replace('-PERP', '').replace('_PERP', '').replace('PERP', '')

            # 首先尝试使用完整的 symbol 查找代币记录
            token = Token.objects.filter(symbol=symbol.upper()).first()

            # 如果找不到，再尝试使用清理后的 symbol 查找
            if not token:
                token = Token.objects.filter(symbol=clean_symbol).first()

            if not token:
                # 记录日志，帮助调试
                print(f"未找到代币记录，尝试查找的符号: {symbol.upper()} 和 {clean_symbol}")

                # 查看数据库中有哪些代币记录
                all_tokens = list(Token.objects.all())
                token_symbols = [t.symbol for t in all_tokens]
                print(f"数据库中的代币记录: {token_symbols}")

                return None

            # get_report 接口：每次都调用 API 获取最新数据，绕过数据库缓存
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
                self._clear_all_cache(self.technical_indicators_view.ta_service, symbol)

            response = self.technical_indicators_view.get(mock_request, symbol)

            if response.status_code == status.HTTP_200_OK:
                data = response.data.get('data', {})

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

                return data

            print(f"获取技术指标数据失败: {response.data}")
            return None
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

    @transaction.atomic
    def _generate_and_save_report(self, token: Token, technical_data: Dict[str, Any], language: str) -> Optional[Dict[str, Any]]:
        try:
            print("[DEBUG] 开始生成并保存报告")
            current_price = technical_data.get('current_price', 0)
            if not current_price:
                print("无法获取当前价格")
                return None
            indicators = technical_data.get('indicators', {})
            def get_indicator_value(indicator_data, default=0):
                if isinstance(indicator_data, dict):
                    return indicator_data.get('value', default)
                return indicator_data if indicator_data is not None else default
            def get_macd_value(macd_data, key, default=0):
                if isinstance(macd_data, dict):
                    return macd_data.get(key, default)
                return default
            def get_bollinger_value(bollinger_data, key, default=0):
                if isinstance(bollinger_data, dict):
                    return bollinger_data.get(key, default)
                return default
            def get_dmi_value(dmi_data, key, default=0):
                if isinstance(dmi_data, dict):
                    return dmi_data.get(key, default)
                return default
            now = timezone.now()
            period_hour = (now.hour // 12) * 12
            period_start = now.replace(minute=0, second=0, microsecond=0, hour=period_hour)
            with transaction.atomic():
                technical_analysis, _ = TechnicalAnalysis.objects.get_or_create(
                    token=token,
                    period_start=period_start,
                    defaults={
                        'timestamp': now,
                        'rsi': get_indicator_value(indicators.get('rsi')),
                        'macd_line': get_macd_value(indicators.get('macd'), 'macd_line'),
                        'macd_signal': get_macd_value(indicators.get('macd'), 'signal_line'),
                        'macd_histogram': get_macd_value(indicators.get('macd'), 'histogram'),
                        'bollinger_upper': get_bollinger_value(indicators.get('bollinger_bands'), 'upper'),
                        'bollinger_middle': get_bollinger_value(indicators.get('bollinger_bands'), 'middle'),
                        'bollinger_lower': get_bollinger_value(indicators.get('bollinger_bands'), 'lower'),
                        'bias': get_indicator_value(indicators.get('bias')),
                        'psy': get_indicator_value(indicators.get('psy')),
                        'dmi_plus': get_dmi_value(indicators.get('dmi'), 'plus_di'),
                        'dmi_minus': get_dmi_value(indicators.get('dmi'), 'minus_di'),
                        'dmi_adx': get_dmi_value(indicators.get('dmi'), 'adx'),
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
                                                                    entry_price = None
                                                            report = AnalysisReport.objects.create(
                                                                token=token,
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
                                                                stop_loss=trading_advice.get('stop_loss', 0),
                                                                take_profit=trading_advice.get('take_profit', 0),
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