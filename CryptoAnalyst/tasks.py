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
    """更新所有代币的技术分析数据

    此任务会在每天0点和12点执行，获取所有代币的技术指标数据并保存到数据库
    """
    try:
        tokens = Token.objects.all()
        analysis_service = TechnicalAnalysisService()

        # 记录成功更新的代币，用于后续触发分析报告任务
        updated_tokens = []

        for token in tokens:
            try:
                with transaction.atomic():
                    # 使用原始符号，不添加USDT后缀
                    analysis_data = analysis_service.get_technical_analysis(token.symbol)

                    # 计算12小时分段起点
                    from django.utils import timezone
                    now = timezone.now()
                    period_hour = (now.hour // 12) * 12
                    period_start = now.replace(minute=0, second=0, microsecond=0, hour=period_hour)

                    # 创建或更新技术分析数据
                    ta, created = TechnicalAnalysis.objects.update_or_create(
                        token=token,
                        period_start=period_start,
                        defaults={
                            'timestamp': now,
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

                    # 添加到成功更新列表
                    updated_tokens.append(token.symbol)

                    if created:
                        logger.info(f"创建代币 {token.symbol} 的技术分析数据成功")
                    else:
                        logger.info(f"更新代币 {token.symbol} 的技术分析数据成功")

            except Exception as e:
                logger.error(f"更新代币 {token.symbol} 的技术分析数据失败: {str(e)}")
                # 单个代币失败不影响其他代币的更新
                continue

        # 如果有成功更新的代币，5分钟后触发分析报告任务
        if updated_tokens:
            logger.info(f"成功更新了 {len(updated_tokens)} 个代币的技术分析数据，将在5分钟后获取分析报告")
            # 使用 Celery 的 countdown 参数设置延迟执行
            generate_analysis_reports.apply_async(args=[updated_tokens], countdown=300)  # 300秒 = 5分钟

        return updated_tokens

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
def generate_analysis_reports(self, symbols=None):
    """生成指定代币的分析报告

    此任务会在技术参数更新后5分钟执行，获取指定代币的分析报告

    Args:
        symbols: 代币符号列表，如果为None则处理所有代币
    """
    try:
        api_view = TechnicalIndicatorsAPIView()

        # 如果没有指定代币，则处理所有代币
        if not symbols:
            tokens = Token.objects.all()
            symbols = [token.symbol for token in tokens]
        else:
            # 确保symbols是列表
            if isinstance(symbols, str):
                symbols = [symbols]

        logger.info(f"开始生成 {len(symbols)} 个代币的分析报告")

        for symbol in symbols:
            try:
                with transaction.atomic():
                    # 获取代币记录
                    token = Token.objects.filter(symbol=symbol).first()
                    if not token:
                        logger.error(f"找不到代币 {symbol} 的记录")
                        continue

                    # 获取最新的技术分析数据
                    technical_analysis = TechnicalAnalysis.objects.filter(token=token).order_by('-timestamp').first()
                    if not technical_analysis:
                        logger.error(f"找不到代币 {symbol} 的技术分析数据")
                        continue

                    # 构建技术指标数据
                    indicators = {
                        'RSI': technical_analysis.rsi,
                        'MACD': {
                            'line': technical_analysis.macd_line,
                            'signal': technical_analysis.macd_signal,
                            'histogram': technical_analysis.macd_histogram
                        },
                        'BollingerBands': {
                            'upper': technical_analysis.bollinger_upper,
                            'middle': technical_analysis.bollinger_middle,
                            'lower': technical_analysis.bollinger_lower
                        },
                        'BIAS': technical_analysis.bias,
                        'PSY': technical_analysis.psy,
                        'DMI': {
                            'plus_di': technical_analysis.dmi_plus,
                            'minus_di': technical_analysis.dmi_minus,
                            'adx': technical_analysis.dmi_adx
                        },
                        'VWAP': technical_analysis.vwap,
                        'FundingRate': technical_analysis.funding_rate,
                        'ExchangeNetflow': technical_analysis.exchange_netflow,
                        'NUPL': technical_analysis.nupl,
                        'MayerMultiple': technical_analysis.mayer_multiple
                    }

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
                    logger.info(f"生成代币 {symbol} 的分析报告成功")

            except Exception as e:
                logger.error(f"生成代币 {symbol} 的分析报告失败: {str(e)}")
                # 单个代币失败不影响其他代币的更新
                continue

        return True

    except Exception as e:
        logger.error(f"生成分析报告任务失败: {str(e)}")
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
    """更新所有代币的 Coze 分析报告 (旧版本，保留兼容性)"""
    # 调用新的分析报告生成任务
    return generate_analysis_reports(self)