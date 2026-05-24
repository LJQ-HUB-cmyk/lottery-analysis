#!/usr/bin/env python3
"""Optuna 自动调参：对 PLS/D3 评分引擎权重做 walk-forward 回测调优。

用法：
  python scripts/tune_scoring_params.py --lottery pls --trials 80 --periods 120
  python scripts/tune_scoring_params.py --lottery d3 --trials 80 --periods 120
"""

import argparse
import json
import random
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import optuna
import pandas as pd
import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = BASE_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from scoring_engine import generate_all, generate_predictions  # noqa: E402
from stats_engine import generate_theoretical_distribution  # noqa: E402

OUT_DIR = BASE_DIR / "output" / "tuning"
RULES_DIR = BASE_DIR / "rules"


# ── 工具函数 ────────────────────────────────────────

def _shape_of(nums):
    u = len(set(nums))
    if u == 1:
        return "豹子"
    if u == 2:
        return "组三"
    return "组六"


def _group_key(nums):
    return "".join(str(x) for x in sorted(nums))


def _build_freq(df, col):
    if col not in df.columns or df.empty:
        return {}
    return {int(k): int(v) for k, v in df[col].value_counts().to_dict().items()}


# ── Optuna 搜索空间 ─────────────────────────────────

def sample_config(trial):
    """生成一组待评估的权重+参数。只包含评分引擎实际使用的键。"""
    weights = {
        "和值":  trial.suggest_int("w_sum", 8, 28),
        "跨度":  trial.suggest_int("w_span", 6, 25),
        "形态":  trial.suggest_int("w_shape", 4, 18),
        "奇偶":  trial.suggest_int("w_odd_even", 2, 12),
        "大小":  trial.suggest_int("w_big_small", 2, 12),
        "012路": trial.suggest_int("w_mod012", 2, 12),
        "冷热":  trial.suggest_int("w_hot_cold", 0, 18),
        "遗漏":  trial.suggest_int("w_missing", 0, 18),
        "多样性": trial.suggest_int("w_diversity", 0, 16),
    }

    params = {
        "cold_threshold": trial.suggest_int("cold_threshold", 4, 12),
        "hot_threshold":  trial.suggest_int("hot_threshold", 1, 6),
        "group_penalty":  trial.suggest_int("group_penalty", 0, 16),
        "span_spread":    trial.suggest_int("span_spread", 0, 18),
        "overheat_high":   trial.suggest_float("overheat_high", 0.35, 0.85),
        "overheat_medium": trial.suggest_float("overheat_medium", 0.55, 1.00),
    }

    runtime = {
        "exclude_recent": trial.suggest_int("exclude_recent", 0, 8),
        "exclude_mode":   trial.suggest_categorical("exclude_mode", ["direct", "group"]),
        "include_baozi":  trial.suggest_categorical("include_baozi", [False, True]),
    }

    return weights, params, runtime


def params_to_config(params_dict):
    """从 Optuna 参数字典重建 weights/params/runtime。"""
    weights = {
        "和值":  int(params_dict["w_sum"]),
        "跨度":  int(params_dict["w_span"]),
        "形态":  int(params_dict["w_shape"]),
        "奇偶":  int(params_dict["w_odd_even"]),
        "大小":  int(params_dict["w_big_small"]),
        "012路": int(params_dict["w_mod012"]),
        "冷热":  int(params_dict["w_hot_cold"]),
        "遗漏":  int(params_dict["w_missing"]),
        "多样性": int(params_dict["w_diversity"]),
    }

    params = {
        "cold_threshold":  int(params_dict["cold_threshold"]),
        "hot_threshold":   int(params_dict["hot_threshold"]),
        "group_penalty":   int(params_dict["group_penalty"]),
        "span_spread":     int(params_dict["span_spread"]),
        "overheat_high":   float(params_dict["overheat_high"]),
        "overheat_medium": float(params_dict["overheat_medium"]),
    }

    runtime = {
        "exclude_recent": int(params_dict["exclude_recent"]),
        "exclude_mode":   str(params_dict["exclude_mode"]),
        "include_baozi":  bool(params_dict["include_baozi"]),
    }

    return weights, params, runtime


# ── walk-forward 评估 ───────────────────────────────

