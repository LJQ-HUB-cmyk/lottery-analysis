#!/usr/bin/env python3
"""
快乐8 复盘 Job —— 替代 kl8_review_push.sh 中的业务逻辑。

职责：
  1. 拉取最新开奖
  2. 删旧文件 + 时间戳校验 → 防旧数据误推
  3. 执行 reviewer + metrics
  4. 计算 dedup_key → 调用 hermes_push
  5. 写 status.json

退出码：0=正常（含等待开奖），2=异常，3=环境错误
"""

import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
PY = sys.executable

CN_TZ = timezone(timedelta(hours=8))

KL8_OUTPUT = BASE / "output" / "kl8"
REVIEW_FILE = KL8_OUTPUT / "kl8_review_latest.json"
PREDICT_FILE = KL8_OUTPUT / "kl8_predict_latest.json"

# 确保能 import 项目内模块
sys.path.insert(0, str(BASE))


def now() -> datetime:
    return datetime.now(CN_TZ)


def run(cmd: list[str], desc: str, timeout: int = 300) -> bool:
    """执行子进程。返回 True=成功。"""
    print(f"  [{desc}] 执行中...")
    result = subprocess.run(
        [PY] + cmd,
        cwd=str(BASE),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    output = result.stdout.decode("utf-8", errors="replace")
    for line in output.strip().split("\n")[-8:]:
        print(f"    {line}")
    ok = result.returncode == 0
    print(f"  → {'✅ 成功' if ok else '⚠️ 失败'} (exit={result.returncode})")
    return ok


def main():
    from scripts.lib.job_status import write, read, READY, PUSHED, SKIPPED_WAITING, SKIPPED_ALREADY_SENT, ERROR

    status = {
        "task": "kl8_review",
        "date": now().strftime("%Y-%m-%d"),
        "run_id": f"kl8_review_{now().strftime('%Y%m%d_%H%M%S')}",
        "status": READY,
        "ok": True,
        "should_push": False,
        "reason": "",
        "dedup_key": "",
        "started_at": now().strftime("%Y-%m-%dT%H:%M:%S%z"),
    }

    try:
        # ── Step 1: 拉取最新开奖 ──
        ok_fetch = run(["scripts/kl8/fetcher.py", "--pages", "3"], "KL8 拉取开奖数据")
        if not ok_fetch:
            print("[WARN] KL8 fetcher 返回非零，继续尝试复盘...")

        # ── Step 2: 删旧文件 + 记时间戳 ──
        if REVIEW_FILE.exists():
            REVIEW_FILE.unlink()
            print(f"  已删除旧复盘文件: {REVIEW_FILE}")
        start_ts = time.time()

        # ── Step 3: 执行 reviewer ──
        ok_review = run(["scripts/kl8/reviewer.py"], "KL8 生成复盘")
        if not ok_review:
            print("[WARN] KL8 reviewer 返回非零")

        # ── Step 4: 文件存在 + 时间戳校验 ──
        if not REVIEW_FILE.exists():
            status["status"] = SKIPPED_WAITING
            status["should_push"] = False
            status["reason"] = "复盘文件未生成（开奖数据可能未就绪）"
            print(f"[SKIP] {status['reason']}")
            write("kl8_review", status)
            sys.exit(0)

        file_ts = REVIEW_FILE.stat().st_mtime
        if file_ts < start_ts:
            status["status"] = SKIPPED_WAITING
            status["should_push"] = False
            status["reason"] = f"复盘文件非本轮生成（file_ts={file_ts:.0f} < start_ts={start_ts:.0f}）"
            print(f"[SKIP] {status['reason']}")
            write("kl8_review", status)
            sys.exit(0)

        # ── Step 5: 校验 JSON 内容 ──
        try:
            review_data = json.loads(REVIEW_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            status["status"] = ERROR
            status["ok"] = False
            status["reason"] = f"复盘 JSON 解析失败: {e}"
            print(f"[ERROR] {status['reason']}")
            write("kl8_review", status)
            sys.exit(2)

        review_issue = str(review_data.get("issue", ""))
        pred_data = {}
        if PREDICT_FILE.exists():
            try:
                pred_data = json.loads(PREDICT_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        target_issue = str(pred_data.get("predicted_issue", ""))

        if not review_issue:
            status["status"] = ERROR
            status["ok"] = False
            status["reason"] = "复盘 JSON 中 issue 为空"
            print(f"[ERROR] {status['reason']}")
            write("kl8_review", status)
            sys.exit(2)

        # 期号闸门：复盘期号必须匹配预测期号
        if target_issue and review_issue != target_issue:
            status["status"] = SKIPPED_WAITING
            status["should_push"] = False
            status["reason"] = f"复盘期号 {review_issue} ≠ 预测期号 {target_issue}，等待新数据"
            print(f"[SKIP] {status['reason']}")
            write("kl8_review", status)
            sys.exit(0)

        # ── Step 6: 生成累计表现 ──
        run(["scripts/kl8/metrics.py"], "KL8 累计表现", timeout=120)

        # ── Step 7: 计算 dedup_key → 推送 ──
        status["dedup_key"] = f"kl8_review:{review_issue}"
        status["should_push"] = True
        status["status"] = READY
        status["reason"] = ""
        status["issues"] = {"kl8": review_issue}
        status["finished_at"] = now().strftime("%Y-%m-%dT%H:%M:%S%z")
        write("kl8_review", status)

        # 调用 hermes_push 输出推送内容到 stdout
        result = subprocess.run(
            [PY, "scripts/hermes_push.py", "--mode", "review", "--lottery", "kl8",
             "--dedup-key", status["dedup_key"], "--stdout"],
            cwd=str(BASE),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
        )
        stderr_output = result.stderr.decode("utf-8", errors="replace")
        if stderr_output:
            print(stderr_output, file=sys.stderr)

        if result.returncode != 0:
            print(f"[WARN] hermes_push 返回 exit={result.returncode}", file=sys.stderr)

        stdout_text = result.stdout.decode("utf-8", errors="replace")
        if stdout_text.strip():
            print(stdout_text)

        if "[跳过]" in stderr_output and "已推送过" in stderr_output:
            status["status"] = SKIPPED_ALREADY_SENT
            write("kl8_review", status)

        sys.exit(0)

    except Exception as e:
        status["status"] = ERROR
        status["ok"] = False
        status["reason"] = f"未预期异常: {e}"
        print(f"[ERROR] {status['reason']}", file=sys.stderr)
        write("kl8_review", status)
        sys.exit(2)


if __name__ == "__main__":
    main()
