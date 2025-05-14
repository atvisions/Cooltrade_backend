from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
from .services.technical_analysis import TechnicalAnalysisService
from .services.token_data_service import TokenDataService
from .services.market_data_service import MarketDataService
from .services.analysis_report_service import AnalysisReportService
from .services.okx_api import OKXAPI
from .models import Token as CryptoToken, Chain, AnalysisReport, TechnicalAnalysis, MarketData, User, VerificationCode, InvitationCode
from .utils import logger, sanitize_indicators, format_timestamp, parse_timestamp, safe_json_loads
import numpy as np
from typing import Dict, Optional, List
import pandas as pd
from datetime import datetime, timedelta
import pytz
from django.utils import timezone
import requests
import json
import asyncio
import aiohttp
from asgiref.sync import sync_to_async
import time
import base64
import traceback
import os
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.contrib.auth import get_user_model, authenticate
from django.core.mail import send_mail
import random
import string
from rest_framework.authtoken.models import Token as AuthToken
from .serializers import (
    UserSerializer, RegisterSerializer, LoginSerializer,
    SendVerificationCodeSerializer, TokenRefreshSerializer,
    ChangePasswordSerializer, ResetPasswordWithCodeSerializer, ResetPasswordCodeSerializer
)
from django.shortcuts import render

