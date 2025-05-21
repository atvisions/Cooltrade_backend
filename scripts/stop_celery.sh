#!/bin/bash

echo "Stopping Celery processes..."

# 停止 Celery Beat (使用更宽松的匹配模式)
pkill -f "celery.*beat" || true
echo "Celery Beat stopped."

# 停止 Celery Worker (使用更宽松的匹配模式)
pkill -f "celery.*worker" || true
echo "Celery Worker stopped."

# 获取当前脚本的PID
CURRENT_PID=$$

# 尝试停止所有剩余的 Celery 进程
echo "Stopping any remaining Celery processes..."
for pid in $(ps aux | grep -i celery | grep -v grep | awk '{print $2}')
do
    # 排除当前脚本的PID
    if [ "$pid" != "$CURRENT_PID" ]; then
        kill $pid 2>/dev/null || true
    fi
done

# 等待一会儿，确保进程有时间退出
sleep 2

# 检查是否还有 Celery 进程在运行
CELERY_PROCESSES=$(ps aux | grep -i celery | grep -v grep | grep -v $CURRENT_PID | wc -l)
if [ $CELERY_PROCESSES -gt 0 ]; then
    echo "Warning: Some Celery processes are still running:"
    ps aux | grep -i celery | grep -v grep | grep -v $CURRENT_PID
    echo "Attempting to force kill these processes..."

    # 尝试强制终止
    for pid in $(ps aux | grep -i celery | grep -v grep | grep -v $CURRENT_PID | awk '{print $2}')
    do
        kill -9 $pid 2>/dev/null || true
    done

    # 再次检查
    sleep 1
    CELERY_PROCESSES=$(ps aux | grep -i celery | grep -v grep | grep -v $CURRENT_PID | wc -l)
    if [ $CELERY_PROCESSES -gt 0 ]; then
        echo "Warning: Unable to kill all Celery processes. You may need to kill them manually."
        ps aux | grep -i celery | grep -v grep | grep -v $CURRENT_PID
    else
        echo "All Celery processes have been stopped successfully."
    fi
else
    echo "All Celery processes have been stopped successfully."
fi

echo "Done!"
