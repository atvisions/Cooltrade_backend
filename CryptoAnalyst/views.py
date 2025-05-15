from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
from .services.token_data_service import TokenDataService
from .services.gate_api import GateAPI
from .models import Token as CryptoToken, Chain, AnalysisReport, TechnicalAnalysis, User, VerificationCode, InvitationCode
from .utils import logger, sanitize_indicators, format_timestamp, parse_timestamp, safe_json_loads
import numpy as np
from typing import Dict, Optional, List
import pandas as pd
from datetime import datetime, timedelta
import pytz
from django.utils import timezone
import requests
import json
import time
import base64
import traceback
import os
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.contrib.auth import get_user_model, authenticate
from django.core.mail import send_mail
import random
import string
from rest_framework.authtoken.models import Token as AuthToken
import concurrent.futures
from .serializers import (
    UserSerializer, RegisterSerializer, LoginSerializer,
    SendVerificationCodeSerializer, TokenRefreshSerializer,
    ChangePasswordSerializer, ResetPasswordWithCodeSerializer, ResetPasswordCodeSerializer
)
from django.shortcuts import render


class TokenDataAPIView(APIView):
    """代币数据API视图"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.token_service = TokenDataService()  # 不传入API密钥，使用免费API

    def get(self, request, token_id: str):
        """获取指定代币的数据

        Args:
            request: HTTP请求对象
            token_id: 代币ID，例如 'bitcoin'

        Returns:
            Response: 包含代币数据的响应
        """
        try:
            # 获取代币数据
            token_data = self.token_service.get_token_data(token_id)

            return Response({
                'status': 'success',
                'data': token_data
            })

        except Exception as e:
            logger.error(f"获取代币数据失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _sanitize_float(self, value, min_val=-np.inf, max_val=np.inf):
        """将输入转换为有效的浮点数，并限制在指定范围内

        Args:
            value: 要处理的输入值
            min_val: 最小有效值，默认为负无穷
            max_val: 最大有效值，默认为正无穷

        Returns:
            float: 处理后的浮点数
        """
        try:
            result = float(value)
            if np.isnan(result) or np.isinf(result):
                return 0.0
            return max(min(result, max_val), min_val)
        except (ValueError, TypeError):
            return 0.0



class SendVerificationCodeView(APIView):
    """发送验证码视图"""
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            serializer = SendVerificationCodeSerializer(data=request.data)
            if not serializer.is_valid():
                return Response({
                    'status': 'error',
                    'message': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)

            email = serializer.validated_data['email']

            # 生成6位数字验证码
            code = ''.join(random.choices(string.digits, k=6))

            # 保存验证码
            expires_at = timezone.now() + timedelta(minutes=10)
            VerificationCode.objects.create(
                email=email,
                code=code,
                expires_at=expires_at
            )

            # 发送邮件
            subject = 'K线军师 - 验证码'
            message = settings.EMAIL_TEMPLATE.format(code=code)
            from_email = settings.DEFAULT_FROM_EMAIL
            recipient_list = [email]

            try:
                logger.info(f"尝试发送邮件到 {email}")
                logger.info(f"使用邮箱: {settings.EMAIL_HOST_USER}")
                logger.info(f"使用服务器: {settings.EMAIL_HOST}:{settings.EMAIL_PORT}")

                send_mail(subject, message, from_email, recipient_list)
                logger.info(f"成功发送验证码到 {email}")

                return Response({
                    'status': 'success',
                    'message': '验证码已发送'
                })
            except Exception as e:
                logger.error(f"发送邮件失败: {str(e)}")
                logger.error(f"错误类型: {type(e)}")
                logger.error(f"错误详情: {str(e)}")

                error_message = '发送验证码失败，请稍后重试'
                if 'Authentication Required' in str(e):
                    error_message = '邮件服务器认证失败，请检查配置'
                elif 'Connection refused' in str(e):
                    error_message = '无法连接到邮件服务器，请检查网络'

                return Response({
                    'status': 'error',
                    'message': error_message
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        except Exception as e:
            logger.error(f"发送验证码失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '发送验证码失败'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class RegisterView(APIView):
    """注册视图"""
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            logger.info(f"开始注册流程，请求数据: {request.data}")

            serializer = RegisterSerializer(data=request.data)
            if not serializer.is_valid():
                logger.error(f"序列化器验证失败: {serializer.errors}")
                return Response({
                    'status': 'error',
                    'message': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)

            # 验证验证码
            email = serializer.validated_data['email']
            code = serializer.validated_data['code']

            logger.info(f"验证验证码: email={email}, code={code}")
            verification = VerificationCode.objects.filter(
                email=email,
                code=code,
                is_used=False,
                expires_at__gt=timezone.now()
            ).first()

            if not verification:
                logger.error(f"验证码验证失败: email={email}, code={code}")
                return Response({
                    'status': 'error',
                    'message': '验证码无效或已过期'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 验证邀请码
            invitation_code = request.data.get('invitation_code')
            if not invitation_code:
                logger.error("邀请码为空")
                return Response({
                    'status': 'error',
                    'message': '邀请码不能为空'
                }, status=status.HTTP_400_BAD_REQUEST)

            try:
                logger.info(f"验证邀请码: {invitation_code}")
                invitation = InvitationCode.objects.get(code=invitation_code, is_used=False)
            except InvitationCode.DoesNotExist:
                logger.error(f"邀请码无效: {invitation_code}")
                return Response({
                    'status': 'error',
                    'message': '无效的邀请码'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 生成随机用户名
            username = f"user_{''.join(random.choices(string.ascii_lowercase + string.digits, k=8))}"
            logger.info(f"生成随机用户名: {username}")

            # 创建用户
            try:
                logger.info(f"创建用户: email={email}, username={username}")
                user = User.objects.create_user(
                    email=email,
                    password=serializer.validated_data['password']
                )
                user.username = username
                user.is_active = True  # 设置用户为激活状态
                user.save()
            except Exception as e:
                logger.error(f"创建用户失败: {str(e)}")
                raise

            # 更新验证码状态
            try:
                logger.info("更新验证码状态")
                verification.is_used = True
                verification.save()
            except Exception as e:
                logger.error(f"更新验证码状态失败: {str(e)}")
                raise

            # 更新邀请码状态
            try:
                logger.info("更新邀请码状态")
                invitation.is_used = True
                invitation.used_by = user
                invitation.used_at = timezone.now()
                invitation.save()
            except Exception as e:
                logger.error(f"更新邀请码状态失败: {str(e)}")
                raise

            # 关联邀请码到用户
            try:
                logger.info("关联邀请码到用户")
                user.invitation_code = invitation
                user.save()
            except Exception as e:
                logger.error(f"关联邀请码到用户失败: {str(e)}")
                raise

            logger.info(f"注册成功: user_id={user.id}")
            return Response({
                'status': 'success',
                'message': '注册成功',
                'data': UserSerializer(user).data
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"注册失败，发生异常: {str(e)}")
            logger.error(f"异常类型: {type(e)}")
            logger.error(f"异常详情: {traceback.format_exc()}")
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class LoginView(APIView):
    """登录视图"""
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            # 打印请求数据，用于调试
            logger.info(f"登录请求数据: {request.data}")

            serializer = LoginSerializer(data=request.data)
            if not serializer.is_valid():
                logger.error(f"登录序列化器验证失败: {serializer.errors}")
                return Response({
                    'status': 'error',
                    'message': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)

            email = serializer.validated_data['email']
            password = serializer.validated_data['password']

            # 验证用户
            user = User.objects.filter(email=email).first()
            if not user or not user.check_password(password):
                return Response({
                    'status': 'error',
                    'message': '邮箱或密码错误'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 生成token
            token, _ = AuthToken.objects.get_or_create(user=user)

            return Response({
                'status': 'success',
                'data': {
                    'token': token.key,
                    'user': UserSerializer(user).data
                }
            })

        except Exception as e:
            logger.error(f"登录失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '登录失败'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class UserProfileView(APIView):
    """用户资料视图"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            return Response({
                'status': 'success',
                'data': UserSerializer(request.user).data
            })

        except Exception as e:
            logger.error(f"获取用户资料失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '获取用户资料失败'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def put(self, request):
        try:
            serializer = UserSerializer(request.user, data=request.data, partial=True)
            if not serializer.is_valid():
                return Response({
                    'status': 'error',
                    'message': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)

            serializer.save()

            return Response({
                'status': 'success',
                'message': '更新成功',
                'data': serializer.data
            })

        except Exception as e:
            logger.error(f"更新用户资料失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '更新用户资料失败'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class GenerateInvitationCodeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # 生成随机邀请码
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

        # 创建邀请码
        invitation = InvitationCode.objects.create(
            code=code,
            created_by=request.user
        )

        return Response({
            'code': code,
            'created_at': invitation.created_at
        }, status=status.HTTP_201_CREATED)

class TokenRefreshView(APIView):
    """Token刷新视图"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            serializer = TokenRefreshSerializer(data=request.data, context={'request': request})
            if serializer.is_valid():
                data = serializer.save()
                return Response({
                    'status': 'success',
                    'data': data
                })
            return Response({
                'status': 'error',
                'message': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"刷新token失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '刷新token失败'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class ChangePasswordView(APIView):
    """修改密码视图"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                'status': 'error',
                'message': '验证失败',
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        # 获取当前用户
        user = request.user
        current_password = serializer.validated_data['current_password']
        new_password = serializer.validated_data['new_password']

        # 验证当前密码
        if not user.check_password(current_password):
            return Response({
                'status': 'error',
                'message': '当前密码不正确'
            }, status=status.HTTP_400_BAD_REQUEST)

        # 设置新密码
        user.set_password(new_password)
        user.save()

        # 删除并重新生成认证令牌
        AuthToken.objects.filter(user=user).delete()
        token = AuthToken.objects.create(user=user)

        return Response({
            'status': 'success',
            'message': '密码修改成功',
            'data': {
                'token': token.key
            }
        })

class RequestPasswordResetView(APIView):
    """请求重置密码视图"""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResetPasswordCodeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                'status': 'error',
                'message': '验证失败',
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        email = serializer.validated_data['email']

        try:
            # 获取用户
            user = User.objects.get(email=email)

            # 生成6位数字验证码
            code = ''.join(random.choices(string.digits, k=6))

            # 删除该邮箱之前的所有未使用验证码
            VerificationCode.objects.filter(
                email=email,
                is_used=False
            ).delete()

            # 保存验证码
            expires_at = timezone.now() + timedelta(minutes=10)
            VerificationCode.objects.create(
                email=email,
                code=code,
                expires_at=expires_at
            )

            # 发送邮件
            subject = '重置您的密码 - K线军师'
            message = f"""
尊敬的用户：

您的验证码是：{code}

验证码有效期为10分钟，请尽快使用验证码重置您的密码。

如果这不是您的操作，请忽略此邮件。

K线军师团队
"""

            # 发送邮件
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [email],
                fail_silently=False,
            )

            return Response({
                'status': 'success',
                'message': '重置密码验证码已发送到您的邮箱'
            })

        except User.DoesNotExist:
            return Response({
                'status': 'error',
                'message': '该邮箱未注册'
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"发送重置密码验证码失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '发送重置密码验证码失败，请稍后重试'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class ResetPasswordWithCodeView(APIView):
    """使用验证码重置密码视图"""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResetPasswordWithCodeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                'status': 'error',
                'message': '验证失败',
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        email = serializer.validated_data['email']
        code = serializer.validated_data['code']
        new_password = serializer.validated_data['new_password']

        try:
            # 获取用户
            user = User.objects.get(email=email)

            # 验证验证码
            verification = VerificationCode.objects.filter(
                email=email,
                code=code,
                is_used=False,
                expires_at__gt=timezone.now()
            ).first()

            if not verification:
                return Response({
                    'status': 'error',
                    'message': '验证码无效或已过期'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 设置新密码
            user.set_password(new_password)
            user.save()

            # 标记验证码为已使用
            verification.is_used = True
            verification.save()

            # 生成新的认证令牌
            AuthToken.objects.filter(user=user).delete()
            token = AuthToken.objects.create(user=user)

            return Response({
                'status': 'success',
                'message': '密码重置成功',
                'data': {
                    'token': token.key,
                    'user': UserSerializer(user).data
                }
            })

        except User.DoesNotExist:
            return Response({
                'status': 'error',
                'message': '该邮箱未注册'
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"重置密码失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '重置密码失败，请稍后重试'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
