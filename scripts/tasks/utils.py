"""
任务脚本工具模块

提供任务脚本中常用的工具函数和配置
"""
import os
import sys
import logging
import django
from pathlib import Path

def setup_django():
    """设置Django环境"""
    # 获取项目根目录
    base_dir = Path(__file__).resolve().parent.parent.parent

    # 将项目根目录添加到Python路径
    sys.path.insert(0, str(base_dir))

    # 设置Django环境
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()

def setup_logging(log_name=None):
    """设置日志配置

    Args:
        log_name: 日志文件名，如果为None则只输出到控制台

    Returns:
        logging.Logger: 日志记录器
    """
    # 获取项目根目录
    base_dir = Path(__file__).resolve().parent.parent.parent

    # 确保日志目录存在
    logs_dir = base_dir / 'logs'
    logs_dir.mkdir(exist_ok=True)

    # 配置日志处理器
    handlers = [logging.StreamHandler(sys.stdout)]

    # 如果指定了日志文件名，添加文件处理器
    if log_name:
        log_file = logs_dir / log_name
        handlers.append(logging.FileHandler(log_file))

    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=handlers
    )

    return logging.getLogger(__name__)

def get_project_root():
    """获取项目根目录

    Returns:
        Path: 项目根目录路径
    """
    return Path(__file__).resolve().parent.parent.parent
