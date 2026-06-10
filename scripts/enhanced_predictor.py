#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强预测器 v1 —— 5 大改进提升命中率
=====================================
1. 分位数字分析：百位/十位/个位各取 Top3-4 组合（27-64 注覆盖密度 37-64 倍）
2. 和值区间过滤：预测最可能和值区间 ±2，候选池优先排列
3. 对子/连号模式：近期对子/连号频率加分
4. 热号池策略：Top10 高频数字展开组合作为互补池
5. 多期窗口动态权重：近 5/10 期表现好的维度自动加权

用法：
    python scripts/enhanced_predictor.py --lottery pls --top-k 30
    python scripts/enhanced_predictor.py --lottery d3 --top-k 30
"""

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

BASE = Path(__file__).resolve().parent.parent


# ==========================================
#  1. 分位数字分析
# ==========================================

def positional_digit_scores(feat_df: pd.DataFrame, window: int = 30) -> dict:
    """分析百位/十位/个位各数字在近 N 期的出现频率，返回评分。

    返回:
        {
            '百位': {0: score, 1: score, ..., 9: score},
            '十位': {...},
            '个位': {...},
        }
    """
    df = feat_df.head(window)
    n = len(df)
    result = {}

    for pos, col in [('百位', '红球1'), ('十位', '红球2'), ('个位', '红球3')]:
        freq = df[col].value_counts().reindex(range(10), fill_value=0)
        # 理论频率 = n * 0.1，实际频率 / 理论频率 = 偏差比
        scores = {}
        for d in range(10):
            actual = freq.get(d, 0)
            expected = n * 0.1
            ratio = actual / expected if expected > 0 else 1.0
            # 评分：偏差比越高分越高，但有上限（过热衰减）
            if ratio > 1.5:
                scores[d] = 0.7  # 过热
            elif ratio > 1.2:
                scores[d] = 1.0  # 热
            elif ratio > 0.8:
                scores[d] = 0.8  # 正常
            elif ratio > 0.5:
                scores[d] = 0.5  # 偏冷
            else:
                scores[d] = 0.3  # 冷
        result[pos] = scores

    return result


def generate_positional_candidates(pos_scores: dict, top_n: int = 3) -> list:
    """从分位评分中取每个位置 Top-N 数字，组合成候选号码。

    top_n=3 → 3×3×3=27 注
    top_n=4 → 4×4×4=64 注
    """
    bai_top = sorted(pos_scores['百位'], key=pos_scores['百位'].get, reverse=True)[:top_n]
    shi_top = sorted(pos_scores['十位'], key=pos_scores['十位'].get, reverse=True)[:top_n]
    ge_top = sorted(pos_scores['个位'], key=pos_scores['个位'].get, reverse=True)[:top_n]

    candidates = []
    for a in bai_top:
        for b in shi_top:
            for c in ge_top:
                candidates.append((a, b, c))
    return candidates


# ==========================================
#  2. 和值区间过滤
# ==========================================

def predict_sum_range(feat_df: pd.DataFrame, window: int = 30) -> tuple:
    """预测最可能的和值区间。

    综合近 5 期和近 30 期的和值分布，返回 (center, low, high)。
    """
    recent5 = feat_df.head(5)
    recent30 = feat_df.head(window)

    # 近 5 期和值均值（加权 60%）
    mean5 = recent5['和值'].mean()
    # 近 30 期高频和值（加权 40%）
    sum_freq = recent30['和值'].value_counts()
    top_sums = sum_freq.head(5).index.tolist()
    mean30_top = np.mean(top_sums) if top_sums else 13

    # 综合预测
    center = int(round(mean5 * 0.6 + mean30_top * 0.4))
    center = max(0, min(27, center))

    return center, center - 2, center + 2


def score_by_sum_range(number: tuple, sum_low: int, sum_high: int) -> float:
    """和值区间评分：在区间内得 1.0，越远越低。"""
    s = sum(number)
    if sum_low <= s <= sum_high:
        return 1.0
    dist = min(abs(s - sum_low), abs(s - sum_high))
    return max(0.0, 1.0 - dist * 0.2)


# ==========================================
#  3. 对子/连号模式
# ==========================================

def analyze_patterns(feat_df: pd.DataFrame, window: int = 30) -> dict:
    """分析近 N 期的对子和连号模式频率。"""
    df = feat_df.head(window)
    n = len(df)

    pair_count = 0
    consecutive_count = 0

    for _, row in df.iterrows():
        digits = [int(row['红球1']), int(row['红球2']), int(row['红球3'])]
        # 对子：有两个相同数字
        if len(set(digits)) == 2:
            pair_count += 1
        # 连号：有两个数字相差 1
        sorted_d = sorted(digits)
        if sorted_d[1] - sorted_d[0] == 1 or sorted_d[2] - sorted_d[1] == 1:
            consecutive_count += 1

    return {
        'pair_rate': pair_count / n if n > 0 else 0.27,
        'consecutive_rate': consecutive_count / n if n > 0 else 0.5,
        'pair_trend': 'high' if pair_count / n > 0.35 else ('low' if pair_count / n < 0.2 else 'normal'),
        'consecutive_trend': 'high' if consecutive_count / n > 0.6 else ('low' if consecutive_count / n < 0.4 else 'normal'),
    }


def score_by_pattern(number: tuple, patterns: dict) -> float:
    """对子/连号模式评分。"""
    digits = sorted(number)
    score = 0.5  # 基础分

    # 对子加分
    is_pair = len(set(digits)) == 2
    if is_pair and patterns['pair_trend'] == 'high':
        score += 0.3  # 近期对子多 + 本注是对子
    elif is_pair and patterns['pair_trend'] == 'normal':
        score += 0.15

    # 连号加分
    has_consecutive = (digits[1] - digits[0] == 1) or (digits[2] - digits[1] == 1)
    if has_consecutive and patterns['consecutive_trend'] == 'high':
        score += 0.2
    elif has_consecutive and patterns['consecutive_trend'] == 'normal':
        score += 0.1

    return min(1.0, score)


# ==========================================
#  4. 热号池策略
# ==========================================

def extract_hot_pool(feat_df: pd.DataFrame, window: int = 30,
                     pool_size: int = 6) -> list:
    """从近 N 期提取高频数字池。"""
    df = feat_df.head(window)
    all_digits = pd.concat([df['红球1'], df['红球2'], df['红球3']])
    freq = all_digits.value_counts()
    return sorted(freq.head(pool_size).index.tolist())


def generate_pool_candidates(hot_pool: list) -> list:
    """从热号池展开所有组六组合。"""
    from itertools import combinations
    combos = list(combinations(hot_pool, 3))
    return [tuple(sorted(c)) for c in combos]


# ==========================================
#  5. 多期窗口动态权重
# ==========================================

def compute_dimension_weights(feat_df: pd.DataFrame,
                              base_weights: dict) -> dict:
    """根据近 5/10 期的实际表现，动态调整各维度权重。

    思路：如果某个维度的"理论值 vs 实际值"偏差在近期持续缩小，
    说明该维度的预测能力在增强，应加权。
    """
    if len(feat_df) < 15:
        return base_weights

    recent5 = feat_df.head(5)
    recent10 = feat_df.head(10)
    recent30 = feat_df.head(30)

    adjusted = dict(base_weights)

    # 和值维度：近 5 期和值标准差 vs 近 30 期标准差
    std5 = recent5['和值'].std()
    std30 = recent30['和值'].std()
    if std30 > 0:
        volatility_ratio = std5 / std30
        if volatility_ratio < 0.7:
            # 近期和值波动小，和值预测更可靠，加权
            adjusted['和值'] = int(base_weights.get('和值', 18) * 1.2)
        elif volatility_ratio > 1.3:
            # 近期波动大，降低和值权重
            adjusted['和值'] = int(base_weights.get('和值', 18) * 0.8)

    # 跨度维度：同理
    span_std5 = recent5['跨度'].std()
    span_std30 = recent30['跨度'].std()
    if span_std30 > 0:
        span_vol = span_std5 / span_std30
        if span_vol < 0.7:
            adjusted['跨度'] = int(base_weights.get('跨度', 15) * 1.2)
        elif span_vol > 1.3:
            adjusted['跨度'] = int(base_weights.get('跨度', 15) * 0.8)

    # 形态维度：近 10 期形态偏差
    morph_theory = {'组六': 70, '组三': 27, '豹子': 3}
    for morph, theory_pct in morph_theory.items():
        actual_pct_10 = len(recent10[recent10['形态'] == morph]) / len(recent10) * 100
        if abs(actual_pct_10 - theory_pct) > 15:
            # 偏差大，形态预测更不确定，降权
            adjusted['形态'] = int(base_weights.get('形态', 16) * 0.85)
            break

    return adjusted


# ==========================================
#  综合评分
# ==========================================

def enhanced_score(number: tuple, pos_scores: dict, sum_range: tuple,
                   patterns: dict, hot_pool: list, dim_weights: dict,
                   base_score: float = 0) -> float:
    """综合 5 大改进的增强评分。"""
    a, b, c = number

    # 1. 分位数字评分 (权重 30%)
    pos_score = (
        pos_scores['百位'].get(a, 0.5) +
        pos_scores['十位'].get(b, 0.5) +
        pos_scores['个位'].get(c, 0.5)
    ) / 3.0

    # 2. 和值区间评分 (权重 25%)
    center, low, high = sum_range
    sum_score = score_by_sum_range(number, low, high)

    # 3. 对子/连号模式评分 (权重 15%)
    pattern_score = score_by_pattern(number, patterns)

    # 4. 热号池加分 (权重 15%)
    pool_score = 0.0
    digits_set = {a, b, c}
    hot_hits = len(digits_set & set(hot_pool))
    pool_score = hot_hits / 3.0

    # 5. 动态权重微调 (权重 15%)
    # 用维度权重的偏差来调整
    weight_sum = sum(dim_weights.values())
    weight_normalized = weight_sum / 105.0  # 105 是默认权重总和
    dynamic_score = min(1.0, weight_normalized)

    # 综合
    final = (
        pos_score * 0.30 +
        sum_score * 0.25 +
        pattern_score * 0.15 +
        pool_score * 0.15 +
        dynamic_score * 0.15
    )

    # 加上基础评分（来自原评分引擎）的贡献
    if base_score > 0:
        final = final * 0.5 + (base_score / 100.0) * 0.5

    return round(final * 100, 1)


# ==========================================
#  主流程
# ==========================================

def predict_enhanced(lottery: str, top_k: int = 30,
                     exclude_recent: int = 5) -> dict:
    """增强预测主入口。"""
    base_dir = BASE
    feat_path = base_dir / 'data' / 'processed' / f'{lottery}_feat.csv'
    stats_path = base_dir / 'data' / 'cache' / f'{lottery}_stats_latest.json'

    if not feat_path.exists():
        raise FileNotFoundError(f"特征文件不存在: {feat_path}")

    # 加载数据
    feat_df = pd.read_csv(feat_path, encoding='utf-8-sig')
    feat_df = feat_df.sort_values('期数', ascending=False).reset_index(drop=True)

    # 加载原评分引擎结果（用于基础评分）
    pred_path = base_dir / 'output' / 'predictions' / f'latest_{lottery}.json'
    base_scores = {}
    if pred_path.exists():
        with open(pred_path, encoding='utf-8') as f:
            pred_data = json.load(f)
        for item in pred_data.get('推荐', []):
            if isinstance(item, dict):
                num = str(item.get('号码', '')).zfill(3)
                base_scores[num] = item.get('总分', 0)

    # 加载权重
    weights_path = base_dir / 'rules' / 'scoring_weights.yaml'
    if weights_path.exists():
        with open(weights_path, encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
        base_weights = cfg.get('weights', {})
    else:
        base_weights = {'和值': 18, '跨度': 15, '形态': 16, '奇偶': 8,
                        '大小': 8, '012路': 7, '冷热': 10, '遗漏': 7,
                        '组三六偏向': 8, '多样性': 10}

    # 5 大改进计算
    # 1. 分位数字分析
    pos_scores = positional_digit_scores(feat_df, window=30)
    pos_candidates = generate_positional_candidates(pos_scores, top_n=3)

    # 2. 和值区间
    sum_range = predict_sum_range(feat_df, window=30)

    # 3. 对子/连号模式
    patterns = analyze_patterns(feat_df, window=30)

    # 4. 热号池
    hot_pool = extract_hot_pool(feat_df, window=30, pool_size=6)
    pool_candidates = generate_pool_candidates(hot_pool)

    # 5. 动态权重
    dim_weights = compute_dimension_weights(feat_df, base_weights)

    # 合并候选池（分位候选 + 热号池候选 + 原 Top10）
    all_candidates = set()
    for n in pos_candidates:
        all_candidates.add(tuple(sorted(n)))
    for n in pool_candidates:
        all_candidates.add(tuple(sorted(n)))

    # 加入原 Top10 的候选
    for num_str, _ in sorted(base_scores.items(), key=lambda x: -x[1])[:50]:
        digits = tuple(int(d) for d in num_str.zfill(3))
        all_candidates.add(tuple(sorted(digits)))

    # 排除近 N 期
    exclude_set = set()
    if exclude_recent > 0:
        for i in range(min(exclude_recent, len(feat_df))):
            row = feat_df.iloc[i]
            exclude_set.add((int(row['红球1']), int(row['红球2']), int(row['红球3'])))

    # 排除豹子
    scored = []
    for num_tuple in all_candidates:
        if len(set(num_tuple)) == 1:  # 豹子
            continue
        if num_tuple in exclude_set:
            continue

        num_str = ''.join(str(d) for d in num_tuple)
        base = base_scores.get(num_str, 0)

        score = enhanced_score(
            num_tuple, pos_scores, sum_range, patterns, hot_pool,
            dim_weights, base_score=base
        )

        scored.append({
            '号码': num_str,
            'group_number': ''.join(str(d) for d in sorted(num_tuple)),
            '和值': sum(num_tuple),
            '跨度': max(num_tuple) - min(num_tuple),
            '形态': '组三' if len(set(num_tuple)) == 2 else '组六',
            '增强分': score,
            '基础分': base,
            '来源': _classify_source(num_tuple, pos_candidates, pool_candidates, base_scores),
        })

    # 排序
    scored.sort(key=lambda x: x['增强分'], reverse=True)
    top_k_result = scored[:top_k]

    # 生成输出
    latest_issue = int(feat_df.iloc[0]['期数'])
    target_issue = latest_issue + 1
    lottery_name = '排列三' if lottery == 'pls' else '福彩3D'

    result = {
        '彩种': lottery_name,
        '数据截至期号': latest_issue,
        '预测期号': target_issue,
        'draw_issue': target_issue,
        'task_id': f'{lottery}_{target_issue}',
        '评分时间': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        '策略': 'enhanced_v1',
        'top_k': top_k,
        '改进信息': {
            '分位Top3': {
                '百位': sorted(pos_scores['百位'], key=pos_scores['百位'].get, reverse=True)[:3],
                '十位': sorted(pos_scores['十位'], key=pos_scores['十位'].get, reverse=True)[:3],
                '个位': sorted(pos_scores['个位'], key=pos_scores['个位'].get, reverse=True)[:3],
            },
            '和值区间': f"{sum_range[1]}-{sum_range[2]}（中心{sum_range[0]}）",
            '对子率': f"{patterns['pair_rate']:.0%}（{patterns['pair_trend']}）",
            '连号率': f"{patterns['consecutive_rate']:.0%}（{patterns['consecutive_trend']}）",
            '热号池': hot_pool,
            '动态权重': dim_weights,
        },
        '摘要': {
            'Top10号码': [c['号码'] for c in top_k_result[:10]],
            'Top10号码': [c['号码'] for c in top_k_result[:30]],
            '候选总数': len(scored),
            '分位候选数': len(pos_candidates),
            '热号池候选数': len(pool_candidates),
        },
        '推荐': [
            {
                '排名': i + 1,
                '号码': c['号码'],
                'group_number': c['group_number'],
                '和值': c['和值'],
                '跨度': c['跨度'],
                '形态': c['形态'],
                '总分': c['增强分'],
                '基础分': c['基础分'],
                '来源': c['来源'],
            }
            for i, c in enumerate(top_k_result)
        ],
    }

    return result


def _classify_source(num_tuple, pos_candidates, pool_candidates, base_scores) -> str:
    """标记号码来源。"""
    sources = []
    if num_tuple in pos_candidates:
        sources.append('分位')
    if num_tuple in pool_candidates:
        sources.append('热池')
    num_str = ''.join(str(d) for d in num_tuple)
    if num_str in base_scores:
        sources.append('原评')
    return '+'.join(sources) if sources else '其他'


def main():
    parser = argparse.ArgumentParser(description='增强预测器 v1')
    parser.add_argument('--lottery', required=True, choices=['pls', 'd3'])
    parser.add_argument('--top-k', type=int, default=30)
    parser.add_argument('--exclude-recent', type=int, default=5)
    args = parser.parse_args()

    lottery_name = '排列三' if args.lottery == 'pls' else '福彩3D'

    print(f"\n{'='*60}")
    print(f"  🎯 {lottery_name} 增强预测器 v1")
    print(f"  Top-K: {args.top_k} | 排除近{args.exclude_recent}期")
    print(f"{'='*60}")

    result = predict_enhanced(args.lottery, args.top_k, args.exclude_recent)

    # 终端输出
    info = result['改进信息']
    print(f"\n  📊 改进信息:")
    print(f"    分位Top3: 百{info['分位Top3']['百位']} 十{info['分位Top3']['十位']} 个{info['分位Top3']['个位']}")
    print(f"    和值区间: {info['和值区间']}")
    print(f"    对子率: {info['对子率']} | 连号率: {info['连号率']}")
    print(f"    热号池: {info['热号池']}")
    print(f"    候选总数: {result['摘要']['候选总数']}（分位{result['摘要']['分位候选数']}+热池{result['摘要']['热号池候选数']}+原评）")

    print(f"\n  {'排名':>4} {'号码':>6} {'组选':>6} {'和值':>4} {'跨度':>4} {'形态':>4} {'增强分':>5} {'基础分':>5} {'来源'}")
    print(f"  {'─'*65}")
    for r in result['推荐'][:15]:
        print(f"  {r['排名']:>4} {r['号码']:>6} {r['group_number']:>6} {r['和值']:>4} {r['跨度']:>4} {r['形态']:>4} {r['总分']:>5} {r['基础分']:>5} {r['来源']}")

    if len(result['推荐']) > 15:
        print(f"  ... 共 {len(result['推荐'])} 注")

    # 保存
    output_dir = BASE / 'output' / 'predictions'
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = args.lottery
    output_path = output_dir / f'{prefix}_enhanced_predict_{result["预测期号"]}.json'
    latest_path = output_dir / f'latest_{prefix}_enhanced.json'

    for p in [output_path, latest_path]:
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n  💾 保存: {output_path}")
    print(f"  💾 同步: {latest_path}")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    main()
