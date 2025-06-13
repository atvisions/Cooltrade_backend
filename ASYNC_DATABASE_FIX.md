# Django异步视图数据库线程安全问题修复

## 问题描述

在Django异步视图中遇到了数据库线程安全问题，主要表现为：

1. **线程安全错误**: `DatabaseWrapper objects created in a thread can only be used in that same thread`
2. **数据库连接错误**: `django.db.utils.InterfaceError: (0, '')`

这些错误发生在 `/api/crypto/technical-indicators/ETHUSDT/` 等异步API端点中。

## 根本原因

Django的数据库连接对象在异步环境中被不同线程共享，导致线程安全问题。主要原因包括：

1. 在异步视图中直接使用 `connection.close()` 
2. 多次调用 `close_old_connections()` 而没有正确的线程隔离
3. 数据库连接池配置不适合异步环境

## 解决方案

### 1. 修改数据库配置 (`backend/config/settings.py`)

```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'cooltrade',
        'USER': 'root',
        'PASSWORD': '@Liuzhao-9575@',
        'HOST': 'localhost',
        'PORT': '3306',
        'OPTIONS': {
            'charset': 'utf8mb4',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            'autocommit': True,
        },
        'CONN_MAX_AGE': 0,  # 禁用持久连接以适配异步视图
        'ATOMIC_REQUESTS': False,  # 禁用原子请求以提高异步兼容性
    }
}
```

### 2. 重构异步数据库操作 (`backend/CryptoAnalyst/views_technical_indicators.py`)

#### 修改前的问题代码：
```python
# 问题：复杂的重试逻辑和手动连接管理
for attempt in range(max_retries):
    try:
        close_old_connections()
        @sync_to_async
        def get_token():
            # 数据库操作
        token = await get_token()
        close_old_connections()
        if token:
            break
    except (OperationalError, InterfaceError) as e:
        await sync_to_async(connection.close)()  # 线程不安全
        close_old_connections()
```

#### 修改后的解决方案：
```python
# 解决方案：简化的线程安全操作
@sync_to_async
def get_token_safe():
    """Thread-safe token retrieval"""
    try:
        token = Token.objects.filter(symbol=symbol.upper()).first()
        if not token:
            token = Token.objects.filter(symbol=clean_symbol).first()
        return token
    except Exception as e:
        logger.error(f"Error occurred while querying token record: {str(e)}")
        raise

token = await get_token_safe()
```

### 3. 修复的关键点

1. **移除手动连接管理**: 不再手动调用 `connection.close()`
2. **简化异步包装**: 每个数据库操作使用独立的 `@sync_to_async` 装饰器
3. **线程安全函数**: 将所有数据库查询封装在线程安全的函数中
4. **移除重试逻辑**: 依赖Django的内置连接管理而不是手动重试

### 4. 修复的文件

- `backend/config/settings.py` - 数据库配置优化
- `backend/CryptoAnalyst/views_technical_indicators.py` - 主要异步视图修复
- `backend/CryptoAnalyst/views_indicators_data.py` - 相关异步视图修复

## 测试验证

运行测试脚本验证修复效果：

```bash
cd backend
python test_async_fix.py
```

## 最佳实践

1. **异步视图中的数据库操作**:
   - 始终使用 `@sync_to_async` 包装数据库操作
   - 避免手动管理数据库连接
   - 每个数据库操作使用独立的异步函数

2. **数据库配置**:
   - 异步环境中设置 `CONN_MAX_AGE = 0`
   - 禁用 `ATOMIC_REQUESTS` 以提高异步兼容性

3. **错误处理**:
   - 依赖Django的内置错误处理
   - 避免复杂的手动重试逻辑

## 预期效果

修复后，异步API端点应该能够：
- 正常处理并发请求
- 避免线程安全错误
- 提供稳定的数据库连接
- 减少 `InterfaceError` 和连接超时问题