def evaluate_config(df, all_df, theory, weights, params, runtime,
                    periods, train_window, top_k, seed=42):
    """对最近 periods 期做 walk-forward 回测。"""
    total = len(df)
    usable = min(periods, max(0, total - train_window - 1))

    metrics = {
        "periods": usable,
        "direct_hits": 0,
        "group_hits": 0,
        "sum_diff_total": 0,
        "span_diff_total": 0,
        "shape_match_total": 0,
        "direct_ranks": [],
        "group_ranks": [],
        "miss_streak": 0,
        "max_miss_streak": 0,
    }

    if usable <= 0:
        metrics["objective"] = -9999
        return metrics

    for i in range(usable):
        target = df.iloc[i]
        actual = (int(target["红球1"]), int(target["红球2"]), int(target["红球3"]))
        actual_group = _group_key(actual)
        actual_sum = sum(actual)
        actual_span = max(actual) - min(actual)
        actual_shape = _shape_of(actual)

        train_df = df.iloc[i + 1:i + 1 + train_window].copy()
        if len(train_df) < 30:
            continue

        # 排除最近 N 期
        exclude = set()
        for j in range(1, min(int(runtime.get("exclude_recent", 5)), total - i - 1) + 1):
            prev = df.iloc[i + j]
            exclude.add((int(prev["红球1"]), int(prev["红球2"]), int(prev["红球3"])))

        # 构造 stats
        t30 = train_df.head(30)
        latest_missing = {}
        miss_vals = []
        for d in range(10):
            col = f"遗漏_{d}"
            if col in train_df.columns and pd.notna(train_df.iloc[0][col]):
                val = int(float(train_df.iloc[0][col]))
                latest_missing[d] = val
                miss_vals.append(val)

        stats = {
            "窗口": {
                "近5期": {
                    "和值频率": _build_freq(train_df.head(5), "和值"),
                    "跨度频率": _build_freq(train_df.head(5), "跨度"),
                },
                "近10期": {
                    "和值频率": _build_freq(train_df.head(10), "和值"),
                    "跨度频率": _build_freq(train_df.head(10), "跨度"),
                },
                "近30期": {
                    "和值频率": _build_freq(t30, "和值"),
                    "跨度频率": _build_freq(t30, "跨度"),
                    "形态_组六_pct": round(t30["形态"].value_counts().get("组六", 0) / max(len(t30), 1) * 100, 2),
                    "形态_组三_pct": round(t30["形态"].value_counts().get("组三", 0) / max(len(t30), 1) * 100, 2),
                    "当前遗漏": latest_missing,
                    "平均遗漏": round(sum(miss_vals) / len(miss_vals), 2) if miss_vals else 0,
                },
            },
            "理论分布": theory,
        }

        try:
            preds, _ = generate_predictions(
                all_df, stats, theory, weights, params,
                exclude_set=exclude, top_k=top_k,
                exclude_mode=runtime.get("exclude_mode", "direct"),
                include_baozi=bool(runtime.get("include_baozi", False)),
            )
        except Exception:
            continue

        pred_nums = [(int(p["号码"][0]), int(p["号码"][1]), int(p["号码"][2])) for p in preds]

        if actual in pred_nums:
            metrics["direct_hits"] += 1
            metrics["direct_ranks"].append(pred_nums.index(actual) + 1)

        group_hit = any(_group_key(p) == actual_group for p in pred_nums)
        if group_hit:
            metrics["group_hits"] += 1
            for idx, p in enumerate(pred_nums, start=1):
                if _group_key(p) == actual_group:
                    metrics["group_ranks"].append(idx)
                    break
            metrics["miss_streak"] = 0
        else:
            metrics["miss_streak"] += 1
            metrics["max_miss_streak"] = max(metrics["max_miss_streak"], metrics["miss_streak"])

        if pred_nums:
            metrics["sum_diff_total"] += min(abs(sum(p) - actual_sum) for p in pred_nums)
            metrics["span_diff_total"] += min(abs((max(p) - min(p)) - actual_span) for p in pred_nums)
            metrics["shape_match_total"] += sum(1 for p in pred_nums if _shape_of(p) == actual_shape)

    n = max(metrics["periods"], 1)
    direct_rate = metrics["direct_hits"] / n
    group_rate = metrics["group_hits"] / n
    avg_sum_diff = metrics["sum_diff_total"] / n
    avg_span_diff = metrics["span_diff_total"] / n
    avg_shape = metrics["shape_match_total"] / n
    avg_grp_rank = (sum(metrics["group_ranks"]) / len(metrics["group_ranks"])
                    if metrics["group_ranks"] else top_k + 1)

    objective = (
        group_rate * 80
        + direct_rate * 140
        + avg_shape * 0.6
        - avg_sum_diff * 2.0
        - avg_span_diff * 2.0
        - metrics["max_miss_streak"] * 0.8
        - avg_grp_rank * 0.15
    )

    metrics.update({
        "direct_rate": direct_rate,
        "group_rate": group_rate,
        "avg_sum_diff": avg_sum_diff,
        "avg_span_diff": avg_span_diff,
        "avg_shape_match": avg_shape,
        "avg_group_rank": avg_grp_rank,
        "objective": objective,
    })
    return metrics


def summarize(m):
    n = max(int(m.get("periods", 0)), 1)
    return {
        "periods": m["periods"],
        "direct_hits": m["direct_hits"],
        "direct_%": round(m["direct_rate"] * 100, 2),
        "group_hits": m["group_hits"],
        "group_%": round(m["group_rate"] * 100, 2),
        "avg_sum_diff": round(m["avg_sum_diff"], 3),
        "avg_span_diff": round(m["avg_span_diff"], 3),
        "shape_match_avg": round(m["avg_shape_match"], 3),
        "group_rank_avg": round(m["avg_group_rank"], 2),
        "max_miss": m["max_miss_streak"],
        "objective": round(m["objective"], 4),
    }


