#!/bin/bash

echo "Checking Celery status..."

# 检查 Celery Worker 进程
WORKER_COUNT=$(ps aux | grep -i "celery worker" | grep -v grep | wc -l)
if [ $WORKER_COUNT -gt 0 ]; then
    echo "Celery Worker is running:"
    ps aux | grep -i "celery worker" | grep -v grep
else
    echo "Celery Worker is NOT running!"
fi

# 检查 Celery Beat 进程
BEAT_COUNT=$(ps aux | grep -i "celery beat" | grep -v grep | wc -l)
if [ $BEAT_COUNT -gt 0 ]; then
    echo "Celery Beat is running:"
    ps aux | grep -i "celery beat" | grep -v grep
else
    echo "Celery Beat is NOT running!"
fi

# 检查日志文件
echo ""
echo "Celery Worker log (last 5 lines):"
if [ -f "celery_worker.log" ]; then
    tail -n 5 celery_worker.log
else
    echo "Worker log file not found!"
fi

echo ""
echo "Celery Beat log (last 5 lines):"
if [ -f "celery_beat.log" ]; then
    tail -n 5 celery_beat.log
else
    echo "Beat log file not found!"
fi

echo ""
echo "Done!"
