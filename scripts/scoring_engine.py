#!/usr/bin/env python3
"""
动态评分引擎 v2（核心）
=====================
对000-999全部1000注号码进行多维度评分，输出Top-K候选。

改进（v2）：
  1. 权重从 YAML 加载，不再硬编码
  2. 组选多样性惩罚：同组选只保留最高分直选
  3. 跨度多样性促进：Top-K尽量覆盖多个跨度
  4. 冷号阈值下调：遗漏>6视为冷号
  5. 过热衰减更敏感

用法：
    python scoring_engine.py --lottery pls --top-k 30
    python scoring_engine.py --lottery d3 --weights rules/scoring_weights.yaml
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np
import yaml


MAX_SCORE = 100


# ==========================================
#  加载YAML权重
# ==========================================

def load_weights(weight_path=None):
    """从YAML加载评分权重"""
    base = Path(__file__).resolve().parent.parent

    if weight_path is None:
        weight_path = base / 'rules' / 'scoring_weights.yaml'
    else:
        p = Path(weight_path)
        weight_path = p if p.is_absolute() else base / p

    if weight_path.exists():
        with open(weight_path, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
        w = cfg.get('weights', {})
        # 兼容旧键名（中文）
        weights = {
            '和值': w.get('和值', 18),
            '跨度': w.get('跨度', 15),
            '形态': w.get('形态', 12),
            '奇偶': w.get('奇偶', 8),
            '大小': w.get('大小', 8),
            '012路': w.get('012路', 7),
            '冷热': w.get('冷热', 10),
            '遗漏': w.get('遗漏', 7),
            '组三/六偏向': w.get('组三六偏向', 8),
            '多样性': w.get('多样性', 10),
        }
        params = {
            'cold_threshold': cfg.get('hot_cold', {}).get('cold_threshold', 6),
            'hot_threshold': cfg.get('hot_cold', {}).get('hot_threshold', 3),
            'group_penalty': cfg.get('diversity', {}).get('group_penalty', 5),
            'span_spread': cfg.get('diversity', {}).get('span_spread', 8),
            'overheat_high': cfg.get('overheat_decay', {}).get('high', 0.6),
            'overheat_medium': cfg.get('overheat_decay', {}).get('medium', 0.8),
        }
        return weights, params
    else:
        # 旧版默认权重（兼容）
        return {
            '和值': 20, '跨度': 18, '形态': 14, '奇偶': 10,
            '大小': 10, '012路': 8, '冷热': 5, '遗漏': 5,
            '组三/六偏向': 10, '多样性': 0,
        }, {}


# ==========================================
#  生成000-999全部号码
# ==========================================

_cached_all_df = None


def generate_all():
    """生成000-999共1000个号码，复用 feature_engine.add_features 计算特征。
    结果缓存到模块级变量，避免回测/调参中重复计算。"""
    global _cached_all_df
    if _cached_all_df is not None:
        return _cached_all_df.copy()
    from feature_engine import add_features
    nums = [(a, b, c) for a in range(10) for b in range(10) for c in range(10)]
    df = pd.DataFrame(nums, columns=['红球1', '红球2', '红球3'])
    df = add_features(df)
    _cached_all_df = df
    return df.copy()


# ==========================================
#  评分函数
# ==========================================

def _score_frequency(value, theory_key, freq_key, weight, theory, window_30, window_5, params):
    """通用频率评分：和值/跨度共用逻辑。返回 (score, desc_str)。"""
    theory_dist = {int(k): v for k, v in theory.get(theory_key, {}).items()}
    freq = theory_dist.get(value, 0)
    max_freq = max(theory_dist.values()) if theory_dist and max(theory_dist.values()) > 0 else 1
    theory_score = int(weight * freq / max_freq)

    freq_30 = {int(k): v for k, v in window_30.get(freq_key, {}).items() if v}
    if freq_30 and sum(freq_30.values()) > 0:
        total_30 = sum(freq_30.values())
        recent_ratio = freq_30.get(value, 0) / total_30
        expected_ratio = theory_dist.get(value, 0) / 1000.0
        recent_score = int(weight * min(recent_ratio / expected_ratio, 1.5) / 1.5) if expected_ratio > 0 else 0
    else:
        recent_score = 0
    recent_score = min(recent_score, int(weight * 0.8))

    freq_5 = {int(k): v for k, v in window_5.get(freq_key, {}).items() if v}
    decay = 1.0
    if freq_5.get(value, 0) >= 3:
        decay = params['overheat_high']
    elif freq_5.get(value, 0) >= 2:
        decay = params['overheat_medium']

    score = int((theory_score * 0.6 + recent_score * 0.4) * decay)
    return score, f"{theory_key}={value}"


def score_number(row, stats, theory, weights, params):
    """
    多维度评分，返回 {总分, 明细}
    """
    details = {}
    total = 0

    s_val = row['和值']
    span_val = row['跨度']
    morph = row['形态']
    window_30 = stats.get('窗口', {}).get('近30期', {})
    window_5 = stats.get('窗口', {}).get('近5期', {})

    W = weights
    P = params
    cold_th = P.get('cold_threshold', 6)
    hot_th = P.get('hot_threshold', 3)

    # ---- 1. 和值评分 ----
    sum_score, sum_desc = _score_frequency(
        s_val, '和值', '和值频率', W['和值'], theory, window_30, window_5, P)
    details['和值'] = (sum_score, sum_desc)
    total += sum_score

    # ---- 2. 跨度评分 ----
    span_score, span_desc = _score_frequency(
        span_val, '跨度', '跨度频率', W['跨度'], theory, window_30, window_5, P)
    details['跨度'] = (span_score, span_desc)
    total += span_score

    # ---- 3. 形态评分（回归惩罚：偏离理论双向扣分） ----
    morph_ratio = {
        '组六': window_30.get('形态_组六_pct', 70),
        '组三': window_30.get('形态_组三_pct', 27),
        '豹子': window_30.get('形态_豹子_pct', 1),
    }
    if morph == '豹子':
        morph_score = 0
    else:
        theory_pct = 70 if morph == '组六' else 27
        actual_pct = morph_ratio['组六'] if morph == '组六' else morph_ratio['组三']
        # 回归惩罚: 实际偏离理论越大扣分越多，双向对称
        ratio = 1.0 + (theory_pct - actual_pct) / theory_pct
        ratio = max(0.2, min(1.8, ratio))
        morph_score = int(W['形态'] * ratio)
    # 允许过冷形态获得适度加分，最多 1.25 倍基准权重（避免形态维度单边惩罚）
    morph_cap = int(W['形态'] * 1.25)
    morph_score = max(1, min(morph_score, morph_cap))
    details['形态'] = (morph_score, f"形态={morph}")
    total += morph_score

    # ---- 4. 奇偶评分 ----
    odd = row['奇数']
    odd_score = W['奇偶'] if 1 <= odd <= 2 else max(1, W['奇偶'] // 4)
    details['奇偶'] = (odd_score, f"奇={odd}")
    total += odd_score

    # ---- 5. 大小评分 ----
    big = row['大号']
    big_score = W['大小'] if 1 <= big <= 2 else max(1, W['大小'] // 4)
    details['大小'] = (big_score, f"大={big}")
    total += big_score

    # ---- 6. 012路评分 ----
    r0, r1, r2 = row['0路数'], row['1路数'], row['2路数']
    n_unique = (r0 > 0) + (r1 > 0) + (r2 > 0)
    if n_unique == 3:
        route_score = W['012路']
    elif n_unique == 2:
        route_score = int(W['012路'] * 0.5)
    else:
        route_score = 1
    details['012路'] = (route_score, f"0路={r0},1路={r1},2路={r2}")
    total += route_score

    # ---- 7. 冷热评分（加强版） ----
    raw_missing = window_30.get('当前遗漏', {})
    latest_missing = {int(k): int(v) for k, v in raw_missing.items() if v is not None} if raw_missing else {}

    cold_count = 0
    hot_count = 0
    if latest_missing:
        for d in [row['红球1'], row['红球2'], row['红球3']]:
            m = latest_missing.get(d, 0)
            if m > cold_th:
                cold_count += 1
            elif m <= hot_th:
                hot_count += 1

        if cold_count == 0 and hot_count >= 1:
            hot_score = W['冷热']
        elif cold_count == 0:
            hot_score = int(W['冷热'] * 0.8)
        elif cold_count == 1:
            hot_score = int(W['冷热'] * 0.4)
        else:
            hot_score = 0  # 2-3个冷号直接0分
    else:
        hot_score = W['冷热'] // 2
    details['冷热'] = (hot_score, f"冷号={cold_count if latest_missing else '?'}")
    total += hot_score

    # ---- 8. 遗漏评分 ----
    avg_miss = window_30.get('平均遗漏', 5)
    if latest_missing:
        miss_scores = []
        for d in [row['红球1'], row['红球2'], row['红球3']]:
            m = latest_missing.get(d, 0)
            if m <= avg_miss * 0.5:
                miss_scores.append(2)
            elif m <= avg_miss * 1.5:
                miss_scores.append(1)
            else:
                miss_scores.append(0)
        miss_score = int(sum(miss_scores) / 6 * W['遗漏'])
        miss_score = max(0, min(miss_score, W['遗漏']))
    else:
        miss_score = W['遗漏'] // 2
    details['遗漏'] = (miss_score, f"均遗={avg_miss}")
    total += miss_score

    # ---- 总分限制 ----
    total = min(total, MAX_SCORE)

    return {'总分': total, '明细': details, '跨度值': span_val, '组选': row['group_number']}


# ==========================================
#  多样性惩罚
# ==========================================

def apply_diversity(scored, weights, params):
    """
    两轮多样性调整：
    1. 组选惩罚：同组选只保留最高分，其它降分
    2. 跨度促进：覆盖更多跨度值
    """
    W = weights
    P = params
    gp = P.get('group_penalty', 5)
    ss = P.get('span_spread', 8)

    # 组选惩罚：同组选只保留最高分，其它降分
    best_per_group = {}
    for c in scored:
        g = c['组选']
        if g not in best_per_group or c['总分'] > best_per_group[g]['总分']:
            best_per_group[g] = c

    for c in scored:
        detail = c['评分明细']
        is_best = (best_per_group.get(c['组选']) is c)
        if not is_best:
            c['总分'] -= gp
            if '多样性' not in detail:
                detail['多样性'] = (0, "")
            d = detail['多样性']
            detail['多样性'] = (d[0] - gp, f"组选重复-{gp}")
        else:
            if '多样性' not in detail:
                detail['多样性'] = (0, "")
            d = detail['多样性']
            detail['多样性'] = (d[0], "组选唯一")

    # 跨度促进：给Top-30中不常见的跨度加分
    top_30 = sorted(scored, key=lambda x: x['总分'], reverse=True)[:30]
    span_counts = {}
    for c in top_30:
        sv = c['跨度值']
        span_counts[sv] = span_counts.get(sv, 0) + 1

    for c in scored:
        sv = c['跨度值']
        count_in_top = span_counts.get(sv, 0)
        if 0 < count_in_top <= 2:
            bonus = int(ss * (1 - count_in_top / 3))
            c['总分'] = min(c['总分'] + bonus, MAX_SCORE)
            detail = c['评分明细']
            if '多样性' not in detail:
                detail['多样性'] = (0, "")
            d = detail['多样性']
            detail['多样性'] = (d[0] + bonus, f"跨度{sv}加{bonus}")

    return scored


# ==========================================
#  generate_predictions — 给 main() 和 backtest() 共用
# ==========================================

def generate_predictions(all_df, stats, theory, weights, params,
                         exclude_set=None, top_k=30,
                         exclude_mode='direct', include_baozi=False):
    """对1000注号码评分 → 多样性调整 → 排序取Top-K

    参数
    ----
    all_df : DataFrame   generate_all() 的输出
    stats : dict          stats_engine 的输出（含窗口统计、理论分布）
    theory : dict         stats['理论分布']
    weights, params :     load_weights() 的返回值
    exclude_set : set     要排除的 (红球1,红球2,红球3) 集合
    top_k : int           返回多少注
    exclude_mode : str    'direct' = 直选排除, 'group' = 组选去重排除
    include_baozi : bool  是否包含豹子

    返回
    ----
    scored : list         全部候选（已排序、含多样性调整）
                          包含 号码/group_number/和值/跨度/形态/总分/评分明细/跨度值/组选
    """
    if exclude_set is None:
        exclude_set = set()

    # 预计算组选排除集合（O(1) 查找）
    group_exclude = set()
    if exclude_mode == 'group':
        for e in exclude_set:
            group_exclude.add(''.join(str(d) for d in sorted(e)))

    scored = []
    for _, row in all_df.iterrows():
        nums = (int(row['红球1']), int(row['红球2']), int(row['红球3']))
        # 排除近N期
        if exclude_mode == 'direct':
            if nums in exclude_set:
                continue
        elif exclude_mode == 'group':
            # 组选排除：使用预计算的 group_number 做 O(1) 查找
            if row['group_number'] in group_exclude:
                continue

        if row['形态'] == '豹子' and not include_baozi:
            continue

        result = score_number(row, stats, theory, weights, params)
        scored.append({
            '号码': row['number'],
            'group_number': row['group_number'],
            '和值': int(row['和值']),
            '跨度': int(row['跨度']),
            '形态': row['形态'],
            '总分': result['总分'],
            '评分明细': result['明细'],
            '跨度值': result['跨度值'],
            '组选': result['组选'],
        })

    # 校验：group_number 必须是号码的数字排序结果
    for c in scored:
        expected_group = ''.join(sorted(c['号码']))
        if expected_group != c["group_number"]:
            raise ValueError(
                f"group_number 不一致: 号码={c['号码']}, "
                f"group_number={c['group_number']}, 期望={expected_group}"
            )

    # 多样性调整
    scored = apply_diversity(scored, weights, params)

    # 排序取Top
    scored.sort(key=lambda x: x['总分'], reverse=True)
    return scored[:top_k], scored


def _add_reason(rank, c):
    """为推荐号码生成机器理由 + 展示理由 + 一句话说明"""
    details = c['评分明细']
    top_reasons = []
    # 找得分最高的3个维度
    sorted_dims = sorted(details.items(), key=lambda x: x[1][0], reverse=True)
    for dim, (score, desc) in sorted_dims[:3]:
        if score > 0:
            top_reasons.append(f"{dim}={score}")

    # 展示理由（适合微信/Hermes推送，中文描述）
    total = c['总分']
    dim_text = ' '.join(top_reasons)
    display = f"第{rank}名 | 直选{c['号码']}｜组选{c['group_number']} | {c['形态']} | 总分{total} | {dim_text}"

    # 一句话说明（适合自然语言推送）
    one_line = (
        f"和值{c['和值']}、跨度{c['跨度']}，"
        f"形态为{c['形态']}，"
        f"{' '.join(d.split('=')[0] for d in top_reasons[:2])} 得分较高。"
    )

    return {
        '排名': rank,
        **{k: c[k] for k in ['号码', 'group_number', '和值', '跨度', '形态', '总分']},
        '推荐理由': ' '.join(top_reasons),
        '展示理由': display,
        '一句话说明': one_line,
        '评分明细': details,
    }


def to_rel(path_str, base_dir):
    """将绝对路径转为相对项目根的路径（JSON 更可移植）"""
    try:
        p = Path(path_str).resolve()
        if base_dir in p.parents or p == base_dir:
            return str(p.relative_to(base_dir))
        # 如果 path_str 本身已经是相对路径
        if not Path(path_str).is_absolute():
            return str(path_str)
        return str(p)
    except Exception:
        return str(path_str)


def get_git_commit(base_dir=None):
    """获取当前git commit hash（失败返回 None）"""
    try:
        cwd = str(base_dir.resolve()) if base_dir else None
        result = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5,
            cwd=cwd,
        )
        if result.returncode == 0:
            return result.stdout.decode().strip()
    except Exception:
        pass
    return None


# ==========================================
#  主流程
# ==========================================

def main():
    parser = argparse.ArgumentParser(description='动态评分引擎 v2')
    parser.add_argument('--lottery', required=True, choices=['pls', 'd3'],
                        help='彩种')
    parser.add_argument('--top-k', type=int, default=30,
                        help='推荐注数')
    parser.add_argument('--exclude-recent', type=int, default=5,
                        help='排除近N期已出号码')
    parser.add_argument('--weights',
                        help='评分权重YAML路径（相对项目根）')
    parser.add_argument('--detail', action='store_true',
                        help='打印每注评分明细')
    parser.add_argument('--exclude-mode', choices=['direct', 'group'], default='direct',
                        help='排除模式: direct=直选排除, group=组选去重排除')
    parser.add_argument('--include-baozi', action='store_true',
                        help='包含豹子（默认排除）')
    parser.add_argument('--target-issue', type=int,
                        help='手动指定预测期号（默认=数据截至期号+1）')
    parser.add_argument('--output-name', default='',
                        help='输出文件名前缀（用于多策略并行，如 conservative/diversity）')
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent.parent
    lottery_name = '排列三' if args.lottery == 'pls' else '福彩3D'

    # 加载权重
    weights, params = load_weights(args.weights)
    print(f"\n{'='*60}")
    print(f"  🎯 {lottery_name} 评分预测引擎 v2")
    print(f"{'='*60}")
    print(f"  Top-K: {args.top_k} | 排除近{args.exclude_recent}期")
    print(f"  排除模式: {args.exclude_mode} | 豹子: {'包含' if args.include_baozi else '排除'}")
    print(f"  权重: {json.dumps(weights, ensure_ascii=False)}")
    print(f"{'='*60}")

    # 加载统计
    stats_path = base_dir / 'data' / 'cache' / f'{args.lottery}_stats_latest.json'
    if not stats_path.exists():
        print(f"[错误] 统计数据不存在: {stats_path}")
        print(f"  请先运行: python scripts/stats_engine.py --lottery {args.lottery}")
        sys.exit(1)
    with open(stats_path, 'r', encoding='utf-8') as f:
        stats = json.load(f)
    theory = stats.get('理论分布', {})

    # 加载历史
    feat_path = base_dir / 'data' / 'processed' / f'{args.lottery}_feat.csv'
    recent_df = pd.read_csv(feat_path, encoding='utf-8-sig')

    # 数据截至期号（第一行是最新一期）
    latest_issue = int(recent_df.iloc[0]['期数'])
    target_issue = args.target_issue if args.target_issue else latest_issue + 1

    # 排除近N期
    exclude_set = set()
    if args.exclude_recent > 0:
        for i in range(min(args.exclude_recent, len(recent_df))):
            row = recent_df.iloc[i]
            exclude_set.add((int(row['红球1']), int(row['红球2']), int(row['红球3'])))

    # 评分预测
    all_df = generate_all()
    top_k, scored = generate_predictions(
        all_df, stats, theory, weights, params,
        exclude_set=exclude_set, top_k=args.top_k,
        exclude_mode=args.exclude_mode, include_baozi=args.include_baozi,
    )

    # 终端输出
    print(f"\n  {'排名':>4} {'号码':>6} {'组选':>6} {'和值':>4} {'跨度':>4} {'形态':>4} {'总分':>4}")
    print(f"  {'─'*60}")
    span_in_top = {}
    morph_in_top = {'组六': 0, '组三': 0, '豹子': 0}
    for i, c in enumerate(top_k):
        print(f"  {i+1:>4} {c['号码']:>6} {c['group_number']:>6} {c['和值']:>4} {c['跨度']:>4} {c['形态']:>4} {c['总分']:>4}")
        sv = c['跨度']
        span_in_top[sv] = span_in_top.get(sv, 0) + 1
        morph_in_top[c['形态']] = morph_in_top.get(c['形态'], 0) + 1

    # 统计
    summary = {}
    if top_k:
        scores = [c['总分'] for c in top_k]
        all_scores = [c['总分'] for c in scored]
        avg_score = sum(scores) / len(scores)
        group_count = len(set(c['group_number'] for c in top_k))
        high_group_count = sum(1 for c in scored if c['总分'] >= 60)
        candidates = len(scored)

        # 动态分位数（替代固定阈值）
        sorted_scores = sorted(all_scores, reverse=True)
        n95 = max(1, int(len(sorted_scores) * 0.05))
        n90 = max(1, int(len(sorted_scores) * 0.10))
        p95_score = sorted_scores[n95 - 1] if n95 <= len(sorted_scores) else sorted_scores[-1]
        p90_score = sorted_scores[n90 - 1] if n90 <= len(sorted_scores) else sorted_scores[-1]
        p95_count = sum(1 for s in all_scores if s >= p95_score)
        p90_count = sum(1 for s in all_scores if s >= p90_score)

        summary = {
            '总分最高': top_k[0]['总分'],
            '总分最低': top_k[-1]['总分'],
            '平均分': round(avg_score, 1),
            '跨度分布': {str(k): v for k, v in sorted(span_in_top.items())},
            '组选数量': group_count,
            '形态分布': morph_in_top,
            '高分阈值': 60,
            '高分候选数': high_group_count,
            '候选总数': candidates,
            'P90分数线': p90_score,
            'P90候选数': p90_count,
            'P95分数线': p95_score,
            'P95候选数': p95_count,
            'Top10号码': [c['号码'] for c in scored[:10]],
            'Top30号码': [c['号码'] for c in scored[:30]],
        }

        print(f"\n  📊 摘要:")
        print(f"    总分最高: {summary['总分最高']} | 最低: {summary['总分最低']} | 平均: {summary['平均分']}")
        print(f"    跨度分布: {summary['跨度分布']}")
        print(f"    组选数: {summary['组选数量']} | P95(最高5%): ≥{p95_score}({p95_count}注) | P90(最高10%): ≥{p90_score}({p90_count}注)")
        print(f"    Top10: {' '.join(summary['Top10号码'][:5])}...")

    # 风险提示
    risk_note = ("⚠️ 彩票开奖具有高度随机性，本评分仅基于历史统计和理论分布，"
                 "不代表未来开奖结果。请理性看待，量力而行。")
    print(f"\n  ⚠️  {risk_note}")

    # 生成信息（相对路径）
    git_commit = get_git_commit(base_dir)
    gen_info = {
        '命令': 'python scripts/scoring_engine.py --lottery {} --top-k {} --exclude-recent {} --exclude-mode {}{}'.format(
            args.lottery, args.top_k, args.exclude_recent, args.exclude_mode,
            ' --include-baozi' if args.include_baozi else ''),
        '权重文件': to_rel(Path(args.weights).resolve() if args.weights else base_dir / 'rules' / 'scoring_weights.yaml', base_dir),
        '统计缓存': to_rel(stats_path, base_dir),
        '数据文件': to_rel(feat_path, base_dir),
    }
    if git_commit:
        gen_info['代码版本'] = git_commit
    else:
        gen_info['代码版本'] = None

    # 保存 JSON（按期号）
    output_dir = base_dir / 'output' / 'predictions'
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = '{}_{}'.format(args.lottery, args.output_name) if args.output_name else args.lottery
    output_path = output_dir / '{}_predict_{}.json'.format(prefix, target_issue)
    # 同时保存 latest 固定入口
    latest_path = output_dir / 'latest_{}.json'.format(prefix)

    # 过滤说明
    filter_desc = {
        '排除近N期': args.exclude_recent,
        '是否排除豹子': not args.include_baozi,
        '排除模式': args.exclude_mode,
    }

    output_json = {
        '彩种': lottery_name,
        '数据截至期号': latest_issue,
        '预测期号': target_issue,
        '评分时间': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'top_k': args.top_k,
        '风险提示': risk_note,
        '摘要': summary,
        '过滤说明': filter_desc,
        '生成信息': gen_info,
        '权重': weights,
        '参数': params,
        '推荐': [_add_reason(i+1, c) for i, c in enumerate(top_k)],
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_json, f, ensure_ascii=False, indent=2)
    with open(latest_path, 'w', encoding='utf-8') as f:
        json.dump(output_json, f, ensure_ascii=False, indent=2)
    print(f"  💾 保存: {output_path}")
    print(f"  💾 同步: {latest_path}")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    main()
