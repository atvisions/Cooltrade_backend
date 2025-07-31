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
        
        # 检查用户是否有未支付的订单
        from user.models import MembershipOrder
        from django.utils import timezone
        
        pending_orders = MembershipOrder.objects.filter(
            user=request.user,
            status='pending',
            expires_at__gt=timezone.now()  # 只检查未过期的订单
        ).order_by('-created_at')
        
        if pending_orders.exists():
            latest_pending_order = pending_orders.first()
            logger.warning(f'User {request.user.id} has pending order {latest_pending_order.order_id}')
            return Response({
                'status': 'error',
                'message': '您有一笔未完成的订单正在等待支付，请先完成该订单或取消后再创建新订单',
                'data': {
                    'pending_order_id': latest_pending_order.order_id,
                    'pending_order_amount': str(latest_pending_order.amount),
                    'pending_order_created_at': latest_pending_order.created_at.isoformat(),
                    'pending_order_expires_at': latest_pending_order.expires_at.isoformat() if latest_pending_order.expires_at else None,
                    'pending_order_plan_name': latest_pending_order.plan.name,
                    'pending_order_payment_method': latest_pending_order.payment_method
                }
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
        logger.info(f'Received verification request data: {data}')
        
        order_id = data.get('order_id')
        tx_hash = data.get('tx_hash')
        token_symbol = data.get('token_symbol', 'USDT')
        network = data.get('network', 'ethereum')
        
        logger.info(f'Parsed parameters - order_id: {order_id}, tx_hash: {tx_hash}, token_symbol: {token_symbol}, network: {network}')
        
        if not order_id or not tx_hash:
            logger.warning(f'Missing required parameters - order_id: {order_id}, tx_hash: {tx_hash}')
            return Response({
                'status': 'error',
                'message': 'Order ID and transaction hash are required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 检查交易hash是否已经被使用过
        from user.models import MembershipOrder
        existing_order_with_tx = MembershipOrder.objects.filter(
            payment_info__contains=tx_hash,
            status='paid'
        ).first()
        
        if existing_order_with_tx:
            logger.warning(f'Transaction hash {tx_hash} has already been used for order {existing_order_with_tx.order_id}')
            return Response({
                'status': 'error',
                'message': f'Transaction hash has already been used for another order: {existing_order_with_tx.order_id}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 获取订单
        logger.info(f'Looking for order {order_id} for user {request.user.id} with status pending')
        try:
            order = MembershipOrder.objects.get(
                order_id=order_id,
                user=request.user,
                status='pending'
            )
            logger.info(f'Found order: {order.order_id}, status: {order.status}')
        except MembershipOrder.DoesNotExist:
            logger.warning(f'Order {order_id} not found or already processed for user {request.user.id}')
            return Response({
                'status': 'error',
                'message': 'Order not found or already processed'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 验证支付
        logger.info(f'Starting verification for order {order_id}, tx_hash: {tx_hash}, token: {token_symbol}, network: {network}')
        
        verification_result = crypto_payment_service.verify_payment(
            order_id=order_id,
            token_symbol=token_symbol,
            network=network,
            tx_hash=tx_hash
        )
        
        logger.info(f'Verification result for order {order_id}: {verification_result}')
        
        if verification_result['verified']:
            # 支付验证成功，更新订单状态
            order.status = 'paid'
            order.paid_at = timezone.now()
            
            # 确保 payment_info 是字典格式
            if isinstance(order.payment_info, str):
                import json
                payment_info = json.loads(order.payment_info)
            else:
                payment_info = order.payment_info or {}
            
            payment_info['tx_hash'] = tx_hash
            payment_info['verification_result'] = verification_result
            order.payment_info = payment_info
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
            from user.models import PointsTransaction
            PointsTransaction.objects.create(
                user=user,
                transaction_type='earn',
                amount=points_to_award,
                reason='premium_purchase',
                description=f'会员购买奖励 - 订单 {order_id}'
            )
            
            logger.info(f'Payment verified successfully for order {order_id}. User {user.id} awarded {points_to_award} points.')
            
            return Response({
                'status': 'success',
                'message': 'Payment verified successfully',
                'data': {
                    'order_id': order_id,
                    'points_awarded': points_to_award,
                    'membership_expires_at': user.premium_expires_at.isoformat() if user.premium_expires_at else None
                }
            })
        else:
            logger.warning(f'Payment verification failed for order {order_id}: {verification_result.get("message", "Unknown error")}')
            return Response({
                'status': 'error',
                'message': verification_result.get('message', 'Payment verification failed')
            }, status=status.HTTP_400_BAD_REQUEST)
            
    except Exception as e:
        import traceback
        logger.error(f'Error verifying crypto payment: {e}')
        logger.error(f'Traceback: {traceback.format_exc()}')
        return Response({
            'status': 'error',
            'message': f'Failed to verify payment: {str(e)}'
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
        
        # 如果订单状态是pending，尝试自动检查支付
        if order.status == 'pending':
            auto_check_result = crypto_payment_service.auto_check_payment(order_id)
            
            # 如果自动检查成功，重新获取订单信息
            if auto_check_result.get('verified'):
                order.refresh_from_db()
                logger.info(f'Auto-check successful for order {order_id}')
        
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
    """取消未支付的订单"""
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
        
        # 取消订单
        order.status = 'cancelled'
        order.save()
        
        logger.info(f'Order {order_id} cancelled by user {request.user.id}')
        
        return Response({
            'status': 'success',
            'message': '订单已取消',
            'data': {
                'order_id': order_id
            }
        })
        
    except Exception as e:
        import traceback
        logger.error(f'Error cancelling order: {e}')
        logger.error(f'Traceback: {traceback.format_exc()}')
        return Response({
            'status': 'error',
            'message': f'Failed to cancel order: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR) 