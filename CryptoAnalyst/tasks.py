from celery import shared_task
from .models import Token, TechnicalAnalysis, AnalysisReport
from .services.market_data_service import MarketDataService
from .services.technical_analysis import TechnicalAnalysisService
from .services.analysis_report_service import AnalysisReportService
from .views import TechnicalIndicatorsAPIView
from .utils import logger
from celery.exceptions import MaxRetriesExceededError
from django.db import transaction
import asyncio

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True
)
def update_market_data(self):
    """更新所有代币的市场数据 - 已废弃，使用 update_coze_analysis 代替

    MarketData 模型已移除，价格数据现在保存在 AnalysisReport 中
    """
    logger.info("MarketData 模型已移除，此任务已废弃")
    return

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True
)
def update_technical_analysis(self):
    """更新所有代币的技术分析数据"""
    try:
        tokens = Token.objects.all()
        analysis_service = TechnicalAnalysisService()

        for token in tokens:
            try:
                with transaction.atomic():
                    # 使用原始符号，不添加USDT后缀
                    analysis_data = analysis_service.get_technical_analysis(token.symbol)
                    TechnicalAnalysis.objects.update_or_create(
                        token=token,
                        defaults={
                            'rsi': analysis_data['rsi'],
                            'macd_line': analysis_data['macd_line'],
                            'macd_signal': analysis_data['macd_signal'],
                            'macd_histogram': analysis_data['macd_histogram'],
                            'bollinger_upper': analysis_data['bollinger_upper'],
                            'bollinger_middle': analysis_data['bollinger_middle'],
                            'bollinger_lower': analysis_data['bollinger_lower'],
                            'bias': analysis_data['bias'],
                            'psy': analysis_data['psy'],
                            'dmi_plus': analysis_data['dmi_plus'],
                            'dmi_minus': analysis_data['dmi_minus'],
                            'dmi_adx': analysis_data['dmi_adx'],
                            'vwap': analysis_data['vwap'],
                            'funding_rate': analysis_data['funding_rate'],
                            'exchange_netflow': analysis_data['exchange_netflow'],
                            'nupl': analysis_data['nupl'],
                            'mayer_multiple': analysis_data['mayer_multiple'],
                        }
                    )
                    logger.info(f"更新代币 {token.symbol} 的技术分析数据成功")
            except Exception as e:
                logger.error(f"更新代币 {token.symbol} 的技术分析数据失败: {str(e)}")
                # 单个代币失败不影响其他代币的更新
                continue

    except Exception as e:
        logger.error(f"更新技术分析数据任务失败: {str(e)}")
        raise self.retry(exc=e)

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True
)
def update_coze_analysis(self):
    """更新所有代币的 Coze 分析报告"""
    try:
        tokens = Token.objects.all()
        api_view = TechnicalIndicatorsAPIView()

        for token in tokens:
            try:
                with transaction.atomic():
                    # 使用原始符号，不添加USDT后缀
                    symbol = token.symbol

                    # 获取技术指标数据
                    technical_data = api_view.ta_service.get_all_indicators(symbol)
                    if technical_data['status'] == 'error':
                        logger.error(f"获取代币 {symbol} 的技术指标数据失败")
                        continue

                    indicators = technical_data['data']['indicators']

                    # 获取市场数据
                    market_data = api_view.market_service.get_market_data(symbol)
                    if not market_data:
                        logger.error(f"获取代币 {symbol} 的市场数据失败")
                        continue

                    # 异步获取 Coze 分析结果
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    coze_analysis = loop.run_until_complete(
                        api_view._get_coze_analysis(symbol, indicators)
                    )
                    loop.close()

                    # 生成分析报告
                    analysis_report = {
                        'trend_analysis': coze_analysis['trend_analysis'],
                        'indicators_analysis': coze_analysis['indicators_analysis'],
                        'trading_advice': coze_analysis['trading_advice'],
                        'risk_assessment': coze_analysis['risk_assessment']
                    }

                    # 保存分析报告
                    api_view.report_service.save_analysis_report(symbol, analysis_report)
                    logger.info(f"更新代币 {symbol} 的 Coze 分析报告成功")

            except Exception as e:
                logger.error(f"更新代币 {symbol} 的 Coze 分析报告失败: {str(e)}")
                # 单个代币失败不影响其他代币的更新
                continue

    except Exception as e:
        logger.error(f"更新 Coze 分析报告任务失败: {str(e)}")
        raise self.retry(exc=e)