# ── YAML 输出 ────────────────────────────────────────

def write_yaml(lottery, weights, params, runtime, stability):
    payload = {
        "meta": {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "lottery": lottery,
            "source": "scripts/tune_scoring_params.py (Optuna)",
            "note": "自动调参生成；建议先灰度观察7天再考虑替换默认策略。",
        },
        "weights": {
            "和值": weights["和值"],
            "跨度": weights["跨度"],
            "形态": weights["形态"],
            "奇偶": weights["奇偶"],
            "大小": weights["大小"],
            "012路": weights["012路"],
            "冷热": weights["冷热"],
            "遗漏": weights["遗漏"],
            "多样性": weights["多样性"],
        },
        "hot_cold": {
            "cold_threshold": params["cold_threshold"],
            "hot_threshold": params["hot_threshold"],
        },
        "diversity": {
            "group_penalty": params["group_penalty"],
            "span_spread": params["span_spread"],
        },
        "overheat_decay": {
            "high": round(float(params["overheat_high"]), 4),
            "medium": round(float(params["overheat_medium"]), 4),
        },
        "runtime": runtime,
        "stability": stability,
    }

    path = RULES_DIR / f"scoring_weights_auto_{lottery}.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False)
    return path


# ── 主流程 ──────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Optuna 自动调参")
    parser.add_argument("--lottery", required=True, choices=["pls", "d3"])
    parser.add_argument("--periods", type=int, default=100)
    parser.add_argument("--train-window", type=int, default=120)
    parser.add_argument("--top-k", type=int, default=30)
    parser.add_argument("--trials", type=int, default=80)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--stability-windows", default="50,100,200")
    parser.add_argument("--min-group-rate", type=float, default=0.08)
    parser.add_argument("--max-miss", type=int, default=35)
    args = parser.parse_args()

    data_path = BASE_DIR / "data" / "processed" / f"{args.lottery}_feat.csv"
    if not data_path.exists():
        print(f"[ERROR] 特征文件不存在: {data_path}")
        sys.exit(1)

    df = pd.read_csv(data_path, encoding="utf-8-sig")
    df = df.sort_values("期数", ascending=False).reset_index(drop=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RULES_DIR.mkdir(parents=True, exist_ok=True)

    theory = generate_theoretical_distribution()
    all_df = generate_all()

    print(f"\n=== {args.lottery} Optuna 自动调参 ===")
    print(f"数据: {len(df)} 期 | trials={args.trials} | periods={args.periods} | "
          f"train={args.train_window} | top_k={args.top_k}")

    def objective(trial):
        w, p, r = sample_config(trial)
        m = evaluate_config(df, all_df, theory, w, p, r,
                            args.periods, args.train_window, args.top_k, args.seed)
        trial.set_user_attr("metrics", summarize(m))
        return float(m["objective"])

    sampler = optuna.samplers.TPESampler(seed=args.seed)
    study = optuna.create_study(direction="maximize", sampler=sampler)
    study.optimize(objective, n_trials=args.trials, show_progress_bar=True)

    # 最佳参数
    weights, params, runtime = params_to_config(study.best_trial.params)

    # 稳定性验证
    windows = [int(x.strip()) for x in args.stability_windows.split(",") if x.strip()]
    stability = {}
    stable_pass = True
    for win in windows:
        m = evaluate_config(df, all_df, theory, weights, params, runtime,
                            win, args.train_window, args.top_k, args.seed)
        s = summarize(m)
        stability[str(win)] = s
        if m["group_rate"] < args.min_group_rate or m["max_miss_streak"] > args.max_miss:
            stable_pass = False
    stability["pass"] = stable_pass
    stability["rules"] = {"min_group_rate": args.min_group_rate, "max_miss": args.max_miss}

    # 输出
    yaml_path = write_yaml(args.lottery, weights, params, runtime, stability)

    report = {
        "lottery": args.lottery,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "best_value": study.best_value,
        "best_params": study.best_trial.params,
        "best_metrics": study.best_trial.user_attrs.get("metrics", {}),
        "stability": stability,
        "yaml_path": str(yaml_path.relative_to(BASE_DIR)),
        "trials": [
            {"number": t.number, "value": t.value, "params": t.params,
             "metrics": t.user_attrs.get("metrics", {})}
            for t in study.trials if t.value is not None
        ],
    }

    for p in [OUT_DIR / f"{args.lottery}_tuning_latest.json",
              OUT_DIR / f"{args.lottery}_tuning_{datetime.now().strftime('%Y%m%d_%H%M')}.json"]:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n=== 调参完成 ===")
    print(f"Best: {study.best_value:.2f} | 稳定通过: {stable_pass}")
    print(f"YAML: {yaml_path}")
    for win in windows:
        s = stability[str(win)]
        print(f"  {win}期: 直选{s['direct_hits']}/{s['periods']}={s['direct_%']}%  "
              f"组选{s['group_hits']}/{s['periods']}={s['group_%']}%  "
              f"和差{s['avg_sum_diff']} 跨差{s['avg_span_diff']} 连未{s['max_miss']}")


if __name__ == "__main__":
    main()
