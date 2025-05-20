#!/bin/bash

# 停止现有的 Celery 进程
echo "Stopping existing Celery processes..."
pkill -f "celery worker" || true
pkill -f "celery beat" || true
sleep 2

# 清理 Celery 的 PID 和日志文件
echo "Cleaning up Celery files..."
rm -f celerybeat.pid celerybeat-schedule.db celery.log celerybeat.log 2>/dev/null || true

# 设置日志文件
WORKER_LOG="celery_worker.log"
BEAT_LOG="celery_beat.log"

# 启动 Celery Worker
echo "Starting Celery Worker..."
celery -A config worker --loglevel=info --concurrency=2 --logfile=$WORKER_LOG --detach

# 启动 Celery Beat
echo "Starting Celery Beat..."
celery -A config beat --loglevel=info --logfile=$BEAT_LOG --detach

echo "Celery Worker and Beat started successfully!"
echo "Worker log: $WORKER_LOG"
echo "Beat log: $BEAT_LOG"

# 显示进程状态
echo "Celery processes:"
ps aux | grep -i celery | grep -v grep

echo "Done!"
