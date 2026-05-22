#!/usr/bin/env python3
"""
每日复盘脚本 —— 供 Hermes cron 调用
=================================
22:00 执行：拉取开奖数据 → 特征工程 → 三策略对比 → 复盘摘要

用法：
    python scripts/daily_review.py
    python scripts/daily_review.py --lottery pls     # 仅排列三

Hermes cron 配置：
    时间: 22:00 (北京时间)
    命令: python scripts/daily_review.py
"""

import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
PY = sys.executable


def run(cmd, desc):
    print(f"\n{'─'*55}")
    print(f"  {desc}")
    print(f"{'─'*55}")
    result = subprocess.run(
        [PY] + cmd,
        cwd=str(BASE),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=300,
    )
    output = result.stdout.decode('utf-8', errors='replace')
    # 只打印最后几行
    for line in output.strip().split('\n')[-5:]:
        print(f"  {line}")
    ok = result.returncode == 0
    print(f"  → {'✅ 成功' if ok else '⚠️ 失败'}")
    return ok


def main():
    import argparse
    parser = argparse.ArgumentParser(description='每日复盘（Hermes cron 专用）')
    parser.add_argument('--lottery', choices=['pls', 'd3'],
                        help='仅复盘指定彩种')
    args = parser.parse_args()

    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    print(f"{'='*55}")
    print(f"  每日复盘  {now}")
    print(f"{'='*55}")

    lotteries = ['pls', 'd3'] if not args.lottery else [args.lottery]

    results = {}  # step_name → ok

    # 1. 拉取最新开奖数据
    results["拉取开奖数据"] = run(["scripts/data_fetcher.py", "--all"], "拉取最新开奖数据")

    # 2. 特征工程
    for lt in lotteries:
        results[f"{lt} 特征工程"] = run(
            ["scripts/feature_engine.py",
             "--input", f"data/raw/{lt}_raw.csv",
             "--output", f"data/processed/{lt}_feat.csv",
             "--lottery", lt, "--force"],
            f"{lt} 特征工程")

    # 3. 三策略对比复盘
    strategies = ['default', 'conservative', 'diversity']
    for lt in lotteries:
        for st in strategies:
            results[f"{lt} {st}对比"] = run(
                ["scripts/compare_result.py", "--lottery", lt, "--strategy", st],
                f"{lt} {st}策略 对比复盘")

    # 4. 复盘摘要
    results["复盘摘要"] = run(["scripts/review_summary.py"], "复盘表现摘要")

    # 聚合结果
    failed = [k for k, v in results.items() if not v]
    all_ok = len(failed) == 0

    print(f"\n{'='*55}")
    if all_ok:
        print(f"  ✅ 每日复盘完成")
        print(f"{'='*55}\n")
        sys.exit(0)
    else:
        print(f"  ❌ 每日复盘存在失败步骤：{', '.join(failed)}")
        print(f"{'='*55}\n")
        sys.exit(2)


if __name__ == '__main__':
    main()
