from rest_framework import serializers
from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from .models import User, VerificationCode, InvitationCode, InvitationRecord
from datetime import datetime, timedelta
from django.utils import timezone
import re

class UserSerializer(serializers.ModelSerializer):
    """用户序列化器"""
    invitation_code = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'email', 'username', 'language', 'points', 'invitation_code', 'created_at', 'updated_at']
        read_only_fields = ['id', 'points', 'invitation_code', 'created_at', 'updated_at']

    def get_invitation_code(self, obj):
        """获取用户的个人邀请码"""
        invitation = obj.get_personal_invitation_code()
        return invitation.code if invitation else None

class RegisterSerializer(serializers.Serializer):
    """注册序列化器"""
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=6)
    code = serializers.CharField(min_length=6, max_length=6)
    invitation_code = serializers.CharField(required=False, allow_blank=True)

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("该邮箱已被注册")
        return value

    def validate_code(self, value):
        email = self.initial_data.get('email')
        verification = VerificationCode.objects.filter(
            email=email,
            code=value,
            is_used=False,
            expires_at__gt=timezone.now()
        ).first()

        if not verification:
            raise serializers.ValidationError("验证码无效或已过期")
        return value

    def validate_invitation_code(self, value):
        if not value:
            return value

        # 验证邀请码是否存在且有效
        invitation = InvitationCode.objects.filter(code=value).first()
        if not invitation:
            raise serializers.ValidationError("邀请码不存在")

        return value

class LoginSerializer(serializers.Serializer):
    """登录序列化器"""
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

class SendVerificationCodeSerializer(serializers.Serializer):
    """发送验证码序列化器"""
    email = serializers.EmailField()

    def validate_email(self, value):
        # 检查是否已经发送过未使用的验证码
        existing_code = VerificationCode.objects.filter(
            email=value,
            is_used=False,
            expires_at__gt=timezone.now()
        ).first()

        if existing_code:
            # 如果存在未过期的验证码，删除它
            existing_code.delete()

        # 检查邮箱是否已注册
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("该邮箱已被注册")

        return value

class TokenRefreshSerializer(serializers.Serializer):
    """Token刷新序列化器"""
    token = serializers.CharField(read_only=True)

    def validate(self, attrs):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            raise serializers.ValidationError('认证失败')
        return attrs

    def create(self, validated_data):
        user = self.context['request'].user
        # 删除旧token
        Token.objects.filter(user=user).delete()
        # 创建新token
        token = Token.objects.create(user=user)
        return {'token': token.key}

class ChangePasswordSerializer(serializers.Serializer):
    """修改密码序列化器"""
    current_password = serializers.CharField(write_only=True, required=True)
    new_password = serializers.CharField(write_only=True, required=True, min_length=6)
    confirm_password = serializers.CharField(write_only=True, required=True)

    def validate(self, attrs):
        # 确认新密码与确认密码一致
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError({"confirm_password": "两次输入的新密码不一致"})

        # 验证新密码的强度
        password = attrs['new_password']
        if not self._check_password_strength(password):
            raise serializers.ValidationError({"new_password": "密码强度不足，请使用包含字母、数字的6位以上密码"})

        return attrs

    def _check_password_strength(self, password):
        """检查密码强度，要求至少6位，包含字母和数字"""
        if len(password) < 6:
            return False
        if not re.search(r'[A-Za-z]', password) or not re.search(r'[0-9]', password):
            return False
        return True

class ResetPasswordWithCodeSerializer(serializers.Serializer):
    """使用验证码重置密码序列化器"""
    email = serializers.EmailField(required=True)
    code = serializers.CharField(min_length=6, max_length=6, required=True)
    new_password = serializers.CharField(write_only=True, required=True, min_length=6)
    confirm_password = serializers.CharField(write_only=True, required=True)

    def validate(self, attrs):
        # 确认新密码与确认密码一致
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError({"confirm_password": "两次输入的新密码不一致"})

        # 验证新密码的强度
        password = attrs['new_password']
        if not self._check_password_strength(password):
            raise serializers.ValidationError({"new_password": "密码强度不足，请使用包含字母、数字的6位以上密码"})

        # 验证验证码
        email = attrs['email']
        code = attrs['code']
        verification = VerificationCode.objects.filter(
            email=email,
            code=code,
            is_used=False,
            expires_at__gt=timezone.now()
        ).first()

        if not verification:
            raise serializers.ValidationError({"code": "验证码无效或已过期"})

        return attrs

    def _check_password_strength(self, password):
        """检查密码强度，要求至少6位，包含字母和数字"""
        if len(password) < 6:
            return False
        if not re.search(r'[A-Za-z]', password) or not re.search(r'[0-9]', password):
            return False
        return True

class ResetPasswordCodeSerializer(serializers.Serializer):
    """重置密码验证码序列化器"""
    email = serializers.EmailField()

    def validate_email(self, value):
        # 检查是否已经发送过未使用的验证码
        existing_code = VerificationCode.objects.filter(
            email=value,
            is_used=False,
            expires_at__gt=timezone.now()
        ).first()

        if existing_code:
            # 如果存在未过期的验证码，删除它
            existing_code.delete()

        # 检查邮箱是否已注册 (必须已注册才能重置密码)
        if not User.objects.filter(email=value).exists():
            raise serializers.ValidationError("该邮箱未注册")

        return value

class InvitationCodeSerializer(serializers.ModelSerializer):
    """邀请码序列化器"""
    class Meta:
        model = InvitationCode
        fields = ['code', 'is_personal', 'is_used', 'created_at']
        read_only_fields = ['code', 'is_personal', 'is_used', 'created_at']

class InvitationRecordSerializer(serializers.ModelSerializer):
    """邀请记录序列化器"""
    invitee_email = serializers.EmailField(source='invitee.email', read_only=True)
    invitee_username = serializers.CharField(source='invitee.username', read_only=True)
    created_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S", read_only=True)

    class Meta:
        model = InvitationRecord
        fields = ['invitee_email', 'invitee_username', 'points_awarded', 'created_at']
        read_only_fields = ['invitee_email', 'invitee_username', 'points_awarded', 'created_at']
