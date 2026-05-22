#!/bin/bash
# Lottery review push script - thin wrapper, all business logic in lottery_review_job.py
# Designed for hermes cron no_agent=true mode.
# --stage: normal=两彩种齐全才推送；final=不齐也推送兜底通知
set -Eeuo pipefail

PROJECT_DIR="/home/admin/bendi/lottery-analysis"
cd "$PROJECT_DIR"

LOG_DIR="logs/push"
mkdir -p "$LOG_DIR"

TODAY="$(date +%F)"
LOG_FILE="$LOG_DIR/lottery_review_${TODAY}.log"

# 全流程锁，防止三波任务重叠执行
LOCK_FILE="/tmp/lottery_review_push.lock"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "[$(date '+%F %T')] 已有 lottery_review 任务运行中，本轮跳过" >> "$LOG_FILE"
    exit 0
fi

if [ ! -x ".venv/bin/python" ]; then
    echo "[$(date '+%F %T')] .venv/bin/python 不存在" >> "$LOG_FILE"
    exit 3
fi

# 23 点后自动启用 final 阶段
STAGE="normal"
if [ "${1:-}" = "--final" ] || [ "$(date +%H)" -ge 23 ]; then
    STAGE="final"
fi

export PYTHONPATH="$PROJECT_DIR"

{
    echo "========== lottery_review start $(date '+%F %T'), stage=$STAGE =========="
    echo "PROJECT_DIR=$PROJECT_DIR"
} >> "$LOG_FILE"

.venv/bin/python scripts/jobs/lottery_review_job.py --stage "$STAGE" 2>> "$LOG_FILE"
EXIT_CODE=$?

{
    echo "========== lottery_review end $(date '+%F %T'), exit=$EXIT_CODE =========="
    echo
} >> "$LOG_FILE"

exit "$EXIT_CODE"
