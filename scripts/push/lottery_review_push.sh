#!/bin/bash
# Lottery review push script - thin wrapper, all business logic in lottery_review_job.py
# Designed for hermes cron no_agent=true mode.
# Usage:
#   bash lottery_review_push.sh                     # all, normal stage (backward compat)
#   bash lottery_review_push.sh --lottery pls       # PLS only
#   bash lottery_review_push.sh --lottery d3        # D3 only
#   bash lottery_review_push.sh --prepare-only      # fetch + compare only, no push
#   bash lottery_review_push.sh --lottery pls --final  # PLS with fallback
set -Eeuo pipefail

PROJECT_DIR="/home/admin/bendi/lottery-analysis"
cd "$PROJECT_DIR"

LOG_DIR="logs/push"
mkdir -p "$LOG_DIR"

TODAY="$(date +%F)"

# ── 参数解析 ──
LOTTERY="all"
PREPARE_ONLY=0
STAGE="normal"

while [ $# -gt 0 ]; do
  case "$1" in
    --final)       STAGE="final" ;;
    --lottery)     LOTTERY="$2"; shift ;;
    --pls)         LOTTERY="pls" ;;
    --d3)          LOTTERY="d3" ;;
    --prepare-only) PREPARE_ONLY=1 ;;
  esac
  shift
done

LOG_FILE="$LOG_DIR/lottery_review_${LOTTERY}_${TODAY}.log"

# 全流程锁，按彩种隔离（PLS和D3不互斥）
LOCK_FILE="/tmp/lottery_review_${LOTTERY}.lock"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "[$(date '+%F %T')] 已有 lottery_review_${LOTTERY} 任务运行中，本轮跳过" >> "$LOG_FILE"
    exit 0
fi

if [ ! -x ".venv/bin/python" ]; then
    echo "[$(date '+%F %T')] .venv/bin/python 不存在" >> "$LOG_FILE"
    exit 3
fi

# 23 点后自动启用 final 阶段（兼容旧版无参调用）
if [ "$STAGE" = "normal" ] && [ "$(date +%H)" -ge 23 ]; then
    STAGE="final"
fi

export PYTHONPATH="$PROJECT_DIR"

{
    echo "========== lottery_review start $(date '+%F %T'), lottery=$LOTTERY, stage=$STAGE =========="
    echo "PROJECT_DIR=$PROJECT_DIR"
} >> "$LOG_FILE"

# ── 构建命令 ──
CMD=(.venv/bin/python scripts/jobs/lottery_review_job.py --stage "$STAGE" --lottery "$LOTTERY")

if [ "$PREPARE_ONLY" = "1" ]; then
  CMD+=(--prepare-only)
fi

set +e
"${CMD[@]}" 2>> "$LOG_FILE"
EXIT_CODE=$?
set -e

{
    echo "========== lottery_review end $(date '+%F %T'), exit=$EXIT_CODE =========="
    echo
} >> "$LOG_FILE"

exit "$EXIT_CODE"
