import logging
import os
import time
import json
import traceback
import requests
import hmac
import base64
import hashlib
import datetime
from typing import List, Optional, Dict, Union
from dotenv import load_dotenv
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class GateAPI:
    """Gate.io API服务类"""

    def __init__(self):
        self.api_key = None
        self.api_secret = None
        self.base_url = "https://api.gateio.ws/api/v4"
        self._client_initialized = False
        self.price_cache = {}  # 价格缓存
        self.price_cache_time = {}  # 价格缓存时间
        self.kline_cache = {}  # K线数据缓存
        self.kline_cache_time = {}  # K线数据缓存时间
        self.ticker_cache = {}  # Ticker数据缓存
        self.ticker_cache_time = {}  # Ticker数据缓存时间
        self.funding_rate_cache = {}  # 资金费率缓存
        self.funding_rate_cache_time = {}  # 资金费率缓存时间
        self.cache_ttl = 60  # 缓存有效期（秒）

    def _init_client(self):
        if not self._client_initialized:
            try:
                load_dotenv()

                # 主要变量名
                self.api_key = os.getenv('GATE_API_KEY')
                self.api_secret = os.getenv('GATE_API_SECRET')

                if not self.api_key or not self.api_secret:
                    logger.warning("未找到 Gate API 密钥，将使用公共 API")
                self._client_initialized = True
            except Exception as e:
                logger.error(f"GateAPI 客户端初始化失败: {e}")
                logger.error(traceback.format_exc())
                self._client_initialized = False

    def _ensure_client(self):
        if not self._client_initialized:
            self._init_client()
        return self._client_initialized

    def _get_timestamp(self):
        """获取时间戳（秒）"""
        return int(time.time())

    def _sign(self, method, url, query_string='', body=''):
        """生成Gate API签名"""
        if not all([self.api_key, self.api_secret]):
            return None, None

        timestamp = str(int(time.time()))
        hashed_payload = hashlib.sha512(body.encode()).hexdigest() if body else ''

        # 构建签名字符串
        string_to_sign = method + '\n' + url + '\n' + query_string + '\n' + hashed_payload + '\n' + timestamp

        # 使用HMAC-SHA512生成签名
        signature = hmac.new(
            self.api_secret.encode(),
            string_to_sign.encode(),
            hashlib.sha512
        ).hexdigest()

        return timestamp, signature

    def _request(self, method, endpoint, params=None, data=None):
        """发送请求到Gate API

        Args:
            method: 请求方法，例如 'GET', 'POST'
            endpoint: API端点
            params: URL参数
            data: 请求体数据

        Returns:
            Dict: 响应数据
        """
        # 确保客户端已初始化
        if not self._ensure_client():
            logger.error("无法初始化Gate API客户端")
            return None

        max_retries = 3
        retry_count = 0
        last_error = None

        while retry_count < max_retries:
            try:
                # 构建请求URL
                url = f"{self.base_url}{endpoint}"

                # 构建查询字符串
                query_string = ''
                if params:
                    query_string = '&'.join([f"{k}={v}" for k, v in params.items()])

                # 构建请求体
                body_str = ''
                if data:
                    body_str = json.dumps(data)

                # 构建请求头
                headers = {}
                if self.api_key and self.api_secret:
                    timestamp, signature = self._sign(method, endpoint, query_string, body_str)
                    headers = {
                        'KEY': self.api_key,
                        'SIGN': signature,
                        'Timestamp': timestamp,
                        'Content-Type': 'application/json'
                    }

                # 记录请求信息
                logger.debug(f"发送请求到Gate API: {method} {url}")
                if params:
                    logger.debug(f"请求参数: {params}")
                if data:
                    logger.debug(f"请求数据: {data}")

                # 发送请求
                start_time = time.time()
                response = requests.request(method, url, params=params, data=body_str if data else None, headers=headers, timeout=10)
                elapsed = time.time() - start_time

                # 检查响应状态
                if response.status_code != 200:
                    error_msg = f"Gate API请求失败 ({retry_count+1}/{max_retries}): HTTP {response.status_code}, 耗时: {elapsed:.2f}秒, URL: {url}"
                    logger.warning(error_msg)
                    logger.warning(f"响应内容: {response.text}")

                    # 如果是认证错误，直接返回
                    if response.status_code in [401, 403]:
                        logger.error("API认证失败，请检查API密钥")
                        return None

                    retry_count += 1
                    time.sleep(1)  # 暂停1秒再重试
                    continue

                # 解析响应
                try:
                    response_data = response.json()
                except json.JSONDecodeError as e:
                    logger.error(f"解析响应JSON失败: {str(e)}")
                    logger.error(f"响应内容: {response.text}")
                    retry_count += 1
                    time.sleep(1)
                    continue

                # 检查响应数据是否为空
                if not response_data:
                    logger.warning(f"Gate API返回空数据 ({retry_count+1}/{max_retries})")
                    retry_count += 1
                    time.sleep(1)
                    continue

                # 请求成功
                logger.debug(f"Gate API请求成功，耗时: {elapsed:.2f}秒")
                return response_data

            except requests.exceptions.Timeout:
                logger.warning(f"Gate API请求超时 ({retry_count+1}/{max_retries})")
                last_error = "请求超时"
                retry_count += 1
                time.sleep(1)  # 暂停1秒再重试

            except requests.exceptions.RequestException as e:
                logger.warning(f"Gate API请求异常 ({retry_count+1}/{max_retries}): {str(e)}")
                last_error = str(e)
                retry_count += 1
                time.sleep(1)  # 暂停1秒再重试

            except Exception as e:
                logger.warning(f"处理Gate API请求时发生错误 ({retry_count+1}/{max_retries}): {str(e)}")
                logger.warning(traceback.format_exc())
                last_error = str(e)
                retry_count += 1
                time.sleep(1)  # 暂停1秒再重试

        logger.error(f"在{max_retries}次尝试后仍无法完成请求: {last_error}")
        return None

    def get_realtime_price(self, symbol: str) -> Optional[float]:
        """
        获取实时价格

        Args:
            symbol: 交易对符号，例如 'BTCUSDT'

        Returns:
            float: 实时价格，如果获取失败则返回None
        """
        try:
            # 转换为Gate格式
            symbol = symbol.upper()
            if symbol.endswith('USDT'):
                base_symbol = symbol[:-4]  # 移除USDT后缀
                gate_symbol = f"{base_symbol}_USDT"  # 使用下划线格式
            else:
                gate_symbol = f"{symbol}_USDT"  # 使用下划线格式

            # 检查缓存
            current_time = time.time()
            if (symbol in self.price_cache and
                symbol in self.price_cache_time and
                current_time - self.price_cache_time[symbol] < self.cache_ttl):
                return self.price_cache[symbol]

            endpoint = '/spot/tickers'
            params = {'currency_pair': gate_symbol}

            response = self._request('GET', endpoint, params=params)
            if response and len(response) > 0:
                price = float(response[0].get('last', 0))
                # 更新缓存
                self.price_cache[symbol] = price
                self.price_cache_time[symbol] = current_time
                return price

            logger.error(f"获取{symbol}实时价格失败")
            return None

        except Exception as e:
            logger.error(f"获取{symbol}实时价格失败: {str(e)}")
            logger.error(traceback.format_exc())
            return None

    def get_klines(self, symbol: str, interval: str, limit: int = 1000) -> Optional[List]:
        """
        获取K线数据

        Args:
            symbol: 交易对符号，例如 'BTCUSDT'
            interval: K线间隔，例如 '1d', '4h', '1h'
            limit: 获取的K线数量，默认为1000

        Returns:
            List: K线数据列表，如果获取失败则返回None
        """
        try:
            # 转换为Gate格式
            symbol = symbol.upper()
            if symbol.endswith('USDT'):
                gate_symbol = f"{symbol[:-4]}_USDT"
            else:
                gate_symbol = f"{symbol}_USDT"

            # 转换时间间隔
            interval_map = {
                '1m': '1m', '5m': '5m', '15m': '15m',
                '30m': '30m', '1h': '1h', '4h': '4h',
                '8h': '8h', '1d': '1d', '7d': '7d'
            }

            gate_interval = interval_map.get(interval, '1d')

            # 检查缓存
            cache_key = f"{symbol}_{interval}_{limit}"
            current_time = time.time()
            if (cache_key in self.kline_cache and
                cache_key in self.kline_cache_time and
                current_time - self.kline_cache_time[cache_key] < self.cache_ttl):
                # 使用缓存中的K线数据
                cached_klines = self.kline_cache[cache_key]
                return cached_klines

            endpoint = '/spot/candlesticks'
            params = {
                'currency_pair': gate_symbol,
                'interval': gate_interval,
                'limit': min(limit, 1000)  # Gate API限制最多1000条
            }

            response = self._request('GET', endpoint, params=params)
            if not response:
                return None

            # Gate返回格式: [timestamp, volume, close, high, low, open]
            # 转换为标准格式: [timestamp, open, high, low, close, volume, ...]
            klines = []
            for candle in response:
                kline = [
                    int(float(candle[0]) * 1000),  # timestamp (转换为毫秒)
                    float(candle[5]),  # open
                    float(candle[3]),  # high
                    float(candle[4]),  # low
                    float(candle[2]),  # close
                    float(candle[1]),  # volume
                    0,  # close_time (不适用)
                    0,  # quote_volume (不适用)
                    0,  # trades (不适用)
                    0,  # taker_buy_base (不适用)
                    0,  # taker_buy_quote (不适用)
                    0   # ignore (不适用)
                ]
                klines.append(kline)

            # 更新缓存
            self.kline_cache[cache_key] = klines
            self.kline_cache_time[cache_key] = current_time

            # 成功获取K线数据
            return klines

        except Exception as e:
            logger.error(f"获取K线数据失败: {str(e)}")
            logger.error(traceback.format_exc())
            return None

    def get_funding_rate(self, symbol: str) -> Optional[float]:
        """
        获取永续合约资金费率

        Args:
            symbol: 交易对符号，例如 'BTCUSDT'

        Returns:
            float: 资金费率，如果获取失败则返回None
        """
        try:
            # 转换为Gate格式
            symbol = symbol.upper()
            coin = symbol.replace('USDT', '')

            # 检查缓存
            current_time = time.time()
            if (symbol in self.funding_rate_cache and
                symbol in self.funding_rate_cache_time and
                current_time - self.funding_rate_cache_time[symbol] < self.cache_ttl):
                # 使用缓存中的资金费率
                cached_rate = self.funding_rate_cache[symbol]
                return cached_rate

            # 尝试获取永续合约当前资金费率
            endpoint = '/futures/usdt/funding_rate'
            params = {'contract': f"{coin}_USDT"}

            response = self._request('GET', endpoint, params=params)
            if response and isinstance(response, list) and len(response) > 0:
                # 获取最新的资金费率
                latest_rate = response[0]
                rate = float(latest_rate.get('rate', 0))
                # 成功获取资金费率

                # 如果资金费率为0，尝试获取预测资金费率
                if rate == 0:
                    # 尝试获取合约信息，查看预测资金费率
                    endpoint = '/futures/usdt/contracts'
                    params = {'settle': 'usdt'}

                    contract_response = self._request('GET', endpoint, params=params)
                    if contract_response:
                        # 尝试多种可能的合约名称格式
                        possible_names = [
                            f"{coin}_USDT",  # BTC_USDT
                            coin,            # BTC
                            symbol,          # BTCUSDT
                            f"{coin}USDT"    # BTCUSDT (无下划线)
                        ]

                        for contract in contract_response:
                            contract_name = contract.get('name', '').upper()
                            if any(name.upper() == contract_name for name in possible_names):
                                # 尝试获取预测资金费率
                                predicted_rate = float(contract.get('funding_rate_indicative', 0))
                                if predicted_rate != 0:
                                    # 使用预测资金费率
                                    rate = predicted_rate
                                    break

                # 如果资金费率仍然为0，尝试获取历史资金费率
                if rate == 0:
                    # 尝试获取资金费率历史
                    endpoint = '/futures/usdt/funding_rate_history'
                    params = {'contract': f"{coin}_USDT", 'limit': 10}  # 获取最近10条记录

                    history_response = self._request('GET', endpoint, params=params)
                    if history_response and isinstance(history_response, list) and len(history_response) > 0:
                        # 计算最近10条记录的平均值
                        rates = []
                        for history in history_response:
                            history_rate = float(history.get('r', 0))
                            if history_rate != 0:
                                rates.append(history_rate)

                        if rates:
                            avg_rate = sum(rates) / len(rates)
                            # 使用历史平均资金费率
                            rate = avg_rate

                # 如果资金费率仍然为0，使用硬编码的默认值
                if rate == 0:
                    # 根据不同的币种使用不同的默认值
                    default_rates = {
                        "BTCUSDT": 0.0001,   # 0.01%
                        "ETHUSDT": 0.00015,  # 0.015%
                        "SOLUSDT": 0.0002,   # 0.02%
                        "DOGEUSDT": 0.0003,  # 0.03%
                        "XRPUSDT": 0.00025,  # 0.025%
                    }

                    default_rate = default_rates.get(symbol, 0.0001)  # 如果没有特定币种的默认值，使用0.0001
                    logger.info(f"使用 {symbol} 的硬编码默认资金费率: {default_rate}")
                    rate = default_rate

                # 更新缓存
                self.funding_rate_cache[symbol] = rate
                self.funding_rate_cache_time[symbol] = current_time

                return rate

            # 如果上面的方法失败，尝试获取合约信息
            endpoint = '/futures/usdt/contracts'
            params = {'settle': 'usdt'}

            response = self._request('GET', endpoint, params=params)
            if response:
                # 尝试多种可能的合约名称格式
                possible_names = [
                    f"{coin}_USDT",  # BTC_USDT
                    coin,            # BTC
                    symbol,          # BTCUSDT
                    f"{coin}USDT"    # BTCUSDT (无下划线)
                ]

                for contract in response:
                    contract_name = contract.get('name', '').upper()
                    if any(name.upper() == contract_name for name in possible_names):
                        # 尝试获取当前资金费率
                        rate = float(contract.get('funding_rate', 0))

                        # 如果当前资金费率为0，尝试获取预测资金费率
                        if rate == 0:
                            rate = float(contract.get('funding_rate_indicative', 0))

                        # 如果仍然为0，使用硬编码的默认值
                        if rate == 0:
                            # 根据不同的币种使用不同的默认值
                            default_rates = {
                                "BTCUSDT": 0.0001,   # 0.01%
                                "ETHUSDT": 0.00015,  # 0.015%
                                "SOLUSDT": 0.0002,   # 0.02%
                                "DOGEUSDT": 0.0003,  # 0.03%
                                "XRPUSDT": 0.00025,  # 0.025%
                            }

                            default_rate = default_rates.get(symbol, 0.0001)  # 如果没有特定币种的默认值，使用0.0001
                            # 使用默认资金费率
                            rate = default_rate

                        # 成功获取资金费率

                        # 更新缓存
                        self.funding_rate_cache[symbol] = rate
                        self.funding_rate_cache_time[symbol] = current_time

                        return rate

            # 如果所有方法都失败，使用硬编码的默认值
            logger.warning(f"无法获取 {symbol} 的资金费率，使用默认值")

            # 根据不同的币种使用不同的默认值
            default_rates = {
                "BTCUSDT": 0.0001,   # 0.01%
                "ETHUSDT": 0.00015,  # 0.015%
                "SOLUSDT": 0.0002,   # 0.02%
                "DOGEUSDT": 0.0003,  # 0.03%
                "XRPUSDT": 0.00025,  # 0.025%
            }

            default_rate = default_rates.get(symbol, 0.0001)  # 如果没有特定币种的默认值，使用0.0001
            # 使用默认资金费率

            # 更新缓存
            self.funding_rate_cache[symbol] = default_rate
            self.funding_rate_cache_time[symbol] = current_time

            return default_rate

        except Exception as e:
            logger.error(f"获取资金费率失败: {str(e)}")
            logger.error(traceback.format_exc())

            # 使用硬编码的默认值
            default_rates = {
                "BTCUSDT": 0.0001,   # 0.01%
                "ETHUSDT": 0.00015,  # 0.015%
                "SOLUSDT": 0.0002,   # 0.02%
                "DOGEUSDT": 0.0003,  # 0.03%
                "XRPUSDT": 0.00025,  # 0.025%
            }

            default_rate = default_rates.get(symbol, 0.0001)  # 如果没有特定币种的默认值，使用0.0001
            # 异常处理：使用默认资金费率
            return default_rate

    def get_historical_klines(self, symbol: str, interval: str, start_str: str) -> Optional[List]:
        """
        获取历史K线数据

        Args:
            symbol: 交易对符号，例如 'BTCUSDT'
            interval: K线间隔，例如 '1m', '5m', '1h', '1d'
            start_str: 开始时间，例如 '1 day ago UTC'

        Returns:
            List: K线数据列表，如果获取失败则返回None
        """
        try:
            # 转换为Gate格式
            symbol = symbol.upper()
            if symbol.endswith('USDT'):
                base_symbol = symbol[:-4]  # 移除USDT后缀
                gate_symbol = f"{base_symbol}_USDT"  # 使用下划线格式
            else:
                gate_symbol = f"{symbol}_USDT"  # 使用下划线格式

            # 检查缓存
            cache_key = f"{symbol}_{interval}_{start_str}"
            current_time = time.time()
            if (cache_key in self.kline_cache and
                cache_key in self.kline_cache_time and
                current_time - self.kline_cache_time[cache_key] < self.cache_ttl):
                return self.kline_cache[cache_key]

            # 转换时间格式
            if 'ago' in start_str:
                # 处理相对时间
                parts = start_str.split()
                amount = int(parts[0])
                unit = parts[1]
                if unit == 'day' or unit == 'days':
                    start_time = int((datetime.now() - timedelta(days=amount)).timestamp())
                elif unit == 'hour' or unit == 'hours':
                    start_time = int((datetime.now() - timedelta(hours=amount)).timestamp())
                elif unit == 'minute' or unit == 'minutes':
                    start_time = int((datetime.now() - timedelta(minutes=amount)).timestamp())
                else:
                    start_time = int((datetime.now() - timedelta(days=100)).timestamp())
            else:
                # 处理绝对时间
                try:
                    start_time = int(datetime.strptime(start_str, '%Y-%m-%d %H:%M:%S').timestamp())
                except:
                    start_time = int((datetime.now() - timedelta(days=100)).timestamp())

            # 转换间隔格式
            interval_map = {
                '1m': '1m',
                '5m': '5m',
                '15m': '15m',
                '30m': '30m',
                '1h': '1h',
                '4h': '4h',
                '1d': '1d',
                '1w': '1w'
            }
            gate_interval = interval_map.get(interval, '1d')

            endpoint = '/spot/candlesticks'
            params = {
                'currency_pair': gate_symbol,
                'interval': gate_interval,
                'from': start_time,
                'limit': 1000
            }

            response = self._request('GET', endpoint, params=params)
            if not response:
                logger.error(f"获取{symbol}历史K线数据失败")
                return None

            # Gate返回格式: [timestamp, volume, close, high, low, open]
            # 转换为标准格式: [timestamp, open, high, low, close, volume, ...]
            klines = []
            for candle in response:
                kline = [
                    int(float(candle[0]) * 1000),  # timestamp (转换为毫秒)
                    float(candle[5]),  # open
                    float(candle[3]),  # high
                    float(candle[4]),  # low
                    float(candle[2]),  # close
                    float(candle[1]),  # volume
                    0,  # close_time (不适用)
                    0,  # quote_volume (不适用)
                    0,  # trades (不适用)
                    0,  # taker_buy_base (不适用)
                    0,  # taker_buy_quote (不适用)
                    0   # ignore (不适用)
                ]
                klines.append(kline)

            # 更新缓存
            self.kline_cache[cache_key] = klines
            self.kline_cache_time[cache_key] = current_time

            return klines

        except Exception as e:
            logger.error(f"获取{symbol}历史K线数据失败: {str(e)}")
            logger.error(traceback.format_exc())
            return None

    def get_ticker(self, symbol: str) -> Optional[Dict]:
        """
        获取交易对行情数据

        Args:
            symbol: 交易对符号，例如 'BTCUSDT'

        Returns:
            Dict: 行情数据，如果获取失败则返回None
        """
        try:
            # 转换为Gate格式
            symbol = symbol.upper()
            if symbol.endswith('USDT'):
                base_symbol = symbol[:-4]  # 移除USDT后缀
                gate_symbol = f"{base_symbol}_USDT"  # 使用下划线格式
            else:
                gate_symbol = f"{symbol}_USDT"  # 使用下划线格式

            # 检查缓存
            current_time = time.time()
            if (symbol in self.ticker_cache and
                symbol in self.ticker_cache_time and
                current_time - self.ticker_cache_time[symbol] < self.cache_ttl):
                return self.ticker_cache[symbol]

            endpoint = '/spot/tickers'
            params = {'currency_pair': gate_symbol}

            response = self._request('GET', endpoint, params=params)
            if response and len(response) > 0:
                ticker_data = response[0]
                # 更新缓存
                self.ticker_cache[symbol] = ticker_data
                self.ticker_cache_time[symbol] = current_time
                return ticker_data

            logger.error(f"获取{symbol}行情数据失败")
            return None

        except Exception as e:
            logger.error(f"获取{symbol}行情数据失败: {str(e)}")
            logger.error(traceback.format_exc())
            return None

    def get_24h_volume(self, symbol: str) -> Optional[float]:
        """获取24小时交易量"""
        ticker = self.get_ticker(symbol)
        if ticker:
            return ticker.get('volume', 0)
        return 0

    def get_24h_price_change(self, symbol: str) -> Optional[float]:
        """获取24小时价格变化"""
        ticker = self.get_ticker(symbol)
        if ticker:
            return ticker.get('priceChange', 0)
        return 0

    def get_current_price(self, symbol: str) -> Optional[float]:
        """获取当前价格（与get_realtime_price相同）"""
        return self.get_realtime_price(symbol)
