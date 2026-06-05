#!/usr/bin/env python3
"""快乐8累计表现统计 —— 从 review_history 计算近N期/全期指标"""
import csv
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

BASE = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = BASE / "output" / "kl8"

CN_TZ = timezone(timedelta(hours=8))


def compute(rows: list[dict]) -> dict:
    """计算累计表现"""
    total = len(rows)
    if total == 0:
        return {"days": 0, "note": "暂无复盘数据"}

    costs = [int(r.get("成本", 2)) for r in rows]
    prizes = [int(r.get("奖金", 0)) for r in rows]
    profits = [int(r.get("盈亏", 0)) for r in rows]
    hit2 = sum(1 for r in rows if r.get("结果", "") == "选四中二")
    hit3 = sum(1 for r in rows if r.get("结果", "") == "选四中三")
    hit4 = sum(1 for r in rows if r.get("结果", "") == "选四中四")
    pool_hits = [int(r.get("池命中", 0)) for r in rows]

    # 最大连续未中奖（中二及以上均算有奖）
    max_miss = cur_miss = 0
    for r in rows:
        if r.get("结果", "") == "未中奖":
            cur_miss += 1
            max_miss = max(max_miss, cur_miss)
        else:
            cur_miss = 0

    # 加权命中分：中四=93, 中三=5, 中二=3, 未中=0
    weighted_score = hit4 * 93 + hit3 * 5 + hit2 * 3
    weighted_avg = round(weighted_score / total, 2) if total else 0

    return {
        "days": total,
        "total_cost": sum(costs),
        "total_prize": sum(prizes),
        "total_profit": sum(profits),
        "hit2_count": hit2,
        "hit3_count": hit3,
        "hit4_count": hit4,
        "hit_rate": round((hit2 + hit3 + hit4) / total, 4) if total else 0,
        "weighted_hit_score": weighted_score,
        "weighted_hit_avg": weighted_avg,
        "avg_pool_hit": round(sum(pool_hits) / total, 2) if total else 0,
        "max_miss_streak": max_miss,
    }


def main():
    p = OUTPUT_DIR / "kl8_review_history.csv"
    if not p.exists():
        print("暂无复盘数据")
        sys.exit(0)

    with open(p, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if "结果" not in (reader.fieldnames or []):
            print("review_history 字段不完整，请先运行 reviewer.py")
            sys.exit(3)
        all_rows = list(reader)

    all_rows.sort(key=lambda r: r.get("期号", ""), reverse=True)

    metrics = {
        "lottery": "kl8",
        "strategy": "kl8_v1_hot12_cold8",
        "last7": compute(all_rows[:7]),
        "last30": compute(all_rows[:30]),
        "all": compute(all_rows),
        "updated_at": datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S"),
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / "kl8_metrics.json"
    out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    m7 = metrics["last7"]
    print(f"✅ 快乐8 累计表现")
    print(f"   近{m7['days']}期: 成本{m7['total_cost']}元 奖金{m7['total_prize']}元 "
          f"盈亏{'+' if m7['total_profit'] > 0 else ''}{m7['total_profit']}元 "
          f"中二{m7['hit2_count']}次 中三{m7['hit3_count']}次 中四{m7['hit4_count']}次")
    print(f"   保存: {out}")


if __name__ == "__main__":
    main()
