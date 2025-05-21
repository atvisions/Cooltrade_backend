"""
强制执行任务测试脚本

使用方法：
python scripts/tasks/force_update_tasks.py

该脚本会强制执行一次技术指标更新和报告生成任务，忽略已有数据，并输出执行结果
"""
import time
import sys
from datetime import timedelta
from pathlib import Path

# 添加当前目录到Python路径
current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(current_dir))

from utils import setup_django, setup_logging

# 设置Django环境后再导入Django相关模块
setup_django()
from django.utils import timezone

# 配置日志
logger = setup_logging('task_force_update.log')

# 导入模型和任务函数
from CryptoAnalyst.models import Token, TechnicalAnalysis, AnalysisReport
from CryptoAnalyst.tasks import update_technical_analysis, generate_analysis_reports
from django.db import transaction

def force_update():
    """强制更新技术指标和报告"""
    try:
        # 删除当前周期的技术分析数据
        now = timezone.now()
        period_hour = (now.hour // 12) * 12
        period_start = now.replace(hour=period_hour, minute=0, second=0, microsecond=0)

        with transaction.atomic():
            # 删除当前周期的技术分析数据
            deleted_ta = TechnicalAnalysis.objects.filter(period_start=period_start).delete()
            logger.info(f"已删除当前周期的技术分析数据: {deleted_ta}")

            # 删除最近24小时内的分析报告
            time_threshold = now - timedelta(hours=24)
            deleted_reports = AnalysisReport.objects.filter(timestamp__gte=time_threshold).delete()
            logger.info(f"已删除最近24小时内的分析报告: {deleted_reports}")

        # 记录开始时间
        start_time = time.time()
        logger.info("开始执行强制更新任务")

        # 执行技术指标更新任务
        logger.info("开始执行技术指标更新任务")
        result_update = update_technical_analysis()
        logger.info(f"技术指标更新任务执行结果: {result_update}")

        # 等待5秒，确保技术指标更新完成
        logger.info("等待5秒...")
        time.sleep(5)

        # 执行报告生成任务
        logger.info("开始执行报告生成任务")
        result_report = generate_analysis_reports()
        logger.info(f"报告生成任务执行结果: {result_report}")

        # 记录结束时间
        end_time = time.time()
        execution_time = end_time - start_time
        logger.info(f"强制更新任务执行完成，总耗时: {execution_time:.2f}秒")

        return True
    except Exception as e:
        logger.error(f"强制更新任务执行失败: {str(e)}")
        return False

if __name__ == "__main__":
    force_update()
