from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
from django.utils import timezone
from django.db import transaction
from asgiref.sync import sync_to_async
import asyncio
import aiohttp
import json
import time
import logging
from typing import Dict, Optional, Any

from .services.technical_analysis import TechnicalAnalysisService
from .services.market_data_service import MarketDataService
from .models import Token as CryptoToken, Chain, AnalysisReport, TechnicalAnalysis

# 配置日志
logger = logging.getLogger(__name__)

class GetReportAPIView(APIView):
    """获取分析报告API视图

    这个API视图用于获取加密货币的分析报告，流程如下：
    1. 获取技术指标数据
    2. 将技术指标提交给Coze进行分析
    3. 保存分析报告到数据库
    4. 返回分析报告
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.ta_service = None  # 延迟初始化
        self.market_service = None  # 延迟初始化
        self.coze_api_key = None
        self.coze_bot_id = None
        self.coze_api_url = None
        self._init_coze_api()

    def _init_coze_api(self):
        """初始化 Coze API 配置"""
        # 从 Django settings 获取 API 密钥
        self.coze_api_key = settings.COZE_API_KEY

        # 检查 API 密钥是否有效
        if not self.coze_api_key or self.coze_api_key == 'your_api_key_here':
            # 使用硬编码的备用 API 密钥
            self.coze_api_key = "pat_bMCDCFaeHmcGFMZbwMZENeE33AlWUzOCHS260y5T4gwjnaqTz4mdWSA7J2FzTL9A"

        if not hasattr(self, 'coze_bot_id') or not self.coze_bot_id:
            self.coze_bot_id = settings.COZE_BOT_ID

        if not hasattr(self, 'coze_api_url') or not self.coze_api_url:
            self.coze_api_url = settings.COZE_API_URL

    def get(self, request, symbol: str):
        """处理GET请求，获取分析报告

        Args:
            request: HTTP请求对象
            symbol: 代币符号，例如 'SOLUSDT'

        Returns:
            Response: 包含分析报告的响应
        """
        # 获取用户语言偏好（注意：目前我们只保存英文报告，此参数仅用于记录）
        language = request.query_params.get('language', 'en-US')
        if request.user.is_authenticated and hasattr(request.user, 'language') and request.user.language:
            language = request.user.language

        # 使用asyncio运行异步处理函数
        return asyncio.run(self.async_get(request, symbol, language))

    async def async_get(self, request, symbol: str, language: str):
        """异步处理GET请求

        Args:
            request: HTTP请求对象
            symbol: 代币符号，例如 'SOLUSDT'
            language: 语言代码，例如 'en-US'

        Returns:
            Response: 包含分析报告的响应
        """
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

            # 获取市场数据
            market_data = await sync_to_async(self.market_service.get_market_data)(symbol)
            if not market_data:
                return Response({
                    'status': 'error',
                    'message': f"无法获取{symbol}的市场数据"
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # 清理符号格式
            clean_symbol = symbol.upper().replace('USDT', '').replace('-PERP', '').replace('_PERP', '').replace('PERP', '')

            # 获取或创建Chain记录 - 使用固定的"CRYPTO"链
            chain_qs = await sync_to_async(Chain.objects.filter)(chain="CRYPTO")
            chain = await sync_to_async(chain_qs.first)()
            if not chain:
                chain = await sync_to_async(Chain.objects.create)(
                    chain="CRYPTO",
                    is_active=True,
                    is_testnet=False
                )

            # 获取或创建Token记录
            token_qs = await sync_to_async(CryptoToken.objects.filter)(symbol=clean_symbol)
            token = await sync_to_async(token_qs.first)()
            if not token:
                token = await sync_to_async(CryptoToken.objects.create)(
                    symbol=clean_symbol,
                    chain=chain,
                    name=clean_symbol,
                    address='0x0000000000000000000000000000000000000000',
                    decimals=18
                )

            # 创建或更新技术分析记录
            technical_analysis = await self._update_technical_analysis(token, indicators)

            # 获取Coze分析
            analysis_data = await self._get_coze_analysis(symbol, indicators, technical_analysis, language)

            if not analysis_data:
                # 使用默认分析报告
                analysis_data = self._create_default_analysis(indicators, float(market_data['price']))

            # 保存分析报告
            report = await self._save_analysis_report(token, technical_analysis, analysis_data, market_data['price'], language)

            # 构建响应
            response_data = await self._build_response(symbol, market_data, indicators, report)

            return Response({
                'status': 'success',
                'data': response_data
            })

        except Exception as e:
            # 记录错误
            logger.error(f"获取分析报告失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    async def _update_technical_analysis(self, token, indicators):
        """更新技术分析记录

        Args:
            token: Token模型实例
            indicators: 技术指标数据

        Returns:
            TechnicalAnalysis: 技术分析记录
        """
        # 创建或更新技术分析记录
        technical_analysis, _ = await sync_to_async(TechnicalAnalysis.objects.update_or_create)(
            token=token,
            timestamp=timezone.now(),
            defaults={
                'rsi': indicators.get('RSI'),
                'macd_line': indicators.get('MACD', {}).get('line'),
                'macd_signal': indicators.get('MACD', {}).get('signal'),
                'macd_histogram': indicators.get('MACD', {}).get('histogram'),
                'bollinger_upper': indicators.get('BollingerBands', {}).get('upper'),
                'bollinger_middle': indicators.get('BollingerBands', {}).get('middle'),
                'bollinger_lower': indicators.get('BollingerBands', {}).get('lower'),
                'bias': indicators.get('BIAS'),
                'psy': indicators.get('PSY'),
                'dmi_plus': indicators.get('DMI', {}).get('plus_di'),
                'dmi_minus': indicators.get('DMI', {}).get('minus_di'),
                'dmi_adx': indicators.get('DMI', {}).get('adx'),
                'vwap': indicators.get('VWAP'),
                'funding_rate': indicators.get('FundingRate'),
                'exchange_netflow': indicators.get('ExchangeNetflow'),
                'nupl': indicators.get('NUPL'),
                'mayer_multiple': indicators.get('MayerMultiple')
            }
        )

        return technical_analysis

    async def _save_analysis_report(self, token, technical_analysis, analysis_data, price, language=None):
        """保存分析报告

        Args:
            token: Token模型实例
            technical_analysis: TechnicalAnalysis模型实例
            analysis_data: 分析数据
            price: 当前价格
            language: 语言代码（注意：目前我们只保存英文报告，忽略此参数）

        Returns:
            AnalysisReport: 分析报告记录
        """
        # 强制使用英文，忽略传入的language参数
        language = 'en-US'

        # 创建分析报告
        report, _ = await sync_to_async(AnalysisReport.objects.update_or_create)(
            token=token,
            technical_analysis=technical_analysis,
            language=language,
            defaults={
                'timestamp': timezone.now(),
                'snapshot_price': price,
                'trend_up_probability': analysis_data.get('trend_up_probability', 0),
                'trend_sideways_probability': analysis_data.get('trend_sideways_probability', 0),
                'trend_down_probability': analysis_data.get('trend_down_probability', 0),
                'trend_summary': analysis_data.get('trend_summary', ''),
                'rsi_analysis': analysis_data.get('indicators_analysis', {}).get('RSI', {}).get('analysis', ''),
                'rsi_support_trend': analysis_data.get('indicators_analysis', {}).get('RSI', {}).get('support_trend', 'neutral'),
                'macd_analysis': analysis_data.get('indicators_analysis', {}).get('MACD', {}).get('analysis', ''),
                'macd_support_trend': analysis_data.get('indicators_analysis', {}).get('MACD', {}).get('support_trend', 'neutral'),
                'bollinger_analysis': analysis_data.get('indicators_analysis', {}).get('BollingerBands', {}).get('analysis', ''),
                'bollinger_support_trend': analysis_data.get('indicators_analysis', {}).get('BollingerBands', {}).get('support_trend', 'neutral'),
                'bias_analysis': analysis_data.get('indicators_analysis', {}).get('BIAS', {}).get('analysis', ''),
                'bias_support_trend': analysis_data.get('indicators_analysis', {}).get('BIAS', {}).get('support_trend', 'neutral'),
                'psy_analysis': analysis_data.get('indicators_analysis', {}).get('PSY', {}).get('analysis', ''),
                'psy_support_trend': analysis_data.get('indicators_analysis', {}).get('PSY', {}).get('support_trend', 'neutral'),
                'dmi_analysis': analysis_data.get('indicators_analysis', {}).get('DMI', {}).get('analysis', ''),
                'dmi_support_trend': analysis_data.get('indicators_analysis', {}).get('DMI', {}).get('support_trend', 'neutral'),
                'vwap_analysis': analysis_data.get('indicators_analysis', {}).get('VWAP', {}).get('analysis', ''),
                'vwap_support_trend': analysis_data.get('indicators_analysis', {}).get('VWAP', {}).get('support_trend', 'neutral'),
                'funding_rate_analysis': analysis_data.get('indicators_analysis', {}).get('FundingRate', {}).get('analysis', ''),
                'funding_rate_support_trend': analysis_data.get('indicators_analysis', {}).get('FundingRate', {}).get('support_trend', 'neutral'),
                'exchange_netflow_analysis': analysis_data.get('indicators_analysis', {}).get('ExchangeNetflow', {}).get('analysis', ''),
                'exchange_netflow_support_trend': analysis_data.get('indicators_analysis', {}).get('ExchangeNetflow', {}).get('support_trend', 'neutral'),
                'nupl_analysis': analysis_data.get('indicators_analysis', {}).get('NUPL', {}).get('analysis', ''),
                'nupl_support_trend': analysis_data.get('indicators_analysis', {}).get('NUPL', {}).get('support_trend', 'neutral'),
                'mayer_multiple_analysis': analysis_data.get('indicators_analysis', {}).get('MayerMultiple', {}).get('analysis', ''),
                'mayer_multiple_support_trend': analysis_data.get('indicators_analysis', {}).get('MayerMultiple', {}).get('support_trend', 'neutral'),
                'trading_action': analysis_data.get('trading_action', '等待'),
                'trading_reason': analysis_data.get('trading_reason', ''),
                'entry_price': analysis_data.get('entry_price', 0),
                'stop_loss': analysis_data.get('stop_loss', 0),
                'take_profit': analysis_data.get('take_profit', 0),
                'risk_level': analysis_data.get('risk_level', '中'),
                'risk_score': analysis_data.get('risk_score', 50),
                'risk_details': analysis_data.get('risk_details', [])
            }
        )

        return report

    async def _get_coze_analysis(self, symbol, indicators, technical_analysis, language='en-US'):
        """获取Coze分析

        Args:
            symbol: 代币符号
            indicators: 技术指标数据
            technical_analysis: 技术分析记录
            language: 语言代码，默认为'en-US'（注意：目前我们只保存英文报告，忽略此参数）

        Returns:
            dict: 分析数据
        """
        # 强制使用英文，忽略传入的language参数
        language = 'en-US'
        try:
            # 记录开始时间
            coze_start_time = time.time()

            # 初始化 Coze API 配置
            self._init_coze_api()

            # 确保 API 密钥不是占位符
            if self.coze_api_key == 'your_api_key_here':
                logger.error("Coze API 密钥是占位符，请设置正确的 API 密钥")
                return None

            # 获取市场数据
            market_data = self.market_service.get_market_data(symbol)
            if not market_data:
                logger.error(f"获取市场数据失败: {symbol}")
                return None

            # 构建请求头
            headers = {
                "Authorization": f"Bearer {self.coze_api_key}",
                "Content-Type": "application/json",
                "Accept": "*/*",
                "Connection": "keep-alive"
            }

            # 构建消息内容
            # 将资金费率转换为百分比形式
            funding_rate = indicators.get('FundingRate', 0)
            if funding_rate is not None:
                funding_rate = funding_rate * 100  # 转换为百分比形式

            # 构建技术指标消息
            indicators_message = f"""
            请分析以下加密货币 {symbol} 的技术指标数据，并提供详细的分析报告：

            当前价格: {market_data['price']} USDT

            技术指标:
            - RSI: {indicators.get('RSI')}
            - MACD: 线 {indicators.get('MACD', {}).get('line')}, 信号线 {indicators.get('MACD', {}).get('signal')}, 柱状图 {indicators.get('MACD', {}).get('histogram')}
            - 布林带: 上轨 {indicators.get('BollingerBands', {}).get('upper')}, 中轨 {indicators.get('BollingerBands', {}).get('middle')}, 下轨 {indicators.get('BollingerBands', {}).get('lower')}
            - BIAS: {indicators.get('BIAS')}
            - PSY: {indicators.get('PSY')}
            - DMI: +DI {indicators.get('DMI', {}).get('plus_di')}, -DI {indicators.get('DMI', {}).get('minus_di')}, ADX {indicators.get('DMI', {}).get('adx')}
            - VWAP: {indicators.get('VWAP')}
            - 资金费率: {funding_rate}%
            - 交易所净流入: {indicators.get('ExchangeNetflow')}
            - NUPL: {indicators.get('NUPL')}
            - Mayer Multiple: {indicators.get('MayerMultiple')}

            请使用 {language} 语言回复，并按照以下JSON格式提供分析结果：
            ```json
            {{
                "trend_up_probability": 0-100之间的整数，表示上涨概率,
                "trend_sideways_probability": 0-100之间的整数，表示横盘概率,
                "trend_down_probability": 0-100之间的整数，表示下跌概率,
                "trend_summary": "对趋势的总体分析和预测",
                "indicators_analysis": {{
                    "RSI": {{
                        "analysis": "RSI指标分析",
                        "support_trend": "bullish/bearish/neutral"
                    }},
                    "MACD": {{
                        "analysis": "MACD指标分析",
                        "support_trend": "bullish/bearish/neutral"
                    }},
                    "BollingerBands": {{
                        "analysis": "布林带指标分析",
                        "support_trend": "bullish/bearish/neutral"
                    }},
                    "BIAS": {{
                        "analysis": "BIAS指标分析",
                        "support_trend": "bullish/bearish/neutral"
                    }},
                    "PSY": {{
                        "analysis": "PSY指标分析",
                        "support_trend": "bullish/bearish/neutral"
                    }},
                    "DMI": {{
                        "analysis": "DMI指标分析",
                        "support_trend": "bullish/bearish/neutral"
                    }},
                    "VWAP": {{
                        "analysis": "VWAP指标分析",
                        "support_trend": "bullish/bearish/neutral"
                    }},
                    "FundingRate": {{
                        "analysis": "资金费率分析",
                        "support_trend": "bullish/bearish/neutral"
                    }},
                    "ExchangeNetflow": {{
                        "analysis": "交易所净流入分析",
                        "support_trend": "bullish/bearish/neutral"
                    }},
                    "NUPL": {{
                        "analysis": "NUPL指标分析",
                        "support_trend": "bullish/bearish/neutral"
                    }},
                    "MayerMultiple": {{
                        "analysis": "Mayer Multiple指标分析",
                        "support_trend": "bullish/bearish/neutral"
                    }}
                }},
                "trading_action": "买入/卖出/持有/等待",
                "trading_reason": "交易建议的原因",
                "entry_price": 建议入场价格,
                "stop_loss": 建议止损价格,
                "take_profit": 建议止盈价格,
                "risk_level": "高/中/低",
                "risk_score": 0-100之间的整数，表示风险评分,
                "risk_details": ["风险因素1", "风险因素2", ...]
            }}
            ```

            请确保所有概率之和为100，并提供详细的分析理由。
            """

            # 准备发送给Coze的提示内容

            # 构建请求体
            payload = {
                "bot_id": self.coze_bot_id,
                "user_id": f"crypto_user_{int(time.time())}",  # 使用时间戳生成唯一用户ID
                "stream": False,  # 不使用流式响应
                "auto_save_history": True,
                "additional_messages": [
                    {
                        "role": "user",
                        "content": indicators_message,
                        "content_type": "text"
                    }
                ]
            }

            # 设置超时
            timeout = aiohttp.ClientTimeout(total=60)  # 60秒超时

            # 发送请求创建对话
            async with aiohttp.ClientSession(timeout=timeout) as session:
                try:
                    async with session.post(
                        f"{self.coze_api_url}/v3/chat",
                        headers=headers,
                        json=payload
                    ) as response:
                        response_text = await response.text()

                        if response.status != 200:
                            logger.error(f"Coze API请求失败: HTTP状态码 {response.status}")
                            return None

                        try:
                            response_data = json.loads(response_text)
                            if response_data.get('code') != 0:
                                logger.error(f"Coze API响应错误: {response_data}")
                                return None
                        except json.JSONDecodeError:
                            logger.error(f"无法解析Coze API响应: {response_text}")
                            return None

                        data = response_data.get('data', {})
                        chat_id = data.get('id')
                        conversation_id = data.get('conversation_id')

                        if not chat_id or not conversation_id:
                            logger.error("创建对话响应中缺少必要的ID")
                            return None

                        # 直接从创建对话的响应中获取内容，而不是再次请求
                        # Coze API已经在创建对话时返回了完整的响应，无需再次请求

                        # 从响应中提取消息内容
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

                                # 尝试从回复中提取JSON
                                json_start = content.find('```json')
                                json_end = content.rfind('```')

                                if json_start != -1 and json_end != -1 and json_end > json_start:
                                    json_content = content[json_start + 7:json_end].strip()
                                    try:
                                        analysis_data = json.loads(json_content)
                                        logger.info(f"成功解析Coze分析数据，耗时: {time.time() - coze_start_time:.2f}秒")
                                        return analysis_data
                                    except json.JSONDecodeError as e:
                                        logger.error(f"解析JSON失败: {str(e)}")
                                        logger.error(f"JSON内容: {json_content}")
                                else:
                                    logger.warning("未找到JSON内容，尝试直接解析整个回复")
                                    try:
                                        # 尝试直接解析整个回复
                                        analysis_data = json.loads(content)
                                        logger.info(f"成功解析Coze分析数据，耗时: {time.time() - coze_start_time:.2f}秒")
                                        return analysis_data
                                    except json.JSONDecodeError:
                                        logger.warning("直接解析整个回复失败")
                            else:
                                logger.warning("未找到助手的回复")
                        except Exception as e:
                            logger.error(f"处理Coze响应时发生错误: {str(e)}")

                        # 轮询获取对话结果，参考线上正确的实现
                        max_retries = 20  # 最大重试次数
                        retry_count = 0
                        retry_interval = 1.0  # 初始重试间隔（秒）
                        max_retry_interval = 5.0  # 最大重试间隔（秒）

                        # 添加初始延迟，给Coze API更多时间来生成回复
                        await asyncio.sleep(2.0)

                        # 设置超时
                        timeout = aiohttp.ClientTimeout(total=30)

                        # 轮询获取对话结果
                        while retry_count < max_retries:
                            try:
                                # 构建获取对话状态的请求
                                retrieve_url = f"{self.coze_api_url}/v3/chat/retrieve"
                                retrieve_params = {
                                    "bot_id": self.coze_bot_id,
                                    "chat_id": chat_id,
                                    "conversation_id": conversation_id
                                }

                                async with aiohttp.ClientSession(timeout=timeout) as session:
                                    async with session.get(retrieve_url, headers=headers, params=retrieve_params) as status_response:
                                        status_text = await status_response.text()

                                        if status_response.status == 200:
                                            try:
                                                status_data = json.loads(status_text)
                                                if status_data.get('code') == 0:
                                                    data = status_data.get('data', {})
                                                    status = data.get('status')

                                                    if status == "completed":
                                                        # 获取消息列表
                                                        message_list_url = f"{self.coze_api_url}/v3/chat/message/list"
                                                        message_list_params = {
                                                            "bot_id": self.coze_bot_id,
                                                            "chat_id": chat_id,
                                                            "conversation_id": conversation_id
                                                        }

                                                        async with session.get(message_list_url, headers=headers, params=message_list_params) as messages_response:
                                                            messages_text = await messages_response.text()
                                                            if messages_response.status == 200:
                                                                try:
                                                                    messages_data = json.loads(messages_text)
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
                                                                            await asyncio.sleep(retry_interval)
                                                                            retry_interval = min(retry_interval * 1.5, max_retry_interval)
                                                                            continue

                                                                        # 查找助手的回复
                                                                        for message in messages:
                                                                            if message.get('role') == 'assistant' and message.get('type') == 'answer':
                                                                                content = message.get('content', '')
                                                                                if content and content != '###':
                                                                                    try:
                                                                                        # 如果内容以 ```json 开头，则去掉前7个和后3个字符
                                                                                        if content.startswith('```json'):
                                                                                            content = content[7:-3].strip()

                                                                                        # 尝试解析JSON
                                                                                        analysis_data = json.loads(content)

                                                                                        # 转换数据格式
                                                                                        formatted_data = {
                                                                                            'trend_up_probability': analysis_data.get('trend_analysis', {}).get('probabilities', {}).get('up', 0),
                                                                                            'trend_sideways_probability': analysis_data.get('trend_analysis', {}).get('probabilities', {}).get('sideways', 0),
                                                                                            'trend_down_probability': analysis_data.get('trend_analysis', {}).get('probabilities', {}).get('down', 0),
                                                                                            'trend_summary': analysis_data.get('trend_analysis', {}).get('summary', ''),
                                                                                            'indicators_analysis': analysis_data.get('indicators_analysis', {}),
                                                                                            'trading_action': analysis_data.get('trading_advice', {}).get('action', '等待'),
                                                                                            'trading_reason': analysis_data.get('trading_advice', {}).get('reason', ''),
                                                                                            'entry_price': float(analysis_data.get('trading_advice', {}).get('entry_price', 0)),
                                                                                            'stop_loss': float(analysis_data.get('trading_advice', {}).get('stop_loss', 0)),
                                                                                            'take_profit': float(analysis_data.get('trading_advice', {}).get('take_profit', 0)),
                                                                                            'risk_level': analysis_data.get('risk_assessment', {}).get('level', '中'),
                                                                                            'risk_score': int(analysis_data.get('risk_assessment', {}).get('score', 50)),
                                                                                            'risk_details': analysis_data.get('risk_assessment', {}).get('details', [])
                                                                                        }

                                                                                        # 成功解析Coze分析数据
                                                                                        return formatted_data
                                                                                    except json.JSONDecodeError as e:
                                                                                        logger.error(f"解析JSON失败: {str(e)}")
                                                                                        logger.error(f"JSON内容: {content}")
                                                                    else:
                                                                        logger.error(f"获取消息列表响应错误: {messages_data}")
                                                                except json.JSONDecodeError:
                                                                    logger.error(f"解析消息列表响应失败: {messages_text}")
                                                            else:
                                                                logger.error(f"获取消息列表失败: HTTP状态码 {messages_response.status}")
                                                else:
                                                    logger.warning(f"获取对话状态响应错误: {status_data}")
                                            except json.JSONDecodeError:
                                                logger.error(f"解析对话状态响应失败: {status_text}")
                                        else:
                                            logger.error(f"获取对话状态失败: HTTP状态码 {status_response.status}")
                            except asyncio.TimeoutError:
                                logger.error("获取对话状态超时")
                            except Exception as e:
                                logger.error(f"获取对话状态时发生错误: {str(e)}")

                            # 如果没有获取到完整结果，继续重试
                            retry_count += 1
                            await asyncio.sleep(retry_interval)
                            retry_interval = min(retry_interval * 1.5, max_retry_interval)  # 指数退避，最大5秒



                        # 在重试失败后，返回默认分析
                        logger.warning("轮询Coze API未获得有效响应，返回默认分析")
                        return self._create_default_analysis(indicators, float(market_data['price']))

                except asyncio.TimeoutError:
                    logger.error("Coze API 请求超时")
                    return None
                except aiohttp.ClientError as e:
                    logger.error(f"Coze API 请求错误: {str(e)}")
                    return None

        except Exception as e:
            logger.error(f"获取Coze分析时发生错误: {str(e)}")
            return None

    def _create_default_analysis(self, indicators, price):
        """创建默认分析报告

        Args:
            indicators: 技术指标数据
            price: 当前价格

        Returns:
            dict: 默认分析数据
        """
        # 创建默认分析报告
        return {
            'trend_up_probability': 33,
            'trend_sideways_probability': 34,
            'trend_down_probability': 33,
            'trend_summary': "由于无法获取完整分析，系统生成了默认分析报告。根据当前市场情况，建议谨慎操作，等待更明确的市场信号。",
            'indicators_analysis': {
                'RSI': {
                    'analysis': "RSI指标分析暂不可用",
                    'support_trend': "neutral"
                },
                'MACD': {
                    'analysis': "MACD指标分析暂不可用",
                    'support_trend': "neutral"
                },
                'BollingerBands': {
                    'analysis': "布林带指标分析暂不可用",
                    'support_trend': "neutral"
                },
                'BIAS': {
                    'analysis': "BIAS指标分析暂不可用",
                    'support_trend': "neutral"
                },
                'PSY': {
                    'analysis': "PSY指标分析暂不可用",
                    'support_trend': "neutral"
                },
                'DMI': {
                    'analysis': "DMI指标分析暂不可用",
                    'support_trend': "neutral"
                },
                'VWAP': {
                    'analysis': "VWAP指标分析暂不可用",
                    'support_trend': "neutral"
                },
                'FundingRate': {
                    'analysis': "资金费率分析暂不可用",
                    'support_trend': "neutral"
                },
                'ExchangeNetflow': {
                    'analysis': "交易所净流入分析暂不可用",
                    'support_trend': "neutral"
                },
                'NUPL': {
                    'analysis': "NUPL指标分析暂不可用",
                    'support_trend': "neutral"
                },
                'MayerMultiple': {
                    'analysis': "Mayer Multiple指标分析暂不可用",
                    'support_trend': "neutral"
                }
            },
            'trading_action': '等待',
            'trading_reason': '无法获取完整分析，建议等待更明确的市场信号',
            'entry_price': price,
            'stop_loss': price * 0.95,
            'take_profit': price * 1.05,
            'risk_level': '中',
            'risk_score': 50,
            'risk_details': ['无法完成分析，使用默认风险评估']
        }

    async def _build_response(self, symbol, market_data, indicators, report):
        """构建响应数据

        Args:
            symbol: 代币符号
            market_data: 市场数据
            indicators: 技术指标数据
            report: 分析报告记录

        Returns:
            dict: 响应数据
        """
        # 构建响应数据
        response_data = {
            'symbol': symbol,
            'price': market_data['price'],
            'timestamp': report.timestamp.isoformat(),
            'trend': {
                'up_probability': report.trend_up_probability or 0,
                'sideways_probability': report.trend_sideways_probability or 0,
                'down_probability': report.trend_down_probability or 0,
                'summary': report.trend_summary or ""
            },
            'indicators_analysis': {
                'RSI': {
                    'value': float(indicators.get('RSI', 0)),
                    'analysis': report.rsi_analysis,
                    'support_trend': report.rsi_support_trend
                },
                'MACD': {
                    'value': {
                        'line': float(indicators.get('MACD', {}).get('line', 0)),
                        'signal': float(indicators.get('MACD', {}).get('signal', 0)),
                        'histogram': float(indicators.get('MACD', {}).get('histogram', 0))
                    },
                    'analysis': report.macd_analysis,
                    'support_trend': report.macd_support_trend
                },
                'BollingerBands': {
                    'value': {
                        'upper': float(indicators.get('BollingerBands', {}).get('upper', 0)),
                        'middle': float(indicators.get('BollingerBands', {}).get('middle', 0)),
                        'lower': float(indicators.get('BollingerBands', {}).get('lower', 0))
                    },
                    'analysis': report.bollinger_analysis,
                    'support_trend': report.bollinger_support_trend
                },
                'BIAS': {
                    'value': float(indicators.get('BIAS', 0)),
                    'analysis': report.bias_analysis,
                    'support_trend': report.bias_support_trend
                },
                'PSY': {
                    'value': float(indicators.get('PSY', 0)),
                    'analysis': report.psy_analysis,
                    'support_trend': report.psy_support_trend
                },
                'DMI': {
                    'value': {
                        'plus_di': float(indicators.get('DMI', {}).get('plus_di', 0)),
                        'minus_di': float(indicators.get('DMI', {}).get('minus_di', 0)),
                        'adx': float(indicators.get('DMI', {}).get('adx', 0))
                    },
                    'analysis': report.dmi_analysis,
                    'support_trend': report.dmi_support_trend
                },
                'VWAP': {
                    'value': float(indicators.get('VWAP', 0)),
                    'analysis': report.vwap_analysis,
                    'support_trend': report.vwap_support_trend
                },
                'FundingRate': {
                    'value': float(indicators.get('FundingRate', 0)) * 100,  # 转换为百分比形式
                    'analysis': report.funding_rate_analysis,
                    'support_trend': report.funding_rate_support_trend
                },
                'ExchangeNetflow': {
                    'value': float(indicators.get('ExchangeNetflow', 0)),
                    'analysis': report.exchange_netflow_analysis,
                    'support_trend': report.exchange_netflow_support_trend
                },
                'NUPL': {
                    'value': float(indicators.get('NUPL', 0)),
                    'analysis': report.nupl_analysis,
                    'support_trend': report.nupl_support_trend
                },
                'MayerMultiple': {
                    'value': float(indicators.get('MayerMultiple', 0)),
                    'analysis': report.mayer_multiple_analysis,
                    'support_trend': report.mayer_multiple_support_trend
                }
            },
            'trading': {
                'action': report.trading_action or "等待",
                'reason': report.trading_reason or "",
                'entry_price': report.entry_price or float(market_data['price']),
                'stop_loss': report.stop_loss or float(market_data['price']) * 0.95,
                'take_profit': report.take_profit or float(market_data['price']) * 1.05
            },
            'risk': {
                'level': report.risk_level or "中",
                'score': report.risk_score or 50,
                'details': report.risk_details or []
            }
        }

        return response_data
