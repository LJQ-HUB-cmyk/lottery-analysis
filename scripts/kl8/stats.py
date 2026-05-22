#!/usr/bin/env python3
"""快乐8统计指标 —— 奇偶/大小/连号/和值/冷热/遗漏"""
import csv
import json
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

from scripts.kl8.common import parse_kl8_numbers

BASE = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE / "data" / "kl8"
OUTPUT_DIR = BASE / "output" / "kl8"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CN_TZ = timezone(timedelta(hours=8))


def load_draws(n: int = 50) -> list[list[int]]:
    p = DATA_DIR / "kl8_history.csv"
    if not p.exists():
        return []
    draws = []
    with open(p, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            nums = parse_kl8_numbers(row.get("numbers", ""))
            if len(nums) == 20:
                draws.append(nums)
    return draws[:n]


def odd_even(nums: list[int]) -> dict:
    odd = sum(1 for n in nums if n % 2 == 1)
    return {"odd": odd, "even": len(nums) - odd}


def big_small(nums: list[int], mid: int = 40) -> dict:
    small = sum(1 for n in nums if n <= mid)
    return {"small": small, "big": len(nums) - small}


def zones(nums: list[int]) -> dict:
    return {
        "01-20": sum(1 for n in nums if 1 <= n <= 20),
        "21-40": sum(1 for n in nums if 21 <= n <= 40),
        "41-60": sum(1 for n in nums if 41 <= n <= 60),
        "61-80": sum(1 for n in nums if 61 <= n <= 80),
    }


def consecutive_pairs(nums: list[int]) -> int:
    s = sorted(nums)
    return sum(1 for i in range(len(s) - 1) if s[i + 1] - s[i] == 1)


def frequency(draws: list[list[int]]) -> dict:
    freq = Counter()
    for nums in draws:
        freq.update(nums)
    return {"hot": [n for n, _ in freq.most_common(20)],
            "cold": [n for n, _ in freq.most_common()[-20:]]}


def missing_streaks(draws: list[list[int]]) -> dict:
    """计算每个号码当前遗漏期数"""
    missing = {}
    for num in range(1, 81):
        for i, nums in enumerate(draws):
            if num in nums:
                missing[num] = i
                break
        else:
            missing[num] = len(draws)
    return dict(sorted(missing.items(), key=lambda x: -x[1])[:10])


def main():
    draws = load_draws()
    if not draws:
        print("无历史数据")
        return

    latest = draws[0]
    recent30 = draws[:30] if len(draws) >= 30 else draws

    # 从 history csv 读取最新期号
    data_until = "unknown"
    hp = DATA_DIR / "kl8_history.csv"
    if hp.exists():
        with open(hp, encoding="utf-8-sig", newline="") as f:
            first = next(csv.DictReader(f), None)
            if first:
                data_until = first["issue"]

    stats = {
        "lottery": "kl8",
        "data_until_issue": data_until,
        "latest_draw": {
            "odd_even": odd_even(latest),
            "big_small": big_small(latest),
            "zones": zones(latest),
            "consecutive_pairs": consecutive_pairs(latest),
            "sum": sum(latest),
        },
        "recent30_avg": {
            "odd_avg": round(sum(odd_even(d)["odd"] for d in recent30) / len(recent30), 1),
            "even_avg": round(sum(odd_even(d)["even"] for d in recent30) / len(recent30), 1),
            "small_avg": round(sum(big_small(d)["small"] for d in recent30) / len(recent30), 1),
            "big_avg": round(sum(big_small(d)["big"] for d in recent30) / len(recent30), 1),
            "consec_avg": round(sum(consecutive_pairs(d) for d in recent30) / len(recent30), 1),
            "sum_avg": round(sum(sum(d) for d in recent30) / len(recent30), 1),
        },
        "frequency": frequency(recent30),
        "top_missing": missing_streaks(recent30),
        "updated_at": datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S"),
    }

    out = OUTPUT_DIR / "kl8_stats.json"
    out.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 快乐8统计指标 → {out}")
    print(f"   最新期: 奇{stats['latest_draw']['odd_even']['odd']}/"
          f"偶{stats['latest_draw']['odd_even']['even']} "
          f"小{stats['latest_draw']['big_small']['small']}/"
          f"大{stats['latest_draw']['big_small']['big']} "
          f"连号{stats['latest_draw']['consecutive_pairs']}组 "
          f"和值{stats['latest_draw']['sum']}")


if __name__ == "__main__":
    main()
