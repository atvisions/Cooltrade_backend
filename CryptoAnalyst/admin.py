from django.contrib import admin
from .models import (
    Chain, Token, TechnicalAnalysis,
    AnalysisReport, User, VerificationCode, InvitationCode
)
from django.utils.html import format_html
from django.contrib import messages
from django.shortcuts import render
from django.http import HttpResponseRedirect
from django.urls import path
import random
import string

@admin.register(InvitationCode)
class InvitationCodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'created_by', 'is_used', 'used_by', 'created_at', 'used_at')
    list_filter = ('is_used', 'created_at')
    search_fields = ('code', 'created_by__email', 'used_by__email')
    readonly_fields = ('created_at', 'used_at')
    change_list_template = 'admin/invitation_code_change_list.html'

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('generate-codes/', self.generate_codes, name='generate-codes'),
        ]
        return custom_urls + urls

    def generate_codes(self, request):
        if request.method == 'POST':
            try:
                count = int(request.POST.get('count', 10))
                if count <= 0 or count > 100:
                    self.message_user(
                        request,
                        '生成数量必须在1-100之间',
                        messages.ERROR
                    )
                    return HttpResponseRedirect('../')

                codes = []
                for _ in range(count):
                    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
                    invitation = InvitationCode.objects.create(
                        code=code,
                        created_by=request.user
                    )
                    codes.append(code)

                self.message_user(
                    request,
                    f'成功生成 {count} 个邀请码：{", ".join(codes)}',
                    messages.SUCCESS
                )
            except ValueError:
                self.message_user(
                    request,
                    '请输入有效的数字',
                    messages.ERROR
                )
            except Exception as e:
                self.message_user(
                    request,
                    f'生成邀请码失败：{str(e)}',
                    messages.ERROR
                )
            return HttpResponseRedirect('../')

        return render(
            request,
            'admin/generate_codes.html',
            context={'title': '生成邀请码'}
        )

# 注册其他模型
admin.site.register(Chain)
admin.site.register(Token)
admin.site.register(TechnicalAnalysis)
# MarketData 模型已移除
admin.site.register(AnalysisReport)
admin.site.register(User)
admin.site.register(VerificationCode)