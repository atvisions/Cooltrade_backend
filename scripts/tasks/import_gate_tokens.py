"""
导入Gate.io热门代币脚本

该脚本从Gate.io API获取交易量最大的前100个代币，并将它们导入到数据库中。
使用方法：
    python scripts/tasks/import_gate_tokens.py
"""
import requests
import time
import sys
from typing import List, Dict, Any
from pathlib import Path

# 添加当前目录到Python路径
current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(current_dir))

from utils import setup_django, setup_logging

# 设置Django环境
setup_django()

# 导入Django相关模块
from django.db import transaction
from CryptoAnalyst.models import Chain, Token

# 配置日志
logger = setup_logging('import_gate_tokens.log')

class GateTokenImporter:
    """Gate.io代币导入器"""

    def __init__(self):
        """初始化导入器"""
        self.base_url = "https://api.gateio.ws/api/v4"
        self.usdt_chain = None

    def _request(self, method: str, endpoint: str, params: Dict = None, max_retries: int = 3) -> Any:
        """发送API请求

        Args:
            method: 请求方法，如'GET'
            endpoint: API端点
            params: 请求参数
            max_retries: 最大重试次数

        Returns:
            Any: 响应数据，如果请求失败则返回None
        """
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

        retry_count = 0
        retry_delay = 1.0

        while retry_count < max_retries:
            try:
                start_time = time.time()
                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    timeout=10
                )
                elapsed = time.time() - start_time

                if response.status_code == 200:
                    logger.debug(f"请求成功: {url}, 耗时: {elapsed:.2f}秒")
                    return response.json()
                else:
                    logger.warning(f"请求失败 ({retry_count + 1}/{max_retries}): HTTP {response.status_code}, 耗时: {elapsed:.2f}秒, URL: {url}")
                    logger.warning(f"响应内容: {response.text}")
                    retry_count += 1
                    time.sleep(retry_delay)
                    retry_delay *= 1.5
            except Exception as e:
                logger.error(f"请求异常 ({retry_count + 1}/{max_retries}): {str(e)}")
                retry_count += 1
                time.sleep(retry_delay)
                retry_delay *= 1.5

        logger.error(f"在{max_retries}次尝试后仍无法完成请求: {url}")
        return None

    def get_top_tokens(self, limit: int = 100) -> List[Dict]:
        """获取交易量最大的代币

        Args:
            limit: 获取的代币数量

        Returns:
            List[Dict]: 代币列表
        """
        logger.info(f"获取交易量最大的{limit}个代币...")

        # 获取所有USDT交易对
        endpoint = "/spot/tickers"
        response = self._request("GET", endpoint)

        if not response:
            logger.error("无法获取交易对数据")
            return []

        # 过滤出USDT交易对
        usdt_pairs = [pair for pair in response if pair.get("currency_pair", "").endswith("_USDT")]

        # 按24小时交易量排序
        usdt_pairs.sort(key=lambda x: float(x.get("quote_volume", 0)), reverse=True)

        # 获取前N个交易对
        top_pairs = usdt_pairs[:limit]

        logger.info(f"成功获取{len(top_pairs)}个热门USDT交易对")
        return top_pairs

    def format_token_data(self, token_data: Dict) -> Dict:
        """格式化代币数据

        Args:
            token_data: 原始代币数据

        Returns:
            Dict: 格式化后的代币数据
        """
        currency_pair = token_data.get("currency_pair", "")
        symbol = currency_pair.split("_")[0]  # 去除_USDT后缀

        return {
            "symbol": symbol,
            "name": symbol,
            "volume_24h": float(token_data.get("quote_volume", 0)),
            "price": float(token_data.get("last", 0))
        }

    def import_tokens(self, limit: int = 100) -> None:
        """导入代币到数据库

        Args:
            limit: 导入的代币数量
        """
        try:
            # 获取热门代币
            top_tokens = self.get_top_tokens(limit)

            if not top_tokens:
                logger.error("没有获取到代币数据，导入终止")
                return

            # 获取或创建USDT链
            with transaction.atomic():
                self.usdt_chain, created = Chain.objects.get_or_create(
                    chain="USDT",
                    defaults={
                        "is_active": True,
                        "is_testnet": False
                    }
                )

                if created:
                    logger.info("创建了新的USDT链记录")
                else:
                    logger.info("使用现有的USDT链记录")

            # 导入代币
            imported_count = 0
            updated_count = 0

            for token_data in top_tokens:
                formatted_data = self.format_token_data(token_data)
                symbol = formatted_data["symbol"]

                try:
                    with transaction.atomic():
                        token, created = Token.objects.get_or_create(
                            symbol=symbol,
                            defaults={
                                "chain": self.usdt_chain,
                                "name": formatted_data["name"],
                                "address": "",  # 地址字段留空
                                "decimals": 18  # 默认精度
                            }
                        )

                        if created:
                            imported_count += 1
                            logger.info(f"导入新代币: {symbol}, 价格: {formatted_data['price']}, 24小时交易量: {formatted_data['volume_24h']}")
                        else:
                            updated_count += 1
                            logger.info(f"更新现有代币: {symbol}, 价格: {formatted_data['price']}, 24小时交易量: {formatted_data['volume_24h']}")

                except Exception as e:
                    logger.error(f"导入代币 {symbol} 时出错: {str(e)}")

            logger.info(f"导入完成。新导入: {imported_count}, 已更新: {updated_count}, 总计: {len(top_tokens)}")

        except Exception as e:
            logger.error(f"导入过程中发生错误: {str(e)}")

def main():
    """主函数"""
    logger.info("开始导入Gate.io热门代币...")

    importer = GateTokenImporter()
    importer.import_tokens(limit=100)

    logger.info("导入过程完成")

if __name__ == "__main__":
    main()
