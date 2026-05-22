#!/usr/bin/env python3
"""
排列三 / 福彩3D 复盘 Job —— 替代 lottery_review_push.sh 中的业务逻辑。

职责：
  1. 执行 daily_review.py（拉取 + 特征 + 对比 + 摘要）
  2. 判断两种彩票开奖是否齐全
  3. normal 阶段：未齐则跳过，不推送
  4. final 阶段：未齐则输出兜底通知
  5. 齐全时调用 hermes_push 输出复盘
  6. 写 status.json

用法：
  python scripts/jobs/lottery_review_job.py --stage normal   # 21:35 / 22:05
  python scripts/jobs/lottery_review_job.py --stage final    # 23:10

退出码：0=正常（含等待开奖），2=异常，3=环境错误
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
PY = sys.executable

CN_TZ = timezone(timedelta(hours=8))

REPORT_DIR = BASE / "output" / "reports"
REVIEW_HISTORY = BASE / "output" / "reviews" / "review_history.csv"

sys.path.insert(0, str(BASE))


def now() -> datetime:
    return datetime.now(CN_TZ)


def today_str() -> str:
    return now().strftime("%Y-%m-%d")


def run(cmd: list[str], desc: str, timeout: int = 300) -> tuple[bool, str]:
    """执行子进程。返回 (ok, stderr_text)。"""
    print(f"  [{desc}] 执行中...", file=sys.stderr)
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    result = subprocess.run(
        [PY] + cmd,
        cwd=str(BASE),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        env=env,
    )
    stdout_text = result.stdout.decode("utf-8", errors="replace")
    stderr_text = result.stderr.decode("utf-8", errors="replace")
    combined = (stderr_text + stdout_text)[-2000:]
    for line in combined.strip().split("\n")[-6:]:
        if line.strip():
            print(f"    {line.strip()}", file=sys.stderr)
    ok = result.returncode == 0
    print(f"  -> {'[OK] 成功' if ok else '[WARN] 失败'} (exit={result.returncode})", file=sys.stderr)
    return ok, combined


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def check_lottery_ready(lottery: str) -> tuple[bool, str]:
    """
    检查指定彩种开奖数据是否就绪。
    通过 compare_latest.json 的 status 字段判断。
    返回 (ready, reason)。
    """
    path = REPORT_DIR / f"{lottery}_compare_latest.json"
    data = read_json(path)
    if not data:
        return False, "无 compare 数据"

    status = data.get("状态", "")
    error = data.get("错误", "")

    if status == "waiting_actual":
        return False, data.get("说明", "等待开奖数据")
    if error:
        return False, f"compare 异常: {error}"

    return True, ""


def main():
    from scripts.lib.job_status import write, READY, SKIPPED_WAITING, SKIPPED_ALREADY_SENT, ERROR

    parser = argparse.ArgumentParser(description="PLS/D3 复盘 Job")
    parser.add_argument("--stage", choices=["normal", "final"], default="normal",
                        help="normal=两彩种齐全才推送；final=不齐也推送兜底通知")
    args = parser.parse_args()

    status = {
        "task": "lottery_review",
        "date": today_str(),
        "run_id": f"lottery_review_{now().strftime('%Y%m%d_%H%M%S')}",
        "stage": args.stage,
        "status": READY,
        "ok": True,
        "should_push": False,
        "reason": "",
        "dedup_key": "",
        "issues": {},
        "started_at": now().strftime("%Y-%m-%dT%H:%M:%S%z"),
    }

    try:
        # ── Step 1: 执行 daily_review.py ──
        daily_ok, daily_output = run(
            ["scripts/daily_review.py"], "拉取开奖 + 特征工程 + 三策略对比 + 复盘摘要",
            timeout=600,
        )

        # ── Step 2: 检查两种彩票开奖是否齐全 ──
        pls_ready, pls_msg = check_lottery_ready("pls")
        d3_ready, d3_msg = check_lottery_ready("d3")
        both_ready = pls_ready and d3_ready

        # 尝试从 compare JSON 提取期号
        pls_data = read_json(REPORT_DIR / "pls_compare_latest.json")
        d3_data = read_json(REPORT_DIR / "d3_compare_latest.json")
        pls_issue = str(pls_data.get("期号", "") or pls_data.get("开奖期号", ""))
        d3_issue = str(d3_data.get("期号", "") or d3_data.get("开奖期号", ""))
        status["issues"] = {"pls": pls_issue, "d3": d3_issue}

        # ── Step 3: 根据齐全状态和 stage 决定行为 ──
        if not both_ready:
            missing = []
            if not pls_ready:
                missing.append(f"排列三({pls_msg})")
            if not d3_ready:
                missing.append(f"福彩3D({d3_msg})")
            missing_str = "、".join(missing)

            if args.stage == "normal":
                status["status"] = SKIPPED_WAITING
                status["should_push"] = False
                status["reason"] = f"开奖未齐: {missing_str}"
                print(f"[SKIP] {status['reason']}", file=sys.stderr)
                write("lottery_review", status)
                sys.exit(0)

            # final 阶段：调用 hermes_push --final-check 输出兜底通知
            status["dedup_key"] = f"review_missing:{today_str()}"
            status["should_push"] = True
            status["status"] = READY
            status["reason"] = f"开奖未齐({missing_str})，输出兜底通知"
            status["issues"] = {}
            status["finished_at"] = now().strftime("%Y-%m-%dT%H:%M:%S%z")
            write("lottery_review", status)

            # --final-check：hermes_push 检测数据未齐时自动生成兜底通知
            # dedup_key 确保同一日期只推一次，不加 --force
            result = subprocess.run(
                [PY, "scripts/hermes_push.py", "--mode", "review",
                 "--dedup-key", status["dedup_key"], "--final-check", "--stdout"],
                cwd=str(BASE),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
            )
            stderr_text = result.stderr.decode("utf-8", errors="replace")
            if stderr_text:
                print(stderr_text, file=sys.stderr)

            # 如果 hermes_push 因为去重跳过了，直接输出兜底文本
            if result.returncode == 0 and result.stdout.decode("utf-8", errors="replace").strip():
                print(result.stdout.decode("utf-8", errors="replace"))
            elif "[跳过]" in stderr_text:
                print(f"[SKIP] 兜底通知今日已发送过", file=sys.stderr)
                status["status"] = SKIPPED_ALREADY_SENT
                write("lottery_review", status)

            sys.exit(0)

        # ── Step 4: 两种彩票齐全 → 正常复盘 ──
        if not daily_ok:
            status["status"] = ERROR
            status["ok"] = False
            status["reason"] = "daily_review.py 执行异常"
            print(f"[ERROR] {status['reason']}", file=sys.stderr)
            write("lottery_review", status)
            sys.exit(2)

        status["dedup_key"] = f"review:{today_str()}:pls-{pls_issue}:d3-{d3_issue}"
        status["should_push"] = True
        status["status"] = READY
        status["reason"] = ""
        status["finished_at"] = now().strftime("%Y-%m-%dT%H:%M:%S%z")
        write("lottery_review", status)

        # 调用 hermes_push 输出复盘内容到 stdout
        result = subprocess.run(
            [PY, "scripts/hermes_push.py", "--mode", "review",
             "--dedup-key", status["dedup_key"], "--stdout"],
            cwd=str(BASE),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
        )
        stderr_text = result.stderr.decode("utf-8", errors="replace")
        if stderr_text:
            print(stderr_text, file=sys.stderr)

        stdout_text = result.stdout.decode("utf-8", errors="replace")
        if stdout_text.strip():
            print(stdout_text)

        if "[跳过]" in stderr_text and "已推送过" in stderr_text:
            status["status"] = SKIPPED_ALREADY_SENT
            write("lottery_review", status)

        sys.exit(0)

    except Exception as e:
        status["status"] = ERROR
        status["ok"] = False
        status["reason"] = f"未预期异常: {e}"
        print(f"[ERROR] {status['reason']}", file=sys.stderr)
        write("lottery_review", status)
        sys.exit(2)


if __name__ == "__main__":
    main()
