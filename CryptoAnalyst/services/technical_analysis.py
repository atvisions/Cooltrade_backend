import logging
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Union
from datetime import datetime, timedelta
from CryptoAnalyst.services.gate_api import GateAPI
import requests
import os
import traceback

logger = logging.getLogger(__name__)

class TechnicalAnalysisService:
    """技术分析服务类"""

    def __init__(self):
        """初始化技术分析服务"""
        self.gate_api = GateAPI()  # 使用Gate API

    def get_all_indicators(self, symbol: str, interval: str = '1d', limit: int = 1000) -> Dict:
        """获取所有技术指标数据

        Args:
            symbol: 交易对符号
            interval: K线间隔
            limit: 获取的K线数量限制

        Returns:
            Dict: 包含所有技术指标的字典
        """
        try:
            # 确保 gate_api 客户端已初始化
            if not self.gate_api._ensure_client():
                logger.error("无法初始化 Gate API 客户端")
                return {
                    'status': 'error',
                    'message': "无法连接到 Gate API"
                }

            # 首先检查是否能获取实时价格，这可以验证交易对是否存在
            price = self.gate_api.get_realtime_price(symbol)
            if not price:
                logger.error(f"无法获取{symbol}的实时价格，交易对可能不存在")
                return {
                    'status': 'error',
                    'message': f"无法获取{symbol}的实时价格，请检查交易对是否存在"
                }

            # 成功获取实时价格，开始计算技术指标

            # 获取历史K线数据，减少请求数据量
            # 从之前的1000天减少到100天，对于新上线的代币更友好
            klines = self.gate_api.get_historical_klines(symbol, interval, '100 days ago UTC')

            # 如果无法获取足够的历史数据，尝试获取更少的数据
            if not klines or len(klines) < 20:  # 至少需要20条数据来计算基本指标
                logger.warning(f"历史数据不足，尝试获取更少的历史数据: {symbol}")
                klines = self.gate_api.get_klines(symbol, interval, 50)  # 尝试只获取50条数据

                if not klines or len(klines) < 14:  # RSI至少需要14条数据
                    logger.warning(f"无法获取足够的K线数据进行分析: {symbol}")
                    return {
                        'status': 'error',
                        'message': f"无法获取{symbol}的K线数据"
                    }

            # 记录获取到的K线数量
            kline_count = len(klines)
            # 开始计算指标

            # 转换为DataFrame
            df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_volume', 'trades', 'taker_buy_base', 'taker_buy_quote', 'ignore'])

            # 确保数据类型正确
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df['close'] = df['close'].astype(float)
            df['volume'] = df['volume'].astype(float)

            # 按时间排序
            df = df.sort_values('timestamp')

            # 检查数据量是否足够
            # 如果数据量不足200天，某些高级指标可能不准确

            # 计算技术指标，基于可用数据量灵活调整
            indicators = {}

            # 基本指标，至少需要14天数据
            if len(df) >= 14:
                indicators['RSI'] = self._calculate_rsi(df)
                indicators['MACD'] = self._calculate_macd(df)
                indicators['BollingerBands'] = self._calculate_bollinger_bands(df)
                indicators['BIAS'] = self._calculate_bias(df)
            else:
                logger.warning(f"数据不足，无法计算基本技术指标")
                # 提供默认值
                indicators['RSI'] = 50.0
                indicators['MACD'] = {'line': 0.0, 'signal': 0.0, 'histogram': 0.0}
                indicators['BollingerBands'] = {'upper': price * 1.02, 'middle': price, 'lower': price * 0.98}
                indicators['BIAS'] = 0.0

            # 其他指标
            if len(df) >= 12:
                indicators['PSY'] = self._calculate_psy(df)
            else:
                indicators['PSY'] = 50.0

            if len(df) >= 14:
                indicators['DMI'] = self._calculate_dmi(df)
            else:
                indicators['DMI'] = {'plus_di': 25.0, 'minus_di': 25.0, 'adx': 20.0}

            if len(df) >= 20:
                indicators['VWAP'] = self._calculate_vwap(df)
            else:
                indicators['VWAP'] = price

            # 资金费率和交易所净流入可能不依赖于历史K线长度
            indicators['FundingRate'] = self._get_funding_rate(symbol)
            indicators['ExchangeNetflow'] = self._calculate_exchange_netflow(df)

            # 高级指标需要更多数据
            if len(df) >= 200:
                indicators['NUPL'] = self._calculate_nupl(df, window=200)
                indicators['MayerMultiple'] = self._calculate_mayer_multiple(df, window=200)
            elif len(df) >= 100:
                # 使用100天数据计算，可能不太准确但比默认值更有意义
                # 数据量不足200天，使用可用数据计算高级指标
                indicators['NUPL'] = self._calculate_nupl(df, window=100)
                indicators['MayerMultiple'] = self._calculate_mayer_multiple(df, window=100)
            elif len(df) >= 50:
                # 使用50天数据计算，作为近似值
                # 数据量较少，使用近似方法计算高级指标
                indicators['NUPL'] = self._calculate_nupl(df, window=50)
                indicators['MayerMultiple'] = self._calculate_mayer_multiple(df, window=50)
            else:
                # 数据太少，使用默认值
                logger.warning(f"数据量过少({len(df)}天)，无法计算高级指标，使用默认值")
                indicators['NUPL'] = 0.0
                indicators['MayerMultiple'] = 1.0

            # 检查所有指标是否有效
            for key, value in indicators.items():
                if isinstance(value, (int, float)):
                    if np.isnan(value) or np.isinf(value):
                        logger.warning(f"指标 {key} 的值无效: {value}，使用默认值")
                        indicators[key] = 0.0
                elif isinstance(value, dict):
                    for sub_key, sub_value in value.items():
                        if isinstance(sub_value, (int, float)):
                            if np.isnan(sub_value) or np.isinf(sub_value):
                                logger.warning(f"指标 {key}.{sub_key} 的值无效: {sub_value}，使用默认值")
                                value[sub_key] = 0.0

            # 成功计算所有技术指标
            return {
                'status': 'success',
                'data': {
                    'symbol': symbol,
                    'interval': interval,
                    'timestamp': datetime.now().isoformat(),
                    'indicators': indicators
                }
            }

        except requests.exceptions.Timeout:
            logger.error(f"请求OKX API超时")
            return {
                'status': 'error',
                'message': "连接OKX API超时，请稍后重试"
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"请求OKX API失败: {str(e)}")
            return {
                'status': 'error',
                'message': f"连接OKX API失败: {str(e)}"
            }
        except Exception as e:
            logger.error(f"计算技术指标时发生错误: {str(e)}")
            logger.error(traceback.format_exc())
            return {
                'status': 'error',
                'message': str(e)
            }

    def _calculate_rsi(self, df: pd.DataFrame, period: int = 14) -> float:
        """计算RSI指标

        Args:
            df: 包含价格数据的DataFrame
            period: RSI周期，默认为14

        Returns:
            float: 当前RSI值
        """
        try:
            # 计算价格变化
            delta = df['close'].diff()

            # 分离上涨和下跌
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

            # 计算相对强度
            rs = gain / loss

            # 计算RSI
            rsi = 100 - (100 / (1 + rs))

            # 获取最新的RSI值并验证
            rsi_value = float(rsi.iloc[-1])

            # 限制数值范围
            rsi_value = max(min(rsi_value, 100.0), 0.0)

            return round(rsi_value, 2)

        except Exception as e:
            logger.error(f"计算RSI指标时发生错误: {str(e)}")
            return 50.0  # 默认值

    def _calculate_macd(self, df: pd.DataFrame, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9) -> Dict:
        """计算MACD指标

        Args:
            df: 包含价格数据的DataFrame
            fast_period: 快线周期，默认为12
            slow_period: 慢线周期，默认为26
            signal_period: 信号线周期，默认为9

        Returns:
            Dict: 包含MACD线、信号线和柱状图的值
        """
        try:
            # 计算快线和慢线的EMA
            exp1 = df['close'].ewm(span=fast_period, adjust=False).mean()
            exp2 = df['close'].ewm(span=slow_period, adjust=False).mean()

            # 计算MACD线
            macd_line = exp1 - exp2

            # 计算信号线
            signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()

            # 计算MACD柱状图
            histogram = macd_line - signal_line

            # 获取最新的值并验证
            macd_value = float(macd_line.iloc[-1])
            signal_value = float(signal_line.iloc[-1])
            hist_value = float(histogram.iloc[-1])

            # 限制数值范围
            macd_value = max(min(macd_value, 10000.0), -10000.0)
            signal_value = max(min(signal_value, 10000.0), -10000.0)
            hist_value = max(min(hist_value, 10000.0), -10000.0)

            return {
                'line': round(macd_value, 2),
                'signal': round(signal_value, 2),
                'histogram': round(hist_value, 2)
            }

        except Exception as e:
            logger.error(f"计算MACD指标时发生错误: {str(e)}")
            return {
                'line': 0.0,
                'signal': 0.0,
                'histogram': 0.0
            }

    def _calculate_bollinger_bands(self, df: pd.DataFrame, period: int = 20, std_dev: int = 2) -> Dict:
        """计算布林带指标

        Args:
            df: 包含价格数据的DataFrame
            period: 移动平均周期，默认为20
            std_dev: 标准差倍数，默认为2

        Returns:
            Dict: 包含上轨、中轨和下轨的值
        """
        try:
            # 获取最新的价格数据
            current_price = float(df['close'].iloc[-1])

            # 计算中轨（20日移动平均线）
            middle_band = df['close'].rolling(window=period).mean()

            # 计算标准差
            std = df['close'].rolling(window=period).std()

            # 计算上轨和下轨
            upper_band = middle_band + (std * std_dev)
            lower_band = middle_band - (std * std_dev)

            # 获取最新的值并验证
            upper_value = float(upper_band.iloc[-1])
            middle_value = float(middle_band.iloc[-1])
            lower_value = float(lower_band.iloc[-1])

            # 验证值是否有效
            if pd.isna(upper_value) or not np.isfinite(upper_value):
                upper_value = current_price * 1.02
            if pd.isna(middle_value) or not np.isfinite(middle_value):
                middle_value = current_price
            if pd.isna(lower_value) or not np.isfinite(lower_value):
                lower_value = current_price * 0.98

            # 限制数值范围
            upper_value = max(min(upper_value, current_price * 1.5), current_price * 1.02)
            middle_value = max(min(middle_value, current_price * 1.2), current_price * 0.8)
            lower_value = max(min(lower_value, current_price * 0.98), current_price * 0.5)

            return {
                'upper': round(upper_value, 2),
                'middle': round(middle_value, 2),
                'lower': round(lower_value, 2)
            }

        except Exception as e:
            logger.error(f"计算布林带指标时发生错误: {str(e)}")
            current_price = float(df['close'].iloc[-1])
            return {
                'upper': round(current_price * 1.02, 2),
                'middle': round(current_price, 2),
                'lower': round(current_price * 0.98, 2)
            }

    def _calculate_bias(self, df: pd.DataFrame, period: int = 6) -> float:
        """计算乖离率指标

        Args:
            df: 包含价格数据的DataFrame
            period: 计算周期，默认为6

        Returns:
            float: 当前乖离率值
        """
        try:
            # 计算移动平均线
            ma = df['close'].rolling(window=period).mean()

            # 计算乖离率：(收盘价 - MA) / MA × 100%
            bias = ((df['close'] - ma) / ma * 100).iloc[-1]

            # 验证值是否有效
            bias_value = float(bias)
            if pd.isna(bias_value) or not np.isfinite(bias_value):
                return 0.0

            return round(bias_value, 2)

        except Exception as e:
            logger.error(f"计算乖离率指标时发生错误: {str(e)}")
            return 0.0

    def _calculate_psy(self, df: pd.DataFrame, period: int = 12) -> float:
        """计算心理线指标

        Args:
            df: 包含价格数据的DataFrame
            period: 计算周期，默认为12

        Returns:
            float: 当前心理线值
        """
        try:
            # 计算价格变化
            df['change'] = df['close'].diff()

            # 标记上涨天数
            df['up'] = df['change'].apply(lambda x: 1 if x > 0 else 0)

            # 计算心理线：上涨天数 / 总天数 × 100
            psy = (df['up'].rolling(window=period).sum() / period * 100).iloc[-1]

            # 验证值是否有效
            psy_value = float(psy)
            if pd.isna(psy_value) or not np.isfinite(psy_value):
                return 50.0

            return round(psy_value, 1)

        except Exception as e:
            logger.error(f"计算心理线指标时发生错误: {str(e)}")
            return 50.0

    def _calculate_dmi(self, df: pd.DataFrame, period: int = 14) -> Dict:
        """计算动向指标

        Args:
            df: 包含价格数据的DataFrame
            period: 计算周期，默认为14

        Returns:
            Dict: 包含+DI、-DI和ADX的值
        """
        try:
            # 确保数据类型正确
            df['high'] = df['high'].astype(float)
            df['low'] = df['low'].astype(float)
            df['close'] = df['close'].astype(float)

            # 计算TR（真实波幅）
            df['tr1'] = df['high'] - df['low']
            df['tr2'] = abs(df['high'] - df['close'].shift(1))
            df['tr3'] = abs(df['low'] - df['close'].shift(1))
            df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)

            # 计算+DM和-DM
            df['up_move'] = df['high'] - df['high'].shift(1)
            df['down_move'] = df['low'].shift(1) - df['low']
            df['plus_dm'] = df.apply(lambda x: x['up_move'] if x['up_move'] > x['down_move'] and x['up_move'] > 0 else 0, axis=1)
            df['minus_dm'] = df.apply(lambda x: x['down_move'] if x['down_move'] > x['up_move'] and x['down_move'] > 0 else 0, axis=1)

            # 计算+DI和-DI
            plus_di = 100 * (df['plus_dm'].rolling(window=period).sum() / df['tr'].rolling(window=period).sum())
            minus_di = 100 * (df['minus_dm'].rolling(window=period).sum() / df['tr'].rolling(window=period).sum())

            # 计算ADX
            dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
            adx = dx.rolling(window=period).mean()

            # 获取最新的值并验证
            plus_di_value = float(plus_di.iloc[-1])
            minus_di_value = float(minus_di.iloc[-1])
            adx_value = float(adx.iloc[-1])

            # 验证值是否有效
            if pd.isna(plus_di_value) or not np.isfinite(plus_di_value):
                plus_di_value = 0.0
            if pd.isna(minus_di_value) or not np.isfinite(minus_di_value):
                minus_di_value = 0.0
            if pd.isna(adx_value) or not np.isfinite(adx_value):
                adx_value = 0.0

            return {
                'plus_di': round(plus_di_value, 1),
                'minus_di': round(minus_di_value, 1),
                'adx': round(adx_value, 1)
            }

        except Exception as e:
            logger.error(f"计算动向指标时发生错误: {str(e)}")
            return {
                'plus_di': 0.0,
                'minus_di': 0.0,
                'adx': 0.0
            }

    def _calculate_vwap(self, df: pd.DataFrame) -> float:
        """计算成交量加权平均价

        Args:
            df: 包含价格和成交量数据的DataFrame

        Returns:
            float: 当前VWAP值
        """
        try:
            # 计算典型价格
            df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3

            # 计算价格×成交量
            df['price_volume'] = df['typical_price'] * df['volume']

            # 计算VWAP
            vwap = df['price_volume'].sum() / df['volume'].sum()

            # 验证值是否有效
            vwap_value = float(vwap)
            if pd.isna(vwap_value) or not np.isfinite(vwap_value):
                return float(df['close'].iloc[-1])

            return round(vwap_value, 2)

        except Exception as e:
            logger.error(f"计算成交量加权平均价时发生错误: {str(e)}")
            return float(df['close'].iloc[-1])

    def _get_funding_rate(self, symbol: str) -> float:
        """获取资金费率

        Args:
            symbol: 交易对符号，例如 'BTCUSDT'

        Returns:
            float: 资金费率（小数形式，例如0.0001表示0.01%）
        """
        try:
            # 尝试从Gate API获取资金费率
            funding_rate = self.gate_api.get_funding_rate(symbol)

            # 如果API返回的资金费率为0或None，使用硬编码的默认值
            if funding_rate is None or funding_rate == 0:
                # 根据不同的币种使用不同的默认值
                default_rates = {
                    "BTCUSDT": 0.0001,   # 0.01%
                    "ETHUSDT": 0.00015,  # 0.015%
                    "SOLUSDT": 0.0002,   # 0.02%
                    "DOGEUSDT": 0.0003,  # 0.03%
                    "XRPUSDT": 0.00025,  # 0.025%
                }

                default_rate = default_rates.get(symbol, 0.0001)  # 如果没有特定币种的默认值，使用0.0001
                # API返回的资金费率为0，使用默认值
                return default_rate

            # 使用API返回的资金费率
            rate = float(funding_rate)
            # 获取到资金费率
            return round(rate, 6)

        except Exception as e:
            logger.warning(f"获取 {symbol} 的资金费率时发生错误: {str(e)}")

            # 使用硬编码的默认值
            default_rates = {
                "BTCUSDT": 0.0001,   # 0.01%
                "ETHUSDT": 0.00015,  # 0.015%
                "SOLUSDT": 0.0002,   # 0.02%
                "DOGEUSDT": 0.0003,  # 0.03%
                "XRPUSDT": 0.00025,  # 0.025%
            }

            default_rate = default_rates.get(symbol, 0.0001)  # 如果没有特定币种的默认值，使用0.0001
            # 使用默认资金费率
            return default_rate

    def _calculate_exchange_netflow(self, df: pd.DataFrame, period: int = 30) -> float:
        """计算交易所净流入流出

        Args:
            df: 包含价格和成交量数据的DataFrame
            period: 计算周期，默认为30天

        Returns:
            float: 交易所净流入流出值
        """
        try:
            # 计算每日净流入流出
            df['net_flow'] = df['volume'] * df['close']

            # 计算30日平均净流入流出
            avg_net_flow = df['net_flow'].rolling(window=period).mean()

            # 计算当前净流入流出与平均值的比率
            current_net_flow = df['net_flow'].iloc[-1]
            avg_net_flow_value = float(avg_net_flow.iloc[-1])

            if avg_net_flow_value == 0:
                return 0.0

            netflow_ratio = (current_net_flow - avg_net_flow_value) / avg_net_flow_value * 100

            # 限制数值范围
            netflow_ratio = max(min(netflow_ratio, 1000.0), -1000.0)

            return round(float(netflow_ratio), 2)

        except Exception as e:
            logger.error(f"计算交易所净流入流出时发生错误: {str(e)}")
            return 0.0

    def _calculate_nupl(self, df: pd.DataFrame, window: int = 200) -> float:
        """计算未实现盈亏比率

        Args:
            df: 包含价格数据的DataFrame
            window: 计算窗口，默认为200天

        Returns:
            float: 未实现盈亏比率
        """
        try:
            # 检查数据长度
            if len(df) < window:
                logger.warning(f"数据长度不足{window}天，无法计算NUPL")
                return 0.0

            # 根据数据可用性动态调整计算窗口
            actual_window = min(window, len(df) - 1)
            # 使用可用数据计算NUPL

            # 确保数据类型正确
            df['close'] = pd.to_numeric(df['close'], errors='coerce')
            df['high'] = pd.to_numeric(df['high'], errors='coerce')
            df['low'] = pd.to_numeric(df['low'], errors='coerce')
            df['volume'] = pd.to_numeric(df['volume'], errors='coerce')

            # 检查是否有无效数据
            if df[['close', 'high', 'low', 'volume']].isna().any().any():
                logger.warning("数据中包含无效值")
                return 0.0

            # 使用实际可用窗口计算已实现价格
            # 这里使用过去actual_window天的成交量加权平均价格
            df_window = df.iloc[-actual_window:].copy()  # 使用copy()创建副本，避免SettingWithCopyWarning

            # 计算已实现价格
            df_window.loc[:, 'typical_price'] = (df_window['high'] + df_window['low'] + df_window['close']) / 3
            df_window.loc[:, 'volume_price'] = df_window['typical_price'] * df_window['volume']

            # 检查计算结果
            if df_window['volume_price'].isna().any() or df_window['volume'].isna().any():
                logger.warning("计算过程中出现无效值")
                return 0.0

            total_volume = df_window['volume'].sum()
            if total_volume == 0 or np.isnan(total_volume) or np.isinf(total_volume):
                logger.warning("总成交量无效")
                return 0.0

            realized_price = df_window['volume_price'].sum() / total_volume

            # 检查已实现价格
            if realized_price == 0 or np.isnan(realized_price) or np.isinf(realized_price):
                logger.warning("已实现价格无效")
                return 0.0

            # 获取当前价格
            current_price = float(df['close'].iloc[-1])
            if np.isnan(current_price) or np.isinf(current_price):
                logger.warning("当前价格无效")
                return 0.0

            # 计算NUPL
            nupl = (current_price - realized_price) / realized_price * 100

            # 检查计算结果
            if np.isnan(nupl) or np.isinf(nupl):
                logger.warning("NUPL计算结果无效")
                return 0.0

            # 限制数值范围在 -100% 到 100% 之间
            nupl = max(min(nupl, 100.0), -100.0)

            # NUPL计算完成
            return round(float(nupl), 2)

        except Exception as e:
            logger.error(f"计算未实现盈亏比率时发生错误: {str(e)}")
            return 0.0

    def _calculate_mayer_multiple(self, df: pd.DataFrame, window: int = 200) -> float:
        """计算梅耶倍数

        Args:
            df: 包含价格数据的DataFrame
            window: 计算窗口，默认为200天

        Returns:
            float: 梅耶倍数
        """
        try:
            # 检查数据长度
            if len(df) < window:
                logger.warning(f"数据长度不足{window}天，使用可用的{len(df)}天数据计算梅耶倍数")

            # 动态调整窗口大小，确保至少有20天数据
            actual_window = min(window, len(df) - 1)
            if actual_window < 20:
                logger.warning(f"数据不足20天，无法可靠计算梅耶倍数")
                return 1.0

            # 使用可用数据计算梅耶倍数

            # 获取当前价格
            current_price = float(df['close'].iloc[-1])

            # 计算适应窗口大小的移动平均线
            moving_avg = df['close'].rolling(window=actual_window).mean()

            # 获取MA数据
            ma_value = float(moving_avg.iloc[-1])

            # 检查移动平均线值是否有效
            if ma_value == 0 or np.isnan(ma_value) or np.isinf(ma_value):
                logger.warning(f"{actual_window}日均线值无效，无法计算梅耶倍数")
                return 1.0

            # 计算当前价格与移动均线的比率
            mayer_multiple = current_price / ma_value

            # 梅耶倍数计算完成

            # 限制数值范围
            mayer_multiple = max(min(mayer_multiple, 10.0), 0.1)

            return round(float(mayer_multiple), 2)

        except Exception as e:
            logger.error(f"计算梅耶倍数时发生错误: {str(e)}")
            return 1.0