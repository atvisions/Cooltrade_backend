import requests
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.conf import settings
from django.core.cache import cache
import json
import logging
import asyncio
import aiohttp
from concurrent.futures import ThreadPoolExecutor
import time
from datetime import datetime, timedelta
import hashlib
import re
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

def detect_market_type(symbol, request_path=None, request=None):
    """检测市场类型"""
    # 通过请求路径判断 - 检查完整的请求路径
    if request_path:
        if '/china/' in request_path:
            return 'china'
        elif '/stock/' in request_path:
            return 'stock'
        elif '/crypto/' in request_path:
            return 'crypto'

    # 如果有request对象，检查完整的请求路径
    if request:
        full_path = request.get_full_path()
        if '/api/china/' in full_path:
            return 'china'
        elif '/api/stock/' in full_path:
            return 'stock'
        elif '/api/crypto/' in full_path:
            return 'crypto'

    # 通过符号判断（备用方法）
    # A股符号检测
    if ('.' in symbol and (symbol.endswith('.SZ') or symbol.endswith('.SH'))) or \
       (symbol.isdigit() and len(symbol) == 6):
        return 'china'

    # 美股符号通常是字母组合，加密货币符号通常较短且常见
    crypto_symbols = ['BTC', 'ETH', 'ADA', 'SOL', 'DOGE', 'XRP', 'DOT', 'LINK', 'LTC', 'BCH', 'UNI', 'MATIC', 'AVAX', 'ATOM', 'FTM', 'NEAR']
    if symbol.upper() in crypto_symbols:
        return 'crypto'

    # 默认根据符号长度判断
    if len(symbol) <= 5 and symbol.isupper():
        return 'crypto'
    else:
        return 'stock'

@csrf_exempt
@require_http_methods(["GET"])
def get_news(request):
    """
    获取Tiingo新闻数据的代理接口
    """
    try:
        # 获取请求参数
        tickers = request.GET.get('tickers', '')
        limit = request.GET.get('limit', '10')
        
        if not tickers:
            return JsonResponse({
                'status': 'error',
                'message': 'tickers parameter is required'
            }, status=400)
        
        # Tiingo API配置
        tiingo_token = getattr(settings, 'TIINGO_API_KEY', None)
        if not tiingo_token:
            logger.error("TIINGO_API_KEY not configured")
            return JsonResponse({
                'status': 'error',
                'message': 'News service not configured'
            }, status=500)
        
        # 构建Tiingo API请求
        tiingo_url = f"https://api.tiingo.com/tiingo/news"
        params = {
            'tickers': tickers,
            'limit': limit,
            'token': tiingo_token
        }
        
        headers = {
            'Content-Type': 'application/json',
        }
        
        logger.info(f"Fetching news for tickers: {tickers}")
        
        # 调用Tiingo API
        response = requests.get(tiingo_url, params=params, headers=headers, timeout=10)
        
        if response.status_code == 200:
            news_data = response.json()
            
            # 确保返回的是数组
            if not isinstance(news_data, list):
                news_data = []
            
            return JsonResponse({
                'status': 'success',
                'data': news_data
            })
        
        elif response.status_code == 404:
            # 没有找到相关新闻
            return JsonResponse({
                'status': 'success',
                'data': []
            })
        
        else:
            logger.error(f"Tiingo API error: {response.status_code} - {response.text}")
            return JsonResponse({
                'status': 'error',
                'message': f'News service error: {response.status_code}'
            }, status=response.status_code)
            
    except requests.exceptions.Timeout:
        logger.error("Tiingo API timeout")
        return JsonResponse({
            'status': 'error',
            'message': 'News service timeout'
        }, status=504)
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Tiingo API request error: {str(e)}")
        return JsonResponse({
            'status': 'error',
            'message': 'News service unavailable'
        }, status=503)
        
    except Exception as e:
        logger.error(f"Unexpected error in get_news: {str(e)}")
        return JsonResponse({
            'status': 'error',
            'message': 'Internal server error'
        }, status=500)


