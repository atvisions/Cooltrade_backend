#!/bin/bash

echo "Stopping Celery processes..."

# 停止 Celery Beat
pkill -f "celery beat" || true
echo "Celery Beat stopped."

# 停止 Celery Worker
pkill -f "celery worker" || true
echo "Celery Worker stopped."

# 检查是否还有 Celery 进程在运行
CELERY_PROCESSES=$(ps aux | grep -i celery | grep -v grep | wc -l)
if [ $CELERY_PROCESSES -gt 0 ]; then
    echo "Warning: Some Celery processes are still running:"
    ps aux | grep -i celery | grep -v grep
    echo "You may need to kill them manually."
else
    echo "All Celery processes have been stopped successfully."
fi

echo "Done!"
