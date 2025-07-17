from django.contrib import admin
from django.urls import path
from django.shortcuts import render
from django.contrib import messages
from django.http import HttpResponseRedirect, HttpResponse
from django.urls import reverse
from django.template.response import TemplateResponse
import random
import string
import csv
from datetime import datetime
from .models import User, VerificationCode, InvitationCode, InvitationRecord, SystemSetting, MembershipPlan, MembershipOrder, PointsTransaction

class UserAdmin(admin.ModelAdmin):
    """用户管理类"""
    list_display = ('email', 'username', 'is_active', 'language', 'points', 'membership_status_display', 'premium_expires_at', 'inviter', 'created_at')
    search_fields = ('email', 'username')
    list_filter = ('is_active', 'language', 'is_premium')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('基本信息', {'fields': ('email', 'username', 'password')}),
        ('权限', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('偏好设置', {'fields': ('language',)}),
        ('会员信息', {'fields': ('is_premium', 'premium_expires_at')}),
        ('邀请信息', {'fields': ('invitation_code', 'inviter', 'points')}),
        ('时间信息', {'fields': ('created_at', 'updated_at')}),
    )

    def membership_status_display(self, obj):
        """显示会员状态"""
        if obj.is_premium_active():
            return "🔥 高级会员"
        return "👤 普通用户"
    membership_status_display.short_description = "会员状态"

    actions = ['make_premium', 'remove_premium', 'extend_membership', 'adjust_points']

    def make_premium(self, request, queryset):
        """批量设置为高级会员"""
        from django.utils import timezone
        from datetime import timedelta

        # 默认设置为1个月会员
        expires_at = timezone.now() + timedelta(days=30)

        updated = queryset.update(
            is_premium=True,
            premium_expires_at=expires_at
        )

        self.message_user(request, f"成功将 {updated} 个用户设置为高级会员（有效期30天）", messages.SUCCESS)
    make_premium.short_description = "设置为高级会员（30天）"

    def remove_premium(self, request, queryset):
        """批量移除高级会员"""
        updated = queryset.update(
            is_premium=False,
            premium_expires_at=None
        )

        self.message_user(request, f"成功移除 {updated} 个用户的高级会员权限", messages.SUCCESS)
    remove_premium.short_description = "移除高级会员权限"

    def extend_membership(self, request, queryset):
        """批量延长会员时间"""
        from django.utils import timezone
        from datetime import timedelta

        for user in queryset:
            if user.is_premium:
                # 如果已经是会员，在现有基础上延长
                if user.premium_expires_at and user.premium_expires_at > timezone.now():
                    user.premium_expires_at += timedelta(days=30)
                else:
                    user.premium_expires_at = timezone.now() + timedelta(days=30)
            else:
                # 如果不是会员，设置为会员并设置到期时间
                user.is_premium = True
                user.premium_expires_at = timezone.now() + timedelta(days=30)
            user.save()

        count = queryset.count()
        self.message_user(request, f"成功为 {count} 个用户延长30天会员时间", messages.SUCCESS)
    extend_membership.short_description = "延长会员时间（30天）"

    def adjust_points(self, request, queryset):
        """批量调整积分"""
        # 这个方法需要自定义页面来输入积分数量
        selected = request.POST.getlist(admin.ACTION_CHECKBOX_NAME)
        return HttpResponseRedirect(f"/admin/user/user/adjust-points/?ids={','.join(selected)}")
    adjust_points.short_description = "调整用户积分"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('points-leaderboard/', self.admin_site.admin_view(self.points_leaderboard_view), name='points_leaderboard'),
            path('adjust-points/', self.admin_site.admin_view(self.adjust_points_view), name='adjust_user_points'),
            path('membership-management/', self.admin_site.admin_view(self.membership_management_view), name='membership_management'),
        ]
        return custom_urls + urls

    def points_leaderboard_view(self, request):
        """用户积分排行榜视图"""
        # 获取排序方式
        order_by = request.GET.get('order_by', '-points')

        # 获取筛选条件
        min_points = request.GET.get('min_points', '')
        max_points = request.GET.get('max_points', '')

        # 基础查询
        queryset = User.objects.all()

        # 应用筛选条件
        if min_points and min_points.isdigit():
            queryset = queryset.filter(points__gte=int(min_points))
        if max_points and max_points.isdigit():
            queryset = queryset.filter(points__lte=int(max_points))

        # 应用排序
        if order_by == 'points':
            queryset = queryset.order_by('points')
        else:
            queryset = queryset.order_by('-points')

        # 获取邀请记录统计
        user_stats = {}
        for user in queryset:
            invitation_count = InvitationRecord.objects.filter(inviter=user).count()
            user_stats[user.id] = {
                'invitation_count': invitation_count
            }

        # 导出CSV
        if request.GET.get('export') == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="user_points_leaderboard_{datetime.now().strftime("%Y%m%d%H%M%S")}.csv"'

            writer = csv.writer(response)
            writer.writerow(['排名', '用户名', '邮箱', '积分', '邀请人数', '注册时间'])

            for i, user in enumerate(queryset, 1):
                writer.writerow([
                    i,
                    user.username,
                    user.email,
                    user.points,
                    user_stats[user.id]['invitation_count'],
                    user.created_at.strftime('%Y-%m-%d %H:%M:%S')
                ])

            return response

        # 渲染模板
        context = {
            'title': '用户积分排行榜',
            'users': queryset,
            'user_stats': user_stats,
            'order_by': order_by,
            'min_points': min_points,
            'max_points': max_points,
            'opts': User._meta,
            'app_label': User._meta.app_label,
        }

        return TemplateResponse(request, 'admin/points_leaderboard.html', context)

    def adjust_points_view(self, request):
        """调整用户积分视图"""
        if request.method == 'POST':
            try:
                user_ids = request.POST.get('user_ids', '').split(',')
                points_change = int(request.POST.get('points_change', 0))
                reason = request.POST.get('reason', '管理员调整')

                if not user_ids or not points_change:
                    messages.error(request, '请选择用户并输入积分变化量')
                    return HttpResponseRedirect(request.get_full_path())

                users = User.objects.filter(id__in=user_ids)
                updated_count = 0

                for user in users:
                    old_points = user.points
                    user.points = max(0, user.points + points_change)  # 确保积分不为负数
                    user.save()

                    # 记录积分交易
                    PointsTransaction.objects.create(
                        user=user,
                        transaction_type='earn' if points_change > 0 else 'spend',
                        amount=abs(points_change),
                        reason='admin_adjust',
                        description=f'{reason}（从{old_points}调整到{user.points}）'
                    )
                    updated_count += 1

                messages.success(request, f'成功调整 {updated_count} 个用户的积分')
                return HttpResponseRedirect(reverse('admin:user_user_changelist'))

            except Exception as e:
                messages.error(request, f'调整积分失败: {str(e)}')

        # 获取用户ID
        user_ids = request.GET.get('ids', '').split(',')
        users = User.objects.filter(id__in=user_ids) if user_ids != [''] else []

        context = {
            'title': '调整用户积分',
            'users': users,
            'user_ids': ','.join(user_ids),
            'opts': User._meta,
            'app_label': User._meta.app_label,
        }

        return TemplateResponse(request, 'admin/adjust_points.html', context)

    def membership_management_view(self, request):
        """会员管理视图"""
        if request.method == 'POST':
            try:
                action = request.POST.get('action')
                user_ids = request.POST.getlist('user_ids')

                if not user_ids:
                    messages.error(request, '请选择要操作的用户')
                    return HttpResponseRedirect(request.get_full_path())

                users = User.objects.filter(id__in=user_ids)

                if action == 'set_premium':
                    from django.utils import timezone
                    from datetime import timedelta

                    days = int(request.POST.get('days', 30))
                    expires_at = timezone.now() + timedelta(days=days)

                    updated = users.update(
                        is_premium=True,
                        premium_expires_at=expires_at
                    )
                    messages.success(request, f'成功将 {updated} 个用户设置为高级会员（{days}天）')

                elif action == 'extend_premium':
                    from django.utils import timezone
                    from datetime import timedelta

                    days = int(request.POST.get('days', 30))

                    for user in users:
                        if user.is_premium and user.premium_expires_at and user.premium_expires_at > timezone.now():
                            user.premium_expires_at += timedelta(days=days)
                        else:
                            user.is_premium = True
                            user.premium_expires_at = timezone.now() + timedelta(days=days)
                        user.save()

                    messages.success(request, f'成功为 {len(users)} 个用户延长 {days} 天会员时间')

                elif action == 'remove_premium':
                    updated = users.update(
                        is_premium=False,
                        premium_expires_at=None
                    )
                    messages.success(request, f'成功移除 {updated} 个用户的高级会员权限')

                return HttpResponseRedirect(request.get_full_path())

            except Exception as e:
                messages.error(request, f'操作失败: {str(e)}')

        # 获取会员统计信息
        from django.utils import timezone

        total_users = User.objects.count()
        premium_users = User.objects.filter(is_premium=True).count()
        active_premium_users = User.objects.filter(
            is_premium=True,
            premium_expires_at__gt=timezone.now()
        ).count()
        expired_premium_users = User.objects.filter(
            is_premium=True,
            premium_expires_at__lte=timezone.now()
        ).count()

        # 获取最近的会员订单
        recent_orders = MembershipOrder.objects.select_related('user', 'plan').order_by('-created_at')[:10]

        # 获取用户列表（支持搜索和筛选）
        search_query = request.GET.get('search', '')
        filter_type = request.GET.get('filter', 'all')

        users_queryset = User.objects.all()

        if search_query:
            users_queryset = users_queryset.filter(
                email__icontains=search_query
            )

        if filter_type == 'premium':
            users_queryset = users_queryset.filter(is_premium=True)
        elif filter_type == 'regular':
            users_queryset = users_queryset.filter(is_premium=False)
        elif filter_type == 'expired':
            users_queryset = users_queryset.filter(
                is_premium=True,
                premium_expires_at__lte=timezone.now()
            )

        users_list = users_queryset.order_by('-created_at')[:50]  # 限制显示50个用户

        context = {
            'title': '会员管理',
            'total_users': total_users,
            'premium_users': premium_users,
            'active_premium_users': active_premium_users,
            'expired_premium_users': expired_premium_users,
            'recent_orders': recent_orders,
            'users_list': users_list,
            'search_query': search_query,
            'filter_type': filter_type,
            'opts': User._meta,
            'app_label': User._meta.app_label,
        }

        return TemplateResponse(request, 'admin/membership_management.html', context)

