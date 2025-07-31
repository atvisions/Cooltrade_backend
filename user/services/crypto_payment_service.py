import os
import requests
import json
import logging
from decimal import Decimal
from django.conf import settings
from django.utils import timezone
from datetime import datetime, timedelta, timezone as dt_timezone

logger = logging.getLogger(__name__)

class CryptoPaymentService:
    """加密货币支付服务"""
    
    def __init__(self):
        self.moralis_api_key = os.getenv('MORALIS_API_KEY')
        self.base_url = 'https://deep-index.moralis.io/api/v2'
        
        if not self.moralis_api_key:
            logger.error('MORALIS_API_KEY not found in environment variables')
            raise ValueError('MORALIS_API_KEY is required for crypto payments')
        
        # 验证收款地址配置
        self._validate_receiver_addresses()
    
    def _validate_receiver_addresses(self):
        """验证收款地址配置"""
        required_addresses = [
            'USDT_ETH_ADDRESS', 'USDT_BSC_ADDRESS', 'USDT_POLYGON_ADDRESS',
            'USDC_ETH_ADDRESS', 'USDC_BSC_ADDRESS', 'USDC_POLYGON_ADDRESS'
        ]
        
        missing_addresses = []
        for addr in required_addresses:
            if not os.getenv(addr):
                missing_addresses.append(addr)
        
        if missing_addresses:
            logger.warning(f'Missing receiver addresses: {missing_addresses}')
            logger.warning('Using placeholder addresses. Please configure real addresses for production.')
    
    def get_token_price(self, token_symbol: str, network: str = 'ethereum') -> Decimal:
        """获取代币价格"""
        try:
            # 代币合约地址映射
            token_addresses = {
                'USDT': {
                    'ethereum': '0xdac17f958d2ee523a2206206994597c13d831ec7',
                    'bsc': '0x55d398326f99059ff775485246999027b3197955',
                    'polygon': '0xc2132d05d31c914a87c6611c10748aeb04b58e8f'
                },
                'USDC': {
                    'ethereum': '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
                    'bsc': '0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d',
                    'polygon': '0x2791bca1f2de4661ed88a30c99a7a9449aa84174'
                }
            }
            
            token_address = token_addresses.get(token_symbol.upper(), {}).get(network)
            if not token_address:
                raise ValueError(f'Token {token_symbol} not supported on network {network}')
            
            # 网络到Moralis chain参数的映射
            chain_mapping = {
                'ethereum': 'eth',
                'bsc': 'bsc',
                'polygon': 'polygon'
            }
            
            chain_param = chain_mapping.get(network, network)
            
            url = f"{self.base_url}/erc20/{token_address}/price"
            params = {
                'chain': chain_param,
                'include': 'percent_change'
            }
            headers = {
                'X-API-Key': self.moralis_api_key
            }
            
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            price = Decimal(str(data.get('usdPrice', 0)))
            
            if price <= 0:
                raise ValueError(f'Invalid token price: {price}')
            
            logger.info(f'Token price for {token_symbol} on {network}: ${price}')
            return price
            
        except requests.exceptions.RequestException as e:
            logger.error(f'Network error getting token price for {token_symbol}: {e}')
            raise
        except Exception as e:
            logger.error(f'Error getting token price for {token_symbol}: {e}')
            raise
    
    def create_payment_request(self, order_id: str, amount_usd: Decimal, token_symbol: str, network: str = 'ethereum') -> dict:
        """创建支付请求"""
        try:
            # 获取代币价格
            token_price = self.get_token_price(token_symbol, network)
            
            # 计算需要的代币数量（向上取整到6位小数）
            token_amount = (amount_usd / token_price).quantize(Decimal('0.000001'), rounding='ROUND_UP')
            
            # 代币合约地址映射
            token_addresses = {
                'USDT': {
                    'ethereum': '0xdac17f958d2ee523a2206206994597c13d831ec7',
                    'bsc': '0x55d398326f99059ff775485246999027b3197955',
                    'polygon': '0xc2132d05d31c914a87c6611c10748aeb04b58e8f'
                },
                'USDC': {
                    'ethereum': '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
                    'bsc': '0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d',
                    'polygon': '0x2791bca1f2de4661ed88a30c99a7a9449aa84174'
                }
            }
            
            token_address = token_addresses.get(token_symbol.upper(), {}).get(network)
            if not token_address:
                raise ValueError(f'Token {token_symbol} not supported on network {network}')
            
            # 获取收款地址
            receiver_addresses = {
                'USDT': {
                    'ethereum': os.getenv('USDT_ETH_ADDRESS', '0x1234567890123456789012345678901234567890'),
                    'bsc': os.getenv('USDT_BSC_ADDRESS', '0x1234567890123456789012345678901234567890'),
                    'polygon': os.getenv('USDT_POLYGON_ADDRESS', '0x1234567890123456789012345678901234567890')
                },
                'USDC': {
                    'ethereum': os.getenv('USDC_ETH_ADDRESS', '0x1234567890123456789012345678901234567890'),
                    'bsc': os.getenv('USDC_BSC_ADDRESS', '0x1234567890123456789012345678901234567890'),
                    'polygon': os.getenv('USDC_POLYGON_ADDRESS', '0x1234567890123456789012345678901234567890')
                }
            }
            
            receiver_address = receiver_addresses.get(token_symbol.upper(), {}).get(network)
            
            # 检查是否为占位符地址
            if receiver_address == '0x1234567890123456789012345678901234567890':
                logger.warning(f'Using placeholder address for {token_symbol} on {network}')
            
            payment_request = {
                'order_id': order_id,
                'token_symbol': token_symbol.upper(),
                'network': network,
                'token_address': token_address,
                'receiver_address': receiver_address,
                'amount_usd': float(amount_usd),
                'token_amount': float(token_amount),
                'token_price': float(token_price),
                'expires_at': (datetime.now() + timedelta(hours=24)).isoformat(),
                'payment_url': f"crypto://{network}/{token_address}/{receiver_address}?amount={token_amount}&order_id={order_id}",
                'min_confirmations': self._get_min_confirmations(network)
            }
            
            logger.info(f'Created payment request: {payment_request}')
            return payment_request
            
        except Exception as e:
            logger.error(f'Error creating payment request: {e}')
            raise
    
    def _get_min_confirmations(self, network: str) -> int:
        """获取最小确认数"""
        confirmations = {
            'ethereum': 12,
            'bsc': 15,
            'polygon': 256
        }
        return confirmations.get(network, 12)
    
    def verify_payment(self, order_id: str, token_symbol: str, network: str = 'ethereum', tx_hash: str = None) -> dict:
        """验证支付"""
        try:
            if not tx_hash:
                return {
                    'verified': False,
                    'message': 'Transaction hash required for verification'
                }
            
            logger.info(f'Starting payment verification for order {order_id}, tx_hash: {tx_hash}, token: {token_symbol}, network: {network}')
            
            # 使用Moralis API验证交易
            # 网络到Moralis chain参数的映射
            chain_mapping = {
                'ethereum': 'eth',
                'bsc': 'bsc',
                'polygon': 'polygon'
            }
            
            chain_param = chain_mapping.get(network, network)
            
            # 使用正确的API端点获取交易信息
            # Moralis API v2: /api/v2/transaction/{tx_hash}?chain={chain}
            url = f"{self.base_url}/transaction/{tx_hash}"
            params = {
                'chain': chain_param
            }
            headers = {
                'X-API-Key': self.moralis_api_key
            }
            
            logger.info(f'Fetching transaction data from Moralis: {url} with chain: {chain_param}')
            response = requests.get(url, params=params, headers=headers, timeout=10)
            
            if response.status_code != 200:
                logger.error(f'Moralis API error: {response.status_code} - {response.text}')
                return {
                    'verified': False,
                    'message': f'Moralis API error: {response.status_code} - {response.text}'
                }
            
            response.raise_for_status()
            
            transaction_data = response.json()
            logger.info(f'Transaction data received: {transaction_data}')
            
            # 检查交易数据格式
            if not isinstance(transaction_data, dict):
                logger.error(f'Invalid transaction data format: {type(transaction_data)}')
                return {
                    'verified': False,
                    'message': f'Invalid transaction data format: {type(transaction_data)}'
                }
            
            # 验证交易详情
            verification_result = self._validate_transaction(transaction_data, order_id, token_symbol, network)
            
            logger.info(f'Payment verification result: {verification_result}')
            return verification_result
            
        except requests.exceptions.RequestException as e:
            logger.error(f'Network error verifying payment: {e}')
            return {
                'verified': False,
                'message': f'Network error: {str(e)}'
            }
        except Exception as e:
            logger.error(f'Error verifying payment: {e}')
            return {
                'verified': False,
                'message': f'Verification error: {str(e)}'
            }
    
    def _validate_transaction(self, transaction_data: dict, order_id: str, token_symbol: str, network: str) -> dict:
        """验证交易详情"""
        try:
            logger.info(f'Validating transaction for order {order_id}')
            logger.info(f'Transaction data keys: {list(transaction_data.keys())}')
            
            # 检查交易状态
            receipt_status = transaction_data.get('receipt_status')
            logger.info(f'Receipt status: {receipt_status}')
            
            if receipt_status != '1':
                return {
                    'verified': False,
                    'message': f'Transaction failed or pending. Status: {receipt_status}'
                }
            
            # 检查确认数
            confirmations = transaction_data.get('confirmations', 0)
            min_confirmations = self._get_min_confirmations(network)
            
            logger.info(f'Confirmation check - Required: {min_confirmations}, Current: {confirmations}')
            logger.info(f'Full transaction data: {transaction_data}')
            
            # 对于测试环境或开发环境，可以放宽确认数要求
            if confirmations < min_confirmations:
                # 如果是开发环境，允许较少的确认数
                if os.getenv('DJANGO_SETTINGS_MODULE', '').endswith('.settings'):
                    logger.warning(f'Development environment: Allowing payment with {confirmations} confirmations (required: {min_confirmations})')
                    # 在开发环境中，只要交易状态是成功的，就允许通过
                    if receipt_status == '1':
                        logger.info('Development environment: Payment allowed despite insufficient confirmations')
                    else:
                        return {
                            'verified': False,
                            'message': f'Transaction failed or pending. Status: {receipt_status}'
                        }
                else:
                    return {
                        'verified': False,
                        'message': f'Insufficient confirmations. Required: {min_confirmations}, Current: {confirmations}'
                    }
            
            # 检查接收地址
            receiver_addresses = {
                'USDT': {
                    'ethereum': os.getenv('USDT_ETH_ADDRESS'),
                    'bsc': os.getenv('USDT_BSC_ADDRESS'),
                    'polygon': os.getenv('USDT_POLYGON_ADDRESS')
                },
                'USDC': {
                    'ethereum': os.getenv('USDC_ETH_ADDRESS'),
                    'bsc': os.getenv('USDC_BSC_ADDRESS'),
                    'polygon': os.getenv('USDC_POLYGON_ADDRESS')
                }
            }
            
            expected_receiver = receiver_addresses.get(token_symbol.upper(), {}).get(network)
            
            # 对于ERC20代币，需要从交易日志中获取真正的收款地址
            # to_address 是代币合约地址，不是收款地址
            actual_receiver = None
            
            # 尝试从交易日志中获取收款地址
            if 'logs' in transaction_data and transaction_data['logs']:
                for log in transaction_data['logs']:
                    # 查找Transfer事件
                    if log.get('topic0') == '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef':  # Transfer event signature
                        # 解析Transfer事件的参数
                        topics = log.get('topics', [])
                        if len(topics) >= 3:
                            # topics[1] = from address, topics[2] = to address
                            to_address = topics[2]
                            if to_address.startswith('0x'):
                                to_address = to_address[2:]  # 移除0x前缀
                            # 补齐到40个字符
                            to_address = '0x' + to_address.zfill(40)
                            actual_receiver = to_address
                            logger.info(f'Found receiver address from Transfer event: {actual_receiver}')
                            break
            
            # 如果没有找到Transfer事件，尝试其他方法
            if not actual_receiver:
                # 尝试从input data中解析
                input_data = transaction_data.get('input', '')
                if input_data and len(input_data) >= 138:  # Transfer method call
                    # 解析transfer(address,uint256)的参数
                    to_address_hex = input_data[34:74]  # 跳过方法签名和padding
                    actual_receiver = '0x' + to_address_hex
                    logger.info(f'Found receiver address from input data: {actual_receiver}')
            
            logger.info(f'Address check - Token: {token_symbol}, Network: {network}')
            logger.info(f'Expected receiver: {expected_receiver}')
            logger.info(f'Actual receiver: {actual_receiver}')
            logger.info(f'Configured addresses: {receiver_addresses}')
            
            if expected_receiver and actual_receiver:
                if expected_receiver.lower() != actual_receiver.lower():
                    logger.warning(f'Address mismatch - Expected: {expected_receiver.lower()}, Actual: {actual_receiver.lower()}')
                    return {
                        'verified': False,
                        'message': f'Receiver address mismatch. Expected: {expected_receiver}, Actual: {actual_receiver}'
                    }
                else:
                    logger.info('Address match confirmed')
            else:
                logger.warning(f'Missing address info - Expected: {expected_receiver}, Actual: {actual_receiver}')
                # 如果地址信息缺失，在开发环境中允许通过
                if os.getenv('DJANGO_SETTINGS_MODULE', '').endswith('.settings'):
                    logger.warning('Development environment: Allowing payment despite missing address info')
                else:
                    return {
                        'verified': False,
                        'message': 'Missing receiver address information'
                    }
            
            # 检查支付金额（减少容错机制）
            # 从数据库获取订单信息以获取期望的金额
            from user.models import MembershipOrder
            try:
                order = MembershipOrder.objects.get(order_id=order_id)
                expected_amount = Decimal(str(order.amount))
                
                # 从订单的payment_info中获取创建时计算的代币数量
                payment_info = order.payment_info
                if isinstance(payment_info, str):
                    import json
                    payment_info = json.loads(payment_info)
                
                expected_token_amount = Decimal(str(payment_info.get('token_amount', 0)))
                
                # 如果订单中没有记录代币数量，则使用当前价格计算（兼容旧订单）
                if expected_token_amount == 0:
                    logger.warning(f'No token amount recorded in order {order_id}, using current price calculation')
                    current_token_price = self.get_token_price(token_symbol, network)
                    expected_token_amount = (expected_amount / current_token_price).quantize(Decimal('0.000001'), rounding='ROUND_UP')
                
                logger.info(f'Using expected token amount from order: {expected_token_amount} {token_symbol}')
                
                # 从交易数据中获取实际支付金额
                # 对于ERC20代币，需要从Transfer事件中获取金额
                actual_token_amount = Decimal('0')
                
                # 尝试从Transfer事件中获取金额
                if 'logs' in transaction_data and transaction_data['logs']:
                    for log in transaction_data['logs']:
                        if log.get('topic0') == '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef':
                            topics = log.get('topics', [])
                            data = log.get('data', '')
                            if len(topics) >= 3 and data:
                                # 解析Transfer事件的金额
                                try:
                                    amount_hex = data[2:]  # 移除0x前缀
                                    amount_decimal = int(amount_hex, 16)
                                    # USDT有6位小数
                                    actual_token_amount = Decimal(amount_decimal) / Decimal('1000000')
                                    logger.info(f'Found token amount from Transfer event: {actual_token_amount}')
                                    break
                                except (ValueError, IndexError) as e:
                                    logger.warning(f'Failed to parse amount from Transfer event: {e}')
                
                # 如果没有从Transfer事件获取到金额，尝试从input data解析
                if actual_token_amount == 0:
                    input_data = transaction_data.get('input', '')
                    if input_data and len(input_data) >= 138:
                        try:
                            amount_hex = input_data[74:138]  # 跳过方法签名和地址参数
                            amount_decimal = int(amount_hex, 16)
                            actual_token_amount = Decimal(amount_decimal) / Decimal('1000000')
                            logger.info(f'Found token amount from input data: {actual_token_amount}')
                        except (ValueError, IndexError) as e:
                            logger.warning(f'Failed to parse amount from input data: {e}')
                
                # 如果仍然没有获取到金额，使用默认值
                if actual_token_amount == 0:
                    actual_token_amount = Decimal(str(transaction_data.get('value', 0)))
                    logger.warning(f'Using default value for token amount: {actual_token_amount}')
                
                # 减少容错范围：从0.01 USDT减少到0.001 USDT（约1美分）
                tolerance = Decimal('0.001')
                difference = abs(expected_token_amount - actual_token_amount)
                
                logger.info(f'Amount comparison - Expected: {expected_token_amount} {token_symbol}, Actual: {actual_token_amount} {token_symbol}, Difference: {difference}')
                
                if difference > tolerance:
                    return {
                        'verified': False,
                        'message': f'Amount mismatch. Expected: {expected_token_amount} {token_symbol}, Actual: {actual_token_amount} {token_symbol}, Difference: {difference}'
                    }
                
                logger.info(f'Payment amount verified. Expected: {expected_token_amount} {token_symbol}, Actual: {actual_token_amount} {token_symbol}, Difference: {difference}')
                
            except MembershipOrder.DoesNotExist:
                logger.warning(f'Order {order_id} not found, skipping amount verification')
            except Exception as e:
                logger.error(f'Error verifying payment amount: {e}')
                # 如果金额验证失败，返回验证失败
                return {
                    'verified': False,
                    'message': f'Amount verification error: {str(e)}'
                }
            
            return {
                'verified': True,
                'message': 'Payment verified successfully',
                'transaction_data': transaction_data,
                'confirmations': confirmations
            }
            
        except Exception as e:
            logger.error(f'Error validating transaction: {e}')
            return {
                'verified': False,
                'message': f'Validation error: {str(e)}'
            }
    
    def get_supported_tokens(self) -> list:
        """获取支持的代币列表"""
        return [
            {
                'symbol': 'USDT',
                'name': 'Tether USD',
                'networks': ['ethereum', 'bsc', 'polygon'],
                'icon': '/icons/usdt.png',
                'description': 'Most popular stablecoin'
            },
            {
                'symbol': 'USDC',
                'name': 'USD Coin',
                'networks': ['ethereum', 'bsc', 'polygon'],
                'icon': '/icons/usdc.png',
                'description': 'Regulated stablecoin'
            }
        ]
    
    def get_supported_networks(self) -> list:
        """获取支持的网络列表"""
        return [
            {
                'id': 'ethereum',
                'name': 'Ethereum',
                'icon': '/icons/eth.png',
                'description': 'Most secure network',
                'gas_fee': 'High'
            },
            {
                'id': 'bsc',
                'name': 'BNB Smart Chain',
                'icon': '/icons/bnb.png',
                'description': 'Fast and low cost',
                'gas_fee': 'Low'
            },
            {
                'id': 'polygon',
                'name': 'Polygon',
                'icon': '/icons/matic.png',
                'description': 'Ethereum scaling solution',
                'gas_fee': 'Very Low'
            }
        ]

    def auto_check_payment(self, order_id: str) -> dict:
        """自动检查支付状态"""
        try:
            from user.models import MembershipOrder
            
            # 获取订单信息
            try:
                order = MembershipOrder.objects.get(order_id=order_id)
            except MembershipOrder.DoesNotExist:
                return {
                    'verified': False,
                    'message': 'Order not found'
                }
            
            # 如果订单已经确认，直接返回
            if order.status == 'paid':
                return {
                    'verified': True,
                    'message': 'Payment already confirmed',
                    'status': 'confirmed'
                }
            
            # 获取收款地址
            payment_info = order.payment_info
            if not payment_info:
                return {
                    'verified': False,
                    'message': 'Payment info not found'
                }
            
            # 确保payment_info是字典
            if isinstance(payment_info, str):
                try:
                    import json
                    payment_info = json.loads(payment_info)
                except (json.JSONDecodeError, TypeError):
                    return {
                        'verified': False,
                        'message': 'Invalid payment info format'
                    }
            
            if not isinstance(payment_info, dict):
                return {
                    'verified': False,
                    'message': 'Payment info is not a valid dictionary'
                }
            
            token_symbol = payment_info.get('token_symbol', 'USDT')
            network = payment_info.get('network', 'ethereum')
            receiver_address = payment_info.get('receiver_address')
            
            if not receiver_address:
                return {
                    'verified': False,
                    'message': 'Receiver address not found'
                }
            
            # 使用Moralis API获取地址的交易历史
            chain_mapping = {
                'ethereum': 'eth',
                'bsc': 'bsc',
                'polygon': 'polygon'
            }
            
            chain_param = chain_mapping.get(network, network)
            
            # 获取最近24小时的交易
            url = f"{self.base_url}/{receiver_address}"
            params = {
                'chain': chain_param,
                'from_date': (datetime.now() - timedelta(hours=24)).isoformat(),
                'to_date': datetime.now().isoformat()
            }
            headers = {
                'X-API-Key': self.moralis_api_key
            }
            
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            
            transactions = response.json()
            
            # 检查是否有匹配的支付
            for tx in transactions:
                # 检查是否是指向收款地址的交易
                if tx.get('to_address', '').lower() == receiver_address.lower():
                    # 验证交易详情
                    verification_result = self._validate_transaction(tx, order_id, token_symbol, network)
                    
                    if verification_result.get('verified'):
                        # 更新订单状态
                        order.status = 'paid'
                        order.paid_at = timezone.now()
                        order.save()
                        
                        logger.info(f'Payment auto-verified for order {order_id}: {tx.get("hash")}')
                        return {
                            'verified': True,
                            'message': 'Payment auto-verified',
                            'status': 'confirmed',
                            'transaction_hash': tx.get('hash')
                        }
            
            return {
                'verified': False,
                'message': 'No matching payment found',
                'status': 'pending'
            }
            
        except requests.exceptions.RequestException as e:
            logger.error(f'Network error in auto-check payment: {e}')
            return {
                'verified': False,
                'message': f'Network error: {str(e)}',
                'status': 'error'
            }
        except Exception as e:
            logger.error(f'Error in auto-check payment: {e}')
            return {
                'verified': False,
                'message': f'Auto-check error: {str(e)}',
                'status': 'error'
            }

# 创建全局实例
crypto_payment_service = CryptoPaymentService() 