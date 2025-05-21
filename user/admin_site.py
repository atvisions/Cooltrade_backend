from django.contrib.admin import AdminSite
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType

class UserAdminSite(AdminSite):
    """自定义管理站点类，用于控制模型顺序"""
    site_title = _('Cooltrade管理')
    site_header = _('Cooltrade管理')
    index_title = _('管理面板')

    def has_permission(self, request):
        """确保用户有权限访问管理站点"""
        # 保持与默认AdminSite相同的权限检查
        return super().has_permission(request)

    def get_app_list(self, request):
        """
        重写获取应用列表的方法，自定义模型顺序
        """
        app_list = super().get_app_list(request)

        # 查找用户应用
        for app in app_list:
            if app['app_label'] == 'user':
                # 自定义模型顺序
                models = app['models']
                model_order = {
                    'User': 0,
                    'PointsLeaderboard': 1,  # 虚拟模型，用于积分排行榜
                    'InvitationCode': 2,
                    'InvitationRecord': 3,
                    'VerificationCode': 4,
                    'SystemSetting': 5,
                }

                # 按自定义顺序排序模型
                app['models'] = sorted(models, key=lambda x: model_order.get(x['object_name'], 999))

                # 在User模型后添加积分排行榜
                if len(models) > 0:
                    # 查找User模型的索引
                    user_index = -1
                    for i, model in enumerate(app['models']):
                        if model['object_name'] == 'User':
                            user_index = i
                            break

                    # 如果找到User模型，在其后添加积分排行榜
                    if user_index >= 0:
                        # 创建积分排行榜模型
                        points_leaderboard = {
                            'name': '用户积分排行榜',
                            'object_name': 'PointsLeaderboard',
                            'perms': {
                                'add': False,
                                'change': False,
                                'delete': False,
                                'view': True,
                            },
                            'admin_url': request.build_absolute_uri('/admin/user/user/points-leaderboard/'),
                            'add_url': None,
                            'view_only': True,
                        }

                        # 在User模型后插入积分排行榜
                        app['models'].insert(user_index + 1, points_leaderboard)

                break

        return app_list
