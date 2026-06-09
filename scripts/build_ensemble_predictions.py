#!/usr/bin/env python3
"""策略融合：共识投票加权，生成 ensemble Top30。

读取多个策略的预测 JSON，按 strategy_registry.yaml 配置的权重
做共识投票，输出 ensemble 预测。

用法：
  python scripts/build_ensemble_predictions.py --lottery pls
  python scripts/build_ensemble_predictions.py --lottery d3
  python scripts/build_ensemble_predictions.py --lottery all
"""

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent.parent
PRED_DIR = BASE / "output" / "predictions"
RULES_DIR = BASE / "rules"
CN_TZ = timezone(timedelta(hours=8))


def load_registry():
    path = RULES_DIR / "strategy_registry.yaml"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def load_prediction(lottery, strategy):
    """加载单个策略的预测 JSON。"""
    suffix = "" if strategy == "default" else f"_{strategy}"
    path = PRED_DIR / f"latest_{lottery}{suffix}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_ensemble(lottery):
    """共识投票加权，生成 ensemble Top30。"""
    registry = load_registry()
    strategies = registry.get("strategies", {})
    fusion_cfg = registry.get("fusion", {})

    # 收集所有启用的规则策略
    active = {}
    weights = {}
    for name, cfg in strategies.items():
        if not cfg.get("enabled"):
            continue
        if cfg.get("type") != "rule":
            continue
        w = cfg.get("weight", 0)
        if w is None or w <= 0:
            continue
        active[name] = cfg
        weights[name] = w

    if len(active) < 2:
        print(f"  [WARN] 可用策略不足 {len(active)} 个，跳过融合", file=sys.stderr)
        return None

    # 收集每个策略的 Top30 号码及分数
    strategy_nums = {}   # name → set of numbers
    strategy_data = {}   # name → full prediction JSON
    all_candidates = {}  # number → {strategy: score}

    for name in active:
        data = load_prediction(lottery, name)
        if not data:
            print(f"  [WARN] {name} 预测文件缺失，跳过", file=sys.stderr)
            continue
        strategy_data[name] = data
        nums = set()
        for item in data.get("推荐", [])[:30]:
            if isinstance(item, dict):
                num = str(item.get("号码", "")).zfill(3)
            else:
                num = str(item).zfill(3)
            if num:
                nums.add(num)
                all_candidates.setdefault(num, {})[name] = item.get("总分", 0) if isinstance(item, dict) else 0
        strategy_nums[name] = nums

    if len(strategy_nums) < 2:
        return None

    # 共识投票：每注号码的 ensemble 分数
    consensus_bonus = fusion_cfg.get("consensus_bonus", 1.1)
    dual_bonus = fusion_cfg.get("dual_select_bonus", 1.05)
    min_strategies = fusion_cfg.get("min_strategies", 2)

    scores = {}
    total_weight = sum(weights.values())

    for num, strat_scores in all_candidates.items():
        vote_count = len(strat_scores)
        if vote_count < min_strategies:
            continue

        # 基础加权分：各策略对该号码的评分加权平均
        weighted_score = sum(
            strat_scores.get(s, 0) * weights.get(s, 0)
            for s in strat_scores
        ) / total_weight

        # 共识加成
        boost = 1.0
        if vote_count >= 3:
            boost *= consensus_bonus
        if "default" in strat_scores and "auto_tuned" in strat_scores:
            boost *= dual_bonus

        scores[num] = weighted_score * boost

    # 排序取 Top30
    ranked = sorted(scores.items(), key=lambda x: -x[1])[:30]
    top30_nums = [n for n, _ in ranked]

    def _num_info(num_str):
        ds = [int(c) for c in num_str.zfill(3)]
        s = sum(ds)
        sp = max(ds) - min(ds)
        u = len(set(ds))
        if u == 1:
            m = "豹子"
        elif u == 2:
            m = "组三"
        else:
            m = "组六"
        return s, sp, m

    # 构建预测 JSON
    template = strategy_data.get("default", {})
    issue = template.get("预测期号", "?")

    result = {
        "彩种": template.get("彩种", lottery),
        "预测期号": issue,
        "策略": "ensemble",
        "评分时间": datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "融合策略数": len(strategy_nums),
        "融合权重": {name: round(w / total_weight, 2) for name, w in weights.items()},
        "推荐": [
            {
                "排名": i + 1,
                "号码": num,
                "group_number": "".join(sorted(num.zfill(3))),
                "和值": _num_info(num)[0],
                "跨度": _num_info(num)[1],
                "形态": _num_info(num)[2],
                "融合分": round(score, 2),
                "策略覆盖数": len(all_candidates.get(num, {})),
            }
            for i, (num, score) in enumerate(ranked)
        ],
        "摘要": {
            "Top10号码": top30_nums[:10],
            "Top10号码": top30_nums,
            "总分最高": round(ranked[0][1], 2) if ranked else 0,
            "融合前策略数": len(strategy_nums),
        },
    }

    return result


def save_prediction(lottery, data):
    """保存预测 JSON，同时写 latest 和按期号文件。"""
    issue = data.get("预测期号", "unknown")
    ts = data["评分时间"].replace(" ", "").replace(":", "")
    # latest
    latest_path = PRED_DIR / f"latest_{lottery}_ensemble.json"
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # 按期号
    issue_path = PRED_DIR / f"{lottery}_ensemble_predict_{issue}.json"
    with open(issue_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"  [OK] {latest_path}")
    print(f"  [OK] {issue_path}")


def main():
    parser = argparse.ArgumentParser(description="策略融合预测")
    parser.add_argument("--lottery", required=True, choices=["pls", "d3", "all"])
    args = parser.parse_args()

    lotteries = ["pls", "d3"] if args.lottery == "all" else [args.lottery]

    for lt in lotteries:
        print(f"\n=== {lt.upper()} 策略融合 ===")
        result = build_ensemble(lt)
        if not result:
            print("  融合失败（策略不足或文件缺失）")
            continue
        save_prediction(lt, result)
        summary = result["摘要"]
        print(f"  预测期号: {result['预测期号']}")
        print(f"  融合策略: {result['融合策略数']} 个")
        print(f"  Top10: {' '.join(summary['Top10号码'][:10])}")


if __name__ == "__main__":
    main()
