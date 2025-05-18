from django.contrib import admin
from .models import (
    Chain, Token, TechnicalAnalysis, AnalysisReport
)

# 注册模型
admin.site.register(Chain)
admin.site.register(Token)
admin.site.register(TechnicalAnalysis)
admin.site.register(AnalysisReport)