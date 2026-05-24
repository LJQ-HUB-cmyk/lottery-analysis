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
import time
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


def check_lottery_ready(lottery: str, start_ts: float = None) -> tuple[bool, str]:
    """
    检查指定彩种开奖数据是否就绪。
    通过 compare_latest.json 的 status 字段 + 文件修改时间判断。
    start_ts: 本轮 job 启动时间（用于防过期 compare 文件）。
    返回 (ready, reason)。
    """
    path = REPORT_DIR / f"{lottery}_compare_latest.json"
    data = read_json(path)
    if not data:
        return False, "无 compare 数据"

    status = data.get("状态", "")
    error = data.get("错误", "")

    # 检查文件是否本轮生成（防旧 compare JSON 被误判为就绪）
    if start_ts is not None:
        mtime = path.stat().st_mtime
        if mtime < start_ts - 2:
            return False, f"compare 文件不是本轮生成 (mtime={mtime:.0f} < start={start_ts:.0f})"

    if status == "waiting_actual":
        return False, data.get("说明", "等待开奖数据")
    if error:
        return False, f"compare 异常: {error}"

    return True, ""


def extract_actual_issue(data: dict) -> str:
    """
    从 compare_latest.json 中提取实际开奖期号。
    优先级：实际期号 > 期号 > 开奖期号 > 预测期号（仅期号匹配时兜底）。
    """
    if not data:
        return ""
    for key in ("实际期号", "期号", "开奖期号"):
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    # 最后兜底：预测期号匹配时才可以用预测期号
    if data.get("预测期号匹配") is True:
        value = data.get("预测期号")
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def main():
    from scripts.lib.job_status import write, READY, SKIPPED_WAITING, SKIPPED_ALREADY_SENT, ERROR

    parser = argparse.ArgumentParser(description="PLS/D3 复盘 Job")
    parser.add_argument("--stage", choices=["normal", "final"], default="normal",
                        help="normal=目标彩种齐全才推送；final=不齐也推送兜底通知")
    parser.add_argument("--lottery", choices=["all", "pls", "d3"], default="all",
                        help="all=排列三+福彩3D合并；pls=只排三；d3=只福彩3D")
    parser.add_argument("--prepare-only", action="store_true",
                        help="只拉取开奖并生成复盘数据，不推送")
    args = parser.parse_args()

    targets = ["pls", "d3"] if args.lottery == "all" else [args.lottery]
    task_name = f"lottery_review_{args.lottery}"

    status = {
        "task": task_name,
        "date": today_str(),
        "run_id": f"lottery_review_{args.lottery}_{now().strftime('%Y%m%d_%H%M%S')}",
        "stage": args.stage,
        "lottery": args.lottery,
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
        start_ts = time.time()
        daily_cmd = ["scripts/daily_review.py"]
        if args.lottery != "all":
            daily_cmd += ["--lottery", args.lottery]
        daily_ok, daily_output = run(
            daily_cmd, "拉取开奖 + 特征工程 + 三策略对比 + 复盘摘要",
            timeout=600,
        )

        # ── Step 2: 检查目标彩种开奖是否齐全 ──
        ready_map = {}
        issues = {}
        for lt in targets:
            r, msg = check_lottery_ready(lt, start_ts)
            ready_map[lt] = (r, msg)
            data = read_json(REPORT_DIR / f"{lt}_compare_latest.json")
            issue = extract_actual_issue(data)
            issues[lt] = issue
        status["issues"] = issues

        selected_ready = all(ready_map[k][0] for k in targets)

        # ── Step 2.5: prepare-only 模式 ──
        if args.prepare_only:
            status["should_push"] = False
            status["reason"] = "prepare-only：已完成开奖拉取和复盘准备，不推送"
            status["finished_at"] = now().strftime("%Y-%m-%dT%H:%M:%S%z")
            if not selected_ready:
                missing = [f"{k}({ready_map[k][1]})" for k in targets if not ready_map[k][0]]
                status["reason"] += f" | 未齐: {'、'.join(missing)}"
            write(task_name, status)
            print(f"[OK] prepare-only 完成，{status['reason']}", file=sys.stderr)
            sys.exit(0)

        # ── Step 2.5: 期号空校验 —— 已就绪的彩种必须能提取实际期号 ──
        if not args.prepare_only:
            for lt in targets:
                if ready_map[lt][0] and not issues.get(lt):
                    status["status"] = ERROR
                    status["ok"] = False
                    status["should_push"] = False
                    status["reason"] = f"{lt} compare 已就绪，但无法提取实际期号，禁止生成空期号 dedup_key"
                    write(task_name, status)
                    print(f"[ERROR] {status['reason']}", file=sys.stderr)
                    sys.exit(2)

        # ── Step 3: 构建 dedup_key（单彩种）──
        if args.lottery == "pls":
            pls_i = issues.get("pls", "?")
            dedup_key = f"review:{today_str()}:pls-{pls_i}"
            miss_key = f"review_missing:{today_str()}:pls"
        elif args.lottery == "d3":
            d3_i = issues.get("d3", "?")
            dedup_key = f"review:{today_str()}:d3-{d3_i}"
            miss_key = f"review_missing:{today_str()}:d3"
        else:
            pls_i = issues.get("pls", "?")
            d3_i = issues.get("d3", "?")
            dedup_key = f"review:{today_str()}:pls-{pls_i}:d3-{d3_i}"
            miss_key = f"review_missing:{today_str()}"

        # ── Step 4: 根据齐全状态和 stage 决定行为 ──
        if not selected_ready:
            missing = []
            for k in targets:
                if not ready_map[k][0]:
                    label = "排列三" if k == "pls" else "福彩3D"
                    missing.append(f"{label}({ready_map[k][1]})")
            missing_str = "、".join(missing)

            if args.stage == "normal":
                status["status"] = SKIPPED_WAITING
                status["should_push"] = False
                status["reason"] = f"开奖未齐: {missing_str}"
                print(f"[SKIP] {status['reason']}", file=sys.stderr)
                write(task_name, status)
                sys.exit(0)

            # final 阶段：输出兜底通知
            status["dedup_key"] = miss_key
            status["should_push"] = True
            status["status"] = READY
            status["reason"] = f"开奖未齐({missing_str})，输出兜底通知"
            status["finished_at"] = now().strftime("%Y-%m-%dT%H:%M:%S%z")
            write(task_name, status)

            result = subprocess.run(
                [PY, "scripts/hermes_push.py", "--mode", "review",
                 "--lottery", args.lottery,
                 "--dedup-key", miss_key, "--final-check", "--stdout"],
                cwd=str(BASE),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
            )
            stderr_text = result.stderr.decode("utf-8", errors="replace")
            stdout_text = result.stdout.decode("utf-8", errors="replace")
            if stderr_text:
                print(stderr_text, file=sys.stderr)

            if "[跳过]" in stderr_text:
                print(f"[SKIP] 兜底通知今日已发送过", file=sys.stderr)
                status["status"] = SKIPPED_ALREADY_SENT
                write(task_name, status)
                sys.exit(0)

            if result.returncode != 0 or not stdout_text.strip():
                status["status"] = ERROR
                status["ok"] = False
                status["reason"] = f"hermes_push --final-check 异常 exit={result.returncode}"
                print(f"[ERROR] {status['reason']}", file=sys.stderr)
                write(task_name, status)
                sys.exit(2)

            print(stdout_text)
            sys.exit(0)

        # ── Step 5: 目标彩种齐全 → 正常复盘 ──
        if not daily_ok:
            status["status"] = ERROR
            status["ok"] = False
            status["reason"] = "daily_review.py 执行异常"
            print(f"[ERROR] {status['reason']}", file=sys.stderr)
            write(task_name, status)
            sys.exit(2)

        status["dedup_key"] = dedup_key
        status["should_push"] = True
        status["status"] = READY
        status["reason"] = ""
        status["finished_at"] = now().strftime("%Y-%m-%dT%H:%M:%S%z")
        write(task_name, status)

        # 调用 hermes_push 输出复盘内容到 stdout
        result = subprocess.run(
            [PY, "scripts/hermes_push.py", "--mode", "review",
             "--lottery", args.lottery,
             "--dedup-key", dedup_key, "--stdout"],
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
            write(task_name, status)

        sys.exit(0)

    except Exception as e:
        status["status"] = ERROR
        status["ok"] = False
        status["reason"] = f"未预期异常: {e}"
        print(f"[ERROR] {status['reason']}", file=sys.stderr)
        write(task_name, status)
        sys.exit(2)


if __name__ == "__main__":
    main()
