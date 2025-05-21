"""
一次性执行任务测试脚本

使用方法：
python scripts/tasks/run_tasks_once.py

该脚本会立即执行一次技术指标更新和报告生成任务，并输出执行结果
"""
import time
import sys
import os
from pathlib import Path

# 添加当前目录到Python路径
current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(current_dir))

from utils import setup_django, setup_logging

# 设置Django环境
setup_django()

# 配置日志
logger = setup_logging('task_run_once.log')

# 导入任务函数
from CryptoAnalyst.tasks import update_technical_analysis, generate_analysis_reports

def main():
    """主函数"""
    try:
        # 记录开始时间
        start_time = time.time()
        logger.info("开始执行任务")

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
        logger.info(f"任务执行完成，总耗时: {execution_time:.2f}秒")

    except Exception as e:
        logger.error(f"任务执行失败: {str(e)}")
    finally:
        logger.info("脚本执行结束")

if __name__ == "__main__":
    main()
