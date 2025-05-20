#!/bin/bash

echo "Restarting Celery..."

# 停止 Celery
./stop_celery.sh

# 等待进程完全停止
sleep 3

# 启动 Celery
./start_celery.sh

echo "Celery restart completed."
