from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
from .models import User, VerificationCode, InvitationCode
from django.utils import timezone
import random
import string
from datetime import timedelta
import traceback
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.contrib.auth import authenticate
from rest_framework.authtoken.models import Token as AuthToken
from .serializers import (
    UserSerializer, RegisterSerializer, LoginSerializer,
    SendVerificationCodeSerializer, TokenRefreshSerializer,
    ChangePasswordSerializer, ResetPasswordWithCodeSerializer, ResetPasswordCodeSerializer
)
from django.core.mail import send_mail
import logging

# 创建日志记录器
logger = logging.getLogger('user')

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
            subject = 'Cooltrade Verification Code'
            html_message = settings.EMAIL_TEMPLATE.format(code=code)
            from_email = settings.DEFAULT_FROM_EMAIL
            recipient_list = [email]

            try:
                send_mail(subject, '', from_email, recipient_list, html_message=html_message)
                return Response({
                    'status': 'success',
                    'message': '验证码已发送'
                })
            except Exception as e:
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
            serializer = RegisterSerializer(data=request.data)
            if not serializer.is_valid():
                return Response({
                    'status': 'error',
                    'message': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)

            # 验证验证码
            email = serializer.validated_data['email']
            code = serializer.validated_data['code']

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

            # 验证邀请码
            invitation_code = request.data.get('invitation_code')
            if not invitation_code:
                return Response({
                    'status': 'error',
                    'message': '邀请码不能为空'
                }, status=status.HTTP_400_BAD_REQUEST)

            try:
                invitation = InvitationCode.objects.get(code=invitation_code, is_used=False)
            except InvitationCode.DoesNotExist:
                return Response({
                    'status': 'error',
                    'message': '无效的邀请码'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 生成随机用户名
            username = f"user_{''.join(random.choices(string.ascii_lowercase + string.digits, k=8))}"

            # 创建用户
            try:
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
                verification.is_used = True
                verification.save()
            except Exception as e:
                logger.error(f"更新验证码状态失败: {str(e)}")
                raise

            # 更新邀请码状态
            try:
                invitation.is_used = True
                invitation.used_by = user
                invitation.used_at = timezone.now()
                invitation.save()
            except Exception as e:
                logger.error(f"更新邀请码状态失败: {str(e)}")
                raise

            # 关联邀请码到用户
            try:
                user.invitation_code = invitation
                user.save()
            except Exception as e:
                logger.error(f"关联邀请码到用户失败: {str(e)}")
                raise

            return Response({
                'status': 'success',
                'message': '注册成功',
                'data': UserSerializer(user).data
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"注册失败，发生异常: {str(e)}")
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
            print(f"[DEBUG] Login request data: {request.data}")

            serializer = LoginSerializer(data=request.data)
            if not serializer.is_valid():
                print(f"[DEBUG] Login serializer errors: {serializer.errors}")
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
            subject = 'Cooltrade Verification Code'
            html_message = settings.EMAIL_TEMPLATE.format(code=code)
            send_mail(
                subject,
                '',
                settings.DEFAULT_FROM_EMAIL,
                [email],
                html_message=html_message,
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
