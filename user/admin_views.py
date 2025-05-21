from django.contrib import admin
from django.template.response import TemplateResponse
from django.http import HttpResponse
from django.urls import reverse
from django.db.models import Count, Sum
import csv
from datetime import datetime
from .models import User, InvitationRecord

class PointsLeaderboardView(admin.views.main.ChangeList):
    """用户积分排行榜视图"""
    
    def __init__(self, request, **kwargs):
        self.model = User
        self.opts = User._meta
        self.app_label = User._meta.app_label
        self.title = "用户积分排行榜"
        self.request = request
        
    def get_results(self, request):
        """获取排序后的用户列表"""
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
            
        return queryset
        
    def get_user_stats(self, users):
        """获取用户统计信息"""
        user_stats = {}
        for user in users:
            invitation_count = InvitationRecord.objects.filter(inviter=user).count()
            user_stats[user.id] = {
                'invitation_count': invitation_count
            }
        return user_stats
        
    def export_csv(self, request, queryset):
        """导出CSV"""
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="user_points_leaderboard_{datetime.now().strftime("%Y%m%d%H%M%S")}.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['排名', '用户名', '邮箱', '积分', '邀请人数', '注册时间'])
        
        user_stats = self.get_user_stats(queryset)
        
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
        
    def render(self):
        """渲染视图"""
        # 获取用户列表
        users = self.get_results(self.request)
        
        # 导出CSV
        if self.request.GET.get('export') == 'csv':
            return self.export_csv(self.request, users)
        
        # 获取用户统计信息
        user_stats = self.get_user_stats(users)
        
        # 渲染模板
        context = {
            'title': '用户积分排行榜',
            'users': users,
            'user_stats': user_stats,
            'order_by': self.request.GET.get('order_by', '-points'),
            'min_points': self.request.GET.get('min_points', ''),
            'max_points': self.request.GET.get('max_points', ''),
            'opts': self.opts,
            'app_label': self.app_label,
        }
        
        return TemplateResponse(self.request, 'admin/points_leaderboard.html', context)
