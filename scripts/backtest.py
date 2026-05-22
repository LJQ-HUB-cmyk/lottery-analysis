#!/usr/bin/env python3
"""
回测系统 v2 —— walk-forward + 基准对比
=======================================
对比三种策略：
  1. 随机Top-K（基准）
  2. 固定规则策略（和值中区+跨度中区+组六）
  3. 动态评分策略（scoring_engine）

用法：
    python backtest.py --lottery pls --periods 100
    python backtest.py --lottery d3 --periods 200 --top-k 30
"""

import argparse
import json
import sys
import random
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np

# 复用评分引擎
from scoring_engine import generate_all, generate_predictions, load_weights


# ==========================================
#  策略定义
# ==========================================

def strategy_random(all_nums: list, top_k: int, rng: random.Random) -> list:
    """随机策略：随机选 top_k 个"""
    return rng.sample(all_nums, min(top_k, len(all_nums)))


def strategy_fixed_rule(all_nums: list, top_k: int, rng=None) -> list:
    """固定规则策略：和值中区+跨度中区+组六"""
    candidates = []
    for a, b, c in all_nums:
        s = a + b + c
        span = max(a, b, c) - min(a, b, c)
        # 和值中区 10-17
        if not (10 <= s <= 17):
            continue
        # 跨度中区 4-6
        if not (4 <= span <= 6):
            continue
        # 排除豹子
        if a == b == c:
            continue
        candidates.append((a, b, c))
    
    # 如果不够，放宽规则
    if len(candidates) < top_k:
        for a, b, c in all_nums:
            if len(candidates) >= top_k:
                break
            t = (a, b, c)
            if t not in candidates:
                candidates.append(t)
    
    return candidates[:top_k]


def strategy_dynamic_scoring(all_nums_list: list, top_k: int, stats: dict, theory: dict,
                              exclude_nums: set, weights: dict, params: dict, rng=None) -> list:
    """动态评分策略（复用 scoring_engine.generate_predictions）"""
    all_df = generate_all()
    preds, _ = generate_predictions(all_df, stats, theory, weights, params,
                                     exclude_set=exclude_nums, top_k=top_k,
                                     exclude_mode='direct', include_baozi=False)
    return [(int(p['号码'][0]), int(p['号码'][1]), int(p['号码'][2])) for p in preds]


# ==========================================
#  命中判断
# ==========================================

def check_direct(pred: tuple, actual: tuple) -> bool:
    return pred == actual


def check_group(pred: tuple, actual: tuple) -> bool:
    return sorted(pred) == sorted(actual)


# ==========================================
#  Walk-forward 回测
# ==========================================

