#!/usr/bin/env python3
"""快乐8候选池预测 —— 热号+冷号混合生成20码池 + 选四主推荐"""
import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.kl8.common import parse_kl8_numbers

BASE = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE / "data" / "kl8"
OUTPUT_DIR = BASE / "output" / "kl8"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CN_TZ = timezone(timedelta(hours=8))
STRATEGY = "kl8_v1_hot12_cold8"


def load_history(n: int = 50) -> list[list[int]]:
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


def next_issue(latest_issue: str) -> str:
    """计算下一期号，处理年份翻转。
    期号格式: YYYYNNN（如 2025365 = 2025年第365期）。
    """
    import calendar
    try:
        y = int(latest_issue[:4])
        n = int(latest_issue[4:])
        max_n = 366 if calendar.isleap(y) else 365
        if n >= max_n:
            return f"{y + 1}001"
        return f"{y}{n + 1:03d}"
    except (ValueError, IndexError):
        return "unknown"


def build_candidate_pool(draws: list[list[int]], pool_size: int = 20,
                         hot_ratio: float = 0.6) -> list[int]:
    """热号+冷号混合生成20码候选池"""
    if not draws:
        return list(range(1, pool_size + 1))

    recent = draws[:30] if len(draws) >= 30 else draws
    freq = Counter()
    for nums in recent:
        freq.update(nums)

    hot_count = max(1, int(pool_size * hot_ratio))
    cold_count = pool_size - hot_count

    hot = [num for num, _ in freq.most_common(hot_count)]
    all_nums = {i: freq.get(i, 0) for i in range(1, 81)}
    cold = [num for num, _ in sorted(all_nums.items(), key=lambda x: x[1])
            if num not in hot][:cold_count]

    pool = sorted(set(hot + cold))
    for num, _ in freq.most_common():
        if len(pool) >= pool_size:
            break
        if num not in pool:
            pool.append(num)
    return sorted(pool[:pool_size])


def pick_play4(pool: list[int], draws: list[list[int]], top_n: int = 4) -> list[int]:
    """从20码池中基于近5期稳定度选4码主推荐"""
    if not draws:
        return pool[:top_n]
    recent5 = Counter()
    for nums in draws[:5]:
        for n in nums:
            if n in pool:
                recent5[n] += 1
    if recent5:
        return [n for n, _ in recent5.most_common(top_n)]
    return pool[:top_n]


def predict(latest_issue: str, pool_size: int = 20, hot_ratio: float = 0.6) -> dict:
    draws = load_history()
    if not draws:
        raise RuntimeError("无历史数据，无法生成预测。请先运行 kl8/fetcher.py")

    pool = build_candidate_pool(draws, pool_size=pool_size, hot_ratio=hot_ratio)
    play4 = pick_play4(pool, draws)
    freq = Counter()
    for nums in draws[:30]:
        freq.update(nums)

    hot_set = {n for n, _ in freq.most_common(12)}

    target = next_issue(latest_issue)
    return {
        "lottery": "kl8",
        "predicted_issue": target,
        "data_until_issue": latest_issue,
        "strategy": STRATEGY,
        "candidate_pool": pool,
        "recommended_play4": play4,
        "play_type": "选四",
        "hot_numbers": [n for n, _ in freq.most_common(20)],
        "cold_numbers": [n for n, _ in sorted(
            {i: freq.get(i, 0) for i in range(1, 81)}.items(),
            key=lambda x: x[1]) if n not in hot_set][:20],
        "zone_distribution": {
            "01-20": sum(1 for n in pool if 1 <= n <= 20),
            "21-40": sum(1 for n in pool if 21 <= n <= 40),
            "41-60": sum(1 for n in pool if 41 <= n <= 60),
            "61-80": sum(1 for n in pool if 61 <= n <= 80),
        },
        "play4_note": "主推荐为选四玩法（2元/注），官方奖级：中4=93元，中3=5元，中2=3元。"
                      "20码候选池仅作辅助参考，不单独推荐投注。",
        "generated_at": datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S"),
    }


def save_prediction(data: dict) -> Path:
    issue = data["predicted_issue"]
    p = OUTPUT_DIR / f"kl8_predict_{issue}.json"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT_DIR / "kl8_predict_latest.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def main():
    parser = argparse.ArgumentParser(description="快乐8候选池+选四预测")
    parser.add_argument("--pool-size", type=int, default=20, help="候选池大小")
    parser.add_argument("--hot-ratio", type=float, default=0.6, help="热号比例")
    args = parser.parse_args()

    latest_path = DATA_DIR / "kl8_latest.json"
    if not latest_path.exists():
        print("[ERROR] 请先运行 kl8/fetcher.py", file=sys.stderr)
        sys.exit(3)

    latest_data = json.loads(latest_path.read_text(encoding="utf-8"))
    latest_issue = latest_data["issue"]

    try:
        data = predict(latest_issue, pool_size=args.pool_size, hot_ratio=args.hot_ratio)
    except RuntimeError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(2)
    path = save_prediction(data)

    pool = data["candidate_pool"]
    play4 = data["recommended_play4"]
    print(f"✅ 快乐8 预测期号: {data['predicted_issue']}")
    print(f"   策略: {data['strategy']}")
    print(f"   选四主推: {' '.join(f'{n:02d}' for n in play4)}")
    print(f"   候选20码: {' '.join(f'{n:02d}' for n in pool[:10])}")
    print(f"            {' '.join(f'{n:02d}' for n in pool[10:])}")
    print(f"   分区: 01-20:{data['zone_distribution']['01-20']} "
          f"21-40:{data['zone_distribution']['21-40']} "
          f"41-60:{data['zone_distribution']['41-60']} "
          f"61-80:{data['zone_distribution']['61-80']}")
    print(f"   保存: {path}")


if __name__ == "__main__":
    main()
