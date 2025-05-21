#!/bin/bash

echo "Restarting Celery..."

# 获取脚本所在目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# 停止 Celery
$SCRIPT_DIR/stop_celery.sh

# 等待进程完全停止
sleep 3

# 启动 Celery
$SCRIPT_DIR/start_celery.sh

echo "Celery restart completed."
