import logging
import os
import time
import json
import traceback
import requests
import hmac
import base64
import datetime
from typing import List, Optional, Dict, Union
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

class OKXAPI:
    """OKX API服务类"""
    
    def __init__(self):
        self.api_key = None
        self.api_secret = None
        self.passphrase = None
        self.base_url = "https://www.okx.com"
        self._client_initialized = False
        logger.info("OKXAPI 实例创建，尚未初始化")
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
                
                # 打印环境变量调试信息
                logger.info("正在检查环境变量...")
                logger.info(f"尝试获取 OKX_API_KEY: {'已设置' if os.getenv('OKX_API_KEY') else '未设置'}")
                logger.info(f"尝试获取 OKX_API_SECRET: {'已设置' if os.getenv('OKX_API_SECRET') else '未设置'}")
                logger.info(f"尝试获取 OKX_API_PASSPHRASE: {'已设置' if os.getenv('OKX_API_PASSPHRASE') else '未设置'}")
                logger.info(f"尝试获取 OKEX_API_SECRET: {'已设置' if os.getenv('OKEX_API_SECRET') else '未设置'}")
                logger.info(f"尝试获取 OKX_SECRET: {'已设置' if os.getenv('OKX_SECRET') else '未设置'}")
                
                # 主要变量名
                self.api_key = os.getenv('OKX_API_KEY')
                self.api_secret = os.getenv('OKX_API_SECRET')
                self.passphrase = os.getenv('OKX_API_PASSPHRASE')
                
                # 尝试备选变量名
                if not self.api_key:
                    self.api_key = os.getenv('OKEX_API_KEY') or os.getenv('OKX_KEY')
                if not self.api_secret:
                    self.api_secret = os.getenv('OKEX_API_SECRET') or os.getenv('OKX_SECRET')
                if not self.passphrase:
                    self.passphrase = os.getenv('OKX_PASSPHRASE') or os.getenv('OKEX_PASSPHRASE')
                
                # 直接硬编码API密钥进行测试
                logger.info("正在使用硬编码的API密钥进行测试...")
                if not self.api_key or not self.api_secret or not self.passphrase:
                    self.api_key = "82f54e2a-588b-4bfc-a3f3-138f982996cf"
                    self.api_secret = "C883644CC67C69D4792D30D4FEEDB1AE"
                    # 注意: passphrase应该根据实际值设置
                    if self.passphrase:
                        logger.info("使用环境变量中的passphrase")
                    else:
                        logger.warning("缺少passphrase，API认证可能失败")
                
                if not self.api_key or not self.api_secret or not self.passphrase:
                    logger.warning("未找到 OKX API 密钥，将使用公共 API")
                    logger.info(f"环境变量检查: API_KEY存在: {bool(self.api_key)}, API_SECRET存在: {bool(self.api_secret)}, PASSPHRASE存在: {bool(self.passphrase)}")
                else:
                    logger.info("成功加载 OKX API 密钥")
                self._client_initialized = True
                logger.info("OKXAPI 客户端初始化完成")
            except Exception as e:
                logger.error(f"OKXAPI 客户端初始化失败: {e}")
                logger.error(traceback.format_exc())
                self._client_initialized = False

    def _ensure_client(self):
        if not self._client_initialized:
            self._init_client()
        return self._client_initialized
    
    def _get_timestamp(self):
        """获取ISO格式的时间戳"""
        return datetime.datetime.utcnow().isoformat(timespec='milliseconds') + 'Z'
    
    def _sign(self, timestamp, method, request_path, body=''):
        """生成OKX API签名"""
        if not all([self.api_key, self.api_secret, self.passphrase]):
            return None
            
        if body:
            body = json.dumps(body)
        
        message = timestamp + method + request_path + (body or '')
        mac = hmac.new(
            bytes(self.api_secret, encoding='utf8'),
            bytes(message, encoding='utf-8'),
            digestmod='sha256'
        )
        d = mac.digest()
        return base64.b64encode(d).decode()
    
    def _request(self, method, endpoint, params=None, data=None):
        """发送请求到OKX API
        
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
            logger.error("无法初始化OKX API客户端")
            return None
            
        max_retries = 3
        retry_count = 0
        last_error = None
        
        while retry_count < max_retries:
            try:
                # 构建请求URL
                url = f"{self.base_url}{endpoint}"
                
                # 构建请求头
                headers = {}
                if method != 'GET' or endpoint.startswith('/api/v5/trade'):
                    timestamp = self._get_timestamp()
                    body = ''
                    if data:
                        body = json.dumps(data)
                    sign = self._sign(timestamp, method, endpoint, body)
                    
                    headers = {
                        'OK-ACCESS-KEY': self.api_key,
                        'OK-ACCESS-SIGN': sign,
                        'OK-ACCESS-TIMESTAMP': timestamp,
                        'OK-ACCESS-PASSPHRASE': self.passphrase,
                        'Content-Type': 'application/json'
                    }
                
                logger.debug(f"OKX API 请求: {method} {url} | 参数: {params} | 数据: {data}")
                
                # 发送请求
                start_time = time.time()
                response = requests.request(method, url, params=params, data=json.dumps(data) if data else None, headers=headers, timeout=10)
                elapsed = time.time() - start_time
                
                # 检查响应状态
                if response.status_code != 200:
                    logger.warning(f"OKX API请求失败 ({retry_count+1}/{max_retries}): HTTP {response.status_code}, 耗时: {elapsed:.2f}秒, URL: {url}")
                    logger.warning(f"响应内容: {response.text}")
                    retry_count += 1
                    time.sleep(1)  # 暂停1秒再重试
                    continue
                
                # 解析响应
                response_data = response.json()
                
                # 检查API响应码
                if response_data.get('code') != '0':
                    logger.warning(f"OKX API返回错误 ({retry_count+1}/{max_retries}): {response_data.get('msg', '未知错误')}, 代码: {response_data.get('code')}")
                    retry_count += 1
                    time.sleep(1)  # 暂停1秒再重试
                    continue
                
                logger.debug(f"OKX API响应成功: 耗时: {elapsed:.2f}秒, 数据大小: {len(response.text)}")
                return response_data.get('data', [])
                
            except requests.exceptions.Timeout:
                logger.warning(f"OKX API请求超时 ({retry_count+1}/{max_retries})")
                last_error = "请求超时"
                retry_count += 1
                time.sleep(1)  # 暂停1秒再重试
                
            except requests.exceptions.RequestException as e:
                logger.warning(f"OKX API请求异常 ({retry_count+1}/{max_retries}): {str(e)}")
                last_error = str(e)
                retry_count += 1
                time.sleep(1)  # 暂停1秒再重试
                
            except Exception as e:
                logger.warning(f"处理OKX API请求时发生错误 ({retry_count+1}/{max_retries}): {str(e)}")
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
            # 转换币安格式为OKX格式
            symbol = symbol.upper()
            if symbol.endswith('USDT'):
                okx_symbol = f"{symbol[:-4]}-USDT"
            else:
                okx_symbol = f"{symbol}-USDT"
                
            # 检查缓存
            current_time = time.time()
            if (symbol in self.price_cache and 
                symbol in self.price_cache_time and 
                current_time - self.price_cache_time[symbol] < self.cache_ttl):
                # 使用缓存中的价格
                cached_price = self.price_cache[symbol]
                logger.info(f"使用缓存获取{symbol}价格: {cached_price}")
                return cached_price
            
            endpoint = '/api/v5/market/ticker'
            params = {'instId': okx_symbol}
            
            response = self._request('GET', endpoint, params=params)
            if response and len(response) > 0:
                price = float(response[0]['last'])
                logger.info(f"成功获取{symbol}价格: {price}")
                
                # 更新缓存
                self.price_cache[symbol] = price
                self.price_cache_time[symbol] = current_time
                
                return price
            
            logger.error(f"获取{symbol}价格失败")
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
            # 转换币安格式为OKX格式
            symbol = symbol.upper()
            if symbol.endswith('USDT'):
                okx_symbol = f"{symbol[:-4]}-USDT"
            else:
                okx_symbol = f"{symbol}-USDT"
            
            # 转换时间间隔
            interval_map = {
                '1m': '1m', '3m': '3m', '5m': '5m', '15m': '15m',
                '30m': '30m', '1h': '1H', '2h': '2H', '4h': '4H',
                '6h': '6H', '12h': '12H', '1d': '1D', '1w': '1W'
            }
            
            okx_interval = interval_map.get(interval, '1D')
            
            # 检查缓存
            cache_key = f"{symbol}_{interval}_{limit}"
            current_time = time.time()
            if (cache_key in self.kline_cache and 
                cache_key in self.kline_cache_time and 
                current_time - self.kline_cache_time[cache_key] < self.cache_ttl):
                # 使用缓存中的K线数据
                cached_klines = self.kline_cache[cache_key]
                logger.info(f"使用缓存获取{symbol}的K线数据，数量: {len(cached_klines)}")
                return cached_klines
            
            endpoint = '/api/v5/market/candles'
            params = {
                'instId': okx_symbol,
                'bar': okx_interval,
                'limit': limit
            }
            
            response = self._request('GET', endpoint, params=params)
            if not response:
                return None
                
            # OKX返回格式: [timestamp, open, high, low, close, volume, ...]
            # 转换为Binance格式: [timestamp, open, high, low, close, volume, ...]
            klines = []
            for candle in response:
                kline = [
                    int(candle[0]),  # timestamp
                    float(candle[1]),  # open
                    float(candle[2]),  # high
                    float(candle[3]),  # low
                    float(candle[4]),  # close
                    float(candle[5]),  # volume
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
            
            logger.info(f"使用常规K线接口获取了 {len(klines)} 条K线数据")
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
            # 转换币安格式为OKX格式
            symbol = symbol.upper()
            if symbol.endswith('USDT'):
                okx_symbol = f"{symbol[:-4]}-USDT-SWAP"
            else:
                okx_symbol = f"{symbol}-USDT-SWAP"
            
            # 检查缓存
            current_time = time.time()
            if (symbol in self.funding_rate_cache and 
                symbol in self.funding_rate_cache_time and 
                current_time - self.funding_rate_cache_time[symbol] < self.cache_ttl):
                # 使用缓存中的资金费率
                cached_rate = self.funding_rate_cache[symbol]
                logger.info(f"使用缓存获取 {symbol} 的资金费率: {cached_rate}")
                return cached_rate
            
            endpoint = '/api/v5/public/funding-rate'
            params = {'instId': okx_symbol}
            
            response = self._request('GET', endpoint, params=params)
            if response and len(response) > 0:
                rate = float(response[0]['fundingRate'])
                logger.info(f"成功获取 {symbol} 的资金费率: {rate}")
                
                # 更新缓存
                self.funding_rate_cache[symbol] = rate
                self.funding_rate_cache_time[symbol] = current_time
                
                return rate
            
            logger.error(f"获取{symbol}资金费率失败")
            return None
            
        except Exception as e:
            logger.error(f"获取资金费率失败: {str(e)}")
            logger.error(traceback.format_exc())
            return None
    
    def get_historical_klines(self, symbol: str, interval: str, start_str: str) -> Optional[List]:
        """
        获取历史K线数据
        
        Args:
            symbol: 交易对符号，例如 'BTCUSDT'
            interval: K线间隔，例如 '1d', '4h', '1h'
            start_str: 开始时间，例如 '1 day ago UTC', '1 Jan 2020'
            
        Returns:
            List: K线数据列表，如果获取失败则返回None
        """
        try:
            # 转换币安格式为OKX格式
            symbol = symbol.upper()
            if symbol.endswith('USDT'):
                okx_symbol = f"{symbol[:-4]}-USDT"
            else:
                okx_symbol = f"{symbol}-USDT"
            
            # 检查缓存 (仅对短周期的历史数据使用缓存，例如"1 day ago UTC")
            if "day ago" in start_str and int(start_str.split()[0]) <= 7:
                cache_key = f"{symbol}_{interval}_{start_str}"
                current_time = time.time()
                if (cache_key in self.kline_cache and 
                    cache_key in self.kline_cache_time and 
                    current_time - self.kline_cache_time[cache_key] < self.cache_ttl):
                    # 使用缓存中的K线数据
                    cached_klines = self.kline_cache[cache_key]
                    logger.info(f"使用缓存获取{symbol}的历史K线数据，数量: {len(cached_klines)}")
                    return cached_klines
            
            # 处理时间字符串
            if 'days ago' in start_str:
                days = int(start_str.split(' ')[0])
                start_time = int((datetime.datetime.now() - datetime.timedelta(days=days)).timestamp() * 1000)
            else:
                # 其他格式的时间处理...
                start_time = int(time.time() - 86400000)  # 默认获取过去1000天的数据
            
            logger.info(f"获取历史K线数据: 原始符号={symbol}, OKX符号={okx_symbol}, 时间间隔={interval}, 开始时间={start_str}")
            
            # 转换时间间隔
            interval_map = {
                '1m': '1m', '3m': '3m', '5m': '5m', '15m': '15m',
                '30m': '30m', '1h': '1H', '2h': '2H', '4h': '4H',
                '6h': '6H', '12h': '12H', '1d': '1D', '1w': '1W'
            }
            
            okx_interval = interval_map.get(interval, '1D')
            
            # OKX要求时间戳为ISO格式，但after参数可以使用Unix时间戳
            endpoint = '/api/v5/market/history-candles'
            params = {
                'instId': okx_symbol,
                'bar': okx_interval,
                'after': start_time,
                'limit': 300  # OKX API每次最多返回300条K线
            }
            
            all_klines = []
            last_id = None
            
            # 先尝试获取最新的K线数据
            # 如果历史数据接口失败，可以尝试使用常规K线接口
            if not all_klines:
                logger.info(f"尝试使用常规K线接口获取数据: {okx_symbol}")
                recent_endpoint = '/api/v5/market/candles'
                recent_params = {
                    'instId': okx_symbol,
                    'bar': okx_interval,
                    'limit': 100  # 获取最近100条K线
                }
                
                response = self._request('GET', recent_endpoint, params=recent_params)
                if response and len(response) > 0:
                    # 转换格式保持一致
                    for candle in response:
                        kline = [
                            int(candle[0]),  # timestamp
                            float(candle[1]),  # open
                            float(candle[2]),  # high
                            float(candle[3]),  # low
                            float(candle[4]),  # close
                            float(candle[5]),  # volume
                            0,  # close_time (不适用)
                            0,  # quote_volume (不适用)
                            0,  # trades (不适用)
                            0,  # taker_buy_base (不适用)
                            0,  # taker_buy_quote (不适用)
                            0   # ignore (不适用)
                        ]
                        all_klines.append(kline)
                    
                    logger.info(f"使用常规K线接口获取了 {len(all_klines)} 条K线数据")
                    return all_klines  # 如果能获取到，直接返回
            
            # 循环获取所有历史K线
            max_pages = 10  # 最多获取10页数据，避免过多请求
            page = 0
            
            while page < max_pages:
                if last_id:
                    params['after'] = last_id
                
                response = self._request('GET', endpoint, params=params)
                if not response or len(response) == 0:
                    break
                
                page_count = len(response)
                logger.info(f"历史K线页 {page+1}: 获取到 {page_count} 条记录")
                
                # OKX返回格式: [timestamp, open, high, low, close, volume, ...]
                # 转换为Binance格式: [timestamp, open, high, low, close, volume, ...]
                for candle in response:
                    try:
                        kline = [
                            int(candle[0]),  # timestamp
                            float(candle[1]),  # open
                            float(candle[2]),  # high
                            float(candle[3]),  # low
                            float(candle[4]),  # close
                            float(candle[5]),  # volume
                            0,  # close_time (不适用)
                            0,  # quote_volume (不适用)
                            0,  # trades (不适用)
                            0,  # taker_buy_base (不适用)
                            0,  # taker_buy_quote (不适用)
                            0   # ignore (不适用)
                        ]
                        all_klines.append(kline)
                    except (IndexError, ValueError) as e:
                        logger.warning(f"解析K线数据错误: {str(e)}, 原始数据: {candle}")
                        continue  # 跳过错误数据，继续处理下一条
                
                # 保存最后一条K线的时间戳用于下一次请求
                if len(response) < 300:
                    break
                
                last_id = response[-1][0]
                page += 1
                
                # 防止请求过于频繁
                time.sleep(0.5)
            
            total_klines = len(all_klines)
            logger.info(f"总共获取到 {total_klines} 条历史K线数据")
            
            if total_klines == 0:
                logger.warning(f"未能获取到任何K线数据")
                return None
                
            # 更新缓存
            self.kline_cache[cache_key] = all_klines
            self.kline_cache_time[cache_key] = time.time()
            
            return all_klines
            
        except Exception as e:
            logger.error(f"获取历史K线数据失败: {str(e)}")
            logger.error(traceback.format_exc())
            return None
    
    def get_ticker(self, symbol: str) -> Optional[Dict]:
        """
        获取24小时交易数据
        
        Args:
            symbol: 交易对符号，例如 'BTCUSDT'
            
        Returns:
            Dict: 24小时交易数据，如果获取失败则返回None
        """
        try:
            # 转换币安格式为OKX格式
            symbol = symbol.upper()
            if symbol.endswith('USDT'):
                okx_symbol = f"{symbol[:-4]}-USDT"
            else:
                okx_symbol = f"{symbol}-USDT"
            
            # 检查缓存
            current_time = time.time()
            if (symbol in self.ticker_cache and 
                symbol in self.ticker_cache_time and 
                current_time - self.ticker_cache_time[symbol] < self.cache_ttl):
                # 使用缓存中的ticker数据
                cached_ticker = self.ticker_cache[symbol]
                logger.info(f"使用缓存获取{symbol}的ticker数据")
                return cached_ticker
            
            # 获取实时行情数据，OKX API不提供单独的24小时统计接口
            endpoint = '/api/v5/market/ticker'
            params = {'instId': okx_symbol}
            
            response = self._request('GET', endpoint, params=params)
            if response and len(response) > 0:
                ticker_data = response[0]
                
                # OKX API不提供类似ticker-24h的接口，我们使用candles接口获取24小时的高低点
                endpoint_candles = '/api/v5/market/candles'
                candle_params = {
                    'instId': okx_symbol,
                    'bar': '1D',
                    'limit': 1
                }
                
                candle_response = self._request('GET', endpoint_candles, params=candle_params)
                
                # 构建与Binance兼容的ticker结构
                ticker = {
                    'symbol': symbol,
                    'lastPrice': ticker_data['last'],
                    'volume': ticker_data.get('vol24h', '0'),
                    'priceChangePercent': ticker_data.get('volCcy24h', '0'),
                }
                
                if candle_response and len(candle_response) > 0:
                    candle = candle_response[0]
                    open_price = float(candle[1])
                    close_price = float(candle[4])
                    price_change = close_price - open_price
                    
                    if open_price > 0:
                        price_change_percent = (price_change / open_price) * 100
                    else:
                        price_change_percent = 0
                    
                    ticker.update({
                        'priceChange': str(price_change),
                        'priceChangePercent': str(price_change_percent),
                        'highPrice': candle[2],  # 高点
                        'lowPrice': candle[3],   # 低点
                    })
                
                # 估算买入和卖出量 (OKX不提供这些数据，模拟计算)
                volume = float(ticker.get('volume', '0'))
                price_change_percent = float(ticker.get('priceChangePercent', '0'))
                
                # 如果价格上涨，假设买入量更多，反之亦然
                if price_change_percent > 0:
                    buy_ratio = 0.5 + min(abs(price_change_percent) / 200, 0.3)  # 最高80%买入
                else:
                    buy_ratio = 0.5 - min(abs(price_change_percent) / 200, 0.3)  # 最低20%买入
                
                buy_volume = volume * buy_ratio
                sell_volume = volume - buy_volume
                
                ticker['buyVolume'] = str(buy_volume)
                ticker['sellVolume'] = str(sell_volume)
                
                # 更新缓存
                self.ticker_cache[symbol] = ticker
                self.ticker_cache_time[symbol] = current_time
                
                return ticker
            
            logger.error(f"获取{symbol}交易数据失败")
            return None
            
        except Exception as e:
            logger.error(f"获取24小时交易数据失败: {str(e)}")
            logger.error(traceback.format_exc())
            return None
    
    def get_current_price(self, symbol: str) -> Optional[float]:
        """
        获取当前价格
        
        Args:
            symbol: 交易对符号，例如 'BTCUSDT'
            
        Returns:
            float: 当前价格，如果获取失败则返回None
        """
        return self.get_realtime_price(symbol)
    
    def get_24h_volume(self, symbol: str) -> Optional[float]:
        """
        获取24小时交易量
        
        Args:
            symbol: 交易对符号，例如 'BTCUSDT'
            
        Returns:
            float: 24小时交易量，如果获取失败则返回None
        """
        ticker = self.get_ticker(symbol)
        if ticker and 'volume' in ticker:
            return float(ticker['volume'])
        return None
    
    def get_24h_price_change(self, symbol: str) -> Optional[float]:
        """
        获取24小时价格变化
        
        Args:
            symbol: 交易对符号，例如 'BTCUSDT'
            
        Returns:
            float: 24小时价格变化，如果获取失败则返回None
        """
        ticker = self.get_ticker(symbol)
        if ticker and 'priceChange' in ticker:
            return float(ticker['priceChange'])
        return None 