@admin.register(VerificationCode)
class VerificationCodeAdmin(admin.ModelAdmin):
    list_display = ('email', 'code', 'is_used', 'created_at', 'expires_at')
    search_fields = ('email',)
    list_filter = ('is_used',)
    readonly_fields = ('created_at',)

@admin.register(InvitationCode)
class InvitationCodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'created_by', 'used_by', 'is_used', 'is_personal', 'created_at', 'used_at')
    search_fields = ('code', 'created_by__email', 'used_by__email')
    list_filter = ('is_used', 'is_personal')
    readonly_fields = ('created_at', 'used_at')

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('generate-codes/', self.admin_site.admin_view(self.generate_codes_view), name='generate_invitation_codes'),
        ]
        return custom_urls + urls

    def generate_codes_view(self, request):
        if request.method == 'POST':
            try:
                count = int(request.POST.get('count', 10))
                count = min(max(count, 1), 100)  # 限制在1-100之间

                codes = []
                for _ in range(count):
                    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
                    invitation = InvitationCode.objects.create(
                        code=code,
                        created_by=request.user,
                        is_personal=False
                    )
                    codes.append(invitation)

                self.message_user(request, f"成功生成 {count} 个邀请码", messages.SUCCESS)
                return HttpResponseRedirect(reverse('admin:user_invitationcode_changelist'))
            except Exception as e:
                self.message_user(request, f"生成邀请码失败: {str(e)}", messages.ERROR)

        return render(request, 'admin/generate_codes.html')

