import logging
import json
import time
from typing import Dict, Any, Optional
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction
from django.conf import settings
from django.utils import timezone
import requests
from datetime import datetime
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
        logger.info(f"使用 settings 中的 API 密钥")

        # 从 settings 获取 API URL
        self.coze_api_url = settings.COZE_API_URL

        # 确保 API URL 是正确的
        # 根据 old.py 文件，API URL 应该是 https://api.coze.com
        # 不需要 /api/v3 后缀，因为我们会在构建具体 API 端点时添加 /v3/chat 等
        if self.coze_api_url.endswith('/api/v3'):
            self.coze_api_url = self.coze_api_url.replace('/api/v3', '')

        logger.info(f"使用 API URL: {self.coze_api_url}")

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

            # 验证语言支持
            if language != 'all' and language not in self.SUPPORTED_LANGUAGES:
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
            token, created = Token.objects.get_or_create(
                symbol=symbol,
                defaults={
                    'chain': chain,
                    'name': symbol
                }
            )
            if created:
                logger.info(f"创建新交易对记录: {symbol}")

            # 获取技术指标数据
            technical_data = self._get_technical_data(symbol)
            if not technical_data:
                return Response({
                    'status': 'error',
                    'message': '获取技术指标数据失败'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # 生成报告
            reports = []
            if language == 'all':
                # 生成所有语言的报告
                for lang in self.SUPPORTED_LANGUAGES:
                    report = self._generate_and_save_report(token, technical_data, lang)
                    if report:
                        reports.append(report)
            else:
                # 生成指定语言的报告
                report = self._generate_and_save_report(token, technical_data, language)
                if report:
                    reports.append(report)

            if not reports:
                return Response({
                    'status': 'error',
                    'message': '生成分析报告失败'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            return Response({
                'status': 'success',
                'data': {
                    'symbol': symbol,
                    'reports': reports
                }
            })

        except Exception as e:
            logger.error(f"生成分析报告时发生错误: {str(e)}", exc_info=True)
            return Response({
                'status': 'error',
                'message': f'生成分析报告时发生错误: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _get_technical_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取技术指标数据

        首先尝试从数据库获取最新的技术指标数据，如果没有找到，则调用 API 获取
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

            # 从数据库获取最新的技术分析记录
            latest_analysis = TechnicalAnalysis.objects.filter(token=token).order_by('-timestamp').first()

            # 如果找到了最新的技术分析记录，并且时间在24小时内，直接使用它
            if latest_analysis:
                # 计算时间差
                time_diff = timezone.now() - latest_analysis.timestamp
                if time_diff.total_seconds() < 24 * 60 * 60:
                    logger.info(f"从数据库获取技术指标数据: {symbol}, ID: {latest_analysis.id}")

                    # 获取实时价格
                    current_price = 0
                    try:
                        # 初始化 TechnicalAnalysisService
                        ta_service = TechnicalAnalysisService()

                        # 获取实时价格
                        current_price = ta_service.gate_api.get_realtime_price(symbol)

                        # 如果无法获取实时价格，使用最新的分析报告中的价格
                        if not current_price:
                            latest_report = AnalysisReport.objects.filter(token=token).order_by('-timestamp').first()
                            if latest_report:
                                current_price = latest_report.snapshot_price
                    except Exception as e:
                        logger.error(f"获取实时价格失败: {str(e)}")
                        # 如果无法获取实时价格，使用最新的分析报告中的价格
                        latest_report = AnalysisReport.objects.filter(token=token).order_by('-timestamp').first()
                        if latest_report:
                            current_price = latest_report.snapshot_price

                    # 构建技术指标数据
                    return {
                        'symbol': symbol,
                        'current_price': current_price,
                        'indicators': {
                            'rsi': {
                                'value': latest_analysis.rsi
                            },
                            'macd': {
                                'macd_line': latest_analysis.macd_line,
                                'signal_line': latest_analysis.macd_signal,
                                'histogram': latest_analysis.macd_histogram
                            },
                            'bollinger_bands': {
                                'upper': latest_analysis.bollinger_upper,
                                'middle': latest_analysis.bollinger_middle,
                                'lower': latest_analysis.bollinger_lower
                            },
                            'bias': {
                                'value': latest_analysis.bias
                            },
                            'psy': {
                                'value': latest_analysis.psy
                            },
                            'dmi': {
                                'plus_di': latest_analysis.dmi_plus,
                                'minus_di': latest_analysis.dmi_minus,
                                'adx': latest_analysis.dmi_adx
                            },
                            'vwap': {
                                'value': latest_analysis.vwap
                            },
                            'funding_rate': {
                                'value': latest_analysis.funding_rate / 100  # 转换回小数形式，例如 0.01% -> 0.0001
                            },
                            'exchange_netflow': {
                                'value': latest_analysis.exchange_netflow
                            },
                            'nupl': {
                                'value': latest_analysis.nupl
                            },
                            'mayer_multiple': {
                                'value': latest_analysis.mayer_multiple
                            }
                        }
                    }

            # 如果没有找到最新的技术分析记录，或者时间超过24小时，调用 API 获取
            logger.info(f"数据库中没有找到最新的技术指标数据，调用 API 获取: {symbol}")

            # 使用 TechnicalIndicatorsAPIView 获取数据
            # 创建一个模拟的请求对象
            class MockRequest:
                def __init__(self):
                    self._request = None
                    self.user = None

            mock_request = MockRequest()
            if hasattr(self, 'request') and hasattr(self.request, '_request'):
                mock_request._request = self.request._request

            # 添加日志记录
            logger.info(f"获取技术指标数据: {symbol}")

            # 确保 technical_indicators_view 已初始化并设置为内部调用
            if not hasattr(self, 'technical_indicators_view') or self.technical_indicators_view is None:
                self.technical_indicators_view = TechnicalIndicatorsDataAPIView(internal_call=True)
            else:
                self.technical_indicators_view.internal_call = True

            response = self.technical_indicators_view.get(mock_request, symbol)

            # 添加日志记录
            logger.info(f"技术指标数据响应状态码: {response.status_code}")

            if response.status_code == status.HTTP_200_OK:
                data = response.data.get('data', {})
                logger.info(f"成功获取技术指标数据: {symbol}")

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
                            logger.info(f"成功获取实时价格: {current_price}")
                    except Exception as e:
                        logger.error(f"获取实时价格失败: {str(e)}")

                return data

            logger.error(f"获取技术指标数据失败: {response.data}")
            return None
        except Exception as e:
            logger.error(f"获取技术指标数据时发生错误: {str(e)}", exc_info=True)
            return None

    @transaction.atomic
    def _generate_and_save_report(self, token: Token, technical_data: Dict[str, Any], language: str) -> Optional[Dict[str, Any]]:
        """生成并保存分析报告"""
        try:
            # 构建提示词
            prompt = self._build_prompt(technical_data, language)

            # 获取对应语言的 Bot ID
            bot_id = self.COZE_BOT_IDS.get(language)
            logger.info(f"使用语言 {language} 对应的 Coze Bot ID: {bot_id}")

            # 打印所有语言的 Bot ID，用于调试
            logger.info(f"所有语言的 Coze Bot ID: {self.COZE_BOT_IDS}")

            if not bot_id:
                logger.error(f"未找到语言 {language} 对应的 Coze Bot ID")
                return None

            # 调用 Coze API 创建对话
            # 根据 old.py 文件，正确的 API 端点是 /v3/chat
            chat_url = f"{self.coze_api_url}/v3/chat"
            logger.info(f"调用 Coze API 创建对话: {chat_url}")

            # 构建请求体
            payload = {
                "bot_id": bot_id,
                "user_id": f"crypto_user_{int(time.time())}",  # 使用时间戳生成唯一用户ID
                "stream": False,  # 不使用流式响应
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

            # 获取当前价格和时间
            current_price = technical_data.get('current_price', 0)
            current_time = timezone.now()

            if response.status_code != 200:
                logger.error(f"Coze API 调用失败: {response.status_code} - {response.text}")
                return None

            # 解析响应
            try:
                response_data = response.json()
                # 记录响应内容，便于调试
                logger.info(f"Coze API 创建对话响应: {response_data}")

                # 检查响应状态
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

                # 尝试从创建对话的响应中获取内容
                try:
                    messages = data.get('messages', [])

                    # 查找助手的回复
                    assistant_message = None
                    for message in messages:
                        if message.get('role') == 'assistant':
                            assistant_message = message
                            break

                    if assistant_message:
                        # 提取JSON内容
                        content = assistant_message.get('content', '')
                        analysis_result = self._extract_json_from_content(content)
                        if analysis_result:
                            logger.info(f"成功从创建对话响应中解析分析数据")
                            return analysis_result
                except Exception as e:
                    logger.error(f"处理Coze响应时发生错误: {str(e)}")

                # 轮询获取对话结果
                max_retries = 20  # 最大重试次数
                retry_count = 0
                retry_interval = 1.0  # 初始重试间隔（秒）
                max_retry_interval = 5.0  # 最大重试间隔（秒）

                # 添加初始延迟，给Coze API更多时间来生成回复
                time.sleep(2.0)

                # 轮询获取对话结果
                while retry_count < max_retries:
                    try:
                        # 构建获取对话状态的请求
                        # 根据 old.py 文件，正确的 API 端点是 /v3/chat/retrieve
                        retrieve_url = f"{self.coze_api_url.replace('/api/v3', '')}/v3/chat/retrieve"
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
                            try:
                                status_data = status_response.json()
                                if status_data.get('code') == 0:
                                    data = status_data.get('data', {})
                                    status = data.get('status')

                                    if status == "completed":
                                        # 获取消息列表
                                        # 根据 old.py 文件，正确的 API 端点是 /v3/chat/message/list
                                        message_list_url = f"{self.coze_api_url.replace('/api/v3', '')}/v3/chat/message/list"
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
                                                    if "data" in messages_data and isinstance(messages_data["data"], dict) and "messages" in messages_data["data"]:
                                                        messages = messages_data["data"]["messages"]
                                                    elif "data" in messages_data and isinstance(messages_data["data"], list):
                                                        messages = messages_data["data"]
                                                    else:
                                                        logger.error("无法解析消息列表格式")
                                                        retry_count += 1
                                                        time.sleep(retry_interval)
                                                        retry_interval = min(retry_interval * 1.5, max_retry_interval)
                                                        continue

                                                    # 查找助手的回复
                                                    for message in messages:
                                                        if message.get('role') == 'assistant' and message.get('type') == 'answer':
                                                            content = message.get('content', '')
                                                            if content and content != '###':
                                                                analysis_result = self._extract_json_from_content(content)
                                                                if analysis_result:
                                                                    logger.info(f"成功从消息列表中解析分析数据")

                                                                    # 创建技术分析记录
                                                                    # 确保 technical_data 是字典类型
                                                                    if not isinstance(technical_data, dict):
                                                                        logger.error(f"technical_data 不是字典类型")
                                                                        return None

                                                                    # 处理技术指标数据
                                                                    technical_analysis = TechnicalAnalysis.objects.create(
                                                                        token=token,
                                                                        timestamp=current_time,
                                                                        rsi=technical_data.get('indicators', {}).get('rsi', {}).get('value'),
                                                                        macd_line=technical_data.get('indicators', {}).get('macd', {}).get('macd_line'),
                                                                        macd_signal=technical_data.get('indicators', {}).get('macd', {}).get('signal_line'),
                                                                        macd_histogram=technical_data.get('indicators', {}).get('macd', {}).get('histogram'),
                                                                        bollinger_upper=technical_data.get('indicators', {}).get('bollinger_bands', {}).get('upper'),
                                                                        bollinger_middle=technical_data.get('indicators', {}).get('bollinger_bands', {}).get('middle'),
                                                                        bollinger_lower=technical_data.get('indicators', {}).get('bollinger_bands', {}).get('lower'),
                                                                        bias=technical_data.get('indicators', {}).get('bias', {}).get('value'),
                                                                        psy=technical_data.get('indicators', {}).get('psy', {}).get('value'),
                                                                        dmi_plus=technical_data.get('indicators', {}).get('dmi', {}).get('plus_di'),
                                                                        dmi_minus=technical_data.get('indicators', {}).get('dmi', {}).get('minus_di'),
                                                                        dmi_adx=technical_data.get('indicators', {}).get('dmi', {}).get('adx'),
                                                                        vwap=technical_data.get('indicators', {}).get('vwap', {}).get('value'),
                                                                        funding_rate=technical_data.get('indicators', {}).get('funding_rate', {}).get('value'),
                                                                        exchange_netflow=technical_data.get('indicators', {}).get('exchange_netflow', {}).get('value'),
                                                                        nupl=technical_data.get('indicators', {}).get('nupl', {}).get('value'),
                                                                        mayer_multiple=technical_data.get('indicators', {}).get('mayer_multiple', {}).get('value')
                                                                    )

                                                                    # 创建分析报告
                                                                    report = AnalysisReport.objects.create(
                                                                        token=token,
                                                                        technical_analysis=technical_analysis,
                                                                        timestamp=current_time,
                                                                        snapshot_price=current_price,
                                                                        language=language,
                                                                        trend_up_probability=analysis_result.get('trend_analysis', {}).get('up_probability', 33),
                                                                        trend_sideways_probability=analysis_result.get('trend_analysis', {}).get('sideways_probability', 34),
                                                                        trend_down_probability=analysis_result.get('trend_analysis', {}).get('down_probability', 33),
                                                                        trend_summary=analysis_result.get('trend_analysis', {}).get('summary', ''),
                                                                        rsi_analysis=analysis_result.get('indicators_analysis', {}).get('rsi', {}).get('analysis', ''),
                                                                        rsi_support_trend=analysis_result.get('indicators_analysis', {}).get('rsi', {}).get('support_trend', 'neutral'),
                                                                        macd_analysis=analysis_result.get('indicators_analysis', {}).get('macd', {}).get('analysis', ''),
                                                                        macd_support_trend=analysis_result.get('indicators_analysis', {}).get('macd', {}).get('support_trend', 'neutral'),
                                                                        bollinger_analysis=analysis_result.get('indicators_analysis', {}).get('bollinger_bands', {}).get('analysis', ''),
                                                                        bollinger_support_trend=analysis_result.get('indicators_analysis', {}).get('bollinger_bands', {}).get('support_trend', 'neutral'),
                                                                        bias_analysis=analysis_result.get('indicators_analysis', {}).get('bias', {}).get('analysis', ''),
                                                                        bias_support_trend=analysis_result.get('indicators_analysis', {}).get('bias', {}).get('support_trend', 'neutral'),
                                                                        psy_analysis=analysis_result.get('indicators_analysis', {}).get('psy', {}).get('analysis', ''),
                                                                        psy_support_trend=analysis_result.get('indicators_analysis', {}).get('psy', {}).get('support_trend', 'neutral'),
                                                                        dmi_analysis=analysis_result.get('indicators_analysis', {}).get('dmi', {}).get('analysis', ''),
                                                                        dmi_support_trend=analysis_result.get('indicators_analysis', {}).get('dmi', {}).get('support_trend', 'neutral'),
                                                                        vwap_analysis=analysis_result.get('indicators_analysis', {}).get('vwap', {}).get('analysis', ''),
                                                                        vwap_support_trend=analysis_result.get('indicators_analysis', {}).get('vwap', {}).get('support_trend', 'neutral'),
                                                                        funding_rate_analysis=analysis_result.get('indicators_analysis', {}).get('funding_rate', {}).get('analysis', ''),
                                                                        funding_rate_support_trend=analysis_result.get('indicators_analysis', {}).get('funding_rate', {}).get('support_trend', 'neutral'),
                                                                        exchange_netflow_analysis=analysis_result.get('indicators_analysis', {}).get('exchange_netflow', {}).get('analysis', ''),
                                                                        exchange_netflow_support_trend=analysis_result.get('indicators_analysis', {}).get('exchange_netflow', {}).get('support_trend', 'neutral'),
                                                                        nupl_analysis=analysis_result.get('indicators_analysis', {}).get('nupl', {}).get('analysis', ''),
                                                                        nupl_support_trend=analysis_result.get('indicators_analysis', {}).get('nupl', {}).get('support_trend', 'neutral'),
                                                                        mayer_multiple_analysis=analysis_result.get('indicators_analysis', {}).get('mayer_multiple', {}).get('analysis', ''),
                                                                        mayer_multiple_support_trend=analysis_result.get('indicators_analysis', {}).get('mayer_multiple', {}).get('support_trend', 'neutral'),
                                                                        trading_action=analysis_result.get('trading_advice', {}).get('action', '等待'),
                                                                        trading_reason=analysis_result.get('trading_advice', {}).get('reason', ''),
                                                                        entry_price=analysis_result.get('trading_advice', {}).get('entry_price', current_price),
                                                                        stop_loss=analysis_result.get('trading_advice', {}).get('stop_loss', current_price * 0.95),
                                                                        take_profit=analysis_result.get('trading_advice', {}).get('take_profit', current_price * 1.05),
                                                                        risk_level=analysis_result.get('risk_assessment', {}).get('level', '中'),
                                                                        risk_score=analysis_result.get('risk_assessment', {}).get('score', 50),
                                                                        risk_details=analysis_result.get('risk_assessment', {}).get('details', ['无法完成分析，使用默认风险评估'])
                                                                    )

                                                                    return {
                                                                        'language': language,
                                                                        'timestamp': current_time.isoformat(),
                                                                        'price': current_price,
                                                                        'trend_analysis': {
                                                                            'probabilities': {
                                                                                'up': report.trend_up_probability,
                                                                                'sideways': report.trend_sideways_probability,
                                                                                'down': report.trend_down_probability
                                                                            },
                                                                            'summary': report.trend_summary
                                                                        },
                                                                        'indicators_analysis': {
                                                                            'RSI': {
                                                                                'value': technical_analysis.rsi,
                                                                                'analysis': report.rsi_analysis,
                                                                                'support_trend': report.rsi_support_trend
                                                                            },
                                                                            'MACD': {
                                                                                'value': {
                                                                                    'macd_line': technical_analysis.macd_line,
                                                                                    'signal_line': technical_analysis.macd_signal,
                                                                                    'histogram': technical_analysis.macd_histogram
                                                                                },
                                                                                'analysis': report.macd_analysis,
                                                                                'support_trend': report.macd_support_trend
                                                                            },
                                                                            'BollingerBands': {
                                                                                'value': {
                                                                                    'upper': technical_analysis.bollinger_upper,
                                                                                    'middle': technical_analysis.bollinger_middle,
                                                                                    'lower': technical_analysis.bollinger_lower
                                                                                },
                                                                                'analysis': report.bollinger_analysis,
                                                                                'support_trend': report.bollinger_support_trend
                                                                            },
                                                                            'BIAS': {
                                                                                'value': technical_analysis.bias,
                                                                                'analysis': report.bias_analysis,
                                                                                'support_trend': report.bias_support_trend
                                                                            },
                                                                            'PSY': {
                                                                                'value': technical_analysis.psy,
                                                                                'analysis': report.psy_analysis,
                                                                                'support_trend': report.psy_support_trend
                                                                            },
                                                                            'DMI': {
                                                                                'value': {
                                                                                    'plus_di': technical_analysis.dmi_plus,
                                                                                    'minus_di': technical_analysis.dmi_minus,
                                                                                    'adx': technical_analysis.dmi_adx
                                                                                },
                                                                                'analysis': report.dmi_analysis,
                                                                                'support_trend': report.dmi_support_trend
                                                                            },
                                                                            'VWAP': {
                                                                                'value': technical_analysis.vwap,
                                                                                'analysis': report.vwap_analysis,
                                                                                'support_trend': report.vwap_support_trend
                                                                            },
                                                                            'FundingRate': {
                                                                                'value': technical_analysis.funding_rate,
                                                                                'analysis': report.funding_rate_analysis,
                                                                                'support_trend': report.funding_rate_support_trend
                                                                            },
                                                                            'ExchangeNetflow': {
                                                                                'value': technical_analysis.exchange_netflow,
                                                                                'analysis': report.exchange_netflow_analysis,
                                                                                'support_trend': report.exchange_netflow_support_trend
                                                                            },
                                                                            'NUPL': {
                                                                                'value': technical_analysis.nupl,
                                                                                'analysis': report.nupl_analysis,
                                                                                'support_trend': report.nupl_support_trend
                                                                            },
                                                                            'MayerMultiple': {
                                                                                'value': technical_analysis.mayer_multiple,
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
                                                else:
                                                    logger.error(f"获取消息列表响应错误: {messages_data}")
                                            except json.JSONDecodeError:
                                                logger.error(f"解析消息列表响应失败: {messages_response.text}")
                                        else:
                                            logger.error(f"获取消息列表失败: HTTP状态码 {messages_response.status_code}")
                                else:
                                    logger.warning(f"获取对话状态响应错误: {status_data}")
                            except json.JSONDecodeError:
                                logger.error(f"解析对话状态响应失败: {status_response.text}")
                        else:
                            logger.error(f"获取对话状态失败: HTTP状态码 {status_response.status_code}")
                    except requests.Timeout:
                        logger.error("获取对话状态超时")
                    except Exception as e:
                        logger.error(f"获取对话状态时发生错误: {str(e)}")

                    # 如果没有获取到完整结果，继续重试
                    retry_count += 1
                    time.sleep(retry_interval)
                    retry_interval = min(retry_interval * 1.5, max_retry_interval)  # 指数退避，最大5秒

                # 在重试失败后，返回错误
                logger.error("轮询Coze API未获得有效响应")
                return None

            except Exception as e:
                logger.error(f"解析 Coze API 响应时发生错误: {str(e)}", exc_info=True)
                return None

            # 这里不需要重复的代码，因为我们已经在上面的代码中处理了这个逻辑

        except Exception as e:
            logger.error(f"生成并保存报告时发生错误: {str(e)}", exc_info=True)
            return None

    def _build_prompt(self, technical_data: Dict[str, Any], language: str) -> str:
        """构建提示词

        由于 Coze 已经配置了提示语，我们只需要提交技术参数就可以了
        """
        # 格式化技术指标数据，确保格式一致
        formatted_data = self._format_technical_data_for_prompt(technical_data)

        # 直接返回格式化后的技术指标数据
        return formatted_data

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

            # 打印提交给Coze的技术指标数据
            logger.info(f"提交给Coze的技术指标数据: {formatted_str}")

            return formatted_str
        except Exception as e:
            logger.error(f"格式化技术指标数据时发生错误: {str(e)}", exc_info=True)
            # 如果格式化失败，直接返回原始数据的字符串表示
            return str(technical_data)

    def _handle_language_specific_json(self, content: str) -> Optional[Dict[str, Any]]:
        """处理不同语言的 JSON 格式"""
        try:
            # 日语格式处理
            if "上昇確率" in content:
                logger.info("处理日语 JSON 格式")
                # 尝试提取日语 JSON 对象
                import re
                ja_pattern = r'\{"上昇確率":[^}]*,"横ばい確率":[^}]*,"下降確率":[^}]*,"トレンド概要":"[^"]*"\}'
                match = re.search(ja_pattern, content)
                if match:
                    ja_json = match.group(0)
                    logger.info(f"提取的日语 JSON: {ja_json}")
                    return json.loads(ja_json)
            
            # 韩语格式处理
            elif "상승 확률" in content:
                logger.info("处理韩语 JSON 格式")
                # 尝试提取韩语 JSON 对象
                ko_pattern = r'\{"상승 확률":[^}]*,"횡보 확률":[^}]*,"하락 확률":[^}]*,"트렌드 요약":"[^"]*"\}'
                match = re.search(ko_pattern, content)
                if match:
                    ko_json = match.group(0)
                    logger.info(f"提取的韩语 JSON: {ko_json}")
                    return json.loads(ko_json)
            
            # 中文格式处理
            elif "上涨概率" in content:
                logger.info("处理中文 JSON 格式")
                # 尝试提取中文 JSON 对象
                zh_pattern = r'\{"上涨概率":[^}]*,"横盘概率":[^}]*,"下跌概率":[^}]*,"趋势总结":"[^"]*"\}'
                match = re.search(zh_pattern, content)
                if match:
                    zh_json = match.group(0)
                    logger.info(f"提取的中文 JSON: {zh_json}")
                    return json.loads(zh_json)
            
            # 英文格式处理
            elif "up_probability" in content:
                logger.info("处理英文 JSON 格式")
                # 尝试提取英文 JSON 对象
                en_pattern = r'\{"up_probability":[^}]*,"sideways_probability":[^}]*,"down_probability":[^}]*,"trend_summary":"[^"]*"\}'
                match = re.search(en_pattern, content)
                if match:
                    en_json = match.group(0)
                    logger.info(f"提取的英文 JSON: {en_json}")
                    return json.loads(en_json)
            
            return None
        except Exception as e:
            logger.error(f"处理语言特定 JSON 时发生错误: {str(e)}")
            return None

    def _extract_json_from_content(self, content: str) -> Optional[Dict[str, Any]]:
        """从内容中提取JSON数据"""
        try:
            # 保存原始内容到文件，方便调试
            self._save_coze_response_to_file(content)
            
            # 添加语言检测日志
            logger.info("=== 开始分析 Coze 返回的原始数据 ===")
            logger.info(f"原始内容长度: {len(content)}")
            logger.info(f"原始内容前500个字符: {content[:500]}")
            
            # 检测语言
            if "上昇確率" in content or "トレンド概要" in content:
                logger.info("检测到日语内容")
            elif "상승 확률" in content or "트렌드 요약" in content:
                logger.info("检测到韩语内容")
            elif "上涨概率" in content or "趋势总结" in content:
                logger.info("检测到中文内容")
            elif "up_probability" in content or "trend_summary" in content:
                logger.info("检测到英文内容")
            
            # 首先尝试语言特定的 JSON 处理
            language_specific_result = self._handle_language_specific_json(content)
            if language_specific_result:
                logger.info("成功使用语言特定的 JSON 处理")
                return self._convert_chinese_to_english_fields(language_specific_result)
            
            # 如果语言特定的处理失败，尝试直接解析
            try:
                import json
                analysis_result = json.loads(content)
                logger.info(f"从内容中直接提取的分析结果: {json.dumps(analysis_result, ensure_ascii=False, indent=2)}")
                return self._convert_chinese_to_english_fields(analysis_result)
            except json.JSONDecodeError as e:
                logger.warning(f"直接解析JSON失败，尝试修复JSON格式: {str(e)}")
                try:
                    # 尝试修复JSON格式
                    # 1. 移除可能的markdown代码块标记
                    content = content.replace('```json', '').replace('```', '').strip()

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
                    import re

                    # 尝试提取完整的JSON对象
                    json_pattern = r'\{(?:[^{}]|(?:\{(?:[^{}]|(?:\{[^{}]*\}))*\}))*\}'
                    matches = re.finditer(json_pattern, fixed_content)

                    # 按长度排序匹配结果，优先使用最长的匹配（可能是最完整的JSON）
                    potential_jsons = sorted([match.group(0) for match in matches], key=len, reverse=True)

                    for potential_json in potential_jsons:
                        try:
                            analysis_result = json.loads(potential_json)
                            logger.info(f"使用正则表达式提取的分析结果: {json.dumps(analysis_result, ensure_ascii=False, indent=2)}")

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
                                logger.info(f"提取到趋势分析部分: {json.dumps(analysis_result, ensure_ascii=False, indent=2)}")
                                return self._convert_chinese_to_english_fields(analysis_result)
                            except json.JSONDecodeError:
                                continue

                    # 5. 尝试解析修复后的JSON
                    try:
                        analysis_result = json.loads(fixed_content)
                        logger.info(f"修复后提取的分析结果: {json.dumps(analysis_result, ensure_ascii=False, indent=2)}")
                        return self._convert_chinese_to_english_fields(analysis_result)
                    except json.JSONDecodeError:
                        # 6. 尝试使用更宽松的JSON解析器
                        try:
                            # 尝试使用 json5 库（更宽松的JSON解析器）
                            try:
                                import json5
                                analysis_result = json5.loads(fixed_content)
                                logger.info(f"使用json5提取的分析结果: {json.dumps(analysis_result, ensure_ascii=False, indent=2)}")
                                return self._convert_chinese_to_english_fields(analysis_result)
                            except ImportError:
                                logger.warning("json5库未安装，尝试其他方法")

                            # 尝试使用 demjson3 库（另一个宽松的JSON解析器）
                            try:
                                import demjson3
                                analysis_result = demjson3.decode(fixed_content)
                                logger.info(f"使用demjson3提取的分析结果: {json.dumps(analysis_result, ensure_ascii=False, indent=2)}")
                                return self._convert_chinese_to_english_fields(analysis_result)
                            except ImportError:
                                logger.warning("demjson3库未安装，尝试其他方法")

                            # 尝试使用 ast.literal_eval（Python内置的安全求值函数）
                            try:
                                import ast
                                # 将JSON格式的字符串转换为Python字典
                                fixed_content = fixed_content.replace('null', 'None').replace('true', 'True').replace('false', 'False')
                                analysis_result = ast.literal_eval(fixed_content)
                                logger.info(f"使用ast.literal_eval提取的分析结果: {json.dumps(analysis_result, ensure_ascii=False, indent=2)}")
                                return self._convert_chinese_to_english_fields(analysis_result)
                            except (SyntaxError, ValueError):
                                logger.warning("ast.literal_eval解析失败")
                        except Exception as e:
                            logger.warning(f"所有宽松JSON解析器都失败: {str(e)}")

                    # 7. 如果所有尝试都失败，创建一个默认的分析结果
                    logger.error("所有JSON修复尝试都失败，使用默认分析结果")
                    default_result = self._create_default_analysis_result()
                    return default_result

                except Exception as fix_error:
                    logger.error(f"修复JSON格式失败: {str(fix_error)}")
                    # 创建一个默认的分析结果
                    default_result = self._create_default_analysis_result()
                    return default_result

        except Exception as e:
            logger.error(f"处理语言特定 JSON 时发生错误: {str(e)}")
            return None

    def _save_coze_response_to_file(self, content: str) -> None:
        """保存Coze响应内容到文件"""
        try:
            import os
            import time

            # 创建日志目录
            log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
            os.makedirs(log_dir, exist_ok=True)

            # 生成文件名
            timestamp = int(time.time())
            log_file = os.path.join(log_dir, f'coze_response_{timestamp}.txt')

            # 写入文件
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write(content)

            logger.info(f"已保存Coze原始响应到文件: {log_file}")
        except Exception as e:
            logger.error(f"保存Coze响应到文件时发生错误: {str(e)}")

    def _create_default_analysis_result(self) -> Dict[str, Any]:
        """创建默认的分析结果"""
        return {
            "trend_analysis": {
                "up_probability": 33,
                "sideways_probability": 34,
                "down_probability": 33,
                "summary": "无法解析Coze返回的数据，使用默认分析结果。"
            },
            "indicators_analysis": {
                "rsi": {
                    "analysis": "无法解析Coze返回的数据。",
                    "support_trend": "neutral"
                },
                "macd": {
                    "analysis": "无法解析Coze返回的数据。",
                    "support_trend": "neutral"
                },
                "bollinger_bands": {
                    "analysis": "无法解析Coze返回的数据。",
                    "support_trend": "neutral"
                },
                "bias": {
                    "analysis": "无法解析Coze返回的数据。",
                    "support_trend": "neutral"
                },
                "psy": {
                    "analysis": "无法解析Coze返回的数据。",
                    "support_trend": "neutral"
                },
                "dmi": {
                    "analysis": "无法解析Coze返回的数据。",
                    "support_trend": "neutral"
                },
                "vwap": {
                    "analysis": "无法解析Coze返回的数据。",
                    "support_trend": "neutral"
                },
                "funding_rate": {
                    "analysis": "无法解析Coze返回的数据。",
                    "support_trend": "neutral"
                },
                "exchange_netflow": {
                    "analysis": "无法解析Coze返回的数据。",
                    "support_trend": "neutral"
                },
                "nupl": {
                    "analysis": "无法解析Coze返回的数据。",
                    "support_trend": "neutral"
                },
                "mayer_multiple": {
                    "analysis": "无法解析Coze返回的数据。",
                    "support_trend": "neutral"
                }
            },
            "trading_advice": {
                "action": "等待",
                "reason": "无法解析Coze返回的数据，建议等待。",
                "entry_price": 0,
                "stop_loss": 0,
                "take_profit": 0
            },
            "risk_assessment": {
                "level": "中",
                "score": 50,
                "details": ["无法解析Coze返回的数据，使用默认风险评估。"]
            }
        }

    def _convert_chinese_to_english_fields(self, analysis_result: Dict[str, Any]) -> Dict[str, Any]:
        """将中文/日语/韩语字段名转换为英文字段名"""
        try:
            # 检查是否已经是英文格式
            if "trend_analysis" in analysis_result:
                logger.info("数据已经是英文格式，无需转换")
                return analysis_result

            # 检查是否是部分提取的JSON数据
            # 如果只有趋势分析部分，创建一个完整的结构
            if "上昇確率" in analysis_result or "上涨概率" in analysis_result or "상승 확률" in analysis_result:
                logger.info("检测到部分提取的JSON数据，创建完整结构")

                # 创建一个默认的完整结构
                complete_result = self._create_default_analysis_result()

                # 更新趋势分析部分
                if "上昇確率" in analysis_result:  # 日语
                    complete_result["trend_analysis"]["up_probability"] = analysis_result.get("上昇確率", 33)
                    complete_result["trend_analysis"]["sideways_probability"] = analysis_result.get("横ばい確率", 34)
                    complete_result["trend_analysis"]["down_probability"] = analysis_result.get("下降確率", 33)
                    complete_result["trend_analysis"]["summary"] = analysis_result.get("トレンド概要", "")
                elif "上涨概率" in analysis_result:  # 中文
                    complete_result["trend_analysis"]["up_probability"] = analysis_result.get("上涨概率", 33)
                    complete_result["trend_analysis"]["sideways_probability"] = analysis_result.get("横盘概率", 34)
                    complete_result["trend_analysis"]["down_probability"] = analysis_result.get("下跌概率", 33)
                    complete_result["trend_analysis"]["summary"] = analysis_result.get("趋势总结", "")
                elif "상승 확률" in analysis_result:  # 韩语
                    complete_result["trend_analysis"]["up_probability"] = analysis_result.get("상승 확률", 33)
                    complete_result["trend_analysis"]["sideways_probability"] = analysis_result.get("횡보 확률", 34)
                    complete_result["trend_analysis"]["down_probability"] = analysis_result.get("하락 확률", 33)
                    complete_result["trend_analysis"]["summary"] = analysis_result.get("트렌드 요약", "")

                # 如果有其他部分，也更新它们
                # ...

                return complete_result

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

            logger.info(f"转换后的分析结果: {json.dumps(converted_result, ensure_ascii=False, indent=2)}")
            return converted_result
        except Exception as e:
            logger.error(f"转换中文字段名时发生错误: {str(e)}", exc_info=True)
            return analysis_result