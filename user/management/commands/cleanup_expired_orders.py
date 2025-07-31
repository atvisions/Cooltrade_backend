from django.core.management.base import BaseCommand
from django.utils import timezone
from user.models import MembershipOrder
from user.tasks import cleanup_expired_orders


class Command(BaseCommand):
    help = '清理过期的会员订单'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='只显示将要清理的订单，不实际执行清理',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        if dry_run:
            self.stdout.write('执行模拟清理...')
            expired_orders = MembershipOrder.objects.filter(
                status='pending',
                expires_at__lt=timezone.now()
            )
            
            count = expired_orders.count()
            if count > 0:
                self.stdout.write(f'将清理 {count} 个过期订单:')
                for order in expired_orders[:10]:  # 只显示前10个
                    self.stdout.write(f'  - {order.order_id} (用户: {order.user.email}, 金额: ${order.amount})')
                if count > 10:
                    self.stdout.write(f'  ... 还有 {count - 10} 个订单')
            else:
                self.stdout.write('没有找到过期的订单')
        else:
            self.stdout.write('开始清理过期订单...')
            try:
                cleanup_expired_orders()
                self.stdout.write(self.style.SUCCESS('过期订单清理完成'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'清理失败: {e}')) 