from django.db import models
from django.utils import timezone
from django.contrib.auth.models import AbstractUser, BaseUserManager
import random
import string
from datetime import timedelta, datetime
import uuid

class UserManager(BaseUserManager):
    """自定义用户管理器"""
    def create_user(self, email, password=None, **extra_fields):
        """创建普通用户"""
        if not email:
            raise ValueError('邮箱是必填项')
        email = self.normalize_email(email)
        username = f"user_{''.join(random.choices(string.ascii_lowercase + string.digits, k=8))}"
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        """创建超级用户"""
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('超级用户必须设置 is_staff=True')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('超级用户必须设置 is_superuser=True')

        return self.create_user(email, password, **extra_fields)

class User(AbstractUser):
    """用户模型"""
    LANGUAGE_CHOICES = (
        ('zh-CN', '简体中文'),
        ('en-US', 'English'),
        ('ja-JP', '日本語'),
        ('ko-KR', '한국어'),
    )

    username = models.CharField(max_length=150, unique=True, verbose_name='用户名')
    email = models.EmailField(unique=True, verbose_name='邮箱')
    is_active = models.BooleanField(default=False, verbose_name='是否激活')
    language = models.CharField(max_length=10, choices=LANGUAGE_CHOICES, default='en-US', verbose_name='语言偏好')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    points = models.IntegerField(default=0, verbose_name='积分')
    invitation_code = models.ForeignKey('InvitationCode', on_delete=models.SET_NULL, null=True, blank=True, related_name='registered_users')
    inviter = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='invited_users', verbose_name='邀请人')

    # 会员相关字段
    is_premium = models.BooleanField(default=False, verbose_name='是否为高级会员')
    premium_expires_at = models.DateTimeField(null=True, blank=True, verbose_name='会员到期时间')

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = UserManager()

    # 修复反向关系冲突
    groups = models.ManyToManyField(
        'auth.Group',
        related_name='user_set',
        blank=True,
        help_text='The groups this user belongs to. A user will get all permissions granted to each of their groups.',
        verbose_name='groups',
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        related_name='user_set',
        blank=True,
        help_text='Specific permissions for this user.',
        verbose_name='user permissions',
    )

    class Meta:
        verbose_name = '用户'
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.email

    def get_personal_invitation_code(self):
        """获取用户的个人邀请码"""
        # 查找用户创建的长期有效的邀请码
        invitation = InvitationCode.objects.filter(
            created_by=self,
            is_personal=True
        ).first()

        # 如果没有，则创建一个
        if not invitation:
            code = f"U{self.id}{''.join(random.choices(string.ascii_uppercase + string.digits, k=6))}"
            invitation = InvitationCode.objects.create(
                code=code,
                created_by=self,
                is_personal=True,
                is_used=False  # 个人邀请码的is_used字段不再使用
            )

        return invitation

    def is_premium_active(self):
        """检查用户是否为有效的高级会员"""
        if not self.is_premium:
            return False
        if not self.premium_expires_at:
            return False
        return timezone.now() < self.premium_expires_at

    def get_membership_status(self):
        """获取用户会员状态"""
        if self.is_premium_active():
            return 'premium'
        return 'regular'

class VerificationCode(models.Model):
    """验证码模型"""
    email = models.EmailField(verbose_name='邮箱')
    code = models.CharField(max_length=6, verbose_name='验证码')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    expires_at = models.DateTimeField(verbose_name='过期时间')
    is_used = models.BooleanField(default=False, verbose_name='是否已使用')

    class Meta:
        verbose_name = '验证码'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.email} - {self.code}"

class InvitationCode(models.Model):
    """邀请码模型"""
    code = models.CharField(max_length=20, unique=True, verbose_name='邀请码')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_invitation_codes', verbose_name='创建者')
    used_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='used_invitation_code', verbose_name='使用者')
    is_used = models.BooleanField(default=False, verbose_name='是否已使用')
    is_personal = models.BooleanField(default=False, verbose_name='是否个人专属')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    used_at = models.DateTimeField(null=True, blank=True, verbose_name='使用时间')

    class Meta:
        verbose_name = '邀请码'
        verbose_name_plural = verbose_name

    def __str__(self):
        if self.is_personal:
            return f"{self.code} - 个人邀请码"
        else:
            status = '已使用' if self.is_used else '可用'
            return f"{self.code} - {status} - 一次性邀请码"