class TechnicalIndicatorsAPIView(APIView):
    """技术指标API视图"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.ta_service = None  # 延迟初始化
        self.market_service = None  # 延迟初始化
        self.report_service = None  # 延迟初始化
        self.okx_api = None  # 延迟初始化
        self._init_coze_api()

    def _lazy_init_services(self):
        """延迟初始化服务，只在需要时创建实例"""
        if self.ta_service is None:
            self.ta_service = TechnicalAnalysisService()
            logger.info("延迟初始化: 技术分析服务")
        if self.market_service is None:
            self.market_service = MarketDataService()
            logger.info("延迟初始化: 市场数据服务")
        if self.report_service is None:
            self.report_service = AnalysisReportService()
            logger.info("延迟初始化: 分析报告服务")
        if self.okx_api is None:
            self.okx_api = OKXAPI()
            logger.info("延迟初始化: OKX API服务")

    def get(self, request, symbol: str):
        """同步入口点，调用异步处理"""
        # 检查是否需要强制刷新
        force_refresh = request.query_params.get('force_refresh', 'false').lower() == 'true'

        try:
            # 统一 symbol 格式，去除常见后缀
            clean_symbol = symbol.upper().replace('USDT', '').replace('-PERP', '').replace('_PERP', '').replace('PERP', '')

            # 在 get 方法中添加日志
            logger.info(f"查询 symbol: {symbol}, clean_symbol: {clean_symbol}")
            try:
                token = CryptoToken.objects.get(symbol=clean_symbol)
                logger.info(f"找到 token: {token.id}, {token.symbol}")
                token_exists = True
            except CryptoToken.DoesNotExist:
                logger.info(f"未找到 token: {clean_symbol}")
                token_exists = False

            if force_refresh:
                # 强制刷新数据
                return self._handle_force_refresh(symbol, token_exists)

            if not token_exists:
                return Response({
                    'status': 'not_found',
                    'message': f"未找到代币 {clean_symbol} 的分析数据",
                    'needs_refresh': True
                }, status=status.HTTP_404_NOT_FOUND)

            # 获取最新的分析报告
            latest_report = AnalysisReport.objects.filter(token=token).order_by('-timestamp').first()

            if not latest_report:
                return Response({
                    'status': 'not_found',
                    'message': f"未找到代币 {clean_symbol} 的分析数据",
                    'needs_refresh': True
                }, status=status.HTTP_404_NOT_FOUND)

            # 获取相关的技术分析数据
            technical_analysis = TechnicalAnalysis.objects.filter(token=token).order_by('-timestamp').first()
            market_data = MarketData.objects.filter(token=token).order_by('-timestamp').first()

            if not technical_analysis or not market_data:
                return Response({
                    'status': 'not_found',
                    'message': f"未找到代币 {clean_symbol} 的完整数据",
                    'needs_refresh': True
                }, status=status.HTTP_404_NOT_FOUND)

            # 尝试获取实时价格，但不阻止主要功能
            try:
                # 只有在需要时才初始化 okx_api
                if self.okx_api is None:
                    self.okx_api = OKXAPI()

                realtime_price = self.okx_api.get_realtime_price(symbol)
                if realtime_price:
                    market_data.price = realtime_price
                    market_data.save()
            except Exception as price_error:
                # 记录错误但继续使用数据库中的价格
                logger.warning(f"获取实时价格失败，使用数据库价格: {str(price_error)}")

            # 构建响应数据
            response_data = {
                'status': 'success',
                'data': {
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
                        'entry_price': float(latest_report.entry_price),
                        'stop_loss': float(latest_report.stop_loss),
                        'take_profit': float(latest_report.take_profit)
                    },
                    'risk_assessment': {
                        'level': latest_report.risk_level,
                        'score': int(latest_report.risk_score),
                        'details': latest_report.risk_details
                    },
                    'current_price': float(market_data.price),
                    'snapshot_price': float(latest_report.snapshot_price),
                    'last_update_time': format_timestamp(latest_report.timestamp)
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

    def _handle_force_refresh(self, symbol: str, token_exists: bool = False):
        """强制刷新数据"""
        try:
            # 初始化必要的服务
            self._lazy_init_services()

            # 增加检查，确保服务已初始化
            if self.ta_service is None:
                self.ta_service = TechnicalAnalysisService()
                logger.info("手动初始化技术分析服务")
            if self.market_service is None:
                self.market_service = MarketDataService()
                logger.info("手动初始化市场数据服务")
            if self.report_service is None:
                self.report_service = AnalysisReportService()
                logger.info("手动初始化分析报告服务")
            if self.okx_api is None:
                self.okx_api = OKXAPI()
                logger.info("手动初始化OKX API服务")

            # 获取最新的技术指标数据
            technical_data = self.ta_service.get_all_indicators(symbol)
            if technical_data['status'] == 'error':
                logger.error(f"获取技术指标数据失败: {technical_data.get('message', '未知错误')}")
                return Response({
                    'status': 'error',
                    'message': technical_data.get('message', '获取技术指标数据失败')
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # 获取市场数据
            market_data = self.market_service.get_market_data(symbol)
            if not market_data:
                logger.error(f"获取市场数据失败: {symbol}")
                return Response({
                    'status': 'error',
                    'message': f"获取市场数据失败"
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # 获取 Chain 记录
            try:
                chain = Chain.objects.get(chain='CRYPTO')
            except Chain.DoesNotExist:
                # 如果不存在，创建新记录
                chain = Chain.objects.create(
                    chain='CRYPTO',
                    is_active=True,
                    is_testnet=False
                )

            # 统一 symbol 格式，去除常见后缀
            clean_symbol = symbol.upper().replace('USDT', '').replace('-PERP', '').replace('_PERP', '').replace('PERP', '')

            # 获取 Token 记录
            try:
                token = CryptoToken.objects.get(symbol=clean_symbol)
            except CryptoToken.DoesNotExist:
                # 如果不存在，创建新记录
                token = CryptoToken.objects.create(
                    symbol=clean_symbol,
                    chain=chain,
                    name=clean_symbol,
                    address='0x0000000000000000000000000000000000000000',
                    decimals=18
                )

            # 更新技术分析数据
            indicators = technical_data['data']['indicators']
            technical_analysis = self._update_analysis_data(token, indicators, market_data['price'])

            # 尝试使用Coze API获取分析结果
            try:
                # 如果有Coze API配置，使用异步调用，但这里需要在同步环境中执行
                analysis_data = None

                if hasattr(self, 'coze_api_key') and self.coze_api_key:
                    logger.info(f"准备获取Coze分析: {symbol}")
                    # 借助异步转同步执行
                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        # 首先测试认证
                        auth_ok = loop.run_until_complete(self._test_coze_auth())
                        if auth_ok:
                            logger.info("Coze API认证成功，获取分析报告")
                            analysis_data = loop.run_until_complete(
                                self._get_coze_analysis(symbol, indicators, technical_analysis)
                            )
                        else:
                            logger.warning("Coze API认证失败，使用默认分析报告")
                    finally:
                        loop.close()

                # 如果没有获取到Coze分析，使用默认分析报告
                if not analysis_data:
                    logger.info("使用默认分析报告")
                    analysis_data = self._create_default_analysis(indicators, float(market_data['price']))

                # 保存分析报告
                try:
                    # 使用默认语言，因为这里没有request对象
                    language = 'zh-CN'  # 默认语言

                    # 使用 report_service 保存分析报告，不用 await
                    self.report_service.save_analysis_report(clean_symbol, analysis_data, language)

                    # 添加时间戳字段，使用当前时间
                    analysis_data['last_update_time'] = format_timestamp(timezone.now())

                    # 添加当前价格字段
                    analysis_data['current_price'] = float(market_data['price'])

                except Exception as e:
                    logger.error(f"保存分析报告失败: {str(e)}")
                    return Response({
                        'status': 'error',
                        'message': f"保存分析报告失败: {str(e)}"
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

                # 返回最新数据
                try:
                    # 获取代币信息，使用清理后的符号
                    token = CryptoToken.objects.get(symbol=clean_symbol)

                    # 获取最新的分析报告
                    latest_report = AnalysisReport.objects.filter(token=token).order_by('-timestamp').first()

                    if not latest_report:
                        return Response({
                            'status': 'not_found',
                            'message': f"未找到代币 {clean_symbol} 的分析数据",
                            'needs_refresh': True
                        }, status=status.HTTP_404_NOT_FOUND)

                    # 获取相关的技术分析数据
                    technical_analysis = TechnicalAnalysis.objects.filter(token=token).order_by('-timestamp').first()
                    market_data = MarketData.objects.filter(token=token).order_by('-timestamp').first()

                    if not technical_analysis or not market_data:
                        return Response({
                            'status': 'not_found',
                            'message': f"未找到代币 {clean_symbol} 的完整数据",
                            'needs_refresh': True
                        }, status=status.HTTP_404_NOT_FOUND)

                    # 获取实时价格
                    realtime_price = self.okx_api.get_realtime_price(symbol)
                    if realtime_price:
                        market_data.price = realtime_price
                        market_data.save()

                    # 构建响应数据
                    response_data = {
                        'status': 'success',
                        'data': {
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
                                'entry_price': float(latest_report.entry_price),
                                'stop_loss': float(latest_report.stop_loss),
                                'take_profit': float(latest_report.take_profit)
                            },
                            'risk_assessment': {
                                'level': latest_report.risk_level,
                                'score': int(latest_report.risk_score),
                                'details': latest_report.risk_details
                            },
                            'current_price': float(market_data.price),
                            'snapshot_price': float(latest_report.snapshot_price),
                            'last_update_time': format_timestamp(latest_report.timestamp)
                        }
                    }

                    return Response(response_data)

                except CryptoToken.DoesNotExist:
                    return Response({
                        'status': 'not_found',
                        'message': f"未找到代币 {clean_symbol} 的分析数据",
                        'needs_refresh': True
                    }, status=status.HTTP_404_NOT_FOUND)
                except Exception as e:
                    logger.error(f"从数据库读取数据时发生错误: {str(e)}")
                    return Response({
                        'status': 'error',
                        'message': f"读取数据失败: {str(e)}",
                        'needs_refresh': True
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            except Exception as e:
                logger.error(f"保存分析报告时发生错误: {str(e)}")
                return Response({
                    'status': 'error',
                    'message': f"保存分析报告失败: {str(e)}"
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        except Exception as e:
            error_msg = str(e)
            if not error_msg:  # 处理空错误信息
                error_msg = "未知错误"
            logger.error(f"强制刷新数据时发生错误: {error_msg}")
            logger.error(f"错误类型: {type(e).__name__}")
            logger.error(f"堆栈跟踪: {traceback.format_exc()}")
            return Response({
                'status': 'error',
                'message': f"刷新数据失败: {error_msg}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _update_analysis_data(self, token: CryptoToken, indicators: Dict, current_price: float) -> None:
        """更新技术分析数据"""
        try:
            # 处理指标数据
            indicators = sanitize_indicators(indicators)

            # 创建或更新技术分析记录
            technical_analysis, _ = TechnicalAnalysis.objects.update_or_create(
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

            # 创建或更新市场数据记录
            MarketData.objects.update_or_create(
                token=token,
                timestamp=timezone.now(),
                defaults={
                    'price': current_price,
                    'volume': 0.0,
                    'price_change_24h': 0.0,
                    'price_change_percent_24h': 0.0,
                    'high_24h': 0.0,
                    'low_24h': 0.0
                }
            )

            logger.info(f"成功更新代币 {token.symbol} 的技术分析数据")

            return technical_analysis

        except Exception as e:
            logger.error(f"更新代币技术分析数据失败: {str(e)}")
            raise

    def _init_coze_api(self):
        """初始化 Coze API 配置"""
        # 直接使用硬编码的 API 密钥，不再从环境变量获取
        self.coze_api_key = 'pat_mGFYEurP7DS6f9XMW8ZHtAxZwghcYCWfayQraqVYDN4Zz71zvF94Mm3fJ2dV7wBH'
        logger.info("使用硬编码的 COZE_API_KEY")
        logger.info(f"使用 Coze API 密钥: {self.coze_api_key[:10]}...{self.coze_api_key[-5:]}")

        if not hasattr(self, 'coze_bot_id') or not self.coze_bot_id:
            self.coze_bot_id = os.getenv('COZE_BOT_ID', '7494575252253720584')
            if not self.coze_bot_id:
                logger.warning("COZE_BOT_ID 环境变量未设置，使用默认值")
            logger.info(f"使用 Coze Bot ID: {self.coze_bot_id}")

        if not hasattr(self, 'coze_api_url') or not self.coze_api_url:
            self.coze_api_url = os.getenv('COZE_API_URL', 'https://api.coze.com')
            if not self.coze_api_url:
                logger.warning("COZE_API_URL 环境变量未设置，使用默认值")
            logger.info(f"使用 Coze API URL: {self.coze_api_url}")

    def _create_default_analysis(self, indicators: Dict, current_price: float) -> Dict:
        """创建默认的分析报告"""
        return {
            'trend_up_probability': 33,
            'trend_sideways_probability': 34,
            'trend_down_probability': 33,
            'trend_summary': '暂无趋势分析',
            'indicators_analysis': {
                'RSI': {
                    'value': float(indicators.get('RSI', 0)),
                    'analysis': '暂无RSI分析',
                    'support_trend': 'neutral'
                },
                'MACD': {
                    'value': {
                        'line': float(indicators.get('MACD', {}).get('line', 0)),
                        'signal': float(indicators.get('MACD', {}).get('signal', 0)),
                        'histogram': float(indicators.get('MACD', {}).get('histogram', 0))
                    },
                    'analysis': '暂无MACD分析',
                    'support_trend': 'neutral'
                },
                'BollingerBands': {
                    'value': {
                        'upper': float(indicators.get('BollingerBands', {}).get('upper', 0)),
                        'middle': float(indicators.get('BollingerBands', {}).get('middle', 0)),
                        'lower': float(indicators.get('BollingerBands', {}).get('lower', 0))
                    },
                    'analysis': '暂无布林带分析',
                    'support_trend': 'neutral'
                },
                'BIAS': {
                    'value': float(indicators.get('BIAS', 0)),
                    'analysis': '暂无BIAS分析',
                    'support_trend': 'neutral'
                },
                'PSY': {
                    'value': float(indicators.get('PSY', 0)),
                    'analysis': '暂无PSY分析',
                    'support_trend': 'neutral'
                },
                'DMI': {
                    'value': {
                        'plus_di': float(indicators.get('DMI', {}).get('plus_di', 0)),
                        'minus_di': float(indicators.get('DMI', {}).get('minus_di', 0)),
                        'adx': float(indicators.get('DMI', {}).get('adx', 0))
                    },
                    'analysis': '暂无DMI分析',
                    'support_trend': 'neutral'
                },
                'VWAP': {
                    'value': float(indicators.get('VWAP', 0)),
                    'analysis': '暂无VWAP分析',
                    'support_trend': 'neutral'
                },
                'FundingRate': {
                    'value': float(indicators.get('FundingRate', 0)),
                    'analysis': '暂无资金费率分析',
                    'support_trend': 'neutral'
                },
                'ExchangeNetflow': {
                    'value': float(indicators.get('ExchangeNetflow', 0)),
                    'analysis': '暂无交易所净流入分析',
                    'support_trend': 'neutral'
                },
                'NUPL': {
                    'value': float(indicators.get('NUPL', 0)),
                    'analysis': '暂无NUPL分析',
                    'support_trend': 'neutral'
                },
                'MayerMultiple': {
                    'value': float(indicators.get('MayerMultiple', 0)),
                    'analysis': '暂无梅耶倍数分析',
                    'support_trend': 'neutral'
                }
            },
            'trading_action': '观望',
            'trading_reason': '等待更多信号确认',
            'entry_price': current_price,
            'stop_loss': current_price * 0.95,
            'take_profit': current_price * 1.05,
            'risk_level': '中等',
            'risk_score': 50,
            'risk_details': ['暂无风险评估详情']
        }

    async def _get_coze_analysis(self, symbol: str, indicators: Dict, technical_analysis: TechnicalAnalysis, language: str = 'zh-CN') -> Dict:
        """异步获取 Coze 分析报告

        Args:
            symbol: 代币符号
            indicators: 技术指标数据
            technical_analysis: 技术分析对象
            language: 语言代码，默认为'zh-CN'
        """
        try:
            # 初始化 Coze API 配置
            self._init_coze_api()

            # 确保 API 密钥不是占位符
            if self.coze_api_key == 'your_api_key_here':
                logger.error("Coze API 密钥是占位符，请设置正确的 API 密钥")
                return None

            # 获取市场数据
            market_data = await sync_to_async(self.market_service.get_market_data)(symbol)
            if not market_data:
                logger.error(f"获取市场数据失败: {symbol}")
                return None

            # 构建请求头 - 与 _test_coze_auth 方法保持一致
            headers = {
                "Authorization": f"{self.coze_api_key}",  # 移除 "Bearer " 前缀
                "Content-Type": "application/json",
                "Accept": "*/*",
                "Connection": "keep-alive"
            }

            # 构建请求体
            additional_messages = [{
                "role": "user",
                "content": json.dumps({
                    "technical_indicators": {
                        "symbol": symbol,
                        "interval": "1d",
                        "timestamp": format_timestamp(timezone.now()),
                        "indicators": indicators
                    },
                    "market_data": {
                        "price": market_data['price']
                    },
                    "language": language  # 添加语言参数
                }, ensure_ascii=False),
                "content_type": "text"
            }]

            payload = {
                "bot_id": self.coze_bot_id,
                "user_id": "crypto_user_001",
                "stream": False,
                "auto_save_history": True,
                "additional_messages": additional_messages
            }

            # 设置超时
            timeout = aiohttp.ClientTimeout(total=30)

            # 发送请求创建对话
            async with aiohttp.ClientSession(timeout=timeout) as session:
                try:
                    async with session.post(
                        f"{self.coze_api_url}/v3/chat",
                        headers=headers,
                        json=payload
                    ) as response:
                        response_text = await response.text()
                        logger.info(f"Coze API响应: 状态码={response.status}, 内容={response_text}")

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

                        # 轮询获取对话结果
                        max_retries = 20
                        retry_count = 0
                        retry_interval = 1  # 初始重试间隔（秒）

                        while retry_count < max_retries:
                            try:
                                # 构建获取对话状态的请求
                                retrieve_url = f"{self.coze_api_url}/v3/chat/retrieve"
                                retrieve_params = {
                                    "bot_id": self.coze_bot_id,
                                    "chat_id": chat_id,
                                    "conversation_id": conversation_id
                                }

                                logger.info(f"第 {retry_count + 1} 次尝试获取对话状态")

                                async with session.get(retrieve_url, headers=headers, params=retrieve_params) as status_response:
                                    status_text = await status_response.text()
                                    logger.info(f"状态响应: {status_text}")

                                    if status_response.status == 200:
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
                                                    logger.info(f"消息列表响应: {messages_text}")

                                                    if messages_response.status == 200:
                                                        messages_data = json.loads(messages_text)
                                                        if messages_data.get('code') == 0:
                                                            # 处理消息列表数据
                                                            if "data" in messages_data and isinstance(messages_data["data"], dict) and "messages" in messages_data["data"]:
                                                                messages = messages_data["data"]["messages"]
                                                            elif "data" in messages_data and isinstance(messages_data["data"], list):
                                                                messages = messages_data["data"]
                                                            else:
                                                                logger.error("无法解析消息列表格式")
                                                                return None

                                                            # 查找助手的回复
                                                            for message in messages:
                                                                if message.get('role') == 'assistant' and message.get('type') == 'answer':
                                                                    content = message.get('content', '')
                                                                    if content and content != '###':
                                                                        try:
                                                                            if content.startswith('```json'):
                                                                                content = content[7:-3].strip()
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

                                                                            return formatted_data
                                                                        except json.JSONDecodeError as e:
                                                                            logger.error(f"解析JSON失败: {str(e)}")
                                                                            return None

                                # 如果没有获取到完整结果，继续重试
                                await asyncio.sleep(retry_interval)
                                retry_interval = min(retry_interval * 1.5, 5)  # 指数退避，最大5秒
                                retry_count += 1

                            except asyncio.TimeoutError:
                                logger.error("获取对话状态超时")
                                retry_count += 1
                                await asyncio.sleep(retry_interval)
                            except Exception as e:
                                logger.error(f"获取对话状态时发生错误: {str(e)}")
                                retry_count += 1
                                await asyncio.sleep(retry_interval)

                        logger.error("所有重试失败，无法获取对话结果")
                        return None

                except asyncio.TimeoutError:
                    logger.error("Coze API 请求超时")
                    return None
                except aiohttp.ClientError as e:
                    logger.error(f"Coze API 请求错误: {str(e)}")
                    return None

        except Exception as e:
            logger.error(f"获取Coze分析时发生错误: {str(e)}")
            return None

    async def _test_coze_auth(self) -> bool:
        """测试Coze API认证"""
        try:
            url = f"{self.coze_api_url}/v3/chat"

            # 确保 API 密钥已初始化
            self._init_coze_api()

            # 设置请求头 - 尝试不同的认证头格式，移除 "Bearer " 前缀
            headers = {
                "Authorization": f"{self.coze_api_key}",  # 移除 "Bearer " 前缀
                "Content-Type": "application/json",
                "Accept": "*/*",
                "Connection": "keep-alive"
            }

            # 构建最简单的请求体
            payload = {
                "bot_id": self.coze_bot_id,
                "user_id": "crypto_user_001",
                "stream": False,
                "auto_save_history": True,
                "additional_messages": [
                    {
                        "role": "user",
                        "content": "hi",
                        "content_type": "text"
                    }
                ]
            }

            logger.info(f"Coze API 请求 URL: {url}")
            logger.info(f"Coze API 请求头: {headers}")
            logger.info(f"Coze API 请求体: {payload}")

            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload) as response:
                    response_text = await response.text()
                    logger.info("=== 测试认证响应详情 ===")
                    logger.info(f"响应状态码: {response.status}")
                    logger.info(f"响应头: {dict(response.headers)}")
                    logger.info(f"响应内容: {response_text}")

                    # 解析响应内容
                    try:
                        response_data = json.loads(response_text)
                        # 检查响应中的错误代码
                        if response_data.get('code') != 0:  # 假设 code=0 表示成功
                            logger.error(f"Coze API认证失败: {response_data}")
                            return False
                        return True
                    except json.JSONDecodeError:
                        logger.error(f"无法解析响应内容: {response_text}")
                        return False

        except Exception as e:
            logger.error(f"测试认证失败: {str(e)}")
            return False

    async def async_get(self, request, symbol: str):
        """异步处理 GET 请求"""
        try:
            # 检查是否需要强制刷新
            force_refresh = request.query_params.get('force_refresh', 'false').lower() == 'true'

            # 统一 symbol 格式，去除常见后缀 (移到最前面，确保所有分支都能使用)
            clean_symbol = symbol.upper().replace('USDT', '').replace('-PERP', '').replace('_PERP', '').replace('PERP', '')
            logger.info(f"异步处理请求: symbol={symbol}, clean_symbol={clean_symbol}, force_refresh={force_refresh}")

            # 确保服务已初始化
            if self.ta_service is None:
                self.ta_service = TechnicalAnalysisService()
                logger.info("异步处理：手动初始化技术分析服务")
            if self.market_service is None:
                self.market_service = MarketDataService()
                logger.info("异步处理：手动初始化市场数据服务")
            if self.report_service is None:
                self.report_service = AnalysisReportService()
                logger.info("异步处理：手动初始化分析报告服务")
            if self.okx_api is None:
                self.okx_api = OKXAPI()
                logger.info("异步处理：手动初始化OKX API服务")

            if force_refresh:
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

                # 获取或创建 Chain 记录
                chain, _ = await sync_to_async(Chain.objects.get_or_create)(
                    chain='CRYPTO',  # 使用通用的链名称
                    defaults={
                        'is_active': True,
                        'is_testnet': False
                    }
                )

                # 获取或创建 Token 记录
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

                # 更新分析数据
                technical_analysis = await sync_to_async(self._update_analysis_data)(token, indicators, market_data['price'])

                # 尝试使用Coze API获取分析结果
                try:
                    # 如果有Coze API配置，使用异步调用，但这里需要在同步环境中执行
                    analysis_data = None

                    if hasattr(self, 'coze_api_key') and self.coze_api_key:
                        logger.info(f"准备获取Coze分析: {symbol}")
                        # 借助异步转同步执行
                        import asyncio
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            # 首先测试认证
                            auth_ok = loop.run_until_complete(self._test_coze_auth())
                            if auth_ok:
                                logger.info("Coze API认证成功，获取分析报告")
                                # 获取用户的语言偏好
                                language = 'zh-CN'  # 默认语言
                                if request and hasattr(request, 'user') and request.user.is_authenticated:
                                    language = request.user.language

                                analysis_data = loop.run_until_complete(
                                    self._get_coze_analysis(symbol, indicators, technical_analysis, language)
                                )

                                # 检查是否成功获取分析数据
                                if not analysis_data:
                                    logger.warning("未能获取Coze分析数据，使用默认分析报告")
                            else:
                                logger.warning("Coze API认证失败，使用默认分析报告")
                        finally:
                            loop.close()

                    # 如果没有获取到Coze分析，使用默认分析报告
                    if not analysis_data:
                        logger.info("使用默认分析报告")
                        analysis_data = self._create_default_analysis(indicators, float(market_data['price']))

                    # 保存分析报告
                    try:
                        # 统一使用 clean_symbol
                        await sync_to_async(self.report_service.save_analysis_report)(clean_symbol, analysis_data)

                        # 添加时间戳字段，使用当前时间
                        analysis_data['last_update_time'] = format_timestamp(timezone.now())

                        # 添加当前价格字段
                        analysis_data['current_price'] = float(market_data['price'])

                    except Exception as e:
                        logger.error(f"保存分析报告失败: {str(e)}")
                        return Response({
                            'status': 'error',
                            'message': f"保存分析报告失败: {str(e)}"
                        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

                    # 返回最新数据
                    try:
                        # 获取代币信息，使用清理后的符号
                        token = CryptoToken.objects.get(symbol=clean_symbol)

                        # 获取最新的分析报告
                        latest_report = AnalysisReport.objects.filter(token=token).order_by('-timestamp').first()

                        if not latest_report:
                            return Response({
                                'status': 'not_found',
                                'message': f"未找到代币 {clean_symbol} 的分析数据",
                                'needs_refresh': True
                            }, status=status.HTTP_404_NOT_FOUND)

                        # 获取相关的技术分析数据
                        technical_analysis = TechnicalAnalysis.objects.filter(token=token).order_by('-timestamp').first()
                        market_data = MarketData.objects.filter(token=token).order_by('-timestamp').first()

                        if not technical_analysis or not market_data:
                            return Response({
                                'status': 'not_found',
                                'message': f"未找到代币 {clean_symbol} 的完整数据",
                                'needs_refresh': True
                            }, status=status.HTTP_404_NOT_FOUND)

                        # 获取实时价格
                        realtime_price = self.okx_api.get_realtime_price(symbol)
                        if realtime_price:
                            market_data.price = realtime_price
                            market_data.save()

                        # 构建响应数据
                        response_data = {
                            'status': 'success',
                            'data': {
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
                                    'entry_price': float(latest_report.entry_price),
                                    'stop_loss': float(latest_report.stop_loss),
                                    'take_profit': float(latest_report.take_profit)
                                },
                                'risk_assessment': {
                                    'level': latest_report.risk_level,
                                    'score': int(latest_report.risk_score),
                                    'details': latest_report.risk_details
                                },
                                'current_price': float(market_data.price),
                                'snapshot_price': float(latest_report.snapshot_price),
                                'last_update_time': format_timestamp(latest_report.timestamp)
                            }
                        }

                        return Response(response_data)

                    except CryptoToken.DoesNotExist:
                        return Response({
                            'status': 'not_found',
                            'message': f"未找到代币 {clean_symbol} 的分析数据",
                            'needs_refresh': True
                        }, status=status.HTTP_404_NOT_FOUND)
                    except Exception as e:
                        logger.error(f"从数据库读取数据时发生错误: {str(e)}")
                        return Response({
                            'status': 'error',
                            'message': f"读取数据失败: {str(e)}",
                            'needs_refresh': True
                        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

                except Exception as e:
                    logger.error(f"保存分析报告时发生错误: {str(e)}")
                    return Response({
                        'status': 'error',
                        'message': f"保存分析报告失败: {str(e)}"
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            return Response({
                'status': 'error',
                'message': "未找到数据，请使用 force_refresh=true 参数刷新数据"
            }, status=status.HTTP_404_NOT_FOUND)

        except Exception as e:
            logger.error(f"处理请求时发生错误: {str(e)}")
            return Response({
                'status': 'error',
                'message': f"处理请求失败: {str(e)}",
                'needs_refresh': True
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class TokenDataAPIView(APIView):
    """代币数据API视图"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.token_service = TokenDataService()  # 不传入API密钥，使用免费API

    def get(self, request, token_id: str):
        """获取指定代币的数据

        Args:
            request: HTTP请求对象
            token_id: 代币ID，例如 'bitcoin'

        Returns:
            Response: 包含代币数据的响应
        """
        try:
            # 获取代币数据
            token_data = self.token_service.get_token_data(token_id)

            return Response({
                'status': 'success',
                'data': token_data
            })

        except Exception as e:
            logger.error(f"获取代币数据失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _sanitize_float(self, value, min_val=-np.inf, max_val=np.inf):
        """将输入转换为有效的浮点数，并限制在指定范围内

        Args:
            value: 要处理的输入值
            min_val: 最小有效值，默认为负无穷
            max_val: 最大有效值，默认为正无穷

        Returns:
            float: 处理后的浮点数
        """
        try:
            result = float(value)
            if np.isnan(result) or np.isinf(result):
                return 0.0
            return max(min(result, max_val), min_val)
        except (ValueError, TypeError):
            return 0.0

class TechnicalIndicatorsDataAPIView(APIView):
    """技术指标数据API视图"""
    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.ta_service = None
        self.market_service = None

    async def async_get(self, request, symbol: str):
        """异步处理 GET 请求"""
        try:
            # 确保服务已初始化
            if self.ta_service is None:
                self.ta_service = TechnicalAnalysisService()
                logger.info("TechnicalIndicatorsDataAPIView: 初始化技术分析服务")
            if self.market_service is None:
                self.market_service = MarketDataService()
                logger.info("TechnicalIndicatorsDataAPIView: 初始化市场数据服务")

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

            # 格式化指标数据
            formatted_indicators = {
                'rsi': float(indicators.get('RSI', 0)),
                'macd_line': float(indicators.get('MACD', {}).get('line', 0)),
                'macd_signal': float(indicators.get('MACD', {}).get('signal', 0)),
                'macd_histogram': float(indicators.get('MACD', {}).get('histogram', 0)),
                'bollinger_upper': float(indicators.get('BollingerBands', {}).get('upper', 0)),
                'bollinger_middle': float(indicators.get('BollingerBands', {}).get('middle', 0)),
                'bollinger_lower': float(indicators.get('BollingerBands', {}).get('lower', 0)),
                'bias': float(indicators.get('BIAS', 0)),
                'psy': float(indicators.get('PSY', 0)),
                'dmi_plus': float(indicators.get('DMI', {}).get('plus_di', 0)),
                'dmi_minus': float(indicators.get('DMI', {}).get('minus_di', 0)),
                'dmi_adx': float(indicators.get('DMI', {}).get('adx', 0)),
                'vwap': float(indicators.get('VWAP', 0)),
                'funding_rate': float(indicators.get('FundingRate', 0)),
                'exchange_netflow': float(indicators.get('ExchangeNetflow', 0)),
                'nupl': float(indicators.get('NUPL', 0)),
                'mayer_multiple': float(indicators.get('MayerMultiple', 0))
            }

            return Response({
                'status': 'success',
                'data': {
                    'symbol': symbol,
                    'price': market_data['price'],
                    'indicators': formatted_indicators
                }
            })

        except Exception as e:
            logger.error(f"获取技术指标数据失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def get(self, request, symbol: str):
        """同步入口点，调用异步处理"""
        return asyncio.run(self.async_get(request, symbol))

class SendVerificationCodeView(APIView):
    """发送验证码视图"""
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            serializer = SendVerificationCodeSerializer(data=request.data)
            if not serializer.is_valid():
                return Response({
                    'status': 'error',
                    'message': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)

            email = serializer.validated_data['email']

            # 生成6位数字验证码
            code = ''.join(random.choices(string.digits, k=6))

            # 保存验证码
            expires_at = timezone.now() + timedelta(minutes=10)
            VerificationCode.objects.create(
                email=email,
                code=code,
                expires_at=expires_at
            )

            # 发送邮件
            subject = 'K线军师 - 验证码'
            message = settings.EMAIL_TEMPLATE.format(code=code)
            from_email = settings.DEFAULT_FROM_EMAIL
            recipient_list = [email]

            try:
                logger.info(f"尝试发送邮件到 {email}")
                logger.info(f"使用邮箱: {settings.EMAIL_HOST_USER}")
                logger.info(f"使用服务器: {settings.EMAIL_HOST}:{settings.EMAIL_PORT}")

                send_mail(subject, message, from_email, recipient_list)
                logger.info(f"成功发送验证码到 {email}")

                return Response({
                    'status': 'success',
                    'message': '验证码已发送'
                })
            except Exception as e:
                logger.error(f"发送邮件失败: {str(e)}")
                logger.error(f"错误类型: {type(e)}")
                logger.error(f"错误详情: {str(e)}")

                error_message = '发送验证码失败，请稍后重试'
                if 'Authentication Required' in str(e):
                    error_message = '邮件服务器认证失败，请检查配置'
                elif 'Connection refused' in str(e):
                    error_message = '无法连接到邮件服务器，请检查网络'

                return Response({
                    'status': 'error',
                    'message': error_message
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        except Exception as e:
            logger.error(f"发送验证码失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '发送验证码失败'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class RegisterView(APIView):
    """注册视图"""
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            logger.info(f"开始注册流程，请求数据: {request.data}")

            serializer = RegisterSerializer(data=request.data)
            if not serializer.is_valid():
                logger.error(f"序列化器验证失败: {serializer.errors}")
                return Response({
                    'status': 'error',
                    'message': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)

            # 验证验证码
            email = serializer.validated_data['email']
            code = serializer.validated_data['code']

            logger.info(f"验证验证码: email={email}, code={code}")
            verification = VerificationCode.objects.filter(
                email=email,
                code=code,
                is_used=False,
                expires_at__gt=timezone.now()
            ).first()

            if not verification:
                logger.error(f"验证码验证失败: email={email}, code={code}")
                return Response({
                    'status': 'error',
                    'message': '验证码无效或已过期'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 验证邀请码
            invitation_code = request.data.get('invitation_code')
            if not invitation_code:
                logger.error("邀请码为空")
                return Response({
                    'status': 'error',
                    'message': '邀请码不能为空'
                }, status=status.HTTP_400_BAD_REQUEST)

            try:
                logger.info(f"验证邀请码: {invitation_code}")
                invitation = InvitationCode.objects.get(code=invitation_code, is_used=False)
            except InvitationCode.DoesNotExist:
                logger.error(f"邀请码无效: {invitation_code}")
                return Response({
                    'status': 'error',
                    'message': '无效的邀请码'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 生成随机用户名
            username = f"user_{''.join(random.choices(string.ascii_lowercase + string.digits, k=8))}"
            logger.info(f"生成随机用户名: {username}")

            # 创建用户
            try:
                logger.info(f"创建用户: email={email}, username={username}")
                user = User.objects.create_user(
                    email=email,
                    password=serializer.validated_data['password']
                )
                user.username = username
                user.is_active = True  # 设置用户为激活状态
                user.save()
            except Exception as e:
                logger.error(f"创建用户失败: {str(e)}")
                raise

            # 更新验证码状态
            try:
                logger.info("更新验证码状态")
                verification.is_used = True
                verification.save()
            except Exception as e:
                logger.error(f"更新验证码状态失败: {str(e)}")
                raise

            # 更新邀请码状态
            try:
                logger.info("更新邀请码状态")
                invitation.is_used = True
                invitation.used_by = user
                invitation.used_at = timezone.now()
                invitation.save()
            except Exception as e:
                logger.error(f"更新邀请码状态失败: {str(e)}")
                raise

            # 关联邀请码到用户
            try:
                logger.info("关联邀请码到用户")
                user.invitation_code = invitation
                user.save()
            except Exception as e:
                logger.error(f"关联邀请码到用户失败: {str(e)}")
                raise

            logger.info(f"注册成功: user_id={user.id}")
            return Response({
                'status': 'success',
                'message': '注册成功',
                'data': UserSerializer(user).data
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"注册失败，发生异常: {str(e)}")
            logger.error(f"异常类型: {type(e)}")
            logger.error(f"异常详情: {traceback.format_exc()}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class LoginView(APIView):
    """登录视图"""
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            # 打印请求数据，用于调试
            logger.info(f"登录请求数据: {request.data}")

            serializer = LoginSerializer(data=request.data)
            if not serializer.is_valid():
                logger.error(f"登录序列化器验证失败: {serializer.errors}")
                return Response({
                    'status': 'error',
                    'message': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)

            email = serializer.validated_data['email']
            password = serializer.validated_data['password']

            # 验证用户
            user = User.objects.filter(email=email).first()
            if not user or not user.check_password(password):
                return Response({
                    'status': 'error',
                    'message': '邮箱或密码错误'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 生成token
            token, _ = AuthToken.objects.get_or_create(user=user)

            return Response({
                'status': 'success',
                'data': {
                    'token': token.key,
                    'user': UserSerializer(user).data
                }
            })

        except Exception as e:
            logger.error(f"登录失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '登录失败'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class UserProfileView(APIView):
    """用户资料视图"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            return Response({
                'status': 'success',
                'data': UserSerializer(request.user).data
            })

        except Exception as e:
            logger.error(f"获取用户资料失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '获取用户资料失败'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def put(self, request):
        try:
            serializer = UserSerializer(request.user, data=request.data, partial=True)
            if not serializer.is_valid():
                return Response({
                    'status': 'error',
                    'message': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)

            serializer.save()

            return Response({
                'status': 'success',
                'message': '更新成功',
                'data': serializer.data
            })

        except Exception as e:
            logger.error(f"更新用户资料失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '更新用户资料失败'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class GenerateInvitationCodeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # 生成随机邀请码
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

        # 创建邀请码
        invitation = InvitationCode.objects.create(
            code=code,
            created_by=request.user
        )

        return Response({
            'code': code,
            'created_at': invitation.created_at
        }, status=status.HTTP_201_CREATED)

class TokenRefreshView(APIView):
    """Token刷新视图"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            serializer = TokenRefreshSerializer(data=request.data, context={'request': request})
            if serializer.is_valid():
                data = serializer.save()
                return Response({
                    'status': 'success',
                    'data': data
                })
            return Response({
                'status': 'error',
                'message': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"刷新token失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '刷新token失败'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class ChangePasswordView(APIView):
    """修改密码视图"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                'status': 'error',
                'message': '验证失败',
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        # 获取当前用户
        user = request.user
        current_password = serializer.validated_data['current_password']
        new_password = serializer.validated_data['new_password']

        # 验证当前密码
        if not user.check_password(current_password):
            return Response({
                'status': 'error',
                'message': '当前密码不正确'
            }, status=status.HTTP_400_BAD_REQUEST)

        # 设置新密码
        user.set_password(new_password)
        user.save()

        # 删除并重新生成认证令牌
        AuthToken.objects.filter(user=user).delete()
        token = AuthToken.objects.create(user=user)

        return Response({
            'status': 'success',
            'message': '密码修改成功',
            'data': {
                'token': token.key
            }
        })

class RequestPasswordResetView(APIView):
    """请求重置密码视图"""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResetPasswordCodeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                'status': 'error',
                'message': '验证失败',
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        email = serializer.validated_data['email']

        try:
            # 获取用户
            user = User.objects.get(email=email)

            # 生成6位数字验证码
            code = ''.join(random.choices(string.digits, k=6))

            # 删除该邮箱之前的所有未使用验证码
            VerificationCode.objects.filter(
                email=email,
                is_used=False
            ).delete()

            # 保存验证码
            expires_at = timezone.now() + timedelta(minutes=10)
            VerificationCode.objects.create(
                email=email,
                code=code,
                expires_at=expires_at
            )

            # 发送邮件
            subject = '重置您的密码 - K线军师'
            message = f"""
尊敬的用户：

您的验证码是：{code}

验证码有效期为10分钟，请尽快使用验证码重置您的密码。

如果这不是您的操作，请忽略此邮件。

K线军师团队
"""

            # 发送邮件
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [email],
                fail_silently=False,
            )

            return Response({
                'status': 'success',
                'message': '重置密码验证码已发送到您的邮箱'
            })

        except User.DoesNotExist:
            return Response({
                'status': 'error',
                'message': '该邮箱未注册'
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"发送重置密码验证码失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '发送重置密码验证码失败，请稍后重试'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class ResetPasswordWithCodeView(APIView):
    """使用验证码重置密码视图"""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResetPasswordWithCodeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                'status': 'error',
                'message': '验证失败',
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        email = serializer.validated_data['email']
        code = serializer.validated_data['code']
        new_password = serializer.validated_data['new_password']

        try:
            # 获取用户
            user = User.objects.get(email=email)

            # 验证验证码
            verification = VerificationCode.objects.filter(
                email=email,
                code=code,
                is_used=False,
                expires_at__gt=timezone.now()
            ).first()

            if not verification:
                return Response({
                    'status': 'error',
                    'message': '验证码无效或已过期'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 设置新密码
            user.set_password(new_password)
            user.save()

            # 标记验证码为已使用
            verification.is_used = True
            verification.save()

            # 生成新的认证令牌
            AuthToken.objects.filter(user=user).delete()
            token = AuthToken.objects.create(user=user)

            return Response({
                'status': 'success',
                'message': '密码重置成功',
                'data': {
                    'token': token.key,
                    'user': UserSerializer(user).data
                }
            })

        except User.DoesNotExist:
            return Response({
                'status': 'error',
                'message': '该邮箱未注册'
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"重置密码失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '重置密码失败，请稍后重试'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
