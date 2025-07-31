import logging
from django.utils import timezone
from django.db import transaction
from user.models import MembershipOrder

logger = logging.getLogger(__name__)

def cleanup_expired_orders():
    """清理过期的订单"""
    try:
        with transaction.atomic():
            # 查找所有过期的待支付订单
            expired_orders = MembershipOrder.objects.filter(
                status='pending',
                expires_at__lt=timezone.now()
            )
            
            expired_count = expired_orders.count()
            if expired_count > 0:
                # 批量更新订单状态为已过期
                expired_orders.update(status='expired')
                logger.info(f'Cleaned up {expired_count} expired orders')
            else:
                logger.info('No expired orders to clean up')
                
    except Exception as e:
        logger.error(f'Error cleaning up expired orders: {e}')
        raise 