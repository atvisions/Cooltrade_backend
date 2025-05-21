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
from .models import User, VerificationCode, InvitationCode, InvitationRecord, SystemSetting

class UserAdmin(admin.ModelAdmin):
    """用户管理类"""
    list_display = ('email', 'username', 'is_active', 'language', 'points', 'inviter', 'created_at')
    search_fields = ('email', 'username')
    list_filter = ('is_active', 'language')
    readonly_fields = ('created_at', 'updated_at', 'points')
    fieldsets = (
        ('基本信息', {'fields': ('email', 'username', 'password')}),
        ('权限', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('偏好设置', {'fields': ('language',)}),
        ('邀请信息', {'fields': ('invitation_code', 'inviter', 'points')}),
        ('时间信息', {'fields': ('created_at', 'updated_at')}),
    )

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('points-leaderboard/', self.admin_site.admin_view(self.points_leaderboard_view), name='points_leaderboard'),
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

# 注册用户管理类
admin.site.register(User, UserAdmin)
