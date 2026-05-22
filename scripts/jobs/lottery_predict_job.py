#!/usr/bin/env python3
"""
排列三 / 福彩3D 预测 Job —— 替代 lottery_predict_push.sh 中的业务逻辑。

职责：
  1. 执行 run_daily.py 生成预测
  2. 执行 source_health.py 生成健康报告
  3. 计算 dedup_key → 调用 hermes_push
  4. 写 status.json

退出码：0=正常，2=异常
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
PY = sys.executable

CN_TZ = timezone(timedelta(hours=8))
PRED_DIR = BASE / "output" / "predictions"
REPORT_DIR = BASE / "output" / "reports"

sys.path.insert(0, str(BASE))


def now() -> datetime:
    return datetime.now(CN_TZ)


def today_str() -> str:
    return now().strftime("%Y-%m-%d")


def run(cmd: list[str], desc: str, timeout: int = 300) -> bool:
    print(f"  [{desc}] 执行中...", file=sys.stderr)
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    result = subprocess.run(
        [PY] + cmd,
        cwd=str(BASE),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        env=env,
    )
    output = result.stdout.decode("utf-8", errors="replace")
    for line in output.strip().split("\n")[-6:]:
        if line.strip():
            print(f"    {line.strip()}", file=sys.stderr)
    ok = result.returncode == 0
    print(f"  -> {'[OK] 成功' if ok else '[WARN] 失败'} (exit={result.returncode})", file=sys.stderr)
    return ok


def main():
    from scripts.lib.job_status import write, READY, ERROR, SKIPPED_ALREADY_SENT

    status = {
        "task": "lottery_predict",
        "date": today_str(),
        "run_id": f"lottery_predict_{now().strftime('%Y%m%d_%H%M%S')}",
        "status": READY,
        "ok": True,
        "should_push": False,
        "reason": "",
        "dedup_key": "",
        "started_at": now().strftime("%Y-%m-%dT%H:%M:%S%z"),
    }

    try:
        # ── Step 1: 生成预测 ──
        ok_pred = run(["run_daily.py", "--strategy", "all", "--top-k", "30"],
                       "生成今日预测", timeout=600)
        if not ok_pred:
            status["status"] = ERROR
            status["ok"] = False
            status["reason"] = "run_daily.py 执行失败"
            print(f"[ERROR] {status['reason']}", file=sys.stderr)
            write("lottery_predict", status)
            sys.exit(2)

        # ── Step 2: 生成健康报告 ──
        run(["scripts/source_health.py", "--json", "--output",
             "output/reports/source_health.json"], "数据源健康报告", timeout=120)

        # ── Step 3: 计算 dedup_key → 推送 ──
        pls_data = {}
        d3_data = {}
        pls_path = PRED_DIR / "latest_pls.json"
        d3_path = PRED_DIR / "latest_d3.json"
        if pls_path.exists():
            try:
                pls_data = json.loads(pls_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        if d3_path.exists():
            try:
                d3_data = json.loads(d3_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        pls_issue = str(pls_data.get("预测期号", "?"))
        d3_issue = str(d3_data.get("预测期号", "?"))
        status["dedup_key"] = f"predict:{today_str()}:pls-{pls_issue}:d3-{d3_issue}"
        status["should_push"] = True
        status["issues"] = {"pls": pls_issue, "d3": d3_issue}
        status["finished_at"] = now().strftime("%Y-%m-%dT%H:%M:%S%z")
        write("lottery_predict", status)

        # 调用 hermes_push 输出到 stdout（不加 --force，靠 dedup_key 去重）
        result = subprocess.run(
            [PY, "scripts/hermes_push.py", "--mode", "predict",
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
            write("lottery_predict", status)

        sys.exit(0)

    except Exception as e:
        status["status"] = ERROR
        status["ok"] = False
        status["reason"] = f"未预期异常: {e}"
        print(f"[ERROR] {status['reason']}", file=sys.stderr)
        write("lottery_predict", status)
        sys.exit(2)


if __name__ == "__main__":
    main()
