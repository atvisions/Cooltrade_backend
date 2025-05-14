from django.db import models
from django.utils import timezone
from django.contrib.auth.models import AbstractUser, BaseUserManager
import random
import string
from datetime import timedelta

class Chain(models.Model):
    """链模型"""
    chain = models.CharField(max_length=50, unique=True)
    is_active = models.BooleanField(default=True)
    is_testnet = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "区块链"
        verbose_name_plural = "区块链"

    def __str__(self):
        return self.chain

class Token(models.Model):
    """代币基本信息模型"""
    chain = models.ForeignKey(Chain, on_delete=models.CASCADE, related_name='tokens')
    symbol = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    address = models.CharField(max_length=100, blank=True)
    decimals = models.IntegerField(default=18)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.chain.chain} - {self.symbol} - {self.name}"

class TechnicalAnalysis(models.Model):
    """技术分析数据模型 - 存储原始指标数据"""
    token = models.ForeignKey(Token, on_delete=models.CASCADE, related_name='technical_analysis')
    timestamp = models.DateTimeField(default=timezone.now)

    # RSI
    rsi = models.FloatField(null=True)

    # MACD
    macd_line = models.FloatField(null=True)
    macd_signal = models.FloatField(null=True)
    macd_histogram = models.FloatField(null=True)

    # 布林带
    bollinger_upper = models.FloatField(null=True)
    bollinger_middle = models.FloatField(null=True)
    bollinger_lower = models.FloatField(null=True)

    # BIAS
    bias = models.FloatField(null=True)

    # PSY
    psy = models.FloatField(null=True)

    # DMI
    dmi_plus = models.FloatField(null=True)
    dmi_minus = models.FloatField(null=True)
    dmi_adx = models.FloatField(null=True)

    # VWAP
    vwap = models.FloatField(null=True)

    # 资金费率
    funding_rate = models.FloatField(null=True)

    # 链上数据
    exchange_netflow = models.FloatField(null=True)
    nupl = models.FloatField(null=True)
    mayer_multiple = models.FloatField(null=True)

    class Meta:
        ordering = ['-timestamp']
        get_latest_by = 'timestamp'

class MarketData(models.Model):
    """市场数据模型"""
    token = models.ForeignKey(Token, on_delete=models.CASCADE, related_name='market_data')
    timestamp = models.DateTimeField(default=timezone.now)
    price = models.FloatField()
    volume = models.FloatField(null=True)
    price_change_24h = models.FloatField(null=True)
    price_change_percent_24h = models.FloatField(null=True)
    high_24h = models.FloatField(null=True)
    low_24h = models.FloatField(null=True)

    class Meta:
        ordering = ['-timestamp']
        get_latest_by = 'timestamp'

class AnalysisReport(models.Model):
    """分析报告模型 - 存储所有分析结果"""
    LANGUAGE_CHOICES = (
        ('zh-CN', '简体中文'),
        ('en-US', 'English'),
        ('ja-JP', '日本語'),
        ('ko-KR', '한국어'),
    )

    token = models.ForeignKey(Token, on_delete=models.CASCADE, related_name='analysis_reports')
    timestamp = models.DateTimeField(default=timezone.now)
    technical_analysis = models.ForeignKey(TechnicalAnalysis, on_delete=models.CASCADE, related_name='analysis_reports')
    snapshot_price = models.FloatField(default=0)  # 添加报告生成时的价格字段
    language = models.CharField(max_length=10, choices=LANGUAGE_CHOICES, default='en-US', verbose_name='报告语言')

    # 趋势分析
    trend_up_probability = models.IntegerField(default=0)  # 上涨概率
    trend_sideways_probability = models.IntegerField(default=0)  # 横盘概率
    trend_down_probability = models.IntegerField(default=0)  # 下跌概率
    trend_summary = models.TextField(blank=True)  # 趋势总结

    # 指标分析
    # RSI
    rsi_analysis = models.TextField(blank=True)
    rsi_support_trend = models.CharField(max_length=20, blank=True)

    # MACD
    macd_analysis = models.TextField(blank=True)
    macd_support_trend = models.CharField(max_length=20, blank=True)

    # 布林带
    bollinger_analysis = models.TextField(blank=True)
    bollinger_support_trend = models.CharField(max_length=20, blank=True)

    # BIAS
    bias_analysis = models.TextField(blank=True)
    bias_support_trend = models.CharField(max_length=20, blank=True)

    # PSY
    psy_analysis = models.TextField(blank=True)
    psy_support_trend = models.CharField(max_length=20, blank=True)

    # DMI
    dmi_analysis = models.TextField(blank=True)
    dmi_support_trend = models.CharField(max_length=20, blank=True)

    # VWAP
    vwap_analysis = models.TextField(blank=True)
    vwap_support_trend = models.CharField(max_length=20, blank=True)

    # 资金费率
    funding_rate_analysis = models.TextField(blank=True)
    funding_rate_support_trend = models.CharField(max_length=20, blank=True)

    # 交易所净流入
    exchange_netflow_analysis = models.TextField(blank=True)
    exchange_netflow_support_trend = models.CharField(max_length=20, blank=True)

    # NUPL
    nupl_analysis = models.TextField(blank=True)
    nupl_support_trend = models.CharField(max_length=20, blank=True)

    # Mayer Multiple
    mayer_multiple_analysis = models.TextField(blank=True)
    mayer_multiple_support_trend = models.CharField(max_length=20, blank=True)

    # 交易建议
    trading_action = models.CharField(max_length=20, default='等待')  # 买入/卖出/持有
    trading_reason = models.TextField(blank=True)  # 建议原因
    entry_price = models.FloatField(default=0)  # 入场价格
    stop_loss = models.FloatField(default=0)  # 止损价格
    take_profit = models.FloatField(default=0)  # 止盈价格

    # 风险评估
    risk_level = models.CharField(max_length=10, default='中')  # 高/中/低
    risk_score = models.IntegerField(default=50)  # 0-100
    risk_details = models.JSONField(default=list)  # 风险详情列表

    class Meta:
        ordering = ['-timestamp']
        get_latest_by = 'timestamp'

    def __str__(self):
        return f"{self.token.symbol} - {self.timestamp}"

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

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = UserManager()

    # 修复反向关系冲突
    groups = models.ManyToManyField(
        'auth.Group',
        related_name='crypto_user_set',
        blank=True,
        help_text='The groups this user belongs to. A user will get all permissions granted to each of their groups.',
        verbose_name='groups',
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        related_name='crypto_user_set',
        blank=True,
        help_text='Specific permissions for this user.',
        verbose_name='user permissions',
    )

    invitation_code = models.ForeignKey('InvitationCode', on_delete=models.SET_NULL, null=True, blank=True, related_name='registered_users')

    class Meta:
        verbose_name = '用户'
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.email

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
    code = models.CharField(max_length=20, unique=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_invitation_codes')
    used_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='used_invitation_code')
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.code} - {'Used' if self.is_used else 'Available'}"