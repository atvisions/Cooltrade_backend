from django.db import models
from django.utils import timezone
from django.conf import settings
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

    # 每12小时唯一分段起点
    period_start = models.DateTimeField(null=True, default=timezone.now)

    class Meta:
        ordering = ['-timestamp']
        get_latest_by = 'timestamp'
        unique_together = ('token', 'period_start')

# MarketData 模型已移除，使用 AnalysisReport 中的 snapshot_price 作为价格数据

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

# 用户相关模型已移至 user 应用