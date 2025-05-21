"""
临时测试脚本，用于测试定时任务是否成功执行

使用方法：
python scripts/tasks/test_tasks.py

该脚本会每5分钟执行一次技术指标更新和报告生成任务，并输出执行结果
"""
import time
import sys
from datetime import datetime
from pathlib import Path

# 添加当前目录到Python路径
current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(current_dir))

from utils import setup_django, setup_logging

# 设置Django环境
setup_django()

# 配置日志
logger = setup_logging('task_test.log')

# 导入任务函数
from CryptoAnalyst.tasks import update_technical_analysis, generate_analysis_reports

def run_test():
    """运行测试"""
    try:
        # 记录开始时间
        start_time = time.time()
        logger.info("开始执行测试任务")

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
        logger.info(f"测试任务执行完成，总耗时: {execution_time:.2f}秒")

        return True
    except Exception as e:
        logger.error(f"测试任务执行失败: {str(e)}")
        return False

def main():
    """主函数"""
    logger.info("启动测试脚本，每5分钟执行一次任务")

    try:
        while True:
            # 获取当前时间
            now = datetime.now()
            logger.info(f"当前时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")

            # 执行测试
            success = run_test()

            if success:
                logger.info("本轮测试成功完成")
            else:
                logger.error("本轮测试失败")

            # 等待到下一个5分钟
            logger.info("等待到下一个5分钟...")
            next_run = now.replace(minute=(now.minute // 5 + 1) * 5, second=0, microsecond=0)
            if next_run.minute >= 60:  # 处理小时进位
                next_run = next_run.replace(hour=next_run.hour + 1, minute=0)

            sleep_seconds = (next_run - now).total_seconds()
            if sleep_seconds <= 0:  # 如果计算出负值，等待到下一个小时
                next_run = now.replace(hour=now.hour + 1, minute=0, second=0, microsecond=0)
                sleep_seconds = (next_run - now).total_seconds()

            logger.info(f"下一次执行时间: {next_run.strftime('%Y-%m-%d %H:%M:%S')}, 等待 {sleep_seconds:.2f} 秒")
            time.sleep(sleep_seconds)

    except KeyboardInterrupt:
        logger.info("测试脚本被用户中断")
    except Exception as e:
        logger.error(f"测试脚本执行出错: {str(e)}")
    finally:
        logger.info("测试脚本结束")

if __name__ == "__main__":
    main()
