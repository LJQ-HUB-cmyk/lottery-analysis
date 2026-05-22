#!/usr/bin/env python3
"""
快乐8 预测 Job —— 替代 kl8_predict_push.sh 中的业务逻辑。

职责：
  1. 拉取数据 → 生成预测 → 生成统计
  2. 计算 dedup_key → 调用 hermes_push
  3. 写 status.json

退出码：0=正常，2=异常
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
PY = sys.executable

CN_TZ = timezone(timedelta(hours=8))
KL8_OUTPUT = BASE / "output" / "kl8"

sys.path.insert(0, str(BASE))


def now() -> datetime:
    return datetime.now(CN_TZ)


def run(cmd: list[str], desc: str, timeout: int = 300) -> bool:
    print(f"  [{desc}] 执行中...")
    result = subprocess.run(
        [PY] + cmd,
        cwd=str(BASE),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    output = result.stdout.decode("utf-8", errors="replace")
    for line in output.strip().split("\n")[-6:]:
        if line.strip():
            print(f"    {line.strip()}")
    ok = result.returncode == 0
    print(f"  → {'✅ 成功' if ok else '⚠️ 失败'} (exit={result.returncode})")
    return ok


def main():
    from scripts.lib.job_status import write, READY, ERROR, SKIPPED_ALREADY_SENT

    status = {
        "task": "kl8_predict",
        "date": now().strftime("%Y-%m-%d"),
        "run_id": f"kl8_predict_{now().strftime('%Y%m%d_%H%M%S')}",
        "status": READY,
        "ok": True,
        "should_push": False,
        "reason": "",
        "dedup_key": "",
        "started_at": now().strftime("%Y-%m-%dT%H:%M:%S%z"),
    }

    try:
        # ── Step 1: 拉取数据 ──
        run(["scripts/kl8/fetcher.py", "--pages", "3"], "KL8 拉取数据")

        # ── Step 2: 生成预测 ──
        ok_pred = run(["scripts/kl8/predictor.py"], "KL8 生成预测")
        if not ok_pred:
            status["status"] = ERROR
            status["ok"] = False
            status["reason"] = "predictor.py 执行失败"
            print(f"[ERROR] {status['reason']}", file=sys.stderr)
            write("kl8_predict", status)
            sys.exit(2)

        # ── Step 3: 生成统计 ──
        run(["scripts/kl8/stats.py"], "KL8 生成统计", timeout=120)

        # ── Step 4: 计算 dedup_key → 推送 ──
        pred_file = KL8_OUTPUT / "kl8_predict_latest.json"
        pred_data = {}
        if pred_file.exists():
            try:
                pred_data = json.loads(pred_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        predicted_issue = str(pred_data.get("predicted_issue", "?"))

        status["dedup_key"] = f"kl8_predict:{predicted_issue}"
        status["should_push"] = True
        status["issues"] = {"kl8": predicted_issue}
        status["finished_at"] = now().strftime("%Y-%m-%dT%H:%M:%S%z")
        write("kl8_predict", status)

        # 调用 hermes_push 输出到 stdout（不加 --force，靠 dedup_key 去重）
        result = subprocess.run(
            [PY, "scripts/hermes_push.py", "--mode", "predict", "--lottery", "kl8",
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
            write("kl8_predict", status)

        sys.exit(0)

    except Exception as e:
        status["status"] = ERROR
        status["ok"] = False
        status["reason"] = f"未预期异常: {e}"
        print(f"[ERROR] {status['reason']}", file=sys.stderr)
        write("kl8_predict", status)
        sys.exit(2)


if __name__ == "__main__":
    main()
