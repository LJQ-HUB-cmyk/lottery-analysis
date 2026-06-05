#!/usr/bin/env python3
"""快乐8 Walk-Forward 回测 —— 对比热冷策略 vs 随机基准

用法：
  python scripts/kl8/backtest.py --periods 30
  python scripts/kl8/backtest.py --periods 50 --pool-size 20 --hot-ratio 0.6
"""
import argparse
import csv
import json
import random
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.kl8.common import parse_kl8_numbers
from scripts.kl8.predictor import build_candidate_pool, pick_play4, ZONES, _zone_of

BASE = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE / "data" / "kl8"
OUTPUT_DIR = BASE / "output" / "kl8"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CN_TZ = timezone(timedelta(hours=8))

# 选四奖级
PLAY4_PRIZES = {4: 93, 3: 5, 2: 3, 1: 0, 0: 0}
COST_PER_BET = 2


def load_draws() -> list[list[int]]:
    p = DATA_DIR / "kl8_history.csv"
    if not p.exists():
        return []
    draws = []
    with open(p, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            nums = parse_kl8_numbers(row.get("numbers", ""))
            if len(nums) == 20:
                draws.append(nums)
    return draws


def evaluate_prediction(pool: list[int], play4: list[int],
                        actual: list[int]) -> dict:
    """评估单期预测结果。"""
    pool_set = set(pool)
    play4_set = set(play4)
    drawn = set(actual)

    pool_hit = len(pool_set & drawn)
    play4_hit = len(play4_set & drawn)
    prize = PLAY4_PRIZES.get(play4_hit, 0)
    profit = prize - COST_PER_BET

    return {
        "pool_hit": pool_hit,
        "play4_hit": play4_hit,
        "prize": prize,
        "profit": profit,
    }


def walk_forward(draws: list[list[int]], periods: int = 30,
                 train_window: int = 30, pool_size: int = 20,
                 hot_ratio: float = 0.6, seed: int = 42) -> dict:
    """Walk-forward 回测：对最近 periods 期做滚动评估。"""
    total = len(draws)
    usable = min(periods, max(0, total - train_window - 1))
    if usable <= 0:
        return {"error": "数据不足", "total": total, "train_window": train_window}

    rng = random.Random(seed)

    strategies = {
        "热冷策略": {
            "pool_hits": [], "play4_hits": [], "prizes": [], "profits": [],
            "max_miss": 0, "cur_miss": 0,
        },
        "随机基准": {
            "pool_hits": [], "play4_hits": [], "prizes": [], "profits": [],
            "max_miss": 0, "cur_miss": 0,
        },
    }

    for i in range(usable):
        # 待预测期
        actual = draws[i]
        # 训练数据
        train = draws[i + 1:i + 1 + train_window]

        if len(train) < 10:
            continue

        # ── 策略 1: 热冷策略 ──
        pool_hot = build_candidate_pool(train, pool_size=pool_size,
                                        hot_ratio=hot_ratio)
        play4_hot = pick_play4(pool_hot, train)
        r_hot = evaluate_prediction(pool_hot, play4_hot, actual)
        for k, v in r_hot.items():
            strategies["热冷策略"][f"{k}s" if k != "profit" else "profits"].append(v)
        if r_hot["play4_hit"] >= 2:
            strategies["热冷策略"]["cur_miss"] = 0
        else:
            strategies["热冷策略"]["cur_miss"] += 1
            strategies["热冷策略"]["max_miss"] = max(
                strategies["热冷策略"]["max_miss"],
                strategies["热冷策略"]["cur_miss"])

        # ── 策略 2: 随机基准 ──
        pool_rand = sorted(rng.sample(range(1, 81), pool_size))
        play4_rand = sorted(rng.sample(pool_rand, 4))
        r_rand = evaluate_prediction(pool_rand, play4_rand, actual)
        for k, v in r_rand.items():
            strategies["随机基准"][f"{k}s" if k != "profit" else "profits"].append(v)
        if r_rand["play4_hit"] >= 2:
            strategies["随机基准"]["cur_miss"] = 0
        else:
            strategies["随机基准"]["cur_miss"] += 1
            strategies["随机基准"]["max_miss"] = max(
                strategies["随机基准"]["max_miss"],
                strategies["随机基准"]["cur_miss"])

    # 汇总
    results = {}
    for sname, s in strategies.items():
        n = len(s["prizes"])
        if n == 0:
            results[sname] = {"periods": 0}
            continue
        hit2 = sum(1 for h in s["play4_hits"] if h == 2)
        hit3 = sum(1 for h in s["play4_hits"] if h == 3)
        hit4 = sum(1 for h in s["play4_hits"] if h == 4)
        results[sname] = {
            "periods": n,
            "total_cost": COST_PER_BET * n,
            "total_prize": sum(s["prizes"]),
            "total_profit": sum(s["profits"]),
            "roi": round(sum(s["profits"]) / (COST_PER_BET * n) * 100, 1),
            "pool_hit_avg": round(sum(s["pool_hits"]) / n, 2),
            "hit2": hit2,
            "hit3": hit3,
            "hit4": hit4,
            "hit_rate": round((hit2 + hit3 + hit4) / n * 100, 1),
            "max_miss_streak": s["max_miss"],
        }

    return results


def main():
    parser = argparse.ArgumentParser(description="快乐8 Walk-Forward 回测")
    parser.add_argument("--periods", type=int, default=30, help="回测期数")
    parser.add_argument("--train-window", type=int, default=30, help="训练窗口")
    parser.add_argument("--pool-size", type=int, default=20, help="候选池大小")
    parser.add_argument("--hot-ratio", type=float, default=0.6, help="热号比例")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    args = parser.parse_args()

    draws = load_draws()
    if len(draws) < args.train_window + 10:
        print(f"[ERROR] 数据不足：{len(draws)} 期（需 {args.train_window + 10}+）")
        sys.exit(1)

    print(f"\n{'='*55}")
    print(f"  快乐8 Walk-Forward 回测")
    print(f"  数据: {len(draws)} 期 | 回测: {args.periods}期 | 训练窗口: {args.train_window}")
    print(f"  候选池: {args.pool_size}码 | 热号比例: {args.hot_ratio}")
    print(f"{'='*55}")

    results = walk_forward(draws, args.periods, args.train_window,
                           args.pool_size, args.hot_ratio, args.seed)

    if "error" in results:
        print(f"[ERROR] {results['error']}")
        sys.exit(1)

    # 输出对比表
    print(f"\n  {'策略':<10} {'期数':>4} {'投入':>6} {'奖金':>6} {'盈亏':>6} "
          f"{'ROI':>6} {'池均命中':>6} {'中二':>3} {'中三':>3} {'中四':>3} "
          f"{'命中率':>5} {'最长连未':>4}")
    print(f"  {'─'*75}")

    for sname, r in results.items():
        print(f"  {sname:<10} {r['periods']:>4} "
              f"{r.get('total_cost', 0):>6} "
              f"{r.get('total_prize', 0):>6} "
              f"{r.get('total_profit', 0):>+6} "
              f"{r.get('roi', 0):>5.1f}% "
              f"{r.get('pool_hit_avg', 0):>6.1f} "
              f"{r.get('hit2', 0):>3} "
              f"{r.get('hit3', 0):>3} "
              f"{r.get('hit4', 0):>3} "
              f"{r.get('hit_rate', 0):>4.1f}% "
              f"{r.get('max_miss_streak', 0):>4}期")

    print(f"\n  ⚠️ 彩票具有随机性，回测结果不代表未来表现。")

    # 保存
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / "kl8_backtest.json"
    out.write_text(json.dumps({
        "lottery": "kl8",
        "periods": args.periods,
        "train_window": args.train_window,
        "pool_size": args.pool_size,
        "hot_ratio": args.hot_ratio,
        "results": results,
        "generated_at": datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  💾 保存: {out}")


if __name__ == "__main__":
    main()
