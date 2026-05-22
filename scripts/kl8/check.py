#!/usr/bin/env python3
"""快乐8全链路健康检查 —— 数据、预测、复盘三个层面"""
import csv
import json
import sys
from pathlib import Path

from scripts.kl8.common import parse_kl8_numbers

BASE = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE / "data" / "kl8"
OUTPUT_DIR = BASE / "output" / "kl8"

ERRORS = 0


def ok(msg: str):
    print(f"  ✅ {msg}")


def info(msg: str):
    print(f"  ℹ️ {msg}")


def warn(msg: str):
    global ERRORS
    ERRORS += 1
    print(f"  ❌ {msg}")


def check_history():
    print("\n── kl8_history.csv ──")
    p = DATA_DIR / "kl8_history.csv"
    if not p.exists():
        warn("kl8_history.csv 不存在")
        return
    with open(p, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    ok(f"{len(rows)} 期")

    if len(rows) == 0:
        warn("kl8_history.csv 为空（仅表头或无数据），请先运行 fetcher.py")
        return

    seen = set()
    for r in rows:
        issue = r.get("issue", "")
        nums = parse_kl8_numbers(r.get("numbers", ""))
        if not nums:
            warn(f"期号{issue}无号码")
            continue
        if len(nums) != 20:
            warn(f"期号{issue}: {len(nums)}个号码(应为20)")
        if min(nums) < 1 or max(nums) > 80:
            warn(f"期号{issue}: 号码超范围1-80")
        if len(set(nums)) != 20:
            warn(f"期号{issue}: 号码重复")
        if issue in seen:
            warn(f"期号{issue}: 重复")
        seen.add(issue)
    ok("数据校验完成")


def check_latest():
    print("\n── kl8_latest.json ──")
    p = DATA_DIR / "kl8_latest.json"
    if not p.exists():
        warn("kl8_latest.json 不存在")
        return
    data = json.loads(p.read_text(encoding="utf-8"))
    for f in ["lottery", "issue", "date", "numbers"]:
        if f not in data:
            warn(f"缺少字段: {f}")
    nums = data.get("numbers", [])
    if len(nums) != 20:
        warn(f"号码数={len(nums)}")
    if data.get("lottery") != "kl8":
        warn("lottery 字段非 kl8")
    # 和 history 最新期对比
    hp = DATA_DIR / "kl8_history.csv"
    if hp.exists():
        with open(hp, encoding="utf-8-sig", newline="") as f:
            first = next(csv.DictReader(f))
        if first["issue"] != data["issue"]:
            warn(f"latest({data['issue']}) ≠ history最新({first['issue']})")
        else:
            ok(f"latest 与 history 一致 ({data['issue']})")


def check_predict():
    print("\n── kl8_predict_latest.json ──")
    p = OUTPUT_DIR / "kl8_predict_latest.json"
    if not p.exists():
        warn("kl8_predict_latest.json 不存在")
        return
    data = json.loads(p.read_text(encoding="utf-8"))
    for f in ["lottery", "predicted_issue", "strategy", "candidate_pool",
              "recommended_play4", "play_type"]:
        if f not in data:
            warn(f"缺少字段: {f}")
    pool = data.get("candidate_pool", [])
    play4 = data.get("recommended_play4", [])
    if len(pool) != 20:
        warn(f"候选池={len(pool)}个(应为20)")
    if len(play4) != 4:
        warn(f"选四推荐={len(play4)}个(应为4)")
    # 选四推荐号必须在候选池中
    pool_set = set(pool)
    if not set(play4).issubset(pool_set):
        warn("选四推荐不在候选池中")
    ok(f"预测期号={data.get('predicted_issue')} "
       f"策略={data.get('strategy')} 选四={play4}")


def check_review():
    print("\n── kl8_review_latest.json ──")
    p = OUTPUT_DIR / "kl8_review_latest.json"
    if not p.exists():
        info("kl8_review_latest.json 不存在（可能尚未开奖）")
        return
    data = json.loads(p.read_text(encoding="utf-8"))
    for f in ["lottery", "issue", "date", "strategy", "play_type",
              "play4_hit_count", "result_level", "prize", "cost", "profit"]:
        if f not in data:
            warn(f"缺少字段: {f}")
    ok(f"复盘期号={data.get('issue')} 玩法={data.get('play_type')} "
       f"命中={data.get('play4_hit_count')}/4 盈亏={data.get('profit')}")

    # review 期号应与 predict 期号一致
    pp = OUTPUT_DIR / "kl8_predict_latest.json"
    if pp.exists():
        pred = json.loads(pp.read_text(encoding="utf-8"))
        if pred.get("predicted_issue") != data.get("issue"):
            warn(f"复盘期号({data.get('issue')}) ≠ 预测期号({pred.get('predicted_issue')})")


def check_review_history():
    print("\n── kl8_review_history.csv ──")
    p = OUTPUT_DIR / "kl8_review_history.csv"
    if not p.exists():
        ok("review_history 尚未创建（无复盘记录）")
        return
    with open(p, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)
    required = ["期号", "策略", "结果", "奖金", "成本", "盈亏"]
    for f in required:
        if f not in fieldnames:
            warn(f"review_history 缺少字段: {f}")
    seen = set()
    for r in rows:
        key = (r.get("期号", ""), r.get("策略", ""))
        if key in seen:
            warn(f"review_history 重复: 期号={key[0]} 策略={key[1]}")
        seen.add(key)
    ok(f"{len(rows)} 条记录，字段完整")


def main():
    global ERRORS
    print("🔍 快乐8 全链路健康检查")

    check_history()
    check_latest()
    check_predict()
    check_review()
    check_review_history()

    print()
    if ERRORS == 0:
        print("✅ KL8 全链路检查通过")
        sys.exit(0)
    else:
        print(f"❌ {ERRORS} 个问题需要处理")
        sys.exit(1)


if __name__ == "__main__":
    main()
