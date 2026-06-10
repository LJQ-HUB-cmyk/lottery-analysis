#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
覆盖率优化器
============
通过均衡覆盖和值区间、形态、胆码等维度，提升同样 Top-K 注的命中概率。

用法：
    python scripts/coverage_optimizer.py --lottery pls --top-k 10
    python scripts/coverage_optimizer.py --lottery d3 --strategy balanced
    python scripts/coverage_optimizer.py --lottery pls --strategy wheeling
"""

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from itertools import combinations
from pathlib import Path

import pandas as pd
import yaml

BASE = Path(__file__).resolve().parent.parent


def load_config():
    path = BASE / 'rules' / 'coverage_strategies.yaml'
    if path.exists():
        with open(path, encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    return {}


def load_scored_numbers(lottery, exclude_recent=5):
    """加载原评分引擎的全量评分结果。"""
    scripts_dir = str(BASE / 'scripts')
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from scoring_engine import generate_all, generate_predictions, load_weights

    stats_path = BASE / 'data' / 'cache' / f'{lottery}_stats_latest.json'
    feat_path = BASE / 'data' / 'processed' / f'{lottery}_feat.csv'

    if not stats_path.exists() or not feat_path.exists():
        return []

    with open(stats_path, encoding='utf-8') as f:
        stats = json.load(f)
    theory = stats.get('理论分布', {})
    weights, params = load_weights()

    feat_df = pd.read_csv(feat_path, encoding='utf-8-sig')
    feat_df = feat_df.sort_values('期数', ascending=False).reset_index(drop=True)

    exclude_set = set()
    if exclude_recent > 0:
        for i in range(min(exclude_recent, len(feat_df))):
            row = feat_df.iloc[i]
            exclude_set.add((int(row['红球1']), int(row['红球2']), int(row['红球3'])))

    all_df = generate_all()
    _, all_scored = generate_predictions(
        all_df, stats, theory, weights, params,
        exclude_set=exclude_set, top_k=1000,
        exclude_mode='direct', include_baozi=False,
    )
    return all_scored


# ── 策略 A：均衡覆盖 ─────────────────────────────

def strategy_balanced(scored, config):
    """从全量评分中按和值区间+形态均衡选取。"""
    cfg = config.get('balanced', {})
    top_k = config.get('global', {}).get('top_k', 10)

    sum_zones = cfg.get('sum_zones', {})
    morph_cfg = cfg.get('morphology', {})

    # 按和值区间分组
    zone_pools = {}
    for zone_name, zone_cfg in sum_zones.items():
        lo, hi = zone_cfg['range']
        min_count = zone_cfg['min_count']
        candidates = [c for c in scored if lo <= c['和值'] <= hi]
        zone_pools[zone_name] = {
            'candidates': candidates,
            'min_count': min_count,
            'selected': [],
        }

    # 第一轮：每个区间取 min_count 个最高分
    for zone_name, pool in zone_pools.items():
        pool['selected'] = pool['candidates'][:pool['min_count']]

    # 第二轮：从剩余候选中按分数填充到 top_k
    selected_nums = set()
    for pool in zone_pools.values():
        for c in pool['selected']:
            selected_nums.add(c['号码'])

    remaining = [c for c in scored if c['号码'] not in selected_nums]
    for c in remaining:
        if len(selected_nums) >= top_k:
            break
        selected_nums.add(c['号码'])

    # 形态均衡：如果组三不足，替换低分组六
    result = [c for c in scored if c['号码'] in selected_nums][:top_k]
    zusan_min = morph_cfg.get('组三_min', 2)
    zusan_count = sum(1 for c in result if c['形态'] == '组三')

    if zusan_count < zusan_min:
        # 从全量候选中找组三替换
        zusan_candidates = [c for c in scored if c['形态'] == '组三' and c['号码'] not in selected_nums]
        for zc in zusan_candidates[:zusan_min - zusan_count]:
            # 替换最低分的组六
            for i in range(len(result) - 1, -1, -1):
                if result[i]['形态'] == '组六':
                    result[i] = zc
                    break

    return sorted(result, key=lambda x: x['总分'], reverse=True)[:top_k]


# ── 策略 B：旋转覆盖 ─────────────────────────────

def strategy_wheeling(scored, config):
    """选 N 个高分数字，旋转矩阵生成组合。"""
    cfg = config.get('wheeling', {})
    pool_size = cfg.get('pool_size', 7)
    output_count = cfg.get('output_count', 10)

    # 从 Top-N 提取高频数字
    digit_freq = Counter()
    for c in scored[:30]:
        for d in c['号码']:
            digit_freq[d] += 1

    pool_digits = [d for d, _ in digit_freq.most_common(pool_size)]

    # 生成所有 3 位组合
    all_combos = []
    for combo in combinations(pool_digits, 3):
        num_str = ''.join(str(d) for d in sorted(combo))
        # 查找原评分
        orig = next((c for c in scored if c['号码'] == num_str), None)
        if orig:
            all_combos.append(orig)

    # 按分数排序取 top
    all_combos.sort(key=lambda x: x['总分'], reverse=True)
    return all_combos[:output_count]


# ── 策略 C：胆码扩展 ─────────────────────────────

def strategy_danma_expand(scored, config):
    """从 Top10 提取高频胆码，展开包含这些胆码的组合。"""
    cfg = config.get('danma_expand', {})
    danma_count = cfg.get('danma_count', 5)
    source_range = cfg.get('source_range', 10)
    min_danma = cfg.get('min_danma_per_bet', 2)
    top_k = config.get('global', {}).get('top_k', 10)

    # 提取胆码（统一为 int）
    digit_freq = Counter()
    for c in scored[:source_range]:
        for d in c['号码']:
            digit_freq[int(d)] += 1
    danma = set(d for d, _ in digit_freq.most_common(danma_count))

    # 筛选：至少包含 min_danma 个胆码的候选
    candidates = []
    for c in scored:
        num_digits = set(int(d) for d in c['号码'])
        danma_hits = len(num_digits & danma)
        if danma_hits >= min_danma:
            candidates.append(c)

    # 如果不够，降低要求到 1 个胆码
    if len(candidates) < top_k:
        for c in scored:
            num_digits = set(int(d) for d in c['号码'])
            danma_hits = len(num_digits & danma)
            if danma_hits >= 1 and c not in candidates:
                candidates.append(c)

    return candidates[:top_k]


# ── 策略 D：和值区间分散 ─────────────────────────

def strategy_sum_spread(scored, config):
    """在每个和值区间内选最高分号码。"""
    cfg = config.get('sum_spread', {})
    zones = cfg.get('zones', [])
    top_k = config.get('global', {}).get('top_k', 10)

    result = []
    used = set()

    for zone in zones:
        lo, hi = zone['range']
        count = zone['count']
        candidates = [c for c in scored if lo <= c['和值'] <= hi and c['号码'] not in used]
        for c in candidates[:count]:
            result.append(c)
            used.add(c['号码'])

    # 不够则从剩余填充
    for c in scored:
        if len(result) >= top_k:
            break
        if c['号码'] not in used:
            result.append(c)
            used.add(c['号码'])

    return sorted(result, key=lambda x: x['总分'], reverse=True)[:top_k]


# ── 策略 E：形态分散 ─────────────────────────────

def strategy_morph_spread(scored, config):
    """强制按形态比例选取。"""
    cfg = config.get('morph_spread', {})
    top_k = config.get('global', {}).get('top_k', 10)

    zuliu_count = cfg.get('组六_count', 7)
    zusan_count = cfg.get('组三_count', 3)
    baozi_count = cfg.get('豹子_count', 0)

    result = []
    used = set()

    # 按形态分组取最高分
    for morph, count in [('组六', zuliu_count), ('组三', zusan_count), ('豹子', baozi_count)]:
        if count <= 0:
            continue
        candidates = [c for c in scored if c['形态'] == morph and c['号码'] not in used]
        for c in candidates[:count]:
            result.append(c)
            used.add(c['号码'])

    # 不够则从剩余填充
    for c in scored:
        if len(result) >= top_k:
            break
        if c['号码'] not in used:
            result.append(c)
            used.add(c['号码'])

    return sorted(result, key=lambda x: x['总分'], reverse=True)[:top_k]


# ── 主流程 ────────────────────────────────────────

STRATEGIES = {
    'balanced': strategy_balanced,
    'wheeling': strategy_wheeling,
    'danma_expand': strategy_danma_expand,
    'sum_spread': strategy_sum_spread,
    'morph_spread': strategy_morph_spread,
}


def optimize(lottery, strategy_name='balanced', config=None):
    """运行覆盖率优化。"""
    if config is None:
        config = load_config()

    exclude_recent = config.get('global', {}).get('exclude_recent', 5)
    scored = load_scored_numbers(lottery, exclude_recent)
    if not scored:
        raise RuntimeError('无评分数据，请先运行 run_daily.py')

    strategy_fn = STRATEGIES.get(strategy_name)
    if not strategy_fn:
        raise ValueError(f'未知策略: {strategy_name}，可选: {list(STRATEGIES.keys())}')

    result = strategy_fn(scored, config)
    return result


def main():
    parser = argparse.ArgumentParser(description='覆盖率优化器')
    parser.add_argument('--lottery', required=True, choices=['pls', 'd3'])
    parser.add_argument('--strategy', default='balanced',
                        choices=list(STRATEGIES.keys()),
                        help='优化策略（默认 balanced）')
    parser.add_argument('--top-k', type=int, default=None,
                        help='输出注数（覆盖 YAML 配置）')
    args = parser.parse_args()

    config = load_config()
    if args.top_k:
        config.setdefault('global', {})['top_k'] = args.top_k

    lottery_name = '排列三' if args.lottery == 'pls' else '福彩3D'

    print(f"\n{'='*60}")
    print(f"  🎯 {lottery_name} 覆盖率优化器")
    print(f"  策略: {args.strategy} | Top-K: {config.get('global',{}).get('top_k',10)}")
    print(f"{'='*60}")

    result = optimize(args.lottery, args.strategy, config)

    # 输出
    print(f"\n  {'排名':>4} {'号码':>6} {'组选':>6} {'和值':>4} {'跨度':>4} {'形态':>4} {'总分':>4} {'来源'}")
    print(f"  {'─'*55}")
    for i, c in enumerate(result):
        source = c.get('来源', '评分')
        print(f"  {i+1:>4} {c['号码']:>6} {c.get('group_number',''):>6} {c['和值']:>4} {c['跨度']:>4} {c['形态']:>4} {c['总分']:>4} {source}")

    # 统计
    if result:
        sums = [c['和值'] for c in result]
        morphs = Counter(c['形态'] for c in result)
        print(f"\n  📊 覆盖统计:")
        print(f"    和值范围: {min(sums)}~{max(sums)}（跨度 {max(sums)-min(sums)}）")
        print(f"    形态分布: {dict(morphs)}")
    else:
        print(f"\n  ⚠️ 无候选结果")
        return

    # 保存
    output_dir = BASE / 'output' / 'predictions'
    output_dir.mkdir(parents=True, exist_ok=True)

    latest_issue = 0
    feat_path = BASE / 'data' / 'processed' / f'{args.lottery}_feat.csv'
    if feat_path.exists():
        feat_df = pd.read_csv(feat_path, encoding='utf-8-sig', nrows=1)
        latest_issue = int(feat_df.iloc[0]['期数'])

    target_issue = latest_issue + 1
    output_json = {
        '彩种': lottery_name,
        '数据截至期号': latest_issue,
        '预测期号': target_issue,
        'draw_issue': target_issue,
        'task_id': f'{args.lottery}_{target_issue}',
        '评分时间': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        '策略': f'coverage_{args.strategy}',
        'top_k': len(result),
        '优化配置': config.get(args.strategy, {}),
        '摘要': {
            'Top10号码': [c['号码'] for c in result[:10]],
            '和值范围': f"{min(sums)}~{max(sums)}",
            '形态分布': dict(morphs),
        },
        '推荐': [
            {
                '排名': i + 1,
                '号码': c['号码'],
                'group_number': c.get('group_number', ''),
                '和值': c['和值'],
                '跨度': c['跨度'],
                '形态': c['形态'],
                '总分': c['总分'],
            }
            for i, c in enumerate(result)
        ],
    }

    prefix = f'{args.lottery}_coverage'
    output_path = output_dir / f'{prefix}_predict_{target_issue}.json'
    latest_path = output_dir / f'latest_{prefix}.json'

    for p in [output_path, latest_path]:
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(output_json, f, ensure_ascii=False, indent=2)

    print(f"\n  💾 保存: {output_path}")
    print(f"  💾 同步: {latest_path}")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    main()
