from django.contrib import admin
from .models import User, VerificationCode, InvitationCode

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('email', 'username', 'is_active', 'language', 'created_at')
    search_fields = ('email', 'username')
    list_filter = ('is_active', 'language')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('基本信息', {'fields': ('email', 'username', 'password')}),
        ('权限', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('偏好设置', {'fields': ('language',)}),
        ('邀请码', {'fields': ('invitation_code',)}),
        ('时间信息', {'fields': ('created_at', 'updated_at')}),
    )

@admin.register(VerificationCode)
class VerificationCodeAdmin(admin.ModelAdmin):
    list_display = ('email', 'code', 'is_used', 'created_at', 'expires_at')
    search_fields = ('email',)
    list_filter = ('is_used',)
    readonly_fields = ('created_at',)

@admin.register(InvitationCode)
class InvitationCodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'created_by', 'used_by', 'is_used', 'created_at', 'used_at')
    search_fields = ('code',)
    list_filter = ('is_used',)
    readonly_fields = ('created_at', 'used_at')