@admin.register(InvitationRecord)
class InvitationRecordAdmin(admin.ModelAdmin):
    list_display = ('inviter', 'invitee', 'invitation_code', 'points_awarded', 'created_at')
    search_fields = ('inviter__email', 'invitee__email', 'invitation_code__code')
    list_filter = ('created_at',)
    readonly_fields = ('created_at',)

@admin.register(SystemSetting)
class SystemSettingAdmin(admin.ModelAdmin):
    list_display = ('key', 'value', 'description', 'updated_at')
    search_fields = ('key', 'value', 'description')
    readonly_fields = ('updated_at',)

# 会员套餐管理
@admin.register(MembershipPlan)
class MembershipPlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'plan_type', 'price', 'duration_days', 'is_active', 'created_at')
    list_filter = ('plan_type', 'is_active')
    search_fields = ('name',)
    readonly_fields = ('created_at',)

# 会员订单管理
@admin.register(MembershipOrder)
class MembershipOrderAdmin(admin.ModelAdmin):
    list_display = ('order_id', 'user', 'plan', 'amount', 'status', 'payment_method', 'created_at', 'paid_at')
    list_filter = ('status', 'payment_method', 'created_at')
    search_fields = ('order_id', 'user__email', 'plan__name')
    readonly_fields = ('order_id', 'created_at')

    actions = ['mark_as_paid', 'mark_as_cancelled']

    def mark_as_paid(self, request, queryset):
        """标记订单为已支付"""
        from django.utils import timezone
        from datetime import timedelta

        updated_count = 0
        for order in queryset.filter(status='pending'):
            order.status = 'paid'
            order.paid_at = timezone.now()
            order.save()

            # 激活用户会员
            user = order.user
            if user.is_premium and user.premium_expires_at and user.premium_expires_at > timezone.now():
                # 如果已经是会员，延长时间
                user.premium_expires_at += timedelta(days=order.plan.duration_days)
            else:
                # 设置为会员
                user.is_premium = True
                user.premium_expires_at = timezone.now() + timedelta(days=order.plan.duration_days)
            user.save()
            updated_count += 1

        self.message_user(request, f'成功处理 {updated_count} 个订单，用户会员已激活', messages.SUCCESS)
    mark_as_paid.short_description = "标记为已支付并激活会员"

    def mark_as_cancelled(self, request, queryset):
        """标记订单为已取消"""
        updated = queryset.update(status='cancelled')
        self.message_user(request, f'成功取消 {updated} 个订单', messages.SUCCESS)
    mark_as_cancelled.short_description = "标记为已取消"

# 积分交易记录管理
@admin.register(PointsTransaction)
class PointsTransactionAdmin(admin.ModelAdmin):
    list_display = ('user', 'transaction_type', 'amount', 'reason', 'created_at')
    list_filter = ('transaction_type', 'reason', 'created_at')
    search_fields = ('user__email', 'description')
    readonly_fields = ('created_at',)

# 注册用户管理类
admin.site.register(User, UserAdmin)
