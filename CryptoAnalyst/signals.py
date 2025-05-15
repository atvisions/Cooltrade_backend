from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Token, TechnicalAnalysis, AnalysisReport
from .utils import logger

@receiver(post_save, sender=TechnicalAnalysis)
def log_technical_analysis_update(sender, instance, created, **kwargs):
    """记录技术分析数据更新"""
    try:
        # 技术分析数据已更新
        pass
    except Exception as e:
        logger.error(f"更新代币技术分析数据失败: {str(e)}")