def walk_forward(df: pd.DataFrame, theory: dict, top_k: int = 30,
                 test_periods: int = 100, train_window: int = 100,
                 lottery_code: str = 'pls', weight_path: str = None,
                 seed: int = None) -> dict:
    """
    Walk-forward 滚动回测
    
    对每期 t：
      train = df[t-test_periods:t]  ← 只用之前的数据
      target = df[t-1]               ← 待预测的下一期
      
    避免未来函数。
    """
    total = len(df)
    if test_periods > total - train_window:
        test_periods = max(0, total - train_window)
    
    strategies = {
        '随机策略': {'hits_direct': 0, 'hits_group': 0, 'hits_group3': 0, 'hits_group6': 0, 'candidates': [], 'miss_streak': 0, 'max_miss_streak': 0},
        '固定规则': {'hits_direct': 0, 'hits_group': 0, 'hits_group3': 0, 'hits_group6': 0, 'candidates': [], 'miss_streak': 0, 'max_miss_streak': 0},
        '动态评分': {'hits_direct': 0, 'hits_group': 0, 'hits_group3': 0, 'hits_group6': 0, 'candidates': [], 'miss_streak': 0, 'max_miss_streak': 0},
    }
    
    rng = random.Random(seed if seed is not None else 42)

    # 加载权重（支持自定义路径）
    weights, params = load_weights(weight_path)

    all_nums = generate_all()
    all_nums_list = [(int(r['红球1']), int(r['红球2']), int(r['红球3'])) 
                     for _, r in all_nums.iterrows()]
    
    # 准备stats模板（供动态评分使用）
    stats_template = {
        '窗口': {
            '近5期': {},
            '近10期': {},
            '近30期': {},
        },
        '理论分布': theory,
    }
    
    # 尝试加载真实的stats数据（用于理论分布和长期基准）
    stats_path = Path(__file__).resolve().parent.parent / 'data' / 'cache' / f'{lottery_code}_stats_latest.json'
    if stats_path.exists():
        with open(stats_path, encoding='utf-8') as f:
            real_stats = json.load(f)
        stats_template['理论分布'] = real_stats.get('理论分布', theory)
    
    print(f"\n  开始 walk-forward 回测 ({test_periods}期)...")
    print(f"  {'─'*50}")
    
    for i in range(test_periods):
        # 训练数据：从最近一期往前 i 个位置，取 train_window 期
        start_idx = i + 1
        end_idx = min(i + 1 + train_window, total)
        train_df = df.iloc[start_idx:end_idx].copy()
        
        # 待预测期
        target_idx = i
        if target_idx >= total:
            break
        target = df.iloc[target_idx]
        actual = (int(target['红球1']), int(target['红球2']), int(target['红球3']))
        
        # 排除目标期之前的最近5期（不是全局最新，避免未来信息泄露）
        exclude = set()
        for j in range(1, min(5, total - i - 1) + 1):
            if i + j < total:
                prev = df.iloc[i + j]
                exclude.add((int(prev['红球1']), int(prev['红球2']), int(prev['红球3'])))
        
        # 更新stats（用训练数据模拟stats_engine）
        if len(train_df) >= 30:
            # 计算真实的近期统计
            t5 = train_df.head(5)
            t10 = train_df.head(10)
            t30 = train_df.head(30)
            
            def _build_freq(df_window, col_name):
                freq = df_window[col_name].value_counts().to_dict()
                return {int(k): int(v) for k, v in freq.items()}
            
            stats_template['窗口']['近5期'] = {
                '和值频率': _build_freq(t5, '和值'),
                '跨度频率': _build_freq(t5, '跨度'),
            }
            stats_template['窗口']['近10期'] = {
                '和值频率': _build_freq(t10, '和值'),
                '跨度频率': _build_freq(t10, '跨度'),
            }
            
            latest_missing = {}
            last = train_df.iloc[0]
            for d in range(10):
                col = f'遗漏_{d}'
                if col in last.index:
                    latest_missing[d] = int(last[col])
            
            morph_pct_30 = {}
            for m in ['组六', '组三', '豹子']:
                cnt = len(t30[t30['形态'] == m])
                morph_pct_30[f'形态_{m}_pct'] = round(cnt / len(t30) * 100, 1)
            
            stats_template['窗口']['近30期'] = {
                '当前遗漏': latest_missing,
                '和值频率': _build_freq(t30, '和值'),
                '跨度频率': _build_freq(t30, '跨度'),
                '平均遗漏': float(last[[c for c in last.index if '遗漏_' in str(c)]].mean() 
                                   if any('遗漏_' in str(c) for c in last.index) else 5),
                **morph_pct_30,
            }
        
        # 执行三种策略
        for sname in strategies:
            if sname == '随机策略':
                preds = strategy_random(all_nums_list, top_k, rng)
            elif sname == '固定规则':
                preds = strategy_fixed_rule(all_nums_list, top_k)
            else:
                preds = strategy_dynamic_scoring(all_nums_list, top_k, stats_template, theory, exclude, weights, params)
            
            s = strategies[sname]
            s['candidates'].append(len(preds))
            
            direct_count = sum(1 for pred in preds if check_direct(pred, actual))
            group_only_count = sum(1 for pred in preds if check_group(pred, actual)) - direct_count

            s['hits_direct'] += direct_count

            if group_only_count > 0:
                s['hits_group'] += group_only_count
                a, b, c = actual
                if a == b or b == c or a == c:
                    s['hits_group3'] += group_only_count
                else:
                    s['hits_group6'] += group_only_count

            if direct_count > 0 or group_only_count > 0:
                s['miss_streak'] = 0
            else:
                s['miss_streak'] += 1
                s['max_miss_streak'] = max(s['max_miss_streak'], s['miss_streak'])
        
        if (i + 1) % 20 == 0:
            print(f"    进度: {i+1}/{test_periods} 期")
    
    # 汇总
    results = {}
    for sname, s in strategies.items():
        avg_candidates = np.mean(s['candidates']) if s['candidates'] else 0
        total_cost = avg_candidates * 2 * test_periods
        direct_prize = s['hits_direct'] * 1040
        group3_prize = s['hits_group3'] * 346
        group6_prize = s['hits_group6'] * 173
        group_prize = group3_prize + group6_prize
        total_prize = direct_prize + group_prize
        roi = (total_prize - total_cost) / total_cost * 100 if total_cost > 0 else 0
        
        direct_cost = avg_candidates * 2 * test_periods
        direct_roi = (direct_prize - direct_cost) / direct_cost * 100 if direct_cost > 0 else 0
        group_roi = (group_prize - direct_cost) / direct_cost * 100 if direct_cost > 0 else 0
        results[sname] = {
            '直选命中': s['hits_direct'],
            '直选命中率': f"{s['hits_direct']/test_periods*100:.2f}%",
            '组选命中': s['hits_group'],
            '组选命中率': f"{s['hits_group']/test_periods*100:.2f}%",
            '平均注数': f"{avg_candidates:.1f}",
            '总投入': f"{total_cost:.0f}元",
            '总回报': f"{total_prize:.0f}元",
            'ROI': f"{roi:.1f}%",
            '直选ROI': f"{direct_roi:.1f}%",
            '组选ROI': f"{group_roi:.1f}%",
            '最大连续未中': s['max_miss_streak'],
        }
    
    return results