def fetch_rss_news_sync(rss_url, limit, symbol=None):
    """同步获取RSS新闻"""
    try:
        logger.info(f"Fetching RSS news from: {rss_url}")

        # 获取RSS feed
        response = requests.get(rss_url, timeout=10, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

        if response.status_code != 200:
            logger.error(f"RSS feed request failed: {response.status_code}")
            return []

        # 解析RSS XML
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as e:
            logger.error(f"RSS XML parsing failed: {str(e)}")
            return []

        # 查找所有item元素
        items = []
        for item in root.findall('.//item'):
            try:
                title_elem = item.find('title')
                link_elem = item.find('link')
                description_elem = item.find('description')
                pub_date_elem = item.find('pubDate')

                title = title_elem.text if title_elem is not None else ''
                link = link_elem.text if link_elem is not None else ''
                description = description_elem.text if description_elem is not None else ''
                pub_date = pub_date_elem.text if pub_date_elem is not None else ''

                # 如果指定了symbol，进行关键词过滤
                if symbol and symbol.upper() != 'ALL':
                    # 构建关键词列表
                    crypto_keywords = {
                        'BTC': ['bitcoin', 'btc'],
                        'ETH': ['ethereum', 'eth', 'ether'],
                        'ADA': ['cardano', 'ada'],
                        'SOL': ['solana', 'sol'],
                        'DOGE': ['dogecoin', 'doge'],
                        'XRP': ['ripple', 'xrp'],
                        'DOT': ['polkadot', 'dot'],
                        'LINK': ['chainlink', 'link'],
                        'LTC': ['litecoin', 'ltc'],
                        'BCH': ['bitcoin cash', 'bch'],
                        'UNI': ['uniswap', 'uni'],
                        'MATIC': ['polygon', 'matic']
                    }

                    keywords = crypto_keywords.get(symbol.upper(), [symbol.lower()])

                    # 检查标题和描述中是否包含关键词
                    text_to_search = (title + ' ' + description).lower()
                    if not any(keyword in text_to_search for keyword in keywords):
                        continue

                # 生成唯一ID
                news_id = hashlib.md5((link + title).encode()).hexdigest()

                items.append({
                    'id': news_id,
                    'title': title.strip(),
                    'url': link.strip(),
                    'published_at': pub_date.strip(),
                    'source': 'RSS Feed',
                    'body': description.strip()[:200] + '...' if len(description) > 200 else description.strip(),
                    'source_type': 'rss'
                })

                if len(items) >= limit:
                    break

            except Exception as e:
                logger.error(f"Error parsing RSS item: {str(e)}")
                continue

        logger.info(f"RSS feed returned {len(items)} news items")
        return items

    except Exception as e:
        logger.error(f"RSS feed error: {str(e)}")
        return []


def fetch_coindesk_news_sync(symbol, limit):
    """同步获取CoinDesk新闻"""
    return fetch_rss_news_sync("https://www.coindesk.com/arc/outboundfeeds/rss/", limit, symbol)


def fetch_cointelegraph_news_sync(symbol, limit):
    """同步获取Cointelegraph新闻"""
    return fetch_rss_news_sync("https://cointelegraph.com/rss", limit, symbol)


def fetch_decrypt_news_sync(symbol, limit):
    """同步获取Decrypt新闻"""
    return fetch_rss_news_sync("https://decrypt.co/feed", limit, symbol)


def fetch_beincrypto_news_sync(symbol, limit):
    """同步获取BeInCrypto新闻"""
    return fetch_rss_news_sync("https://beincrypto.com/feed/", limit, symbol)


def fetch_newsapi_crypto_news_sync(symbol, limit, newsapi_key):
    """同步获取NewsAPI加密货币新闻"""
    try:
        logger.info(f"NewsAPI key available: {bool(newsapi_key)}")

        if not newsapi_key:
            logger.warning("NewsAPI key not available")
            return []

        # NewsAPI URL
        newsapi_url = "https://newsapi.org/v2/everything"

        # 构建搜索查询
        # 为特定币种构建更精确的查询
        crypto_names = {
            'BTC': 'Bitcoin',
            'ETH': 'Ethereum',
            'ADA': 'Cardano',
            'SOL': 'Solana',
            'DOGE': 'Dogecoin',
            'XRP': 'Ripple',
            'DOT': 'Polkadot',
            'LINK': 'Chainlink',
            'LTC': 'Litecoin',
            'BCH': 'Bitcoin Cash',
            'UNI': 'Uniswap',
            'MATIC': 'Polygon'
        }

        # 构建查询字符串
        if symbol.upper() in crypto_names:
            query = f"{crypto_names[symbol.upper()]} OR {symbol.upper()}"
        else:
            query = f"{symbol} cryptocurrency"

        # 构建参数
        params = {
            'q': query,
            'apiKey': newsapi_key,
            'language': 'en',
            'sortBy': 'publishedAt',
            'pageSize': min(limit * 2, 100),  # 获取更多以便过滤
            'from': (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')  # 最近7天
        }

        logger.info(f"Fetching NewsAPI crypto news with query: {query}")

        response = requests.get(newsapi_url, params=params, timeout=10)
        logger.info(f"NewsAPI response status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            articles = data.get('articles', [])
            logger.info(f"NewsAPI returned {len(articles)} articles")

            # 过滤和格式化结果
            filtered_articles = []
            for article in articles:
                # 跳过移除的文章
                if article.get('title') == '[Removed]':
                    continue

                filtered_articles.append({
                    'id': hash(article.get('url', '')),
                    'title': article.get('title'),
                    'url': article.get('url'),  # 原始新闻源URL
                    'published_at': article.get('publishedAt'),
                    'source': article.get('source', {}).get('name', 'NewsAPI'),
                    'body': article.get('description', ''),
                    'source_type': 'newsapi'
                })

                if len(filtered_articles) >= limit:
                    break

            return filtered_articles
        else:
            logger.error(f"NewsAPI error: {response.status_code} - {response.text}")
            return []

    except Exception as e:
        logger.error(f"NewsAPI error: {str(e)}")
        return []


def fetch_tiingo_news_sync(tickers, limit, tiingo_token):
    """同步获取Tiingo新闻（用于美股）"""
    try:
        if not tiingo_token:
            logger.warning("Tiingo API key not available")
            return []

        tiingo_url = f"https://api.tiingo.com/tiingo/news"
        params = {
            'tickers': tickers,
            'limit': limit,
            'token': tiingo_token
        }

        response = requests.get(tiingo_url, params=params, timeout=5)
        if response.status_code == 200:
            return response.json()
        return []
    except Exception as e:
        logger.error(f"Tiingo API error: {str(e)}")
        return []


def fetch_alphavantage_news_sync(symbol, limit, av_key):
    """同步获取Alpha Vantage新闻"""
    try:
        logger.info(f"Alpha Vantage API key available: {bool(av_key)}")

        if not av_key:
            logger.warning("Alpha Vantage API key not available")
            return []

        # Alpha Vantage News API URL
        av_url = "https://www.alphavantage.co/query"

        # 构建参数
        params = {
            'function': 'NEWS_SENTIMENT',
            'tickers': f"CRYPTO:{symbol.upper()}",
            'apikey': av_key,
            'limit': limit * 2  # 获取更多以便过滤
        }

        logger.info(f"Fetching Alpha Vantage news for {symbol}")

        response = requests.get(av_url, params=params, timeout=10)
        logger.info(f"Alpha Vantage API response status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            articles = data.get('feed', [])
            logger.info(f"Alpha Vantage returned {len(articles)} articles")

            # 格式化结果
            formatted_articles = []
            for article in articles:
                formatted_articles.append({
                    'id': hash(article.get('url', '')),
                    'title': article.get('title'),
                    'url': article.get('url'),  # 原始新闻源URL
                    'published_at': article.get('time_published'),
                    'source': article.get('source', 'Alpha Vantage'),
                    'body': article.get('summary', ''),
                    'source_type': 'alphavantage'
                })

                if len(formatted_articles) >= limit:
                    break

            return formatted_articles
        else:
            logger.error(f"Alpha Vantage API error: {response.status_code} - {response.text}")
            return []

    except Exception as e:
        logger.error(f"Alpha Vantage API error: {str(e)}")
        return []


def fetch_coingecko_news_sync(symbol, limit, crypto_key=None):
    """同步获取CoinGecko新闻"""
    try:
        logger.info(f"CoinGecko API key available: {bool(crypto_key)}")
        logger.info(f"CoinGecko API key (first 10 chars): {crypto_key[:10] if crypto_key else 'None'}")

        if not crypto_key:
            logger.warning("CoinGecko API key not available")
            return []

        # 根据API密钥类型确定URL
        # Pro API密钥通常以 'CG-' 开头
        if crypto_key.startswith('CG-'):
            base_url = "https://pro-api.coingecko.com/api/v3"
            headers = {
                'Content-Type': 'application/json',
                'x-cg-pro-api-key': crypto_key
            }
            logger.info("Using CoinGecko Pro API")
        else:
            base_url = "https://api.coingecko.com/api/v3"
            headers = {
                'Content-Type': 'application/json',
                'x-cg-demo-api-key': crypto_key
            }
            logger.info("Using CoinGecko Demo API")

        crypto_url = f"{base_url}/news"
        params = {
            'page': 1,
            'per_page': limit * 2  # 获取更多新闻以便过滤
        }

        logger.info(f"Trying CoinGecko API URL: {crypto_url}")
        response = requests.get(crypto_url, params=params, headers=headers, timeout=10)
        logger.info(f"CoinGecko API response status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            results = data.get('data', [])
            logger.info(f"CoinGecko returned {len(results)} news items")

            # 格式化新闻数据
            formatted_news = []
            for news in results:
                formatted_news.append({
                    'id': news.get('id'),
                    'title': news.get('title'),
                    'url': news.get('url'),  # CoinGecko提供原始新闻URL
                    'published_at': news.get('updated_at') or news.get('created_at'),
                    'source': news.get('news_site', 'CoinGecko'),
                    'body': news.get('description', ''),
                    'source_type': 'coingecko'
                })

                if len(formatted_news) >= limit:
                    break

            return formatted_news
        else:
            logger.error(f"CoinGecko API failed: {response.status_code} - {response.text}")
            return []

    except Exception as e:
        logger.error(f"CoinGecko API error: {str(e)}")
        return []


@csrf_exempt
@require_http_methods(["GET"])
def get_news_by_market(request, symbol):
    """
    根据市场类型获取新闻 - 统一接口
    支持加密货币和美股市场
    """
    try:
        # 获取请求参数
        limit = int(request.GET.get('limit', '10'))
        market_type = request.GET.get('market_type', None)

        # 如果没有指定市场类型，通过请求路径检测
        if not market_type:
            market_type = detect_market_type(symbol, request.path, request)

        logger.info(f"Getting news for {symbol} in {market_type} market")

        # 检查缓存
        cache_key = f"{market_type}_news_{symbol.upper()}_{limit}"
        skip_cache = request.GET.get('skip_cache', 'false').lower() == 'true'

        if not skip_cache:
            cached_news = cache.get(cache_key)
            if cached_news:
                logger.info(f"Returning cached news for {symbol} ({market_type})")
                return JsonResponse({
                    'status': 'success',
                    'data': cached_news,
                    'cached': True
                })

        # 根据市场类型获取新闻
        if market_type == 'crypto':
            news_data = get_crypto_news_data(symbol, limit)
        elif market_type == 'stock':
            news_data = get_stock_news_data(symbol, limit)
        elif market_type == 'china':
            news_data = get_china_stock_news_data(symbol, limit)
        else:
            return JsonResponse({
                'status': 'error',
                'message': f'Unsupported market type: {market_type}'
            }, status=400)

        # 缓存结果（1分钟）
        if news_data:
            cache.set(cache_key, news_data, 60)

        return JsonResponse({
            'status': 'success',
            'data': news_data,
            'cached': False,
            'market_type': market_type
        })

    except Exception as e:
        logger.error(f"Unexpected error in get_news_by_market: {str(e)}")
        return JsonResponse({
            'status': 'error',
            'message': 'Internal server error'
        }, status=500)


def get_crypto_news_data(symbol, limit):
    """获取加密货币新闻数据"""
    logger.info(f"Getting crypto news for {symbol}")

    news_data = []

    # 使用线程池并行调用多个RSS源
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = []

        # RSS新闻源 (主要新闻源，免费且提供原始URL)
        futures.append(('coindesk', executor.submit(
            fetch_coindesk_news_sync,
            symbol,
            limit // 4
        )))

        futures.append(('cointelegraph', executor.submit(
            fetch_cointelegraph_news_sync,
            symbol,
            limit // 4
        )))

        futures.append(('decrypt', executor.submit(
            fetch_decrypt_news_sync,
            symbol,
            limit // 4
        )))

        futures.append(('beincrypto', executor.submit(
            fetch_beincrypto_news_sync,
            symbol,
            limit // 4
        )))

        # API新闻源 (备用)
        newsapi_key = getattr(settings, 'NEWSAPI_KEY', None)
        if newsapi_key:
            futures.append(('newsapi', executor.submit(
                fetch_newsapi_crypto_news_sync,
                symbol,
                limit // 4,
                newsapi_key
            )))

        # 收集结果
        for source_name, future in futures:
            try:
                source_news = future.result(timeout=10)
                if source_news:
                    news_data.extend(source_news)
                    logger.info(f"{source_name} returned {len(source_news)} news items")
            except Exception as e:
                logger.error(f"{source_name} error: {str(e)}")

    # 去重和排序
    seen_urls = set()
    unique_news = []
    for news in news_data:
        url = news.get('url', '')
        title = news.get('title', '')

        # 使用URL和标题的组合来去重
        unique_key = url or title
        if unique_key and unique_key not in seen_urls:
            seen_urls.add(unique_key)
            unique_news.append(news)

    # 按发布时间排序（RSS的pubDate格式可能不同，所以使用简单排序）
    try:
        # 将新闻按来源分组，然后合并
        unique_news.sort(key=lambda x: x.get('published_at', ''), reverse=True)
    except Exception as e:
        logger.error(f"Error sorting news: {str(e)}")
        # 如果排序失败，至少保持原有顺序
        pass

    return unique_news[:limit]


def get_stock_news_data(symbol, limit):
    """获取美股新闻数据"""
    # 获取API密钥
    tiingo_token = getattr(settings, 'TIINGO_API_KEY', None)
    newsapi_key = getattr(settings, 'NEWSAPI_KEY', None)

    logger.info(f"Tiingo key available: {bool(tiingo_token)}")
    logger.info(f"NewsAPI key available: {bool(newsapi_key)}")

    news_data = []

    # 使用线程池并行调用API
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = []

        # Tiingo (主要美股新闻源)
        if tiingo_token:
            futures.append(('tiingo', executor.submit(
                fetch_tiingo_news_sync,
                symbol.upper(),
                limit,
                tiingo_token
            )))

        # NewsAPI (备用新闻源，搜索股票相关新闻)
        if newsapi_key:
            futures.append(('newsapi', executor.submit(
                fetch_newsapi_stock_news_sync,
                symbol,
                limit // 2,
                newsapi_key
            )))

        # 收集结果
        for source_name, future in futures:
            try:
                source_news = future.result(timeout=8)
                if source_news:
                    # 格式化Tiingo新闻数据
                    if source_name == 'tiingo':
                        formatted_news = []
                        for news in source_news:
                            formatted_news.append({
                                'id': news.get('id'),
                                'title': news.get('title'),
                                'url': news.get('url'),
                                'published_at': news.get('publishedDate'),
                                'source': news.get('source', 'Tiingo'),
                                'body': news.get('description', ''),
                                'source_type': 'tiingo'
                            })
                        news_data.extend(formatted_news)
                    else:
                        news_data.extend(source_news)

                    logger.info(f"{source_name} returned {len(source_news)} news items")
            except Exception as e:
                logger.error(f"{source_name} API error: {str(e)}")

    # 去重和排序
    seen_urls = set()
    unique_news = []
    for news in news_data:
        url = news.get('url', '')
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_news.append(news)

    # 按发布时间排序
    try:
        unique_news.sort(key=lambda x: x.get('published_at', ''), reverse=True)
    except Exception as e:
        logger.error(f"Error sorting news: {str(e)}")

    return unique_news[:limit]


def fetch_newsapi_stock_news_sync(symbol, limit, newsapi_key):
    """同步获取NewsAPI美股新闻"""
    try:
        if not newsapi_key:
            return []

        # NewsAPI URL
        newsapi_url = "https://newsapi.org/v2/everything"

        # 构建搜索查询
        query = f"{symbol} stock OR {symbol} shares"

        # 构建参数
        params = {
            'q': query,
            'apiKey': newsapi_key,
            'language': 'en',
            'sortBy': 'publishedAt',
            'pageSize': min(limit * 2, 100),
            'from': (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        }

        response = requests.get(newsapi_url, params=params, timeout=10)

        if response.status_code == 200:
            data = response.json()
            articles = data.get('articles', [])

            # 格式化结果
            formatted_articles = []
            for article in articles:
                if article.get('title') == '[Removed]':
                    continue

                formatted_articles.append({
                    'id': hash(article.get('url', '')),
                    'title': article.get('title'),
                    'url': article.get('url'),
                    'published_at': article.get('publishedAt'),
                    'source': article.get('source', {}).get('name', 'NewsAPI'),
                    'body': article.get('description', ''),
                    'source_type': 'newsapi'
                })

                if len(formatted_articles) >= limit:
                    break

            return formatted_articles
        else:
            logger.error(f"NewsAPI stock news error: {response.status_code}")
            return []

    except Exception as e:
        logger.error(f"NewsAPI stock news error: {str(e)}")
        return []


def get_china_stock_news_data(symbol, limit):
    """获取A股新闻数据"""
    from .services.tushare_api import TushareAPI

    logger.info(f"Getting China stock news for {symbol}")

    news_data = []

    try:
        # 初始化Tushare API
        tushare_api = TushareAPI()

        # 格式化股票代码
        ts_code = tushare_api.format_symbol(symbol)

        # 尝试从Tushare获取新闻（如果API支持）
        # 注意：Tushare的新闻接口可能需要更高级别的权限
        try:
            # 这里可以扩展Tushare API来获取新闻
            # 目前先使用模拟数据或通用新闻源
            pass
        except Exception as e:
            logger.warning(f"Tushare news API not available: {str(e)}")

        # 使用通用新闻API搜索A股相关新闻
        newsapi_key = getattr(settings, 'NEWSAPI_KEY', None)
        if newsapi_key:
            try:
                # 获取股票基本信息用于搜索
                stock_info = tushare_api.get_stock_basic()
                stock_name = None

                if stock_info is not None and not stock_info.empty:
                    # 查找对应的股票名称
                    matching_stocks = stock_info[stock_info['ts_code'] == ts_code]
                    if not matching_stocks.empty:
                        stock_name = matching_stocks.iloc[0]['name']

                # 构建搜索查询
                if stock_name:
                    query = f"{stock_name} OR {ts_code} OR {symbol}"
                else:
                    query = f"{ts_code} OR {symbol}"

                # 添加A股相关关键词
                query += " 股票 OR 上市公司 OR A股"

                # 调用NewsAPI
                china_news = fetch_newsapi_china_stock_news_sync(query, limit, newsapi_key)
                if china_news:
                    news_data.extend(china_news)

            except Exception as e:
                logger.error(f"Error fetching China stock news from NewsAPI: {str(e)}")

        # 如果没有获取到新闻，返回默认消息
        if not news_data:
            logger.info(f"No news found for China stock {symbol}")
            return []

        # 去重和排序
        seen_urls = set()
        unique_news = []
        for news in news_data:
            url = news.get('url', '')
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_news.append(news)

        # 按发布时间排序
        try:
            unique_news.sort(key=lambda x: x.get('published_at', ''), reverse=True)
        except Exception as e:
            logger.error(f"Error sorting China stock news: {str(e)}")

        return unique_news[:limit]

    except Exception as e:
        logger.error(f"Error in get_china_stock_news_data: {str(e)}")
        return []


def fetch_newsapi_china_stock_news_sync(query, limit, newsapi_key):
    """同步获取NewsAPI A股新闻"""
    try:
        if not newsapi_key:
            return []

        # NewsAPI URL
        newsapi_url = "https://newsapi.org/v2/everything"

        # 构建参数
        params = {
            'q': query,
            'apiKey': newsapi_key,
            'language': 'zh',  # 中文新闻
            'sortBy': 'publishedAt',
            'pageSize': min(limit * 2, 100),
            'from': (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        }

        response = requests.get(newsapi_url, params=params, timeout=10)

        if response.status_code == 200:
            data = response.json()
            articles = data.get('articles', [])

            # 格式化结果
            formatted_articles = []
            for article in articles:
                if article.get('title') == '[Removed]':
                    continue

                formatted_articles.append({
                    'id': hash(article.get('url', '')),
                    'title': article.get('title'),
                    'url': article.get('url'),
                    'published_at': article.get('publishedAt'),
                    'source': article.get('source', {}).get('name', 'NewsAPI'),
                    'body': article.get('description', ''),
                    'source_type': 'newsapi_china'
                })

                if len(formatted_articles) >= limit:
                    break

            return formatted_articles
        else:
            logger.error(f"NewsAPI China stock news error: {response.status_code}")
            return []

    except Exception as e:
        logger.error(f"NewsAPI China stock news error: {str(e)}")
        return []


# 保持向后兼容的函数别名
@csrf_exempt
@require_http_methods(["GET"])
def get_crypto_news(request, symbol):
    """获取加密货币新闻 - 向后兼容接口"""
    # 设置市场类型为crypto
    request.GET = request.GET.copy()
    request.GET['market_type'] = 'crypto'
    return get_news_by_market(request, symbol)
