#!/usr/bin/env python3
"""快乐8 多策略对比报告 —— 从 review_history 对比不同策略的累计表现

用法：
  python scripts/kl8/compare_strategies.py
  python scripts/kl8/compare_strategies.py --window 30
"""
import argparse
import csv
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

BASE = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = BASE / "output" / "kl8"

CN_TZ = timezone(timedelta(hours=8))

PLAY4_PRIZES = {4: 93, 3: 5, 2: 3, 1: 0, 0: 0}


def compute_strategy_stats(rows: list[dict], window: int = 0) -> dict:
    """计算单个策略的表现统计。"""
    if window > 0:
        rows = rows[:window]

    total = len(rows)
    if total == 0:
        return {"periods": 0}

    costs = [int(r.get("成本", 2)) for r in rows]
    prizes = [int(r.get("奖金", 0)) for r in rows]
    profits = [int(r.get("盈亏", 0)) for r in rows]

    hit2 = sum(1 for r in rows if r.get("结果", "") == "选四中二")
    hit3 = sum(1 for r in rows if r.get("结果", "") == "选四中三")
    hit4 = sum(1 for r in rows if r.get("结果", "") == "选四中四")
    pool_hits = [int(r.get("池命中", 0)) for r in rows]

    # 加权命中分
    weighted = hit4 * 93 + hit3 * 5 + hit2 * 3

    # 最大连续未中
    max_miss = cur_miss = 0
    for r in rows:
        if r.get("结果", "") == "未中奖":
            cur_miss += 1
            max_miss = max(max_miss, cur_miss)
        else:
            cur_miss = 0

    return {
        "periods": total,
        "total_cost": sum(costs),
        "total_prize": sum(prizes),
        "total_profit": sum(profits),
        "roi": round(sum(profits) / sum(costs) * 100, 1) if sum(costs) > 0 else 0,
        "hit2": hit2,
        "hit3": hit3,
        "hit4": hit4,
        "hit_rate": round((hit2 + hit3 + hit4) / total * 100, 1),
        "weighted_score": weighted,
        "weighted_avg": round(weighted / total, 2),
        "pool_hit_avg": round(sum(pool_hits) / total, 2),
        "max_miss_streak": max_miss,
    }


def main():
    parser = argparse.ArgumentParser(description="快乐8 多策略对比报告")
    parser.add_argument("--window", type=int, default=30, help="统计窗口（默认30期）")
    args = parser.parse_args()

    p = OUTPUT_DIR / "kl8_review_history.csv"
    if not p.exists():
        print("暂无复盘数据")
        sys.exit(0)

    with open(p, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print("暂无复盘数据")
        sys.exit(0)

    # 按策略分组
    by_strategy: dict[str, list] = {}
    for r in rows:
        st = r.get("策略", "unknown")
        by_strategy.setdefault(st, []).append(r)

    # 每组按期号降序
    for st in by_strategy:
        by_strategy[st].sort(key=lambda r: r.get("期号", ""), reverse=True)

    print(f"\n{'='*70}")
    print(f"  快乐8 多策略对比报告（近{args.window}期）")
    print(f"{'='*70}")

    results = {}
    print(f"\n  {'策略':<25} {'期数':>4} {'投入':>6} {'奖金':>6} {'盈亏':>6} "
          f"{'ROI':>6} {'命中率':>5} {'加权均':>5} {'池均':>4} {'连未':>3}")
    print(f"  {'─'*70}")

    for st in sorted(by_strategy.keys()):
        st_rows = by_strategy[st]
        stats = compute_strategy_stats(st_rows, args.window)
        results[st] = stats

        if stats["periods"] == 0:
            print(f"  {st:<25} 无数据")
            continue

        print(f"  {st:<25} {stats['periods']:>4} "
              f"{stats['total_cost']:>6} "
              f"{stats['total_prize']:>6} "
              f"{stats['total_profit']:>+6} "
              f"{stats['roi']:>5.1f}% "
              f"{stats['hit_rate']:>4.1f}% "
              f"{stats['weighted_avg']:>5.1f} "
              f"{stats['pool_hit_avg']:>4.1f} "
              f"{stats['max_miss_streak']:>3}期")

    print(f"\n  ⚠️ 彩票具有随机性，对比结果不代表未来表现。")

    # 保存
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / "kl8_strategy_comparison.json"
    out.write_text(json.dumps({
        "lottery": "kl8",
        "window": args.window,
        "strategies": results,
        "generated_at": datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  💾 保存: {out}")


if __name__ == "__main__":
    main()
