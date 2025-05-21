"""
定时任务模块

包含所有与定时任务相关的功能，如：
- 更新技术指标参数
- 生成分析报告
"""
import logging
from celery import shared_task
from django.utils import timezone
from django.db import transaction

from .models import Token, TechnicalAnalysis, AnalysisReport
from .services.technical_analysis import TechnicalAnalysisService
from .views_report import CryptoReportAPIView

# 配置日志
logger = logging.getLogger(__name__)


@shared_task
def update_technical_analysis():
    """
    更新所有代币的技术指标参数

    从数据库中获取所有活跃的代币，并更新它们的技术指标参数
    """
    logger.info("开始执行技术指标参数更新任务")

    try:
        # 获取所有代币
        tokens = Token.objects.all()

        if not tokens:
            logger.warning("数据库中没有找到代币记录")
            return "数据库中没有找到代币记录"

        # 初始化服务
        ta_service = TechnicalAnalysisService()

        # 计算当前12小时周期的起始时间
        now = timezone.now()
        # 如果当前时间小于12点，则周期起始时间为当天0点
        # 否则周期起始时间为当天12点
        if now.hour < 12:
            period_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            period_start = now.replace(hour=12, minute=0, second=0, microsecond=0)

        # 更新每个代币的技术指标
        success_count = 0
        error_count = 0

        for token in tokens:
            try:
                symbol = token.symbol

                # 检查是否已经有当前周期的技术分析数据
                existing_analysis = TechnicalAnalysis.objects.filter(
                    token=token,
                    period_start=period_start
                ).first()

                if existing_analysis:
                    logger.info(f"代币 {symbol} 在当前周期已有技术分析数据，跳过更新")
                    continue

                # 获取技术指标数据
                # 为了与Gate API兼容，确保符号格式正确
                # 清理符号格式，去除可能的USDT后缀
                clean_symbol = symbol.upper().replace('USDT', '').replace('-PERP', '').replace('_PERP', '').replace('PERP', '')
                # 添加USDT后缀
                api_symbol = f"{clean_symbol}USDT"
                technical_data = ta_service.get_all_indicators(api_symbol)

                if technical_data['status'] == 'error':
                    logger.error(f"获取代币 {symbol} 的技术指标数据失败: {technical_data['message']}")
                    error_count += 1
                    continue

                # 获取指标数据
                indicators = technical_data['data']['indicators']

                # 获取实时价格
                current_price = 0
                try:
                    current_price = ta_service.gate_api.get_realtime_price(api_symbol)
                except Exception as e:
                    logger.error(f"获取代币 {symbol} 的实时价格失败: {str(e)}")

                # 格式化指标数据
                formatted_indicators = {
                    'rsi': indicators['RSI'],
                    'macd_line': indicators['MACD']['line'],
                    'macd_signal': indicators['MACD']['signal'],
                    'macd_histogram': indicators['MACD']['histogram'],
                    'bollinger_upper': indicators['BollingerBands']['upper'],
                    'bollinger_middle': indicators['BollingerBands']['middle'],
                    'bollinger_lower': indicators['BollingerBands']['lower'],
                    'bias': indicators['BIAS'],
                    'psy': indicators['PSY'],
                    'dmi_plus': indicators['DMI']['plus_di'],
                    'dmi_minus': indicators['DMI']['minus_di'],
                    'dmi_adx': indicators['DMI']['adx'],
                    'vwap': indicators.get('VWAP', 0),
                    'funding_rate': indicators.get('FundingRate', 0),
                    'exchange_netflow': indicators.get('ExchangeNetflow', 0),
                    'nupl': indicators.get('NUPL', 0),
                    'mayer_multiple': indicators.get('MayerMultiple', 0)
                }

                # 保存技术分析数据
                with transaction.atomic():
                    technical_analysis = TechnicalAnalysis.objects.create(
                        token=token,
                        timestamp=timezone.now(),
                        period_start=period_start,
                        **formatted_indicators
                    )

                logger.info(f"成功更新代币 {symbol} 的技术指标数据，ID: {technical_analysis.id}")
                success_count += 1

            except Exception as e:
                logger.error(f"更新代币 {token.symbol} 的技术指标数据时发生错误: {str(e)}")
                error_count += 1

        result_message = f"技术指标参数更新任务完成。成功: {success_count}, 失败: {error_count}, 总计: {len(tokens)}"
        logger.info(result_message)
        return result_message

    except Exception as e:
        error_message = f"执行技术指标参数更新任务时发生错误: {str(e)}"
        logger.error(error_message)
        return error_message


@shared_task
def generate_analysis_reports():
    """
    为所有代币生成英文分析报告

    从数据库中获取所有代币，并为每个代币生成英文分析报告
    """
    logger.info("开始执行分析报告生成任务")

    try:
        # 获取所有代币
        tokens = Token.objects.all()

        if not tokens:
            logger.warning("数据库中没有找到代币记录")
            return "数据库中没有找到代币记录"

        # 初始化报告API视图
        report_view = CryptoReportAPIView()

        # 生成每个代币的英文分析报告
        success_count = 0
        error_count = 0

        for token in tokens:
            try:
                symbol = token.symbol

                # 检查是否有最新的技术分析数据
                latest_analysis = TechnicalAnalysis.objects.filter(
                    token=token
                ).order_by('-timestamp').first()

                if not latest_analysis:
                    logger.warning(f"代币 {symbol} 没有技术分析数据，跳过生成报告")
                    continue

                # 检查是否已经有基于此技术分析数据的英文报告
                existing_report = AnalysisReport.objects.filter(
                    token=token,
                    technical_analysis=latest_analysis,
                    language='en-US'
                ).first()

                if existing_report:
                    logger.info(f"代币 {symbol} 已有基于最新技术分析数据的英文报告，跳过生成")
                    continue

                # 为了与Gate API兼容，确保符号格式正确
                # 清理符号格式，去除可能的USDT后缀
                clean_symbol = symbol.upper().replace('USDT', '').replace('-PERP', '').replace('_PERP', '').replace('PERP', '')
                # 添加USDT后缀
                api_symbol = f"{clean_symbol}USDT"

                # 获取技术指标数据
                technical_data = report_view._get_technical_data(api_symbol)

                if not technical_data:
                    logger.error(f"获取代币 {symbol} 的技术指标数据失败")
                    error_count += 1
                    continue

                # 生成英文分析报告
                report = report_view._generate_and_save_report(token, technical_data, 'en-US')

                if not report:
                    logger.error(f"生成代币 {symbol} 的英文分析报告失败")
                    error_count += 1
                    continue

                logger.info(f"成功生成代币 {symbol} 的英文分析报告，ID: {report.id}")
                success_count += 1

            except Exception as e:
                logger.error(f"生成代币 {token.symbol} 的英文分析报告时发生错误: {str(e)}")
                error_count += 1

        result_message = f"分析报告生成任务完成。成功: {success_count}, 失败: {error_count}, 总计: {len(tokens)}"
        logger.info(result_message)
        return result_message

    except Exception as e:
        error_message = f"执行分析报告生成任务时发生错误: {str(e)}"
        logger.error(error_message)
        return error_message