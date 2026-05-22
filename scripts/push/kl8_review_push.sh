#!/bin/bash
# KL8 review push script - thin wrapper, all business logic in kl8_review_job.py
# Designed for hermes cron no_agent=true mode.
set -Eeuo pipefail

PROJECT_DIR="/home/admin/bendi/lottery-analysis"
cd "$PROJECT_DIR"

LOG_DIR="logs/push"
mkdir -p "$LOG_DIR"

TODAY="$(date +%F)"
LOG_FILE="$LOG_DIR/kl8_review_${TODAY}.log"

# 全流程锁，防止重叠执行
LOCK_FILE="/tmp/kl8_review_push.lock"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "[$(date '+%F %T')] 已有 KL8 复盘任务运行中，本轮跳过" >> "$LOG_FILE"
    exit 0
fi

if [ ! -x ".venv/bin/python" ]; then
    echo "[$(date '+%F %T')] .venv/bin/python 不存在" >> "$LOG_FILE"
    exit 3
fi

export PYTHONPATH="$PROJECT_DIR"

{
    echo "========== kl8_review start $(date '+%F %T') =========="
    echo "PROJECT_DIR=$PROJECT_DIR"
} >> "$LOG_FILE"

set +e
.venv/bin/python scripts/jobs/kl8_review_job.py 2>> "$LOG_FILE"
EXIT_CODE=$?
set -e

{
    echo "========== kl8_review end $(date '+%F %T'), exit=$EXIT_CODE =========="
    echo
} >> "$LOG_FILE"

exit "$EXIT_CODE"
