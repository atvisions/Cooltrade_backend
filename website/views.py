from django.shortcuts import render
from django.http import HttpRequest
import logging
from user.models import TemporaryInvitation
from django.http import HttpResponse
import uuid

logger = logging.getLogger(__name__)

# Create your views here.

def home(request: HttpRequest):
    invitation_code = request.GET.get('code')
    logger.info(f"Accessed home view. code parameter: {invitation_code}")

    if invitation_code:
        # 存储邀请码和 Session Key 到临时邀请模型
        try:
            # 使用邀请码查找或创建临时邀请记录
            # 如果同一个邀请码多次访问，我们更新其 UUID (可选，取决于业务需求)
            temp_invitation, created = TemporaryInvitation.objects.update_or_create(
                invitation_code=invitation_code,
                defaults={'uuid': uuid.uuid4()}
            )
            logger.info(f"Processed invitation code {invitation_code}. Temporary Invitation UUID: {temp_invitation.uuid}")

            # 将 UUID 设置到 cookie 中，以便插件读取
            response = render(request, 'website/home.html')
            response.set_cookie('temporary_invitation_uuid', str(temp_invitation.uuid), max_age=3600*24) # 例如，cookie 有效期 24 小时
            return response

        except Exception as e:
            logger.error(f"Failed to process invitation code {invitation_code} and save to TemporaryInvitation: {e}")
            # 渲染页面并记录错误，不设置 cookie
            return render(request, 'website/home.html')

    return render(request, 'website/home.html')

def privacy_policy(request):
    return render(request, 'website/privacy-policy.html')