class InvitationRecord(models.Model):
    """邀请记录模型"""
    inviter = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_invitations', verbose_name='邀请人')
    invitee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_invitation', verbose_name='被邀请人')
    invitation_code = models.ForeignKey(InvitationCode, on_delete=models.CASCADE, related_name='invitation_records', verbose_name='邀请码')
    points_awarded = models.IntegerField(default=0, verbose_name='奖励积分')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        verbose_name = '邀请记录'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.inviter} 邀请 {self.invitee} - {self.created_at.strftime('%Y-%m-%d')}"

class SystemSetting(models.Model):
    """系统设置模型"""
    key = models.CharField(max_length=50, unique=True, verbose_name='设置键')
    value = models.CharField(max_length=255, verbose_name='设置值')
    description = models.TextField(blank=True, null=True, verbose_name='描述')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = '系统设置'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.key}: {self.value}"

    @classmethod
    def get_invitation_points(cls):
        """获取邀请积分设置"""
        try:
            setting = cls.objects.get(key='invitation_points')
            return int(setting.value)
        except (cls.DoesNotExist, ValueError):
            # 默认值为10
            return 10

# 新增临时邀请模型
class TemporaryInvitation(models.Model):
    """暂存从网站捕获的邀请码，等待用户在插件中认领"""
    invitation_code = models.CharField(max_length=8, help_text="捕获的邀请码")
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, help_text="用于认领的唯一标识符")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'临时邀请码: {{self.invitation_code}} (UUID: {{self.uuid}})'

# 会员相关模型
class MembershipPlan(models.Model):
    """会员套餐模型"""
    PLAN_TYPE_CHOICES = (
        ('monthly', '月付'),
        ('yearly', '年付'),
    )

    name = models.CharField(max_length=50, verbose_name='套餐名称')
    plan_type = models.CharField(max_length=10, choices=PLAN_TYPE_CHOICES, verbose_name='套餐类型')
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='价格')
    duration_days = models.IntegerField(verbose_name='有效天数')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        verbose_name = '会员套餐'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.name} - {self.price}元"

class MembershipOrder(models.Model):
    """会员订单模型"""
    STATUS_CHOICES = (
        ('pending', '待支付'),
        ('paid', '已支付'),
        ('expired', '已过期'),
        ('cancelled', '已取消'),
    )

    PAYMENT_METHOD_CHOICES = (
        ('alipay', '支付宝'),
        ('bank_transfer', '银行转账'),
        ('wechat_friend', '微信好友'),
        ('other', '其他'),
    )

    order_id = models.CharField(max_length=32, unique=True, verbose_name='订单号')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='membership_orders', verbose_name='用户')
    plan = models.ForeignKey(MembershipPlan, on_delete=models.CASCADE, verbose_name='套餐')
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='金额')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending', verbose_name='状态')
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, null=True, blank=True, verbose_name='支付方式')
    payment_info = models.JSONField(default=dict, blank=True, verbose_name='支付信息')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name='支付时间')
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name='过期时间')

    class Meta:
        verbose_name = '会员订单'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.order_id} - {self.user.email} - {self.plan.name}"

    def save(self, *args, **kwargs):
        if not self.order_id:
            # 生成订单号
            import time
            self.order_id = f"MB{int(time.time())}{random.randint(1000, 9999)}"
        super().save(*args, **kwargs)

class PointsTransaction(models.Model):
    """积分交易记录模型"""
    TRANSACTION_TYPE_CHOICES = (
        ('earn', '获得'),
        ('spend', '消费'),
    )

    REASON_CHOICES = (
        ('registration', '注册奖励'),
        ('invitation', '邀请好友'),
        ('premium_analysis', '查看高级分析'),
        ('save_image', '保存图片'),
        ('admin_adjust', '管理员调整'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='points_transactions', verbose_name='用户')
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPE_CHOICES, verbose_name='交易类型')
    amount = models.IntegerField(verbose_name='积分数量')
    reason = models.CharField(max_length=20, choices=REASON_CHOICES, verbose_name='原因')
    description = models.TextField(blank=True, verbose_name='描述')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        verbose_name = '积分交易记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        sign = '+' if self.transaction_type == 'earn' else '-'
        return f"{self.user.email} {sign}{self.amount} 积分 - {self.get_reason_display()}"
