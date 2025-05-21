# 任务脚本

本目录包含各种任务脚本，用于执行定时任务、导入数据等操作。

## 脚本列表

### 1. 运行一次任务 (run_tasks_once.py)

立即执行一次技术指标更新和报告生成任务。

```bash
python scripts/tasks/run_tasks_once.py
```

### 2. 强制更新任务 (force_update_tasks.py)

强制执行一次技术指标更新和报告生成任务，忽略已有数据。这将删除当前周期的技术分析数据和最近24小时内的分析报告，然后重新生成。

```bash
python scripts/tasks/force_update_tasks.py
```

### 3. 测试定时任务 (test_tasks.py)

每5分钟执行一次技术指标更新和报告生成任务，用于测试定时任务是否正常工作。

```bash
python scripts/tasks/test_tasks.py
```

### 4. 导入Gate.io热门代币 (import_gate_tokens.py)

从Gate.io API获取交易量最大的前100个代币，并将它们导入到数据库中。

```bash
python scripts/tasks/import_gate_tokens.py
```

## 日志

所有脚本的日志文件都保存在`logs/`目录中，可以通过查看相应的日志文件来了解任务执行情况。

## 工具模块

`utils.py`提供了一些通用的工具函数，如设置Django环境、配置日志等。
