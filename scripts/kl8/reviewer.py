#!/usr/bin/env python3
"""快乐8复盘 —— 候选池+选四 vs 实际开奖，含命中/盈亏/奖级"""
import argparse
import csv
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from scripts.kl8.common import parse_kl8_numbers

BASE = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE / "data" / "kl8"
OUTPUT_DIR = BASE / "output" / "kl8"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CN_TZ = timezone(timedelta(hours=8))

def find_actual_by_issue(target_issue: str) -> dict | None:
    """在 history.csv 中按期号精确查找开奖数据"""
    p = DATA_DIR / "kl8_history.csv"
    if not p.exists():
        return None
    with open(p, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row["issue"] == target_issue:
                return {
                    "lottery": "kl8",
                    "issue": row["issue"],
                    "date": row["date"],
                    "numbers": parse_kl8_numbers(row.get("numbers", "")),
                }
    return None


# 选四奖级表：命中数 → 奖金(元)
# 官方标准：中4=93元 中3=5元 中2=3元（派奖期间中4可能上调至100元）
PLAY4_PRIZES = {4: 93, 3: 5, 2: 3, 1: 0, 0: 0}
COST_PER_BET = 2


def review(prediction: dict, actual: dict) -> dict:
    pool = set(prediction["candidate_pool"])
    play4 = set(prediction.get("recommended_play4", []))
    drawn = set(actual["numbers"])

    pool_hit = sorted(pool & drawn)
    play4_hit = sorted(play4 & drawn)
    play4_hit_count = len(play4_hit)

    prize = PLAY4_PRIZES.get(play4_hit_count, 0)
    profit = prize - COST_PER_BET

    if play4_hit_count == 4:
        result_level = "选四中四"
    elif play4_hit_count == 3:
        result_level = "选四中三"
    elif play4_hit_count == 2:
        result_level = "选四中二"
    else:
        result_level = "未中奖"

    return {
        "lottery": "kl8",
        "issue": actual["issue"],
        "date": actual["date"],
        "strategy": prediction.get("strategy", ""),
        "play_type": prediction.get("play_type", "选四"),
        "recommended_play4": prediction.get("recommended_play4", []),
        "candidate_pool": prediction["candidate_pool"],
        "actual_numbers": actual["numbers"],
        "play4_hit_count": play4_hit_count,
        "play4_hit_numbers": play4_hit,
        "result_level": result_level,
        "prize": prize,
        "cost": COST_PER_BET,
        "profit": profit,
        "pool_hit_count": len(pool_hit),
        "pool_hit_numbers": pool_hit,
        "zone_hit": {
            "01-20": sum(1 for n in pool_hit if 1 <= n <= 20),
            "21-40": sum(1 for n in pool_hit if 21 <= n <= 40),
            "41-60": sum(1 for n in pool_hit if 41 <= n <= 60),
            "61-80": sum(1 for n in pool_hit if 61 <= n <= 80),
        },
        "reviewed_at": datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S"),
    }


def save_review(data: dict) -> Path:
    issue = data["issue"]
    p = OUTPUT_DIR / f"kl8_review_{issue}.json"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT_DIR / "kl8_review_latest.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def append_review_history(data: dict) -> Path:
    p = OUTPUT_DIR / "kl8_review_history.csv"
    row = {
        "日期": data["date"],
        "期号": data["issue"],
        "策略": data["strategy"],
        "玩法": data["play_type"],
        "推荐号码": " ".join(f"{n:02d}" for n in data["recommended_play4"]),
        "开奖号码": " ".join(f"{n:02d}" for n in data["actual_numbers"]),
        "命中数": str(data["play4_hit_count"]),
        "命中号码": " ".join(f"{n:02d}" for n in data["play4_hit_numbers"]) or "-",
        "结果": data["result_level"],
        "奖金": str(data["prize"]),
        "成本": str(data["cost"]),
        "盈亏": str(data["profit"]),
        "池命中": str(data["pool_hit_count"]),
        "复盘时间": data["reviewed_at"],
    }
    # 清理旧格式记录（无'结果'等新字段），用字段黑名单
    existed = []
    if p.exists():
        with open(p, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            old_fieldnames = reader.fieldnames or []
            for r in reader:
                # 跳过旧格式记录：缺少 "结果" 字段的视为废弃
                if "结果" not in old_fieldnames or "结果" not in r:
                    continue
                existed.append(r)
    existed = [r for r in existed
               if not (r.get("期号") == row["期号"] and r.get("策略") == row["策略"])]
    existed.append(row)
    existed.sort(key=lambda r: r.get("期号", ""), reverse=True)
    with open(p, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        w.writeheader()
        w.writerows(existed)
    return p


def main():
    parser = argparse.ArgumentParser(description="快乐8复盘")
    parser.add_argument("--predict", help="预测JSON路径(默认latest)")
    parser.add_argument("--actual", help="开奖JSON路径(默认latest)")
    args = parser.parse_args()

    pred_path = Path(args.predict) if args.predict else OUTPUT_DIR / "kl8_predict_latest.json"
    actual_path = Path(args.actual) if args.actual else DATA_DIR / "kl8_latest.json"

    if not pred_path.exists():
        print(f"[ERROR] 预测文件不存在: {pred_path}", file=sys.stderr)
        sys.exit(3)

    pred = json.loads(pred_path.read_text(encoding="utf-8"))

    # 按预测期号精确查找对应开奖（优先 history.csv，回退 latest.json）
    target_issue = pred.get("predicted_issue", "")
    actual = find_actual_by_issue(target_issue)
    latest_data = None
    if not actual and actual_path.exists():
        latest_data = json.loads(actual_path.read_text(encoding="utf-8"))
        if latest_data.get("issue") == target_issue:
            actual = latest_data

    if not actual:
        print(f"⏳ 等待开奖数据更新（预测{target_issue}，"
              f"最新{latest_data.get('issue','?') if latest_data else '?'}）")
        sys.exit(0)

    data = review(pred, actual)
    rpath = save_review(data)
    hpath = append_review_history(data)

    print(f"📊 快乐8 复盘  {data['issue']}")
    print(f"   选四主推: {' '.join(f'{n:02d}' for n in data['recommended_play4'])}")
    print(f"   选四命中: {data['play4_hit_count']}/4 → {data['result_level']}")
    print(f"   奖金: {data['prize']}元 | 成本: {data['cost']}元 | 盈亏: {'+' if data['profit'] > 0 else ''}{data['profit']}元")
    print(f"   候选池命中: {data['pool_hit_count']}/20")
    print(f"   保存: {rpath}")


if __name__ == "__main__":
    main()