# ==========================================
#  输出报告
# ==========================================

def print_report(results: dict, lottery_name: str, top_k: int, periods: int):
    """打印对比报告"""
    print(f"\n{'='*60}")
    print(f"  📊 Walk-Forward 回测报告")
    print(f"  {'='*60}")
    print(f"  🎯 {lottery_name} | Top-K: {top_k} | 回测: {periods}期")
    print(f"  {'='*60}")
    
    print(f"\n  {'策略名称':<12} {'直选命中':>8} {'组选命中':>8} {'平均注数':>8} {'ROI':>8} {'最长连未':>8}")
    print(f"  {'─'*60}")
    
    for sname, sr in results.items():
        print(f"  {sname:<12} {sr['直选命中']:>4}/{periods} {sr['组选命中']:>4}/{periods} "
              f"{sr['平均注数']:>8} {sr['ROI']:>8} {sr['最大连续未中']:>4}期")
    
    print(f"  {'─'*60}")
    print(f"\n  💰 详细盈亏:")
    for sname, sr in results.items():
        print(f"  {sname:<12}: 投入{sr['总投入']:>8} | 回报{sr['总回报']:>8} | ROI {sr['ROI']:>8}")
    
    print(f"\n  ⚠️  风险提示")
    print(f"  本回测仅基于历史数据，不代表未来表现。")
    print(f"  彩票开奖具有高度随机性，回测结果不构成投注建议。")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description='Walk-forward 回测系统 v2')
    parser.add_argument('--lottery', required=True, choices=['pls', 'd3'])
    parser.add_argument('--periods', type=int, default=100,
                        help='回测期数')
    parser.add_argument('--top-k', type=int, default=30,
                        help='推荐注数')
    parser.add_argument('--train-window', type=int, default=100,
                        help='训练窗口期数')
    args = parser.parse_args()

    if args.top_k <= 0:
        print("[错误] --top-k 必须 > 0")
        sys.exit(1)
    if args.periods <= 0:
        print("[错误] --periods 必须 > 0")
        sys.exit(1)
    if args.train_window <= 0:
        print("[错误] --train-window 必须 > 0")
        sys.exit(1)
    
    base_dir = Path(__file__).resolve().parent.parent
    lottery_name = '排列三' if args.lottery == 'pls' else '福彩3D'
    
    # 加载数据（按期号降序，新→旧）
    data_path = base_dir / 'data' / 'processed' / f'{args.lottery}_feat.csv'
    if not data_path.exists():
        print(f"[错误] 特征数据不存在: {data_path}")
        print(f"  请先运行: python run_daily.py {args.lottery}")
        sys.exit(1)
    df = pd.read_csv(data_path, encoding='utf-8-sig')
    df = df.sort_values('期数', ascending=False).reset_index(drop=True)
    
    print(f"\n{'='*60}")
    print(f"  🔄 Walk-Forward 回测 - {lottery_name}")
    print(f"{'='*60}")
    print(f"  数据: {len(df)} 期 ({df['期数'].min()} ~ {df['期数'].max()})")
    print(f"  回测: 最近{args.periods}期 | Top-K: {args.top_k} | 训练窗口: {args.train_window}期")
    
    # 加载理论分布
    from stats_engine import generate_theoretical_distribution
    theory = generate_theoretical_distribution()
    
    # 运行回测
    results = walk_forward(df, theory, args.top_k, args.periods, args.train_window, args.lottery)
    
    # 输出
    print_report(results, lottery_name, args.top_k, args.periods)
    
    # 保存
    output_dir = base_dir / 'output' / 'backtests'
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M')
    output_path = output_dir / f'{args.lottery}_backtest_{timestamp}.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump({
            '彩种': lottery_name,
            '回测期数': args.periods,
            'top_k': args.top_k,
            '训练窗口': args.train_window,
            '回测时间': timestamp,
            '结果': results,
        }, f, ensure_ascii=False, indent=2)
    print(f"  💾 结果已保存: {output_path}")


if __name__ == '__main__':
    main()
