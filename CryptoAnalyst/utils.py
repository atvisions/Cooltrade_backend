import logging
import json
from typing import Dict, Any
from datetime import datetime, timezone

# 配置日志记录器
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 创建控制台处理器
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

# 创建文件处理器
file_handler = logging.FileHandler('crypto_analyst.log')
file_handler.setLevel(logging.INFO)

# 创建格式化器
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
file_handler.setFormatter(formatter)

# 添加处理器到日志记录器
logger.addHandler(console_handler)
logger.addHandler(file_handler)

def sanitize_float(value: Any, min_value: float = -1000000.0, max_value: float = 1000000.0) -> float:
    """确保浮点数值在合理范围内
    
    Args:
        value: 要检查的值
        min_value: 最小值
        max_value: 最大值
        
    Returns:
        float: 在范围内的值
    """
    try:
        if value is None:
            return 0.0

        float_value = float(value)

        # 检查是否为无穷大或NaN
        if not isinstance(float_value, float) or float_value != float_value or abs(float_value) == float('inf'):
            return 0.0

        # 限制数值范围
        return max(min(float_value, max_value), min_value)

    except (ValueError, TypeError):
        return 0.0

def sanitize_indicators(indicators: Dict) -> Dict:
    """确保所有指标值都在合理范围内
    
    Args:
        indicators: 指标字典
        
    Returns:
        dict: 处理后的指标字典
    """
    try:
        # 处理简单数值
        for key in ['RSI', 'BIAS', 'PSY', 'VWAP', 'ExchangeNetflow', 'NUPL', 'MayerMultiple', 'FundingRate']:
            if key in indicators:
                indicators[key] = sanitize_float(indicators[key])

        # 处理MACD
        if 'MACD' in indicators:
            macd = indicators['MACD']
            macd['line'] = sanitize_float(macd.get('line'), -10000.0, 10000.0)
            macd['signal'] = sanitize_float(macd.get('signal'), -10000.0, 10000.0)
            macd['histogram'] = sanitize_float(macd.get('histogram'), -10000.0, 10000.0)

        # 处理布林带
        if 'BollingerBands' in indicators:
            bb = indicators['BollingerBands']
            bb['upper'] = sanitize_float(bb.get('upper'), 0.0, 1000000.0)
            bb['middle'] = sanitize_float(bb.get('middle'), 0.0, 1000000.0)
            bb['lower'] = sanitize_float(bb.get('lower'), 0.0, 1000000.0)

        # 处理DMI
        if 'DMI' in indicators:
            dmi = indicators['DMI']
            dmi['plus_di'] = sanitize_float(dmi.get('plus_di'), 0.0, 100.0)
            dmi['minus_di'] = sanitize_float(dmi.get('minus_di'), 0.0, 100.0)
            dmi['adx'] = sanitize_float(dmi.get('adx'), 0.0, 100.0)

        return indicators

    except Exception as e:
        logger.error(f"处理指标数据时出错: {str(e)}")
        return {}

def format_timestamp(timestamp: datetime) -> str:
    """格式化时间戳为ISO格式
    
    Args:
        timestamp: 时间戳
        
    Returns:
        str: ISO格式的时间字符串
    """
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.isoformat()

def parse_timestamp(timestamp_str: str) -> datetime:
    """解析ISO格式的时间字符串
    
    Args:
        timestamp_str: ISO格式的时间字符串
        
    Returns:
        datetime: 时间戳对象
    """
    return datetime.fromisoformat(timestamp_str)

def safe_json_loads(json_str: str) -> Dict:
    """安全地解析JSON字符串

    Args:
        json_str: JSON字符串

    Returns:
        dict: 解析后的字典，如果解析失败则返回空字典
    """
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        logger.error(f"JSON解析失败: {json_str}")
        return {}


# Database utilities for robust connection handling
import time
from functools import wraps
from django.db import connection, transaction
from django.db.utils import OperationalError, InterfaceError


