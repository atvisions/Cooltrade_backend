import logging
from .gate_api import GateAPI
import requests
import pandas as pd

class MarketDataService:
    def __init__(self):
        self.gate_api = GateAPI()
        self.logger = logging.getLogger(__name__)

    def calculate_nupl(self, symbol: str) -> float:
        """计算未实现盈亏比率

        Args:
            symbol: 交易对符号

        Returns:
            float: 未实现盈亏比率
        """
        try:
            # 获取最近200天的K线数据
            klines = self.gate_api.get_historical_klines(
                symbol=symbol,
                interval="1d",
                start_str="200 days ago UTC"
            )

            if not klines or len(klines) < 200:
                self.logger.warning(f"获取{symbol}的K线数据失败或数据不足")
                return 0.0

            # 转换为DataFrame
            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'buy_base_volume',
                'buy_quote_volume', 'ignore'
            ])

            # 转换数据类型
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')

            # 计算已实现价格
            df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3
            df['volume_price'] = df['typical_price'] * df['volume']
            realized_price = df['volume_price'].sum() / df['volume'].sum()

            # 计算当前价格与已实现价格的比率
            current_price = float(df['close'].iloc[-1])

            if realized_price == 0:
                self.logger.warning(f"{symbol}的已实现价格为0，无法计算NUPL")
                return 0.0

            nupl = (current_price - realized_price) / realized_price * 100

            # 限制数值范围在 -100% 到 100% 之间
            nupl = max(min(nupl, 100.0), -100.0)

            return round(float(nupl), 2)

        except Exception as e:
            self.logger.error(f"计算{symbol}的未实现盈亏比率时发生错误: {str(e)}")
            return 0.0

    def calculate_exchange_netflow(self, symbol):
        """计算交易所净流入

        Args:
            symbol: 交易对符号，如'BTC'

        Returns:
            float: 净流入量
        """
        try:
            # 确保符号格式正确
            symbol = self._format_symbol(symbol)

            # 获取24小时交易数据
            ticker = self.gate_api.get_ticker(symbol)
            if not ticker:
                self.logger.warning(f"无法获取{symbol}的24小时交易数据")
                return None

            # 计算净流入
            buy_volume = float(ticker.get('buyVolume', 0))
            sell_volume = float(ticker.get('sellVolume', 0))
            netflow = buy_volume - sell_volume

            # 转换为BTC单位
            current_price = self.gate_api.get_current_price(symbol)
            if current_price:
                netflow_btc = netflow / current_price
                return round(netflow_btc, 4)
            return round(netflow, 4)

        except Exception as e:
            self.logger.error(f"计算{symbol}的交易所净流入时出错: {str(e)}")
            return None

    def calculate_mayer_multiple(self, symbol):
        """计算梅耶倍数

        Args:
            symbol: 交易对符号，如'BTC'

        Returns:
            float: 梅耶倍数
        """
        try:
            # 确保符号格式正确
            symbol = self._format_symbol(symbol)

            # 获取200天历史K线数据
            klines = self.gate_api.get_historical_klines(symbol, "1d", "200 days ago UTC")
            if not klines or len(klines) < 200:
                self.logger.warning(f"无法获取{symbol}的足够历史K线数据来计算梅耶倍数")
                return None

            # 计算200日移动平均线
            ma200 = sum(float(k[4]) for k in klines) / len(klines)
            # 获取当前价格
            current_price = self.gate_api.get_current_price(symbol)
            if not current_price:
                self.logger.warning(f"无法获取{symbol}的当前价格")
                return None

            # 计算梅耶倍数
            mayer_multiple = current_price / ma200
            return round(mayer_multiple, 4)

        except Exception as e:
            self.logger.error(f"计算{symbol}的梅耶倍数时出错: {str(e)}")
            return None

    def get_fear_greed_index(self) -> float:
        """获取恐慌贪婪指数

        Returns:
            float: 恐慌贪婪指数值
        """
        try:
            # 使用替代API获取恐慌贪婪指数
            url = "https://api.alternative.me/fng/"
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()

            if data['data']:
                return float(data['data'][0]['value'])
            return 50.0  # 默认值

        except Exception as e:
            self.logger.error(f"获取恐慌贪婪指数失败: {str(e)}")
            return 50.0  # 默认值

    def get_market_data(self, symbol):
        """获取市场数据

        Args:
            symbol: 代币符号，如'BTC'

        Returns:
            dict: 包含市场数据的字典
        """
        try:
            # 确保符号格式正确
            symbol = self._format_symbol(symbol)

            # 获取24小时市场数据
            ticker = self.gate_api.get_ticker(symbol)
            if not ticker:
                self.logger.warning(f"无法获取{symbol}的24小时市场数据，尝试使用备选方法")
                # 使用备选方法
                return self.get_market_data_for_symbol(symbol)

            # 计算其他市场指标
            nupl = self.calculate_nupl(symbol)
            exchange_netflow = self.calculate_exchange_netflow(symbol)
            mayer_multiple = self.calculate_mayer_multiple(symbol)
            fear_greed_index = self.get_fear_greed_index()

            try:
                return {
                    'price': float(ticker.get('lastPrice', 0)),
                    'volume': float(ticker.get('volume', 0)),
                    'price_change_24h': float(ticker.get('priceChange', 0)),
                    'price_change_percent_24h': float(ticker.get('priceChangePercent', 0)),
                    'high_24h': float(ticker.get('highPrice', 0)),
                    'low_24h': float(ticker.get('lowPrice', 0)),
                    'nupl': nupl if nupl is not None else 0.0,
                    'exchange_netflow': exchange_netflow if exchange_netflow is not None else 0.0,
                    'mayer_multiple': mayer_multiple if mayer_multiple is not None else 0.0,
                    'fear_greed_index': fear_greed_index if fear_greed_index is not None else 50.0,
                    'buy_volume': float(ticker.get('buyVolume', 0)),
                    'sell_volume': float(ticker.get('sellVolume', 0))
                }
            except KeyError as e:
                self.logger.error(f"获取{symbol}的市场数据键错误: {e}，尝试使用备选方法")
                return self.get_market_data_for_symbol(symbol)

        except Exception as e:
            self.logger.error(f"获取{symbol}的市场数据失败: {str(e)}")
            # 使用备选方法
            return self.get_market_data_for_symbol(symbol)

    def _format_symbol(self, symbol):
        """格式化交易对符号

        Args:
            symbol: 原始符号

        Returns:
            str: 格式化后的符号
        """
        # 统一大写
        symbol = symbol.upper()

        # 如果不含USDT，添加USDT后缀
        if 'USDT' not in symbol:
            symbol = symbol + 'USDT'

        return symbol

    def get_realtime_price(self, symbol: str) -> float:
        """获取实时价格

        Args:
            symbol: 交易对符号

        Returns:
            float: 实时价格
        """
        try:
            # 确保符号格式正确
            symbol = self._format_symbol(symbol)

            # 获取实时价格
            price = self.gate_api.get_realtime_price(symbol)
            if price:
                return float(price)
            return None
        except Exception as e:
            self.logger.error(f"获取{symbol}的实时价格失败: {str(e)}")
            return None

    def get_market_data_for_symbol(self, symbol: str) -> dict:
        """获取单个交易对的市场数据"""

        try:
            result = {}

            # 获取当前价格
            current_price = self.gate_api.get_current_price(symbol)
            if current_price:
                result['price'] = current_price
            else:
                result['price'] = 0.0

            # 获取24小时交易量
            try:
                volume_24h = self.gate_api.get_24h_volume(symbol)
                if volume_24h:
                    result['volume_24h'] = volume_24h
                else:
                    result['volume_24h'] = 0.0
            except Exception as e:
                self.logger.error(f"获取{symbol}的24小时交易量失败: {e}")
                result['volume_24h'] = 0.0

            # 获取24小时价格变化
            try:
                price_change_24h = self.gate_api.get_24h_price_change(symbol)
                if price_change_24h is not None:
                    result['price_change_24h'] = price_change_24h
                else:
                    # 如果无法获取价格变化，则计算一个估计值
                    ticker = self.gate_api.get_ticker(symbol)
                    if ticker and 'lastPrice' in ticker and 'priceChangePercent' in ticker:
                        # 使用价格变化百分比和当前价格估算价格变化
                        price_change_percent = float(ticker['priceChangePercent'])
                        last_price = float(ticker['lastPrice'])
                        estimated_price_change = (price_change_percent / 100) * last_price
                        result['price_change_24h'] = estimated_price_change
                    else:
                        result['price_change_24h'] = 0.0
            except Exception as e:
                self.logger.error(f"获取{symbol}的价格变化失败: {e}")
                result['price_change_24h'] = 0.0

            # 获取其他市场数据...
            try:
                # 其他可能的市场数据
                # ...
                pass
            except Exception as e:
                self.logger.error(f"获取{symbol}的其他市场数据失败: {e}")

            return result
        except Exception as e:
            self.logger.error(f"获取{symbol}的市场数据失败: {str(e)}")
            # 返回基本的空数据结构
            return {
                'price': 0.0,
                'volume_24h': 0.0,
                'price_change_24h': 0.0
            }