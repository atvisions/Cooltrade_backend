from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
from .models import User, VerificationCode, InvitationCode, InvitationRecord, SystemSetting, TemporaryInvitation, MembershipPlan, MembershipOrder, PointsTransaction
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
    ChangePasswordSerializer, ResetPasswordWithCodeSerializer, ResetPasswordCodeSerializer,
    InvitationCodeSerializer, InvitationRecordSerializer,
    MembershipPlanSerializer, MembershipOrderSerializer, CreateMembershipOrderSerializer,
    PointsTransactionSerializer, UserMembershipStatusSerializer
)
from django.core.mail import send_mail
from django.db import transaction
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
            invitation_code_str = serializer.validated_data.get('invitation_code', '')

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

            # 使用事务确保所有操作要么全部成功，要么全部失败
            with transaction.atomic():
                # 生成随机用户名
                username = f"user_{''.join(random.choices(string.ascii_lowercase + string.digits, k=8))}"

                # 创建用户
                user = User.objects.create_user(
                    email=email,
                    password=serializer.validated_data['password']
                )
                user.username = username
                user.is_active = True  # 设置用户为激活状态

                # 处理邀请码
                invitation = None
                inviter = None

                if invitation_code_str: # 检查是否有邀请码（无论是临时的还是注册时提供的）
                    try:
                        invitation = InvitationCode.objects.get(code=invitation_code_str)
                        inviter = invitation.created_by

                        # 如果是一次性邀请码且已使用，则报错 (这个逻辑可能需要调整，取决于您的具体业务需求)
                        # 在认领临时邀请时已经处理了一次性邀请码的逻辑，这里可能不再需要严格检查
                        # 但为了安全，保留检查逻辑，如果出现问题再根据实际情况调整
                        if not invitation.is_personal and invitation.is_used and invitation.used_by != user:
                             # 如果是一次性邀请码且被其他用户使用了，则无效
                            pass # 不阻止注册，但忽略邀请码
                        else:
                             # 设置邀请人
                            user.inviter = inviter

                            # 如果是一次性邀请码，标记为已使用 (如果之前没标记)
                            if not invitation.is_personal and not invitation.is_used:
                                invitation.is_used = True
                                invitation.used_by = user
                                invitation.used_at = timezone.now()
                                invitation.save()

                            # 关联邀请码到用户
                            user.invitation_code = invitation

                            # 给邀请人增加积分 (确保邀请人存在且不是自己，并且没有重复奖励)
                            if inviter and inviter != user and not InvitationRecord.objects.filter(inviter=inviter, invitee=user).exists():
                                invitation_points = SystemSetting.get_invitation_points()
                                inviter.points += invitation_points
                                inviter.save()

                                # 创建邀请记录
                                InvitationRecord.objects.create(
                                    inviter=inviter,
                                    invitee=user,
                                    invitation_code=invitation,
                                    points_awarded=invitation_points
                                )
                    except InvitationCode.DoesNotExist:
                        # 邀请码不存在，但不阻止注册
                        pass

                # 给新用户10个积分作为注册奖励
                user.points = 10

                # 保存用户
                user.save()

                # 创建注册奖励积分交易记录
                PointsTransaction.objects.create(
                    user=user,
                    transaction_type='earn',
                    amount=10,
                    reason='registration',
                    description='新用户注册奖励'
                )

                # 更新验证码状态
                verification.is_used = True
                verification.save()

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
    """生成邀请码视图"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """获取用户的个人邀请码"""
        try:
            # 获取用户的个人邀请码
            invitation = request.user.get_personal_invitation_code()

            return Response({
                'status': 'success',
                'data': {
                    'code': invitation.code,
                    'is_personal': True,
                    'created_at': invitation.created_at
                }
            })
        except Exception as e:
            logger.error(f"获取个人邀请码失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '获取个人邀请码失败'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request):
        """生成一次性邀请码"""
        try:
            # 生成随机邀请码
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

            # 创建邀请码
            invitation = InvitationCode.objects.create(
                code=code,
                created_by=request.user,
                is_personal=False
            )

            return Response({
                'status': 'success',
                'data': {
                    'code': invitation.code,
                    'is_personal': False,
                    'created_at': invitation.created_at
                }
            }, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error(f"生成邀请码失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '生成邀请码失败'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class UserInvitationView(APIView):
    """用户邀请信息视图"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """获取用户的邀请信息"""
        try:
            user = request.user

            # 获取用户的个人邀请码
            invitation = user.get_personal_invitation_code()

            # 获取用户的邀请记录
            invitation_records = InvitationRecord.objects.filter(inviter=user).order_by('-created_at')

            # 获取邀请积分设置
            invitation_points = SystemSetting.get_invitation_points()

            return Response({
                'status': 'success',
                'data': {
                    'invitation_code': invitation.code,
                    'points': user.points,
                    'invitation_points_per_user': invitation_points,
                    'invitation_count': invitation_records.count(),
                    'invitation_records': InvitationRecordSerializer(invitation_records, many=True).data
                }
            })
        except Exception as e:
            logger.error(f"获取邀请信息失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '获取邀请信息失败'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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

# 新增用户排名视图
class UserRankingView(APIView):
    """用户排名视图"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """获取用户的积分排名"""
        try:
            # 按积分降序获取所有用户
            users_by_points = User.objects.order_by('-points')

            # 查找当前用户的排名
            ranking = None
            for i, user in enumerate(users_by_points):
                if user == request.user:
                    ranking = i + 1
                    break

            return Response({
                'status': 'success',
                'ranking': ranking
            })
        except Exception as e:
            logger.error(f"获取用户排名失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '获取用户排名失败'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# 新增认领临时邀请视图
class ClaimTemporaryInvitationView(APIView):
    """认领从网站捕获的临时邀请码"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            user = request.user
            # 从请求体中获取临时邀请的 UUID
            temporary_invitation_uuid = request.data.get('temporary_invitation_uuid')
            if not temporary_invitation_uuid:
                return Response({
                    'status': 'error',
                    'message': '缺少临时邀请码 UUID'
                }, status=status.HTTP_400_BAD_REQUEST)

            # 查找是否有匹配的临时邀请记录
            try:
                temporary_invitation = TemporaryInvitation.objects.get(uuid=temporary_invitation_uuid)
            except TemporaryInvitation.DoesNotExist:
                 return Response({
                    'status': 'error',
                    'message': '没有待认领的邀请码或已过期'
                }, status=status.HTTP_404_NOT_FOUND)

            if temporary_invitation:
                invitation_code = temporary_invitation.invitation_code

                # 查找对应的邀请码对象
                try:
                    invitation = InvitationCode.objects.get(code=invitation_code)
                    inviter = invitation.created_by

                    # 检查是否重复认领 (如果需要)
                    if InvitationRecord.objects.filter(inviter=inviter, invitee=user).exists():
                         # 如果已经存在邀请记录，直接删除临时邀请，返回成功但不重复奖励
                        temporary_invitation.delete()
                        return Response({
                            'status': 'success',
                            'message': '已认领过该邀请'
                        })

                    # 确保邀请人存在且不是自己
                    if inviter and inviter != user:
                        # 给邀请人增加积分
                        invitation_points = SystemSetting.get_invitation_points()
                        inviter.points += invitation_points
                        inviter.save()

                        # 创建邀请记录
                        InvitationRecord.objects.create(
                            inviter=inviter,
                            invitee=user,
                            invitation_code=invitation,
                            points_awarded=invitation_points
                        )

                        # 删除临时邀请记录
                        temporary_invitation.delete()

                        return Response({
                            'status': 'success',
                            'message': '成功认领邀请并获得奖励'
                        })
                    else:
                         # 邀请人不存在或邀请的是自己，删除临时邀请，返回失败
                        temporary_invitation.delete()
                        return Response({
                            'status': 'error',
                            'message': '无效的邀请码'
                        }, status=status.HTTP_400_BAD_REQUEST)
                except InvitationCode.DoesNotExist:
                    # 邀请码对象不存在，删除临时邀请，返回失败
                    temporary_invitation.delete()
                    return Response({
                        'status': 'error',
                        'message': '无效的邀请码'
                    }, status=status.HTTP_400_BAD_REQUEST)
            else:
                return Response({
                    'status': 'error',
                    'message': '没有待认领的邀请码'
                }, status=status.HTTP_404_NOT_FOUND)

        except Exception as e:
            logger.error(f"认领临时邀请失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '认领临时邀请失败'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# 会员相关视图
class MembershipPlansView(APIView):
    """会员套餐列表视图"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """获取所有可用的会员套餐"""
        try:
            plans = MembershipPlan.objects.filter(is_active=True).order_by('price')
            serializer = MembershipPlanSerializer(plans, many=True)

            return Response({
                'status': 'success',
                'data': serializer.data
            })
        except Exception as e:
            logger.error(f"获取会员套餐失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '获取会员套餐失败'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class CreateMembershipOrderView(APIView):
    """创建会员订单视图"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """创建会员订单"""
        try:
            serializer = CreateMembershipOrderSerializer(data=request.data)
            if not serializer.is_valid():
                return Response({
                    'status': 'error',
                    'message': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)

            plan_id = serializer.validated_data['plan_id']
            payment_method = serializer.validated_data['payment_method']

            # 获取套餐信息
            plan = MembershipPlan.objects.get(id=plan_id, is_active=True)

            # 创建订单
            order = MembershipOrder.objects.create(
                user=request.user,
                plan=plan,
                amount=plan.price,
                payment_method=payment_method
            )

            # 设置过期时间（创建后30分钟内支付）
            order.expires_at = timezone.now() + timedelta(minutes=30)
            order.save()

            return Response({
                'status': 'success',
                'data': {
                    'order_id': order.order_id,
                    'amount': str(order.amount),
                    'payment_method': order.payment_method,
                    'expires_at': order.expires_at
                }
            }, status=status.HTTP_201_CREATED)

        except MembershipPlan.DoesNotExist:
            return Response({
                'status': 'error',
                'message': '套餐不存在'
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"创建会员订单失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '创建会员订单失败'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class UserMembershipStatusView(APIView):
    """用户会员状态视图"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """获取用户会员状态"""
        try:
            serializer = UserMembershipStatusSerializer(request.user)
            return Response({
                'status': 'success',
                'data': serializer.data
            })
        except Exception as e:
            logger.error(f"获取用户会员状态失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '获取用户会员状态失败'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class UserMembershipOrdersView(APIView):
    """用户会员订单列表视图"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """获取用户的会员订单列表"""
        try:
            orders = MembershipOrder.objects.filter(user=request.user).order_by('-created_at')
            serializer = MembershipOrderSerializer(orders, many=True)

            return Response({
                'status': 'success',
                'data': serializer.data
            })
        except Exception as e:
            logger.error(f"获取用户订单失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '获取用户订单失败'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class SpendPointsView(APIView):
    """消费积分视图"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """消费积分查看高级分析"""
        try:
            # 检查用户是否为会员
            if request.user.is_premium_active():
                return Response({
                    'status': 'success',
                    'message': '会员用户无需消费积分',
                    'is_premium': True
                })

            # 检查配置的时间内是否已经消费过积分
            duration_minutes = getattr(settings, 'POINTS_ACCESS_DURATION_MINUTES', 1440)  # 默认24小时
            time_ago = timezone.now() - timedelta(minutes=duration_minutes)
            recent_transaction = PointsTransaction.objects.filter(
                user=request.user,
                transaction_type='spend',
                reason='premium_analysis',
                created_at__gte=time_ago
            ).first()

            if recent_transaction:
                # 有效期内已经消费过积分，无需再次消费
                duration_minutes = getattr(settings, 'POINTS_ACCESS_DURATION_MINUTES', 1440)
                return Response({
                    'status': 'success',
                    'message': f'{duration_minutes}分钟内已消费积分，可直接查看',
                    'points_spent': 0,
                    'remaining_points': request.user.points,
                    'is_premium': False,
                    'has_valid_access': True,
                    'access_expires_at': recent_transaction.created_at + timedelta(minutes=duration_minutes)
                })

            # 检查积分是否足够
            required_points = 10  # 查看详情需要10积分
            if request.user.points < required_points:
                return Response({
                    'status': 'error',
                    'message': f'积分不足，需要{required_points}积分',
                    'current_points': request.user.points,
                    'required_points': required_points
                }, status=status.HTTP_400_BAD_REQUEST)

            # 扣除积分
            with transaction.atomic():
                request.user.points -= required_points
                request.user.save()

                # 记录积分交易
                transaction_record = PointsTransaction.objects.create(
                    user=request.user,
                    transaction_type='spend',
                    amount=required_points,
                    reason='premium_analysis',
                    description='查看高级分析报告'
                )

            duration_minutes = getattr(settings, 'POINTS_ACCESS_DURATION_MINUTES', 1440)
            return Response({
                'status': 'success',
                'message': '积分扣除成功',
                'points_spent': required_points,
                'remaining_points': request.user.points,
                'is_premium': False,
                'has_valid_access': True,
                'access_expires_at': transaction_record.created_at + timedelta(minutes=duration_minutes)
            })

        except Exception as e:
            logger.error(f"消费积分失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '消费积分失败'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class SpendPointsForImageView(APIView):
    """消费积分保存图片视图"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """消费积分保存图片"""
        try:
            # 检查用户是否为会员
            if request.user.is_premium_active():
                return Response({
                    'status': 'success',
                    'message': '会员用户无需消费积分',
                    'is_premium': True
                })

            # 检查配置的时间内是否已经消费过积分
            duration_minutes = getattr(settings, 'POINTS_ACCESS_DURATION_MINUTES', 1440)  # 默认24小时
            time_ago = timezone.now() - timedelta(minutes=duration_minutes)
            recent_transaction = PointsTransaction.objects.filter(
                user=request.user,
                transaction_type='spend',
                reason__in=['premium_analysis', 'save_image'],  # 检查任何高级功能访问
                created_at__gte=time_ago
            ).first()

            if recent_transaction:
                # 有效期内已经消费过积分，无需再次消费
                duration_minutes = getattr(settings, 'POINTS_ACCESS_DURATION_MINUTES', 1440)
                return Response({
                    'status': 'success',
                    'message': f'{duration_minutes}分钟内已消费积分，可直接使用',
                    'points_spent': 0,
                    'remaining_points': request.user.points,
                    'is_premium': False,
                    'has_valid_access': True,
                    'access_expires_at': recent_transaction.created_at + timedelta(minutes=duration_minutes)
                })

            # 检查积分是否足够
            required_points = 10  # 保存图片需要10积分
            if request.user.points < required_points:
                return Response({
                    'status': 'error',
                    'message': f'积分不足，需要{required_points}积分',
                    'current_points': request.user.points,
                    'required_points': required_points
                }, status=status.HTTP_400_BAD_REQUEST)

            # 扣除积分
            with transaction.atomic():
                request.user.points -= required_points
                request.user.save()

                # 记录积分交易
                transaction_record = PointsTransaction.objects.create(
                    user=request.user,
                    transaction_type='spend',
                    amount=required_points,
                    reason='save_image',
                    description='保存分析图片'
                )

            duration_minutes = getattr(settings, 'POINTS_ACCESS_DURATION_MINUTES', 1440)
            return Response({
                'status': 'success',
                'message': '积分扣除成功',
                'points_spent': required_points,
                'remaining_points': request.user.points,
                'is_premium': False,
                'has_valid_access': True,
                'access_expires_at': transaction_record.created_at + timedelta(minutes=duration_minutes)
            })

        except Exception as e:
            logger.error(f"消费积分保存图片失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '消费积分失败'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class CheckPremiumAccessView(APIView):
    """检查高级分析访问权限视图"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """检查用户是否有访问高级分析的权限"""
        try:
            # 检查用户是否为会员
            if request.user.is_premium_active():
                return Response({
                    'status': 'success',
                    'has_access': True,
                    'access_type': 'premium',
                    'message': '会员用户可直接访问'
                })

            # 检查配置的时间内是否已经消费过积分
            duration_minutes = getattr(settings, 'POINTS_ACCESS_DURATION_MINUTES', 1440)
            time_ago = timezone.now() - timedelta(minutes=duration_minutes)
            recent_transaction = PointsTransaction.objects.filter(
                user=request.user,
                transaction_type='spend',
                reason='premium_analysis',
                created_at__gte=time_ago
            ).first()

            if recent_transaction:
                # 有效期内已经消费过积分
                duration_minutes = getattr(settings, 'POINTS_ACCESS_DURATION_MINUTES', 1440)
                expires_at = recent_transaction.created_at + timedelta(minutes=duration_minutes)
                return Response({
                    'status': 'success',
                    'has_access': True,
                    'access_type': 'points',
                    'message': f'{duration_minutes}分钟内已消费积分，可直接查看',
                    'access_expires_at': expires_at,
                    'time_remaining': (expires_at - timezone.now()).total_seconds()
                })

            # 没有访问权限
            return Response({
                'status': 'success',
                'has_access': False,
                'access_type': 'none',
                'message': '需要消费积分或升级会员',
                'current_points': request.user.points,
                'required_points': 10
            })

        except Exception as e:
            logger.error(f"检查高级分析访问权限失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '检查访问权限失败'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class PointsConfigView(APIView):
    """积分配置视图"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """获取积分相关配置"""
        try:
            duration_minutes = getattr(settings, 'POINTS_ACCESS_DURATION_MINUTES', 1440)

            # 计算友好的时间显示
            if duration_minutes < 60:
                duration_text = f"{duration_minutes}分钟"
                duration_text_en = f"{duration_minutes} minute{'s' if duration_minutes != 1 else ''}"
            elif duration_minutes < 1440:
                hours = duration_minutes // 60
                duration_text = f"{hours}小时"
                duration_text_en = f"{hours} hour{'s' if hours != 1 else ''}"
            else:
                days = duration_minutes // 1440
                duration_text = f"{days}天"
                duration_text_en = f"{days} day{'s' if days != 1 else ''}"

            return Response({
                'status': 'success',
                'duration_minutes': duration_minutes,
                'duration_text': duration_text,
                'duration_text_en': duration_text_en,
                'required_points': 10
            })
        except Exception as e:
            logger.error(f"获取积分配置失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '获取积分配置失败'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class PointsTransactionHistoryView(APIView):
    """积分交易历史视图"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """获取用户的积分交易历史"""
        try:
            transactions = PointsTransaction.objects.filter(user=request.user).order_by('-created_at')[:50]
            serializer = PointsTransactionSerializer(transactions, many=True)

            return Response({
                'status': 'success',
                'data': serializer.data
            })
        except Exception as e:
            logger.error(f"获取积分交易历史失败: {str(e)}")
            return Response({
                'status': 'error',
                'message': '获取积分交易历史失败'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