def robust_db_operation(max_retries=3, retry_delay=1.0, exponential_backoff=True):
    """
    Decorator for robust database operations with automatic retry and connection management

    Args:
        max_retries: Maximum number of retry attempts
        retry_delay: Initial delay between retries (seconds)
        exponential_backoff: Whether to use exponential backoff for retry delays
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    # Ensure connection is healthy before operation
                    ensure_connection_health()

                    # Execute the function
                    return func(*args, **kwargs)

                except (OperationalError, InterfaceError) as e:
                    last_exception = e
                    logger.warning(f"Database operation failed on attempt {attempt + 1}/{max_retries + 1}: {e}")

                    if attempt < max_retries:
                        # Close problematic connection
                        try:
                            connection.close()
                        except:
                            pass

                        # Calculate retry delay
                        if exponential_backoff:
                            delay = retry_delay * (2 ** attempt)
                        else:
                            delay = retry_delay

                        logger.info(f"Retrying in {delay} seconds...")
                        time.sleep(delay)
                        continue
                    else:
                        logger.error(f"Database operation failed after {max_retries + 1} attempts")
                        raise

                except Exception as e:
                    # Non-database errors should not be retried
                    logger.error(f"Non-database error in operation: {e}")
                    raise

            # This should never be reached, but just in case
            if last_exception:
                raise last_exception

        return wrapper
    return decorator


def ensure_connection_health():
    """
    Ensure database connection is healthy, reconnect if necessary
    """
    try:
        # Test connection with a simple query
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return True

    except (OperationalError, InterfaceError):
        logger.warning("Database connection unhealthy, attempting to reconnect")

        try:
            # Close existing connection
            connection.close()

            # Force new connection
            connection.ensure_connection()

            # Test new connection
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()

            logger.info("Database connection restored")
            return True

        except Exception as e:
            logger.error(f"Failed to restore database connection: {e}")
            raise


# Convenience decorators for common use cases
def safe_model_operation(func):
    """Decorator for Django model operations"""
    return robust_db_operation(max_retries=3, retry_delay=1.0)(func)


def safe_bulk_operation(func):
    """Decorator for bulk database operations"""
    return robust_db_operation(max_retries=2, retry_delay=2.0)(func)


def safe_read_operation(func):
    """Decorator for read-only database operations"""
    return robust_db_operation(max_retries=5, retry_delay=0.5)(func)


# Cache utilities for technical indicators
from django.core.cache import cache
import hashlib


def get_technical_indicators_cache_key(symbol: str, language: str) -> str:
    """
    Generate cache key for technical indicators data

    Args:
        symbol: Trading symbol (e.g., 'BTCUSDT')
        language: Language code (e.g., 'en-US')

    Returns:
        str: Cache key
    """
    key_data = f"technical_indicators:{symbol.upper()}:{language}"
    return hashlib.md5(key_data.encode()).hexdigest()


def get_cached_technical_indicators(symbol: str, language: str):
    """
    Get cached technical indicators data

    Args:
        symbol: Trading symbol
        language: Language code

    Returns:
        dict or None: Cached data or None if not found
    """
    cache_key = get_technical_indicators_cache_key(symbol, language)
    return cache.get(cache_key)


def set_cached_technical_indicators(symbol: str, language: str, data: dict, timeout: int = 3600):
    """
    Set cached technical indicators data

    Args:
        symbol: Trading symbol
        language: Language code
        data: Data to cache
        timeout: Cache timeout in seconds (default: 1 hour)
    """
    cache_key = get_technical_indicators_cache_key(symbol, language)
    cache.set(cache_key, data, timeout)
    logger.info(f"Cached technical indicators for {symbol} ({language}) with key: {cache_key}")


def invalidate_technical_indicators_cache(symbol: str, language: str = None):
    """
    Invalidate cached technical indicators data

    Args:
        symbol: Trading symbol
        language: Language code (if None, invalidate all languages)
    """
    if language:
        # Invalidate specific language
        cache_key = get_technical_indicators_cache_key(symbol, language)
        cache.delete(cache_key)
        logger.info(f"Invalidated technical indicators cache for {symbol} ({language})")
    else:
        # Invalidate all languages for this symbol
        languages = ['zh-CN', 'en-US', 'ja-JP', 'ko-KR']
        for lang in languages:
            cache_key = get_technical_indicators_cache_key(symbol, lang)
            cache.delete(cache_key)
        logger.info(f"Invalidated all technical indicators cache for {symbol}")


def get_cache_stats():
    """
    Get cache statistics for monitoring

    Returns:
        dict: Cache statistics
    """
    try:
        # This is a simple implementation for LocMemCache
        # For Redis or Memcached, you might want to use different methods
        return {
            'backend': 'locmem',
            'status': 'active'
        }
    except Exception as e:
        logger.error(f"Error getting cache stats: {e}")
        return {
            'backend': 'unknown',
            'status': 'error',
            'error': str(e)
        }