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

logger = logging.getLogger(__name__)

class CryptoReportAPIView(APIView):
    """加密货币分析报告API视图"""

    SUPPORTED_LANGUAGES = ['zh-CN', 'en-US', 'ja-JP', 'ko-KR']
    COZE_BOT_IDS = {
        'zh-CN': settings.COZE_BOT_ID_ZH,
        'en-US': settings.COZE_BOT_ID_EN,
        'ja-JP': settings.COZE_BOT_ID_JA,
        'ko-KR': settings.COZE_BOT_ID_KO
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.technical_indicators_view = TechnicalIndicatorsDataAPIView(internal_call=True)
        self._init_coze_api()

    def _init_coze_api(self):
        """初始化 Coze API 配置"""
        # 从 settings 获取 API 密钥
        self.coze_api_key = settings.COZE_API_KEY

        # 从 settings 获取 API URL
        self.coze_api_url = settings.COZE_API_URL

        # 确保 API URL 是正确的
        # 根据 old.py 文件，API URL 应该是 https://api.coze.com
        # 不需要 /api/v3 后缀，因为我们会在构建具体 API 端点时添加 /v3/chat 等
        if self.coze_api_url.endswith('/api/v3'):
            self.coze_api_url = self.coze_api_url.replace('/api/v3', '')

    def get(self, request, symbol: str) -> Response:
        """获取加密货币分析报告

        Args:
            request: HTTP请求对象
            symbol: 代币符号，例如 'BTCUSDT'

        Returns:
            Response: 包含分析报告的响应
        """
        try:
            # 获取语言参数
            language = request.GET.get('language', 'zh-CN')

            # 获取强制刷新参数
            force_refresh = request.GET.get('force_refresh', 'false').lower() == 'true'
            logger.info(f"接收到请求参数 - symbol: {symbol}, language: {language}, force_refresh: {force_refresh}, 原始参数: {request.GET.get('force_refresh', 'false')}")

            # 验证语言支持
            if language not in self.SUPPORTED_LANGUAGES:
                return Response({
                    'status': 'error',
                    'message': f'不支持的语言: {language}。支持的语言: {", ".join(self.SUPPORTED_LANGUAGES)}'
                }, status=status.HTTP_400_BAD_REQUEST)

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
            # 创建新交易对记录

            # 获取最新的技术分析记录（24小时内）
            time_window = timezone.now() - timedelta(hours=24)
            latest_analysis = TechnicalAnalysis.objects.filter(
                token=token,
                timestamp__gte=time_window
            ).order_by('-timestamp').first()

            if not latest_analysis:
                # 没有技术分析，走获取技术参数逻辑并新建 TechnicalAnalysis
                technical_data = self._get_technical_data(symbol)
                if not technical_data:
                    return Response({
                        'status': 'error',
                        'message': '获取技术指标数据失败'
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

            # 查询是否已有与该技术分析关联的英文报告
            latest_english_report = AnalysisReport.objects.filter(
                token=token,
                language='en-US',
                technical_analysis=latest_analysis
            ).first()

            # get_report 接口每次都生成全新报告，不使用任何缓存
            logger.info(f"get_report 接口调用，将生成全新的 {symbol} 的 {language} 报告（不使用缓存）")

            # 没有则生成新报告
            if language == 'en-US':
                # 英文报告直接生成
                technical_data = self._get_technical_data(symbol)
                if not technical_data:
                    error_messages = {
                        'zh-CN': '获取技术指标数据失败',
                        'en-US': 'Failed to get technical indicator data',
                        'ja-JP': 'テクニカル指標データの取得に失敗しました',
                        'ko-KR': '기술적 지표 데이터 가져오기에 실패했습니다'
                    }
                    return Response({
                        'status': 'error',
                        'message': error_messages.get(language, error_messages['en-US'])
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                report = self._generate_and_save_report(token, technical_data, language)
            else:
                # 非英文报告，总是基于最新的英文报告
                # 如果前面的代码已经找到了最新的英文报告，直接使用
                if not latest_english_report:
                    # 没有找到最新的英文报告，需要生成
                    technical_data = self._get_technical_data(symbol)
                    if not technical_data:
                        error_messages = {
                            'zh-CN': '获取技术指标数据失败',
                            'en-US': 'Failed to get technical indicator data',
                            'ja-JP': 'テクニカル指標データの取得に失敗しました',
                            'ko-KR': '기술적 지표 데이터 가져오기에 실패했습니다'
                        }
                        return Response({
                            'status': 'error',
                            'message': error_messages.get(language, error_messages['en-US'])
                        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                    latest_english_report = self._generate_and_save_report(token, technical_data, 'en-US')

                # 确保我们有英文报告
                if not latest_english_report:
                    error_messages = {
                        'zh-CN': '生成英文报告失败，无法翻译',
                        'en-US': 'Failed to generate English report, cannot translate',
                        'ja-JP': '英語レポートの生成に失敗しました、翻訳できません',
                        'ko-KR': '영어 보고서 생성에 실패했습니다, 번역할 수 없습니다'
                    }
                    return Response({
                        'status': 'error',
                        'message': error_messages.get(language, error_messages['en-US'])
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

                # 翻译最新的英文报告
                report = self._translate_report(token, latest_english_report, language)

                # 记录日志
                logger.info(f"基于最新英文报告 (ID: {latest_english_report.id}, 时间: {latest_english_report.timestamp}) 生成 {language} 报告")

            if not report:
                # 根据语言返回相应的错误信息
                error_messages = {
                    'zh-CN': '生成分析报告失败',
                    'en-US': 'Failed to generate analysis report',
                    'ja-JP': '分析レポートの生成に失敗しました',
                    'ko-KR': '분석 보고서 생성에 실패했습니다'
                }
                return Response({
                    'status': 'error',
                    'message': error_messages.get(language, error_messages['en-US'])
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
            logger.error(f"生成分析报告时发生错误: {str(e)}", exc_info=True)
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
                logger.error(f"未找到代币记录，尝试查找的符号: {symbol.upper()} 和 {clean_symbol}")

                # 查看数据库中有哪些代币记录
                all_tokens = list(Token.objects.all())
                token_symbols = [t.symbol for t in all_tokens]
                logger.info(f"数据库中的代币记录: {token_symbols}")

                return None

            # get_report 接口：每次都调用 API 获取最新数据，绕过数据库缓存
            logger.info(f"get_report 接口：直接调用 API 获取 {symbol} 的最新技术指标数据")

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
                        logger.error(f"获取实时价格失败: {str(e)}")

                return data

            logger.error(f"获取技术指标数据失败: {response.data}")
            return None
        except Exception as e:
            logger.error(f"获取技术指标数据时发生错误: {str(e)}", exc_info=True)
            return None

    def _clear_all_cache(self, ta_service, symbol: str):
        """清除指定代币的所有缓存"""
        try:
            logger.info(f"清除 {symbol} 的所有缓存")

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

            logger.info(f"已清除 {symbol} 的所有缓存")

        except Exception as e:
            logger.error(f"清除缓存时出错: {str(e)}")
            # 即使清除缓存失败，也继续执行

    @transaction.atomic
    def _generate_and_save_report(self, token: Token, technical_data: Dict[str, Any], language: str) -> Optional[Dict[str, Any]]:
        """生成并保存分析报告，包含自我修复功能"""
        try:
            # 获取当前价格，确保不为空
            current_price = technical_data.get('current_price', 0)
            if not current_price:
                logger.error("无法获取当前价格")
                return None

            # 首先创建或获取技术分析记录
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

            # 使用事务确保数据一致性
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

            # 查找上一份报告（同一代币、同一语言，最近7天内）
            time_window = timezone.now() - timedelta(days=7)
            previous_report = AnalysisReport.objects.filter(
                token=token,
                language=language,
                timestamp__gte=time_window
            ).order_by('-timestamp').first()

            # 获取对应语言的 Bot ID
            bot_id = self.COZE_BOT_IDS.get(language)
            if not bot_id:
                logger.error(f"未找到语言 {language} 对应的 Coze Bot ID")
                return None

            # 如果有上一份报告，构建优化提示
            if previous_report and language == 'en-US':  # 只对英文报告进行自我修复
                logger.info(f"找到上一份报告 ID: {previous_report.id}，时间: {previous_report.timestamp}，将进行自我修复")
                prompt = self._build_optimization_prompt(technical_data, previous_report, language)
                logger.info("已构建优化提示词，包含上一份报告的内容和技术指标变化")
            else:
                if language == 'en-US':
                    logger.info(f"没有找到上一份报告，将生成全新的报告")
                prompt = self._build_prompt(technical_data, language)

            # 调用 Coze API 创建对话
            chat_url = f"{self.coze_api_url}/v3/chat"
            logger.info(f"调用 Coze API 创建对话: {chat_url}")

            # 构建请求体
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

            # 构建请求头
            headers = {
                "Authorization": f"Bearer {self.coze_api_key}",
                "Content-Type": "application/json",
                "Accept": "*/*",
                "Connection": "keep-alive"
            }

            # 发送请求创建对话，增加重试机制
            max_retries = 3
            retry_count = 0
            retry_interval = 1.0
            max_retry_interval = 5.0
            response = None

            while retry_count < max_retries:
                try:
                    response = requests.post(
                        chat_url,
                        headers=headers,
                        json=payload,
                        timeout=30,
                        verify=True
                    )

                    if response.status_code == 200:
                        break
                    else:
                        logger.warning(f"创建对话请求失败，状态码: {response.status_code}，响应: {response.text}")
                        retry_count += 1
                        if retry_count < max_retries:
                            time.sleep(retry_interval)
                            retry_interval = min(retry_interval * 1.5, max_retry_interval)
                        continue

                except requests.exceptions.Timeout:
                    logger.warning(f"创建对话请求超时，重试 {retry_count + 1}/{max_retries}")
                    retry_count += 1
                    if retry_count < max_retries:
                        time.sleep(retry_interval)
                        retry_interval = min(retry_interval * 1.5, max_retry_interval)
                    continue

                except requests.exceptions.ConnectionError as e:
                    logger.warning(f"创建对话连接错误: {str(e)}，重试 {retry_count + 1}/{max_retries}")
                    retry_count += 1
                    if retry_count < max_retries:
                        time.sleep(retry_interval)
                        retry_interval = min(retry_interval * 1.5, max_retry_interval)
                    continue

                except Exception as e:
                    logger.error(f"创建对话时发生未知错误: {str(e)}")
                    retry_count += 1
                    if retry_count < max_retries:
                        time.sleep(retry_interval)
                        retry_interval = min(retry_interval * 1.5, max_retry_interval)
                    continue

            if not response or retry_count >= max_retries:
                logger.error("创建对话失败，已达到最大重试次数")
                return None

            # 解析响应
            try:
                response_data = response.json()
                if response_data.get('code') != 0:
                    logger.error(f"Coze API 响应错误: {response_data}")
                    return None

                # 获取对话ID和会话ID
                data = response_data.get('data', {})
                chat_id = data.get('id')
                conversation_id = data.get('conversation_id')

                if not chat_id or not conversation_id:
                    logger.error("创建对话响应中缺少必要的ID")
                    return None

                # 轮询获取对话结果
                max_poll_retries = 30  # 增加最大重试次数
                poll_retry_count = 0
                poll_retry_interval = 2.0  # 增加初始重试间隔
                max_poll_retry_interval = 8.0  # 增加最大重试间隔

                # 添加初始延迟
                time.sleep(3.0)  # 增加初始延迟

                while poll_retry_count < max_poll_retries:
                    try:
                        # 获取对话状态
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
                                                # 处理消息列表数据
                                                messages = []
                                                if isinstance(messages_data.get('data'), dict):
                                                    messages = messages_data.get('data', {}).get('messages', [])
                                                elif isinstance(messages_data.get('data'), list):
                                                    messages = messages_data.get('data', [])
                                                else:
                                                    logger.error(f"无法解析消息列表格式: {messages_data}")
                                                    continue

                                                for message in messages:
                                                    if message.get('role') == 'assistant' and message.get('type') == 'answer':
                                                        content = message.get('content', '')
                                                        if content and content != '###':
                                                            # 打印 Coze 返回的原始内容用于调试
                                                            logger.info(f"=== Coze 原始响应内容 (生成报告) ===")
                                                            logger.info(f"Content length: {len(content)}")
                                                            logger.info(f"Content: {content}")
                                                            logger.info(f"=== Coze 原始响应内容结束 ===")

                                                            # 解析翻译后的内容
                                                            translated_data = self._extract_json_from_content(content)
                                                            if translated_data:
                                                                # 提取 trading_advice
                                                                trading_advice = translated_data.get('trading_advice', {})
                                                                # 确保 entry_price 不为空
                                                                entry_price = trading_advice.get('entry_price', current_price)
                                                                if not entry_price:
                                                                    entry_price = current_price

                                                                # 创建新的分析报告
                                                                # 记录是否是自我修复的报告
                                                                is_self_repair = 'request_type' in technical_data and technical_data.get('request_type') == 'optimization'
                                                                if is_self_repair and language == 'en-US':
                                                                    logger.info(f"生成自我修复的报告: {token.symbol}")

                                                                translated_report = AnalysisReport.objects.create(
                                                                    token=token,
                                                                    technical_analysis=technical_analysis,
                                                                    timestamp=now,
                                                                    snapshot_price=current_price,
                                                                    language=language,
                                                                    trend_up_probability=translated_data.get('trend_analysis', {}).get('up_probability', 33),
                                                                    trend_sideways_probability=translated_data.get('trend_analysis', {}).get('sideways_probability', 34),
                                                                    trend_down_probability=translated_data.get('trend_analysis', {}).get('down_probability', 33),
                                                                    trend_summary=translated_data.get('trend_analysis', {}).get('summary', ''),
                                                                    rsi_analysis=translated_data.get('indicators_analysis', {}).get('rsi', {}).get('analysis', ''),
                                                                    rsi_support_trend=translated_data.get('indicators_analysis', {}).get('rsi', {}).get('support_trend', 'neutral'),
                                                                    macd_analysis=translated_data.get('indicators_analysis', {}).get('macd', {}).get('analysis', ''),
                                                                    macd_support_trend=translated_data.get('indicators_analysis', {}).get('macd', {}).get('support_trend', 'neutral'),
                                                                    bollinger_analysis=translated_data.get('indicators_analysis', {}).get('bollinger_bands', {}).get('analysis', ''),
                                                                    bollinger_support_trend=translated_data.get('indicators_analysis', {}).get('bollinger_bands', {}).get('support_trend', 'neutral'),
                                                                    bias_analysis=translated_data.get('indicators_analysis', {}).get('bias', {}).get('analysis', ''),
                                                                    bias_support_trend=translated_data.get('indicators_analysis', {}).get('bias', {}).get('support_trend', 'neutral'),
                                                                    psy_analysis=translated_data.get('indicators_analysis', {}).get('psy', {}).get('analysis', ''),
                                                                    psy_support_trend=translated_data.get('indicators_analysis', {}).get('psy', {}).get('support_trend', 'neutral'),
                                                                    dmi_analysis=translated_data.get('indicators_analysis', {}).get('dmi', {}).get('analysis', ''),
                                                                    dmi_support_trend=translated_data.get('indicators_analysis', {}).get('dmi', {}).get('support_trend', 'neutral'),
                                                                    vwap_analysis=translated_data.get('indicators_analysis', {}).get('vwap', {}).get('analysis', ''),
                                                                    vwap_support_trend=translated_data.get('indicators_analysis', {}).get('vwap', {}).get('support_trend', 'neutral'),
                                                                    funding_rate_analysis=translated_data.get('indicators_analysis', {}).get('funding_rate', {}).get('analysis', ''),
                                                                    funding_rate_support_trend=translated_data.get('indicators_analysis', {}).get('funding_rate', {}).get('support_trend', 'neutral'),
                                                                    exchange_netflow_analysis=translated_data.get('indicators_analysis', {}).get('exchange_netflow', {}).get('analysis', ''),
                                                                    exchange_netflow_support_trend=translated_data.get('indicators_analysis', {}).get('exchange_netflow', {}).get('support_trend', 'neutral'),
                                                                    nupl_analysis=translated_data.get('indicators_analysis', {}).get('nupl', {}).get('analysis', ''),
                                                                    nupl_support_trend=translated_data.get('indicators_analysis', {}).get('nupl', {}).get('support_trend', 'neutral'),
                                                                    mayer_multiple_analysis=translated_data.get('indicators_analysis', {}).get('mayer_multiple', {}).get('analysis', ''),
                                                                    mayer_multiple_support_trend=translated_data.get('indicators_analysis', {}).get('mayer_multiple', {}).get('support_trend', 'neutral'),
                                                                    trading_action=trading_advice.get('action', ''),
                                                                    trading_reason=trading_advice.get('reason', ''),
                                                                    entry_price=entry_price,
                                                                    stop_loss=trading_advice.get('stop_loss', 0),
                                                                    take_profit=trading_advice.get('take_profit', 0),
                                                                    risk_level=translated_data.get('risk_assessment', {}).get('level', ''),
                                                                    risk_score=translated_data.get('risk_assessment', {}).get('score', 50),
                                                                    risk_details=translated_data.get('risk_assessment', {}).get('details', [])
                                                                )
                                                                return translated_report
                                        except json.JSONDecodeError:
                                            pass
                                        except Exception:
                                            pass
                                        else:
                                            # 获取消息列表失败
                                            pass
                                else:
                                    # 获取对话状态响应错误
                                    pass
                        else:
                            # 获取对话状态失败
                            pass

                    except requests.exceptions.Timeout as e:
                        # 获取对话状态超时，重试
                        logger.warning(f"获取对话状态超时，重试 {poll_retry_count + 1}/{max_poll_retries}: {str(e)}")
                    except requests.exceptions.ConnectionError as e:
                        # 获取对话状态连接错误，重试
                        logger.warning(f"获取对话状态连接错误，重试 {poll_retry_count + 1}/{max_poll_retries}: {str(e)}")
                    except Exception as e:
                        # 获取对话状态时发生错误
                        logger.error(f"获取对话状态时发生未知错误，重试 {poll_retry_count + 1}/{max_poll_retries}: {str(e)}")
                        pass

                    poll_retry_count += 1
                    time.sleep(poll_retry_interval)
                    poll_retry_interval = min(poll_retry_interval * 1.5, max_poll_retry_interval)

                # 轮询Coze API未获得有效响应
                logger.error(f"轮询Coze API失败，已达到最大重试次数 {max_poll_retries}，总耗时约 {max_poll_retries * poll_retry_interval} 秒")
                return None

            except Exception as e:
                # 解析 Coze API 响应时发生错误
                logger.error(f"解析 Coze API 响应时发生错误: {str(e)}", exc_info=True)
                return None

        except Exception as e:
            # 生成并保存报告时发生错误
            logger.error(f"生成并保存报告时发生错误: {str(e)}", exc_info=True)
            return None

    def _build_prompt(self, technical_data: Dict[str, Any], _: str) -> str:
        """构建提示词

        由于 Coze 已经配置了提示语，我们只需要提交技术参数就可以了
        """
        # 格式化技术指标数据，确保格式一致
        formatted_data = self._format_technical_data_for_prompt(technical_data)

        # 直接返回格式化后的技术指标数据
        return formatted_data

    def _build_optimization_prompt(self, technical_data: Dict[str, Any], previous_report: AnalysisReport, _: str) -> str:
        """构建优化提示词，包含上一份报告的内容和技术指标变化

        Args:
            technical_data: 当前技术指标数据
            previous_report: 上一份报告对象
            _: 语言代码（未使用）

        Returns:
            str: 优化提示词
        """
        # 格式化当前技术指标数据
        current_indicators = self._format_technical_data_for_prompt(technical_data)

        # 获取上一份报告的技术指标数据
        previous_technical_analysis = previous_report.technical_analysis
        previous_indicators = {
            "price": previous_report.snapshot_price,
            "indicators": {
                "rsi": previous_technical_analysis.rsi,
                "macd": {
                    "macd_line": previous_technical_analysis.macd_line,
                    "signal_line": previous_technical_analysis.macd_signal,
                    "histogram": previous_technical_analysis.macd_histogram
                },
                "bollinger_bands": {
                    "upper": previous_technical_analysis.bollinger_upper,
                    "middle": previous_technical_analysis.bollinger_middle,
                    "lower": previous_technical_analysis.bollinger_lower
                },
                "bias": previous_technical_analysis.bias,
                "psy": previous_technical_analysis.psy,
                "dmi": {
                    "plus_di": previous_technical_analysis.dmi_plus,
                    "minus_di": previous_technical_analysis.dmi_minus,
                    "adx": previous_technical_analysis.dmi_adx
                },
                "vwap": previous_technical_analysis.vwap,
                "funding_rate": previous_technical_analysis.funding_rate,
                "exchange_netflow": previous_technical_analysis.exchange_netflow,
                "nupl": previous_technical_analysis.nupl,
                "mayer_multiple": previous_technical_analysis.mayer_multiple
            }
        }

        # 获取上一份报告的分析结果
        previous_analysis = {
            "trend_analysis": {
                "up_probability": previous_report.trend_up_probability,
                "sideways_probability": previous_report.trend_sideways_probability,
                "down_probability": previous_report.trend_down_probability,
                "summary": previous_report.trend_summary
            },
            "indicators_analysis": {
                "rsi": {
                    "analysis": previous_report.rsi_analysis,
                    "support_trend": previous_report.rsi_support_trend
                },
                "macd": {
                    "analysis": previous_report.macd_analysis,
                    "support_trend": previous_report.macd_support_trend
                },
                "bollinger_bands": {
                    "analysis": previous_report.bollinger_analysis,
                    "support_trend": previous_report.bollinger_support_trend
                },
                "bias": {
                    "analysis": previous_report.bias_analysis,
                    "support_trend": previous_report.bias_support_trend
                },
                "psy": {
                    "analysis": previous_report.psy_analysis,
                    "support_trend": previous_report.psy_support_trend
                },
                "dmi": {
                    "analysis": previous_report.dmi_analysis,
                    "support_trend": previous_report.dmi_support_trend
                },
                "vwap": {
                    "analysis": previous_report.vwap_analysis,
                    "support_trend": previous_report.vwap_support_trend
                },
                "funding_rate": {
                    "analysis": previous_report.funding_rate_analysis,
                    "support_trend": previous_report.funding_rate_support_trend
                },
                "exchange_netflow": {
                    "analysis": previous_report.exchange_netflow_analysis,
                    "support_trend": previous_report.exchange_netflow_support_trend
                },
                "nupl": {
                    "analysis": previous_report.nupl_analysis,
                    "support_trend": previous_report.nupl_support_trend
                },
                "mayer_multiple": {
                    "analysis": previous_report.mayer_multiple_analysis,
                    "support_trend": previous_report.mayer_multiple_support_trend
                }
            },
            "trading_advice": {
                "action": previous_report.trading_action,
                "reason": previous_report.trading_reason,
                "entry_price": previous_report.entry_price,
                "stop_loss": previous_report.stop_loss,
                "take_profit": previous_report.take_profit
            },
            "risk_assessment": {
                "level": previous_report.risk_level,
                "score": previous_report.risk_score,
                "details": previous_report.risk_details
            }
        }

        # 构建优化提示词
        optimization_prompt = {
            "current_data": json.loads(current_indicators),
            "previous_data": previous_indicators,
            "previous_analysis": previous_analysis,
            "timestamp": previous_report.timestamp.isoformat(),
            "request_type": "optimization"
        }

        # 将优化提示词转换为字符串
        return json.dumps(optimization_prompt, ensure_ascii=False, indent=2)

    def _format_technical_data_for_prompt(self, technical_data: Dict[str, Any]) -> str:
        """格式化技术指标数据，确保格式一致"""
        try:
            # 检查技术指标数据的格式
            if 'indicators' in technical_data:
                # 来自 API 的数据格式
                indicators = technical_data.get('indicators', {})
                current_price = technical_data.get('current_price', 0)

                # 使用统一的英文格式
                formatted_data = {
                    "price": current_price,
                    "indicators": {
                        "rsi": indicators.get('rsi', 0),
                        "macd": {
                            "macd_line": indicators.get('macd_line', 0),
                            "signal_line": indicators.get('macd_signal', 0),
                            "histogram": indicators.get('macd_histogram', 0)
                        },
                        "bollinger_bands": {
                            "upper": indicators.get('bollinger_upper', 0),
                            "middle": indicators.get('bollinger_middle', 0),
                            "lower": indicators.get('bollinger_lower', 0)
                        },
                        "bias": indicators.get('bias', 0),
                        "psy": indicators.get('psy', 0),
                        "dmi": {
                            "plus_di": indicators.get('dmi_plus', 0),
                            "minus_di": indicators.get('dmi_minus', 0),
                            "adx": indicators.get('dmi_adx', 0)
                        },
                        "vwap": indicators.get('vwap', 0),
                        "funding_rate": indicators.get('funding_rate', 0),
                        "exchange_netflow": indicators.get('exchange_netflow', 0),
                        "nupl": indicators.get('nupl', 0),
                        "mayer_multiple": indicators.get('mayer_multiple', 0)
                    }
                }
            else:
                # 直接使用传入的数据，但确保格式统一
                formatted_data = {
                    "price": technical_data.get('current_price', 0),
                    "indicators": technical_data.get('indicators', {})
                }

            # 将格式化后的数据转换为字符串
            import json
            formatted_str = json.dumps(formatted_data, ensure_ascii=False, indent=2)

            return formatted_str
        except Exception:
            # 格式化技术指标数据时发生错误
            # 如果格式化失败，直接返回原始数据的字符串表示
            return str(technical_data)

    def _handle_language_specific_json(self, content: str) -> Optional[Dict[str, Any]]:
        """处理不同语言的 JSON 格式"""
        try:
            # 日语格式处理
            if "上昇確率" in content:
                # 尝试提取日语 JSON 对象
                ja_pattern = r'\{"上昇確率":[^}]*,"横ばい確率":[^}]*,"下降確率":[^}]*,"トレンド概要":"[^"]*"\}'
                match = re.search(ja_pattern, content)
                if match:
                    ja_json = match.group(0)
                    return json.loads(ja_json)

            # 韩语格式处理
            elif "상승 확률" in content:
                # 尝试提取韩语 JSON 对象
                ko_pattern = r'\{"상승 확률":[^}]*,"횡보 확률":[^}]*,"하락 확률":[^}]*,"트렌드 요약":"[^"]*"\}'
                match = re.search(ko_pattern, content)
                if match:
                    ko_json = match.group(0)
                    return json.loads(ko_json)

            # 中文格式处理
            elif "上涨概率" in content:
                # 尝试提取中文 JSON 对象
                zh_pattern = r'\{"上涨概率":[^}]*,"横盘概率":[^}]*,"下跌概率":[^}]*,"趋势总结":"[^"]*"\}'
                match = re.search(zh_pattern, content)
                if match:
                    zh_json = match.group(0)
                    return json.loads(zh_json)

            # 英文格式处理
            elif "up_probability" in content:
                # 尝试提取英文 JSON 对象
                en_pattern = r'\{"up_probability":[^}]*,"sideways_probability":[^}]*,"down_probability":[^}]*,"trend_summary":"[^"]*"\}'
                match = re.search(en_pattern, content)
                if match:
                    en_json = match.group(0)
                    return json.loads(en_json)

            return None
        except Exception as e:
            logger.error(f"处理语言特定 JSON 时发生错误: {str(e)}")
            return None

    def _extract_json_from_content(self, content: str) -> Optional[Dict[str, Any]]:
        """从内容中提取JSON数据"""
        try:
            logger.info(f"=== 开始解析 JSON 内容 ===")
            logger.info(f"Content preview (first 500 chars): {content[:500]}")

            # 保存原始内容到文件，方便调试
            self._save_coze_response_to_file(content)

            # 检测语言（无需记录日志）

            # 首先尝试语言特定的 JSON 处理
            logger.info("尝试语言特定的 JSON 处理...")
            language_specific_result = self._handle_language_specific_json(content)
            if language_specific_result:
                logger.info("语言特定的 JSON 处理成功")
                return self._convert_chinese_to_english_fields(language_specific_result)
            else:
                logger.warning("语言特定的 JSON 处理失败")

            # 如果语言特定的处理失败，尝试直接解析
            try:
                logger.info("尝试直接解析 JSON...")
                analysis_result = json.loads(content)
                logger.info("直接解析 JSON 成功")
                return self._convert_chinese_to_english_fields(analysis_result)
            except json.JSONDecodeError as e:
                logger.warning(f"直接解析 JSON 失败: {str(e)}")
                # 直接解析JSON失败，尝试修复JSON格式
                try:
                    logger.info("开始尝试修复 JSON 格式...")
                    # 尝试修复JSON格式
                    # 1. 移除可能的markdown代码块标记
                    content = content.replace('```json', '').replace('```', '').strip()

                    # 1.5. 检查是否是截断的JSON，尝试补全
                    if not content.endswith('}') and not content.endswith(']'):
                        logger.info("检测到截断的JSON，尝试补全...")
                        # 计算未闭合的括号和引号
                        open_braces = content.count('{')
                        close_braces = content.count('}')
                        open_brackets = content.count('[')
                        close_brackets = content.count(']')

                        # 检查是否在字符串中
                        quote_count = content.count('"')
                        # 如果引号数量是奇数，说明有未闭合的字符串
                        if quote_count % 2 == 1:
                            content += '"'
                            logger.info("补全了未闭合的字符串")

                        # 补全数组
                        if open_brackets > close_brackets:
                            content += ']' * (open_brackets - close_brackets)
                            logger.info(f"补全了 {open_brackets - close_brackets} 个数组闭合符")

                        # 补全对象
                        if open_braces > close_braces:
                            content += '}' * (open_braces - close_braces)
                            logger.info(f"补全了 {open_braces - close_braces} 个对象闭合符")

                        # 尝试解析补全后的JSON
                        try:
                            logger.info("尝试解析补全后的JSON...")
                            analysis_result = json.loads(content)
                            logger.info("补全后的JSON解析成功！")
                            return self._convert_chinese_to_english_fields(analysis_result)
                        except json.JSONDecodeError as e:
                            logger.warning(f"补全后的JSON解析仍然失败: {str(e)}")
                            # 继续执行原有的修复逻辑

                    # 2. 修复未闭合的字符串
                    lines = content.split('\n')
                    fixed_lines = []
                    in_array = False
                    in_string = False
                    quote_char = None

                    for i, line in enumerate(lines):
                        # 检查是否在字符串中
                        j = 0
                        while j < len(line):
                            if line[j] == '\\' and j + 1 < len(line):
                                # 跳过转义字符
                                j += 2
                                continue

                            if line[j] == '"' and (j == 0 or line[j-1] != '\\'):
                                if not in_string:
                                    in_string = True
                                    quote_char = '"'
                                elif quote_char == '"':
                                    in_string = False
                                    quote_char = None

                            if line[j] == "'" and (j == 0 or line[j-1] != '\\'):
                                if not in_string:
                                    in_string = True
                                    quote_char = "'"
                                elif quote_char == "'":
                                    in_string = False
                                    quote_char = None

                            j += 1

                        # 如果行结束时仍在字符串中，添加结束引号
                        if in_string and i < len(lines) - 1:
                            line = line + quote_char
                            in_string = False
                            quote_char = None

                        # 处理数组
                        if '[' in line and ']' not in line:
                            in_array = True
                        if in_array and '"' in line and not line.strip().endswith('"') and not line.strip().endswith(','):
                            line = line.strip() + '"'
                        if in_array and ']' in line:
                            in_array = False

                        # 修复常见的JSON格式错误
                        # 1. 修复缺少逗号的问题
                        if i < len(lines) - 1 and line.strip().endswith('"') and not line.strip().endswith('",'):
                            next_line = lines[i+1].strip()
                            if next_line.startswith('"') or next_line.startswith('{') or next_line.startswith('['):
                                line = line + ','

                        # 2. 修复缺少冒号的问题
                        if '"' in line and ':' not in line and i < len(lines) - 1:
                            next_line = lines[i+1].strip()
                            if next_line.startswith('"') or next_line.startswith('{') or next_line.startswith('['):
                                line = line + ': '

                        fixed_lines.append(line)

                    fixed_content = '\n'.join(fixed_lines)

                    # 3. 确保对象和数组正确闭合
                    open_braces = fixed_content.count('{')
                    close_braces = fixed_content.count('}')
                    if open_braces > close_braces:
                        fixed_content = fixed_content + '}' * (open_braces - close_braces)

                    open_brackets = fixed_content.count('[')
                    close_brackets = fixed_content.count(']')
                    if open_brackets > close_brackets:
                        fixed_content = fixed_content + ']' * (open_brackets - close_brackets)

                    # 4. 尝试使用正则表达式提取有效的JSON对象
                    json_pattern = r'\{(?:[^{}]|(?:\{(?:[^{}]|(?:\{[^{}]*\}))*\}))*\}'
                    matches = re.finditer(json_pattern, fixed_content)

                    # 按长度排序匹配结果，优先使用最长的匹配（可能是最完整的JSON）
                    potential_jsons = sorted([match.group(0) for match in matches], key=len, reverse=True)

                    for potential_json in potential_jsons:
                        try:
                            analysis_result = json.loads(potential_json)
                            # 检查是否是有意义的JSON（至少包含一些关键字段）
                            if any(key in analysis_result for key in ["上昇確率", "上涨概率", "상승 확률", "市場トレンド分析", "市场趋势分析", "시장 트렌드 분석"]):
                                return self._convert_chinese_to_english_fields(analysis_result)
                        except json.JSONDecodeError:
                            continue

                    # 如果没有找到完整的JSON对象，尝试提取部分JSON对象
                    # 例如，尝试提取趋势分析部分
                    trend_patterns = [
                        r'\{"上昇確率":[^}]*,"横ばい確率":[^}]*,"下降確率":[^}]*,"トレンド概要":"[^"]*"\}',  # 日语
                        r'\{"上涨概率":[^}]*,"横盘概率":[^}]*,"下跌概率":[^}]*,"趋势总结":"[^"]*"\}',  # 中文
                        r'\{"상승 확률":[^}]*,"횡보 확률":[^}]*,"하락 확률":[^}]*,"트렌드 요약":"[^"]*"\}'   # 韩语
                    ]

                    for pattern in trend_patterns:
                        match = re.search(pattern, fixed_content)
                        if match:
                            try:
                                trend_json = match.group(0)
                                # 修复可能的JSON格式问题
                                trend_json = trend_json.replace('""', '"')
                                analysis_result = json.loads(trend_json)
                                return self._convert_chinese_to_english_fields(analysis_result)
                            except json.JSONDecodeError:
                                continue

                    # 5. 尝试解析修复后的JSON
                    try:
                        analysis_result = json.loads(fixed_content)
                        return self._convert_chinese_to_english_fields(analysis_result)
                    except json.JSONDecodeError:
                        # 6. 尝试使用更宽松的JSON解析器
                        try:
                            # 尝试使用更宽松的JSON解析方法
                            # 注意：这些库可能未安装，所以使用try-except捕获ImportError
                            try:
                                # 尝试使用 json5 库
                                try:
                                    # 动态导入，避免IDE警告
                                    json5 = __import__('json5')
                                    analysis_result = json5.loads(fixed_content)
                                    return self._convert_chinese_to_english_fields(analysis_result)
                                except (ImportError, ModuleNotFoundError):
                                    # json5库未安装，尝试其他方法
                                    pass

                                # 尝试使用 demjson3 库
                                try:
                                    # 动态导入，避免IDE警告
                                    demjson3 = __import__('demjson3')
                                    analysis_result = demjson3.decode(fixed_content)
                                    return self._convert_chinese_to_english_fields(analysis_result)
                                except (ImportError, ModuleNotFoundError):
                                    # demjson3库未安装，尝试其他方法
                                    pass
                            except Exception as e:
                                logger.debug(f"尝试使用宽松JSON解析器失败: {str(e)}")
                                pass

                            # 尝试使用 ast.literal_eval（Python内置的安全求值函数）
                            try:
                                import ast
                                # 将JSON格式的字符串转换为Python字典
                                fixed_content = fixed_content.replace('null', 'None').replace('true', 'True').replace('false', 'False')
                                analysis_result = ast.literal_eval(fixed_content)
                                return self._convert_chinese_to_english_fields(analysis_result)
                            except (SyntaxError, ValueError):
                                # ast.literal_eval解析失败
                                pass
                        except Exception:
                            # 所有宽松JSON解析器都失败
                            pass

                    # 7. 如果所有尝试都失败，返回 None 表示解析失败
                    logger.error("Coze API response parsing failed after all attempts")
                    return None

                except Exception:
                    # 修复JSON格式失败，返回 None 表示解析失败
                    logger.error("JSON format fixing failed")
                    return None

        except Exception:
            # 处理语言特定 JSON 时发生错误
            return None

    def _save_coze_response_to_file(self, _: str) -> None:
        """保存Coze响应内容到文件"""
        # 此功能已禁用，不再保存响应到文件
        pass



    def _convert_chinese_to_english_fields(self, analysis_result: Dict[str, Any]) -> Dict[str, Any]:
        """将中文/日语/韩语字段名转换为英文字段名"""
        try:
            # 检查是否已经是英文格式
            if "trend_analysis" in analysis_result:
                return analysis_result

            # 检查是否是部分提取的JSON数据
            # 如果只有趋势分析部分，说明解析不完整，返回 None
            if "上昇確率" in analysis_result or "上涨概率" in analysis_result or "상승 확률" in analysis_result:
                logger.warning("Only partial trend analysis data found, parsing incomplete")
                return None

            # 字段映射
            field_mapping = {
                # 中文字段映射
                "市场趋势分析": "trend_analysis",
                "上涨概率": "up_probability",
                "横盘概率": "sideways_probability",
                "下跌概率": "down_probability",
                "趋势总结": "summary",
                "技术指标分析": "indicators_analysis",
                "RSI": "rsi",
                "MACD": "macd",
                "布林带": "bollinger_bands",
                "BIAS": "bias",
                "PSY": "psy",
                "DMI": "dmi",
                "VWAP": "vwap",
                "资金费率": "funding_rate",
                "交易所净流入": "exchange_netflow",
                "NUPL": "nupl",
                "Mayer Multiple": "mayer_multiple",
                "指标值": "value",
                "分析": "analysis",
                "趋势支持": "support_trend",
                "MACD线": "macd_line",
                "信号线": "signal_line",
                "柱状图": "histogram",
                "上轨": "upper",
                "中轨": "middle",
                "下轨": "lower",
                "+DI": "plus_di",
                "-DI": "minus_di",
                "ADX": "adx",
                "建议操作": "trading_advice",
                "操作": "action",
                "建议原因": "reason",
                "入场价格": "entry_price",
                "止损价格": "stop_loss",
                "止盈价格": "take_profit",
                "风险评估": "risk_assessment",
                "风险等级": "level",
                "风险分数": "score",
                "风险因素": "details",

                # 日语字段映射（新增）
                "市場トレンド分析": "trend_analysis",
                "上昇確率": "up_probability",
                "横ばい確率": "sideways_probability",
                "下降確率": "down_probability",
                "トレンド概要": "summary",
                "テクニカル指標分析": "indicators_analysis",
                "rsi": "rsi",
                "macd": "macd",
                "bollinger_bands": "bollinger_bands",
                "bias": "bias",
                "psy": "psy",
                "dmi": "dmi",
                "vwap": "vwap",
                "funding_rate": "funding_rate",
                "exchange_netflow": "exchange_netflow",
                "nupl": "nupl",
                "mayer_multiple": "mayer_multiple",
                "指標値": "value",
                "分析": "analysis",
                "トレンドサポート": "support_trend",
                "macd_line": "macd_line",
                "signal_line": "signal_line",
                "histogram": "histogram",
                "upper": "upper",
                "middle": "middle",
                "lower": "lower",
                "plus_di": "plus_di",
                "minus_di": "minus_di",
                "adx": "adx",
                "推奨アクション": "trading_advice",
                "アクション": "action",
                "推奨理由": "reason",
                "エントリー価格": "entry_price",
                "ストップロス": "stop_loss",
                "利益確定": "take_profit",
                "リスク評価": "risk_assessment",
                "リスクレベル": "level",
                "リスクスコア": "score",
                "リスク要因": "details",

                # 韩语字段映射（新增）
                "시장 트렌드 분석": "trend_analysis",
                "상승 확률": "up_probability",
                "횡보 확률": "sideways_probability",
                "하락 확률": "down_probability",
                "트렌드 요약": "summary",
                "기술적 지표 분석": "indicators_analysis",
                "지표값": "value",
                "분석": "analysis",
                "트렌드 지원": "support_trend",
                "거래 조언": "trading_advice",
                "행동": "action",
                "추천 이유": "reason",
                "진입 가격": "entry_price",
                "손절 가격": "stop_loss",
                "이익 실현 가격": "take_profit",
                "위험 평가": "risk_assessment",
                "위험 수준": "level",
                "위험 점수": "score",
                "위험 요소": "details"
            }
            # 在这里添加趋势支持值映射
            trend_support_mapping = {
                # 中文趋势支持值映射
                "支持当前趋势": "up",
                "中性": "neutral",
                "反对当前趋势": "down",
                # 日语趋势支持值映射
                "現在のトレンドをサポート": "up",
                "中立": "neutral",
                "現在のトレンドに反対": "down",
                # 韩语趋势支持值映射
                "현재 트렌드 지원": "up",
                "중립": "neutral",
                "현재 트렌드 반대": "down"
            }


            # 创建一个新的结果字典
            converted_result = {}

            # 转换顶层字段
            for trend_key in ["市场趋势分析", "市場トレンド分析", "시장 트렌드 분석"]:
                if trend_key in analysis_result:
                    trend_analysis = analysis_result[trend_key]
                    converted_result["trend_analysis"] = {
                        "up_probability": trend_analysis.get("上涨概率", trend_analysis.get("上昇確率", trend_analysis.get("상승 확률", 33))),
                        "sideways_probability": trend_analysis.get("横盘概率", trend_analysis.get("横ばい確率", trend_analysis.get("횡보 확률", 34))),
                        "down_probability": trend_analysis.get("下跌概率", trend_analysis.get("下降確率", trend_analysis.get("하락 확률", 33))),
                        "summary": trend_analysis.get("趋势总结", trend_analysis.get("トレンド概要", trend_analysis.get("트렌드 요약", "")))
                    }
                    break

            # 转换技术指标分析
            for indicators_key in ["技术指标分析", "テクニカル指標分析", "기술적 지표 분석"]:
                if indicators_key in analysis_result:
                    indicators = analysis_result[indicators_key]
                    converted_indicators = {}

                    # 处理每个指标
                    for indicator_name, indicator_data in indicators.items():
                        english_name = indicator_name.lower()  # 转换为小写以统一处理
                        if indicator_name in field_mapping:
                            english_name = field_mapping[indicator_name]

                        converted_indicator = {}

                        # 处理指标值
                        for value_key in ["指标值", "指標値", "지표값"]:
                            if value_key in indicator_data:
                                if isinstance(indicator_data[value_key], dict):
                                    # 处理复合指标值，如MACD、布林带、DMI
                                    value_dict = {}
                                    for key, val in indicator_data[value_key].items():
                                        if key in field_mapping:
                                            value_dict[field_mapping[key]] = val
                                        else:
                                            value_dict[key] = val
                                    converted_indicator["value"] = value_dict
                                else:
                                    # 处理简单指标值
                                    converted_indicator["value"] = indicator_data[value_key]
                                break

                        # 处理分析
                        for analysis_key in ["分析", "분석"]:
                            if analysis_key in indicator_data:
                                converted_indicator["analysis"] = indicator_data[analysis_key]
                                break

                        # 处理趋势支持
                        for support_key in ["趋势支持", "トレンドサポート", "트렌드 지원"]:
                            if support_key in indicator_data:
                                support_trend = indicator_data[support_key]
                                # 转换趋势支持值
                                converted_indicator["support_trend"] = trend_support_mapping.get(support_trend, "neutral")
                                break

                        converted_indicators[english_name] = converted_indicator

                    converted_result["indicators_analysis"] = converted_indicators
                    break

            # 转换建议操作
            for advice_key in ["建议操作", "推奨アクション", "거래 조언"]:
                if advice_key in analysis_result:
                    trading_advice = analysis_result[advice_key]
                    converted_result["trading_advice"] = {
                        "action": trading_advice.get("操作", trading_advice.get("アクション", trading_advice.get("행동", "等待"))),
                        "reason": trading_advice.get("建议原因", trading_advice.get("推奨理由", trading_advice.get("추천 이유", ""))),
                        "entry_price": trading_advice.get("入场价格", trading_advice.get("エントリー価格", trading_advice.get("진입 가격", 0))),
                        "stop_loss": trading_advice.get("止损价格", trading_advice.get("ストップロス", trading_advice.get("손절 가격", 0))),
                        "take_profit": trading_advice.get("止盈价格", trading_advice.get("利益確定", trading_advice.get("이익 실현 가격", 0)))
                    }
                    break

            # 转换风险评估
            for risk_key in ["风险评估", "リスク評価", "위험 평가"]:
                if risk_key in analysis_result:
                    risk_assessment = analysis_result[risk_key]
                    converted_result["risk_assessment"] = {
                        "level": risk_assessment.get("风险等级", risk_assessment.get("リスクレベル", risk_assessment.get("위험 수준", "中"))),
                        "score": risk_assessment.get("风险分数", risk_assessment.get("リスクスコア", risk_assessment.get("위험 점수", 50))),
                        "details": risk_assessment.get("风险因素", risk_assessment.get("リスク要因", risk_assessment.get("위험 요소", ["无法完成分析，使用默认风险评估"])))
                    }
                    break

            return converted_result
        except Exception:
            # 转换中文字段名时发生错误
            return analysis_result

    def _translate_report(self, token: Token, english_report: AnalysisReport, target_language: str) -> Optional[AnalysisReport]:
        """将英文报告翻译为目标语言

        Args:
            token: 代币对象
            english_report: 英文报告对象
            target_language: 目标语言代码

        Returns:
            Optional[AnalysisReport]: 翻译后的报告对象，如果翻译失败则返回 None
        """
        try:
            # 获取对应语言的 Bot ID
            bot_id = self.COZE_BOT_IDS.get(target_language)
            if not bot_id:
                logger.error(f"未找到语言 {target_language} 对应的 Coze Bot ID")
                return None

            # 构建翻译提示词
            prompt = self._build_translation_prompt(english_report, target_language)

            # 调用 Coze API 创建对话
            chat_url = f"{self.coze_api_url}/v3/chat"

            # 构建请求体
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

            # 构建请求头
            headers = {
                "Authorization": f"Bearer {self.coze_api_key}",
                "Content-Type": "application/json",
                "Accept": "*/*",
                "Connection": "keep-alive"
            }

            # 发送请求创建对话
            response = requests.post(
                chat_url,
                headers=headers,
                json=payload,
                timeout=30
            )

            if response.status_code != 200:
                return None

            # 解析响应
            try:
                response_data = response.json()
                if response_data.get('code') != 0:
                    return None

                # 获取对话ID和会话ID
                data = response_data.get('data', {})
                chat_id = data.get('id')
                conversation_id = data.get('conversation_id')

                if not chat_id or not conversation_id:
                    return None

                # 轮询获取对话结果
                max_retries = 30  # 增加最大重试次数
                retry_count = 0
                retry_interval = 2.0  # 增加初始重试间隔
                max_retry_interval = 8.0  # 增加最大重试间隔

                # 添加初始延迟
                time.sleep(3.0)  # 增加初始延迟

                while retry_count < max_retries:
                    try:
                        # 获取对话状态
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
                            timeout=30
                        )

                        if status_response.status_code == 200:
                            status_data = status_response.json()
                            if status_data.get('code') == 0:
                                data = status_data.get('data', {})
                                status = data.get('status')

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
                                        timeout=30
                                    )

                                    if messages_response.status_code == 200:
                                        try:
                                            messages_data = messages_response.json()
                                            if messages_data.get('code') == 0:
                                                # 处理消息列表数据
                                                messages = []
                                                if isinstance(messages_data.get('data'), dict):
                                                    messages = messages_data.get('data', {}).get('messages', [])
                                                elif isinstance(messages_data.get('data'), list):
                                                    messages = messages_data.get('data', [])
                                                else:
                                                    continue

                                                for message in messages:
                                                    if message.get('role') == 'assistant' and message.get('type') == 'answer':
                                                        content = message.get('content', '')
                                                        if content and content != '###':
                                                            # 打印 Coze 返回的原始内容用于调试
                                                            logger.info(f"=== Coze 原始响应内容 (翻译报告) ===")
                                                            logger.info(f"Target language: {target_language}")
                                                            logger.info(f"Content length: {len(content)}")
                                                            logger.info(f"Content: {content}")
                                                            logger.info(f"=== Coze 原始响应内容结束 ===")

                                                            # 解析翻译后的内容
                                                            translated_data = self._extract_json_from_content(content)
                                                            if translated_data:
                                                                # 创建新的分析报告
                                                                translated_report = AnalysisReport.objects.create(
                                                                    token=token,
                                                                    technical_analysis=english_report.technical_analysis,
                                                                    timestamp=timezone.now(),
                                                                    snapshot_price=english_report.snapshot_price,
                                                                    language=target_language,
                                                                    trend_up_probability=english_report.trend_up_probability,
                                                                    trend_sideways_probability=english_report.trend_sideways_probability,
                                                                    trend_down_probability=english_report.trend_down_probability,
                                                                    trend_summary=translated_data.get('trend_analysis', {}).get('summary', ''),
                                                                    rsi_analysis=translated_data.get('indicators_analysis', {}).get('rsi', {}).get('analysis', ''),
                                                                    rsi_support_trend=english_report.rsi_support_trend,
                                                                    macd_analysis=translated_data.get('indicators_analysis', {}).get('macd', {}).get('analysis', ''),
                                                                    macd_support_trend=english_report.macd_support_trend,
                                                                    bollinger_analysis=translated_data.get('indicators_analysis', {}).get('bollinger_bands', {}).get('analysis', ''),
                                                                    bollinger_support_trend=english_report.bollinger_support_trend,
                                                                    bias_analysis=translated_data.get('indicators_analysis', {}).get('bias', {}).get('analysis', ''),
                                                                    bias_support_trend=english_report.bias_support_trend,
                                                                    psy_analysis=translated_data.get('indicators_analysis', {}).get('psy', {}).get('analysis', ''),
                                                                    psy_support_trend=english_report.psy_support_trend,
                                                                    dmi_analysis=translated_data.get('indicators_analysis', {}).get('dmi', {}).get('analysis', ''),
                                                                    dmi_support_trend=english_report.dmi_support_trend,
                                                                    vwap_analysis=translated_data.get('indicators_analysis', {}).get('vwap', {}).get('analysis', ''),
                                                                    vwap_support_trend=english_report.vwap_support_trend,
                                                                    funding_rate_analysis=translated_data.get('indicators_analysis', {}).get('funding_rate', {}).get('analysis', ''),
                                                                    funding_rate_support_trend=english_report.funding_rate_support_trend,
                                                                    exchange_netflow_analysis=translated_data.get('indicators_analysis', {}).get('exchange_netflow', {}).get('analysis', ''),
                                                                    exchange_netflow_support_trend=english_report.exchange_netflow_support_trend,
                                                                    nupl_analysis=translated_data.get('indicators_analysis', {}).get('nupl', {}).get('analysis', ''),
                                                                    nupl_support_trend=english_report.nupl_support_trend,
                                                                    mayer_multiple_analysis=translated_data.get('indicators_analysis', {}).get('mayer_multiple', {}).get('analysis', ''),
                                                                    mayer_multiple_support_trend=english_report.mayer_multiple_support_trend,
                                                                    trading_action=translated_data.get('trading_advice', {}).get('action', ''),
                                                                    trading_reason=translated_data.get('trading_advice', {}).get('reason', ''),
                                                                    entry_price=english_report.entry_price,
                                                                    stop_loss=english_report.stop_loss,
                                                                    take_profit=english_report.take_profit,
                                                                    risk_level=translated_data.get('risk_assessment', {}).get('level', ''),
                                                                    risk_score=english_report.risk_score,
                                                                    risk_details=translated_data.get('risk_assessment', {}).get('details', [])
                                                                )
                                                                return translated_report
                                        except json.JSONDecodeError:
                                            pass
                                        except Exception:
                                            pass
                                    else:
                                        logger.error(f"获取消息列表失败: HTTP状态码 {messages_response.status_code}")
                            else:
                                logger.warning(f"获取对话状态响应错误: {status_data}")
                        else:
                            logger.error(f"获取对话状态失败: HTTP状态码 {status_response.status_code}")

                    except requests.Timeout:
                        logger.error("获取对话状态超时")
                    except Exception as e:
                        logger.error(f"获取对话状态时发生错误: {str(e)}")

                    retry_count += 1
                    time.sleep(retry_interval)
                    retry_interval = min(retry_interval * 1.5, max_retry_interval)

                logger.error("轮询Coze API未获得有效响应")
                # 如果是非英文报告，尝试使用英文报告作为备选
                if target_language != 'en-US' and english_report:
                    logger.info(f"使用英文报告作为备选，英文报告ID: {english_report.id}")
                    return english_report
                return None

            except Exception as e:
                logger.error(f"解析 Coze API 响应时发生错误: {str(e)}", exc_info=True)
                return None

        except Exception as e:
            logger.error(f"翻译报告时发生错误: {str(e)}", exc_info=True)
            return None

    def _build_translation_prompt(self, english_report: AnalysisReport, target_language: str) -> str:
        """构建翻译提示词

        Args:
            english_report: 英文报告对象
            target_language: 目标语言代码

        Returns:
            str: 翻译提示词
        """
        # 构建英文报告数据
        report_data = {
            "trend_analysis": {
                "up_probability": english_report.trend_up_probability,
                "sideways_probability": english_report.trend_sideways_probability,
                "down_probability": english_report.trend_down_probability,
                "summary": english_report.trend_summary
            },
            "indicators_analysis": {
                "rsi": {
                    "analysis": english_report.rsi_analysis,
                    "support_trend": english_report.rsi_support_trend
                },
                "macd": {
                    "analysis": english_report.macd_analysis,
                    "support_trend": english_report.macd_support_trend
                },
                "bollinger_bands": {
                    "analysis": english_report.bollinger_analysis,
                    "support_trend": english_report.bollinger_support_trend
                },
                "bias": {
                    "analysis": english_report.bias_analysis,
                    "support_trend": english_report.bias_support_trend
                },
                "psy": {
                    "analysis": english_report.psy_analysis,
                    "support_trend": english_report.psy_support_trend
                },
                "dmi": {
                    "analysis": english_report.dmi_analysis,
                    "support_trend": english_report.dmi_support_trend
                },
                "vwap": {
                    "analysis": english_report.vwap_analysis,
                    "support_trend": english_report.vwap_support_trend
                },
                "funding_rate": {
                    "analysis": english_report.funding_rate_analysis,
                    "support_trend": english_report.funding_rate_support_trend
                },
                "exchange_netflow": {
                    "analysis": english_report.exchange_netflow_analysis,
                    "support_trend": english_report.exchange_netflow_support_trend
                },
                "nupl": {
                    "analysis": english_report.nupl_analysis,
                    "support_trend": english_report.nupl_support_trend
                },
                "mayer_multiple": {
                    "analysis": english_report.mayer_multiple_analysis,
                    "support_trend": english_report.mayer_multiple_support_trend
                }
            },
            "trading_advice": {
                "action": english_report.trading_action,
                "reason": english_report.trading_reason,
                "entry_price": english_report.entry_price,
                "stop_loss": english_report.stop_loss,
                "take_profit": english_report.take_profit
            },
            "risk_assessment": {
                "level": english_report.risk_level,
                "score": english_report.risk_score,
                "details": english_report.risk_details
            }
        }

        # 将英文报告数据转换为字符串
        import json
        report_str = json.dumps(report_data, ensure_ascii=False, indent=2)

        # 根据目标语言生成对应的语言名称
        lang_map = {
            'zh-CN': '中文',
            'en-US': '英文',
            'ja-JP': '日语',
            'ko-KR': '韩语'
        }
        lang_name = lang_map.get(target_language, '目标语言')

        # 构建翻译提示词
        prompt = (
            f"请将以下英文加密货币分析报告翻译为{lang_name}，只翻译文本内容，输出请务必为{lang_name}：\n\n"
            f"{report_str}\n\n"
            "请确保：\n"
            "1. 保持所有数值不变\n"
            "2. 保持JSON结构不变\n"
            "3. 只翻译文本内容\n"
            "4. 保持专业术语的准确性\n"
            "5. 保持分析逻辑的一致性"
        )

        return prompt