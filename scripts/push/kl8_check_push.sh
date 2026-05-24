#!/bin/bash
# KL8 health check push script - thin wrapper for hermes cron
# Runs check.py; only outputs to stdout (for delivery) on failure.
# Designed for hermes no_agent=true mode with deliver=origin.
set -Eeuo pipefail

PROJECT_DIR="/home/admin/bendi/lottery-analysis"
cd "$PROJECT_DIR"

LOG_DIR="logs/push"
mkdir -p "$LOG_DIR"
TODAY="$(date +%F)"
LOG_FILE="$LOG_DIR/kl8_check_${TODAY}.log"

if [ ! -x ".venv/bin/python" ]; then
    echo "[$(date '+%F %T')] .venv/bin/python 不存在" >> "$LOG_FILE"
    exit 3
fi

export PYTHONPATH="$PROJECT_DIR"

{
    echo "========== kl8_check start $(date '+%F %T') =========="
} >> "$LOG_FILE"

# 运行检查，捕获输出和退出码
OUTPUT=$(.venv/bin/python scripts/kl8/check.py 2>&1) && EXIT_CODE=$? || EXIT_CODE=$?

{
    echo "$OUTPUT"
    echo "========== kl8_check end $(date '+%F %T'), exit=$EXIT_CODE =========="
    echo
} >> "$LOG_FILE"

if [ "$EXIT_CODE" -ne 0 ]; then
    # 异常时输出到 stdout，Hermes deliver=origin 会推送
    echo "KL8 健康检查异常｜$(date '+%F %T')"
    echo ""
    echo "$OUTPUT"
    exit 0  # 不阻塞 cron，内容已通过 stdout 推送
fi

# 正常时静默（stdout 无输出 = 不推送）
exit 0
