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
            
            # 使用Moralis API验证交易
            url = f"{self.base_url}/{tx_hash}"
            params = {
                'chain': network
            }
            headers = {
                'X-API-Key': self.moralis_api_key
            }
            
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            
            transaction_data = response.json()
            
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
            # 检查交易状态
            if transaction_data.get('receipt_status') != '1':
                return {
                    'verified': False,
                    'message': 'Transaction failed or pending'
                }
            
            # 检查确认数
            confirmations = transaction_data.get('confirmations', 0)
            min_confirmations = self._get_min_confirmations(network)
            
            if confirmations < min_confirmations:
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
            actual_receiver = transaction_data.get('to_address')
            
            if expected_receiver and actual_receiver and expected_receiver.lower() != actual_receiver.lower():
                return {
                    'verified': False,
                    'message': 'Receiver address mismatch'
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
                'icon': '💎',
                'description': 'Most popular stablecoin'
            },
            {
                'symbol': 'USDC',
                'name': 'USD Coin',
                'networks': ['ethereum', 'bsc', 'polygon'],
                'icon': '🪙',
                'description': 'Regulated stablecoin'
            }
        ]
    
    def get_supported_networks(self) -> list:
        """获取支持的网络列表"""
        return [
            {
                'id': 'ethereum',
                'name': 'Ethereum',
                'icon': '🔷',
                'description': 'Most secure network',
                'gas_fee': 'High'
            },
            {
                'id': 'bsc',
                'name': 'BNB Smart Chain',
                'icon': '🟡',
                'description': 'Fast and low cost',
                'gas_fee': 'Low'
            },
            {
                'id': 'polygon',
                'name': 'Polygon',
                'icon': '🟣',
                'description': 'Ethereum scaling solution',
                'gas_fee': 'Very Low'
            }
        ]

# 创建全局实例
crypto_payment_service = CryptoPaymentService() 