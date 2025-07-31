import logging
from decimal import Decimal
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views import View
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
import json
from datetime import timedelta
from django.utils import timezone

from .models import MembershipOrder, MembershipPlan, User, PointsTransaction
from .services.crypto_payment_service import crypto_payment_service

logger = logging.getLogger(__name__)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_supported_tokens(request):
    """获取支持的代币列表"""
    try:
        tokens = crypto_payment_service.get_supported_tokens()
        networks = crypto_payment_service.get_supported_networks()
        
        return Response({
            'status': 'success',
            'data': {
                'tokens': tokens,
                'networks': networks
            }
        })
    except Exception as e:
        logger.error(f'Error getting supported tokens: {e}')
        return Response({
            'status': 'error',
            'message': 'Failed to get supported tokens'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_crypto_payment_order(request):
    """创建加密货币支付订单"""
    try:
        data = request.data
        plan_id = data.get('plan_id')
        token_symbol = data.get('token_symbol', 'USDT')
        network = data.get('network', 'ethereum')
        
        if not plan_id:
            return Response({
                'status': 'error',
                'message': 'Plan ID is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 获取会员套餐
        try:
            plan = MembershipPlan.objects.get(id=plan_id, is_active=True)
        except MembershipPlan.DoesNotExist:
            return Response({
                'status': 'error',
                'message': 'Invalid plan ID'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 生成订单号
        import uuid
        order_id = f"CR{str(uuid.uuid4()).replace('-', '')[:16].upper()}"
        
        # 创建订单
        order = MembershipOrder.objects.create(
            order_id=order_id,
            user=request.user,
            plan=plan,
            amount=plan.price,
            payment_method=f'{token_symbol.lower()}_{network}',
            status='pending',
            expires_at=timezone.now() + timedelta(hours=24)
        )
        
        # 创建支付请求
        payment_request = crypto_payment_service.create_payment_request(
            order_id=order_id,
            amount_usd=plan.price,
            token_symbol=token_symbol,
            network=network
        )
        
        # 更新订单的支付信息
        order.payment_info = payment_request
        order.save()
        
        return Response({
            'status': 'success',
            'data': {
                'order_id': order_id,
                'payment_request': payment_request
            }
        })
        
    except Exception as e:
        import traceback
        logger.error(f'Error creating crypto payment order: {e}')
        logger.error(f'Traceback: {traceback.format_exc()}')
        return Response({
            'status': 'error',
            'message': f'Failed to create payment order: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_crypto_payment(request):
    """验证加密货币支付"""
    try:
        data = request.data
        order_id = data.get('order_id')
        tx_hash = data.get('tx_hash')
        token_symbol = data.get('token_symbol', 'USDT')
        network = data.get('network', 'ethereum')
        
        if not order_id or not tx_hash:
            return Response({
                'status': 'error',
                'message': 'Order ID and transaction hash are required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 获取订单
        try:
            order = MembershipOrder.objects.get(
                order_id=order_id,
                user=request.user,
                status='pending'
            )
        except MembershipOrder.DoesNotExist:
            return Response({
                'status': 'error',
                'message': 'Order not found or already processed'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 验证支付
        verification_result = crypto_payment_service.verify_payment(
            order_id=order_id,
            token_symbol=token_symbol,
            network=network,
            tx_hash=tx_hash
        )
        
        if verification_result['verified']:
            # 支付验证成功，更新订单状态
            order.status = 'paid'
            order.paid_at = timezone.now()
            order.payment_info['tx_hash'] = tx_hash
            order.payment_info['verification_result'] = verification_result
            order.save()
            
            # 激活会员
            user = request.user
            if user.premium_expires_at and user.premium_expires_at > timezone.now():
                # 如果会员未过期，延长会员时间
                user.premium_expires_at += timedelta(days=order.plan.duration_days)
            else:
                # 如果会员已过期或从未购买过，设置新的到期时间
                user.premium_expires_at = timezone.now() + timedelta(days=order.plan.duration_days)
            
            user.is_premium = True
            user.save()
            
            # 计算积分奖励（1:10比例）
            points_to_award = int(float(order.amount) * 10)
            user.points += points_to_award
            user.save()
            
            # 记录积分交易
            PointsTransaction.objects.create(
                user=user,
                transaction_type='earn',
                amount=points_to_award,
                reason='premium_purchase',
                description=f'Premium membership purchase reward for order {order_id}'
            )
            
            return Response({
                'status': 'success',
                'data': {
                    'message': 'Payment verified successfully',
                    'points_awarded': points_to_award,
                    'membership_expires_at': user.premium_expires_at.isoformat()
                }
            })
        else:
            return Response({
                'status': 'error',
                'message': verification_result['message']
            }, status=status.HTTP_400_BAD_REQUEST)
        
    except Exception as e:
        logger.error(f'Error verifying crypto payment: {e}')
        return Response({
            'status': 'error',
            'message': 'Failed to verify payment'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_crypto_payment_status(request, order_id):
    """获取加密货币支付状态"""
    try:
        # 获取订单
        try:
            order = MembershipOrder.objects.get(
                order_id=order_id,
                user=request.user
            )
        except MembershipOrder.DoesNotExist:
            return Response({
                'status': 'error',
                'message': 'Order not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        return Response({
            'status': 'success',
            'data': {
                'order_id': order.order_id,
                'status': order.status,
                'amount': float(order.amount),
                'payment_method': order.payment_method,
                'created_at': order.created_at.isoformat(),
                'paid_at': order.paid_at.isoformat() if order.paid_at else None,
                'expires_at': order.expires_at.isoformat() if order.expires_at else None,
                'payment_info': order.payment_info
            }
        })
        
    except Exception as e:
        logger.error(f'Error getting crypto payment status: {e}')
        return Response({
            'status': 'error',
            'message': 'Failed to get payment status'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_token_price(request):
    """获取代币价格"""
    try:
        token_symbol = request.GET.get('token', 'USDT')
        network = request.GET.get('network', 'ethereum')
        
        price = crypto_payment_service.get_token_price(token_symbol, network)
        
        return Response({
            'status': 'success',
            'data': {
                'token_symbol': token_symbol,
                'network': network,
                'price_usd': float(price)
            }
        })
        
    except Exception as e:
        logger.error(f'Error getting token price: {e}')
        return Response({
            'status': 'error',
            'message': 'Failed to get token price'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR) 

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_user_orders(request):
    """获取用户订单列表"""
    try:
        # 获取查询参数
        status_filter = request.GET.get('status', '')  # 可选的状态过滤
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 10))
        
        # 构建查询
        orders_query = MembershipOrder.objects.filter(user=request.user)
        
        # 状态过滤
        if status_filter:
            orders_query = orders_query.filter(status=status_filter)
        
        # 分页
        total_count = orders_query.count()
        start = (page - 1) * page_size
        end = start + page_size
        orders = orders_query.order_by('-created_at')[start:end]
        
        # 序列化订单数据
        orders_data = []
        for order in orders:
            order_data = {
                'order_id': order.order_id,
                'plan_name': order.plan.name,
                'plan_type': order.plan.plan_type,
                'amount': float(order.amount),
                'status': order.status,
                'payment_method': order.payment_method,
                'created_at': order.created_at.isoformat(),
                'expires_at': order.expires_at.isoformat() if order.expires_at else None,
                'paid_at': order.paid_at.isoformat() if order.paid_at else None,
                'payment_info': order.payment_info
            }
            orders_data.append(order_data)
        
        return Response({
            'status': 'success',
            'data': {
                'orders': orders_data,
                'pagination': {
                    'page': page,
                    'page_size': page_size,
                    'total_count': total_count,
                    'total_pages': (total_count + page_size - 1) // page_size
                }
            }
        })
        
    except Exception as e:
        logger.error(f'Error getting user orders: {e}')
        return Response({
            'status': 'error',
            'message': 'Failed to get orders'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cancel_order(request):
    """取消订单"""
    try:
        data = request.data
        order_id = data.get('order_id')
        
        if not order_id:
            return Response({
                'status': 'error',
                'message': 'Order ID is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 获取订单
        try:
            order = MembershipOrder.objects.get(
                order_id=order_id,
                user=request.user,
                status='pending'
            )
        except MembershipOrder.DoesNotExist:
            return Response({
                'status': 'error',
                'message': 'Order not found or cannot be cancelled'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 检查订单是否过期
        if order.expires_at and order.expires_at < timezone.now():
            order.status = 'expired'
            order.save()
            return Response({
                'status': 'error',
                'message': 'Order has already expired'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 取消订单
        order.status = 'cancelled'
        order.save()
        
        return Response({
            'status': 'success',
            'data': {
                'message': 'Order cancelled successfully',
                'order_id': order_id
            }
        })
        
    except Exception as e:
        logger.error(f'Error cancelling order: {e}')
        return Response({
            'status': 'error',
            'message': 'Failed to cancel order'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR) 