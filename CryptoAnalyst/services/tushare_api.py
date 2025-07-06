import logging
import os
import time
import json
import traceback
import requests
import pandas as pd
from typing import List, Optional, Dict, Union
from datetime import datetime, timedelta
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

class TushareAPI:
    """Tushare API服务类，用于获取A股数据"""

    def __init__(self):
        # 确保加载环境变量
        load_dotenv()

        self.token = None
        self.base_url = "http://api.tushare.pro"
        self._client_initialized = False
        self.price_cache = {}  # 价格缓存
        self.price_cache_time = {}  # 价格缓存时间
        self.kline_cache = {}  # K线数据缓存
        self.kline_cache_time = {}  # K线数据缓存时间
        self.basic_cache = {}  # 基本信息缓存
        self.basic_cache_time = {}  # 基本信息缓存时间
        self.cache_ttl = 300  # 缓存有效期（秒），A股数据更新较慢，可以缓存更久

    def _init_client(self):
        """初始化Tushare客户端"""
        if not self._client_initialized:
            try:
                # 确保加载环境变量并获取API密钥
                load_dotenv()
                self.token = os.getenv('TUSHARE_API_KEY')

                if not self.token:
                    print("未找到 Tushare API 密钥，请设置 TUSHARE_API_KEY 环境变量")
                    return False

                # 测试API连接（简化测试，避免递归调用）
                try:
                    response = requests.post(
                        self.base_url,
                        json={
                            'api_name': 'stock_basic',
                            'token': self.token,
                            'params': {},
                            'fields': 'ts_code,symbol,name'
                        },
                        timeout=10
                    )

                    if response.status_code == 200:
                        result = response.json()
                        if result.get('code') == 0:
                            print("Tushare API 连接成功")
                            self._client_initialized = True
                            return True
                        else:
                            print(f"Tushare API 错误: {result.get('msg', 'Unknown error')}")
                            return False
                    else:
                        print(f"HTTP 错误: {response.status_code}")
                        return False

                except requests.RequestException as e:
                    print(f"网络请求失败: {str(e)}")
                    return False

            except Exception as e:
                print(f"TushareAPI 客户端初始化失败: {e}")
                self._client_initialized = False
                return False
        return True

    def _ensure_client(self):
        """确保客户端已初始化"""
        if not self._client_initialized:
            return self._init_client()
        return True

    def _request(self, api_name: str, **params) -> Optional[pd.DataFrame]:
        """发送API请求"""
        try:
            # 确保有token，但不调用_ensure_client避免递归
            if not self.token:
                self.token = os.getenv('TUSHARE_API_KEY')
                if not self.token:
                    print("未找到 Tushare API 密钥")
                    return None

            # 构建请求数据
            req_params = {
                'api_name': api_name,
                'token': self.token,
                'params': params,
                'fields': params.get('fields', '')
            }

            response = requests.post(self.base_url, json=req_params, timeout=30)

            if response.status_code == 200:
                result = response.json()
                if result['code'] == 0:
                    data = result['data']
                    if data and 'items' in data:
                        # 转换为DataFrame
                        df = pd.DataFrame(data['items'], columns=data['fields'])
                        return df
                    return pd.DataFrame()
                else:
                    print(f"Tushare API 错误: {result.get('msg', 'Unknown error')}")
                    return None
            else:
                print(f"HTTP 错误: {response.status_code}")
                return None

        except Exception as e:
            print(f"Tushare API 请求失败: {str(e)}")
            return None

    def get_stock_basic(self, exchange: str = None) -> Optional[pd.DataFrame]:
        """获取股票基本信息
        
        Args:
            exchange: 交易所代码 SSE上交所 SZSE深交所
            
        Returns:
            DataFrame: 股票基本信息
        """
        try:
            cache_key = f"stock_basic_{exchange or 'all'}"
            current_time = time.time()
            
            # 检查缓存
            if (cache_key in self.basic_cache and 
                cache_key in self.basic_cache_time and
                current_time - self.basic_cache_time[cache_key] < self.cache_ttl):
                return self.basic_cache[cache_key]

            params = {
                'fields': 'ts_code,symbol,name,area,industry,market,list_date'
            }
            if exchange:
                params['exchange'] = exchange

            df = self._request('stock_basic', **params)
            
            if df is not None:
                # 更新缓存
                self.basic_cache[cache_key] = df
                self.basic_cache_time[cache_key] = current_time
                
            return df
            
        except Exception as e:
            logger.error(f"获取股票基本信息失败: {str(e)}")
            return None

    def get_daily_price(self, ts_code: str, start_date: str = None, end_date: str = None, limit: int = 100) -> Optional[pd.DataFrame]:
        """获取日线行情数据
        
        Args:
            ts_code: 股票代码 (如: 000001.SZ)
            start_date: 开始日期 (YYYYMMDD)
            end_date: 结束日期 (YYYYMMDD)
            limit: 数据条数限制
            
        Returns:
            DataFrame: 日线行情数据
        """
        try:
            cache_key = f"daily_{ts_code}_{start_date}_{end_date}_{limit}"
            current_time = time.time()
            
            # 检查缓存
            if (cache_key in self.kline_cache and 
                cache_key in self.kline_cache_time and
                current_time - self.kline_cache_time[cache_key] < self.cache_ttl):
                return self.kline_cache[cache_key]

            params = {
                'ts_code': ts_code,
                'fields': 'ts_code,trade_date,open,high,low,close,vol,amount'
            }
            
            if start_date:
                params['start_date'] = start_date
            if end_date:
                params['end_date'] = end_date
            if limit:
                params['limit'] = limit

            df = self._request('daily', **params)
            
            if df is not None and not df.empty:
                # 转换数据类型
                numeric_columns = ['open', 'high', 'low', 'close', 'vol', 'amount']
                for col in numeric_columns:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                
                # 按日期排序
                df = df.sort_values('trade_date')
                
                # 更新缓存
                self.kline_cache[cache_key] = df
                self.kline_cache_time[cache_key] = current_time
                
            return df
            
        except Exception as e:
            logger.error(f"获取日线数据失败: {str(e)}")
            return None

    def get_realtime_price(self, ts_code: str) -> Optional[float]:
        """获取实时价格（使用最新日线数据）
        
        Args:
            ts_code: 股票代码 (如: 000001.SZ)
            
        Returns:
            float: 最新价格
        """
        try:
            cache_key = f"price_{ts_code}"
            current_time = time.time()
            
            # 检查缓存（实时价格缓存时间较短）
            if (cache_key in self.price_cache and 
                cache_key in self.price_cache_time and
                current_time - self.price_cache_time[cache_key] < 60):  # 1分钟缓存
                return self.price_cache[cache_key]

            # 获取最新的日线数据
            df = self.get_daily_price(ts_code, limit=1)
            
            if df is not None and not df.empty:
                price = float(df.iloc[0]['close'])
                
                # 更新缓存
                self.price_cache[cache_key] = price
                self.price_cache_time[cache_key] = current_time
                
                return price
            
            return None
            
        except Exception as e:
            logger.error(f"获取实时价格失败: {str(e)}")
            return None

    def get_daily_basic(self, ts_code: str = None, trade_date: str = None) -> Optional[pd.DataFrame]:
        """获取每日基本面指标

        Args:
            ts_code: 股票代码 (如: 000001.SZ)
            trade_date: 交易日期 (YYYYMMDD格式)

        Returns:
            DataFrame: 每日基本面指标数据
        """
        try:
            cache_key = f"daily_basic_{ts_code}_{trade_date}"
            current_time = time.time()

            # 检查缓存
            if (cache_key in self.basic_cache and
                cache_key in self.basic_cache_time and
                current_time - self.basic_cache_time[cache_key] < self.cache_ttl):
                return self.basic_cache[cache_key]

            params = {
                'fields': 'ts_code,trade_date,close,turnover_rate,turnover_rate_f,volume_ratio,pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,dv_ttm,total_share,float_share,free_share,total_mv,circ_mv'
            }

            if ts_code:
                params['ts_code'] = ts_code
            if trade_date:
                params['trade_date'] = trade_date
            else:
                # 如果没有指定日期，获取最近的交易日数据
                from datetime import datetime, timedelta
                today = datetime.now()
                # 尝试最近5个工作日
                for i in range(5):
                    check_date = (today - timedelta(days=i)).strftime('%Y%m%d')
                    params['trade_date'] = check_date
                    df = self._request('daily_basic', **params)
                    if df is not None and not df.empty:
                        # 更新缓存
                        self.basic_cache[cache_key] = df
                        self.basic_cache_time[cache_key] = current_time
                        return df
                return None

            df = self._request('daily_basic', **params)

            if df is not None:
                # 更新缓存
                self.basic_cache[cache_key] = df
                self.basic_cache_time[cache_key] = current_time

            return df

        except Exception as e:
            logger.error(f"获取每日基本面指标失败: {str(e)}")
            return None

    def search_stocks(self, query: str, limit: int = 20) -> List[Dict]:
        """搜索股票

        Args:
            query: 搜索关键词（股票代码或名称）
            limit: 返回结果数量限制

        Returns:
            List[Dict]: 搜索结果
        """
        try:
            # 获取股票基本信息
            df = self.get_stock_basic()

            if df is None or df.empty:
                return []

            # 搜索逻辑
            query = query.upper().strip()
            results = []

            for _, row in df.iterrows():
                ts_code = row['ts_code']
                symbol = row['symbol']
                name = row['name']

                # 匹配股票代码或名称
                if (query in ts_code or
                    query in symbol or
                    query in name):
                    results.append({
                        'symbol': ts_code,  # 使用完整的ts_code作为symbol
                        'name': name,
                        'market_type': 'china',
                        'exchange': 'SSE' if ts_code.endswith('.SH') else 'SZSE',
                        'industry': row.get('industry', ''),
                        'is_active': True
                    })

                    if len(results) >= limit:
                        break

            return results
            
        except Exception as e:
            logger.error(f"搜索股票失败: {str(e)}")
            return []

    def format_symbol(self, symbol: str) -> str:
        """格式化股票代码为Tushare格式
        
        Args:
            symbol: 输入的股票代码
            
        Returns:
            str: Tushare格式的股票代码 (如: 000001.SZ)
        """
        try:
            symbol = symbol.upper().strip()
            
            # 如果已经是正确格式，直接返回
            if '.' in symbol and (symbol.endswith('.SZ') or symbol.endswith('.SH')):
                return symbol
            
            # 如果只有数字，需要判断交易所
            if symbol.isdigit():
                if symbol.startswith('6'):
                    return f"{symbol}.SH"  # 上交所
                elif symbol.startswith(('0', '3')):
                    return f"{symbol}.SZ"  # 深交所
            
            return symbol
            
        except Exception as e:
            logger.error(f"格式化股票代码失败: {str(e)}")
            return symbol
