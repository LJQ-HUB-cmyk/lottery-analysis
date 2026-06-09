#!/usr/bin/env python3
"""
复盘表现摘要（按策略拆分）
==========================
读取 review_history.csv，按彩种+策略输出最近N期表现统计。

用法：
    python scripts/review_summary.py
    python scripts/review_summary.py --window 30
    python scripts/review_summary.py --lottery pls
    python scripts/review_summary.py --strategy conservative
"""

import argparse
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent.parent
HISTORY_PATH = BASE_DIR / 'output' / 'reviews' / 'review_history.csv'

NAME_MAP = {'pls': '排列三', 'd3': '福彩3D'}
TRUE_VALUES = {'true', '1', 'yes', 'y', '是', '✅'}


def _is_true(series):
    return series.astype(str).str.strip().str.lower().isin(TRUE_VALUES)


def pct(series):
    if series is None or len(series) == 0:
        return 0.0
    return _is_true(series).mean()


def hit_count(series):
    if series is None or len(series) == 0:
        return 0
    return int(_is_true(series).sum())


def sort_by_issue(sub):
    """按期号排序，取最近 window 期"""
    sub = sub.copy()
    if '期号' in sub.columns:
        sub['_issue_num'] = pd.to_numeric(sub['期号'], errors='coerce')
        sort_cols = ['_issue_num']
        if '复盘时间' in sub.columns:
            sort_cols.append('复盘时间')
        sub = sub.sort_values(sort_cols)
        sub = sub.drop(columns=['_issue_num'])
    return sub


def summarize_strategy(sub, strategy_name, window):
    """单个策略的最近 N 期统计"""
    if sub.empty:
        return [f"  {strategy_name}: 暂无数据"]

    sub = sort_by_issue(sub)

    # 同策略下同期的多条记录只保留最后一次（防止手动补跑污染）
    if '期号' in sub.columns:
        sub = sub.drop_duplicates(subset=['期号'], keep='last')

    sub = sub.tail(window)
    n = len(sub)

    direct_hits = hit_count(sub.get('直选命中Top10', sub.get('直选命中Top30', pd.Series())))
    group_hits = hit_count(sub.get('组选命中Top10', sub.get('组选命中Top30', pd.Series())))
    shape_hits = hit_count(sub['Top1形态一致'])

    direct_rate = pct(sub.get('直选命中Top10', sub.get('直选命中Top30', pd.Series())))
    group_rate = pct(sub.get('组选命中Top10', sub.get('组选命中Top30', pd.Series())))
    shape_rate = pct(sub['Top1形态一致'])

    sum_err = pd.to_numeric(sub['Top1和值误差'], errors='coerce').mean()
    span_err = pd.to_numeric(sub['Top1跨度误差'], errors='coerce').mean()

    lines = [
        f"",
        f"  【{strategy_name}】最近 {n} 期",
        f"  Top10 直选命中 : {direct_hits:>3} 次 / {n} 期 = {direct_rate:.1%}",
        f"  Top10 组选命中 : {group_hits:>3} 次 / {n} 期 = {group_rate:.1%}",
        f"  Top1 形态一致  : {shape_hits:>3} 次 / {n} 期 = {shape_rate:.1%}",
        f"  Top1 平均和值差: {sum_err:.1f}",
        f"  Top1 平均跨度差: {span_err:.1f}",
    ]

    if n >= 5:
        recent_5 = sub.tail(5)
        lines.append(
            f"  最近5期趋势: 直选{pct(recent_5['直选命中Top10']):.1%} | "
            f"组选{pct(recent_5['组选命中Top10']):.1%}"
        )

    return lines


def summarize(df, lottery, window, strategy='all'):
    lottery_name = NAME_MAP.get(lottery, lottery)

    sub = df[df['彩种'].apply(lambda x: lottery_name in str(x))].copy()
    if sub.empty:
        return f"\n〖{lottery_name}〗暂无复盘数据\n"

    # 确保有策略列
    if '策略' not in sub.columns:
        sub['策略'] = 'default'
    sub['策略'] = sub['策略'].fillna('default').astype(str)

    # 确定要展示的策略列表
    if strategy != 'all':
        strategies = [strategy]
    else:
        preferred = ['default', 'conservative', 'diversity']
        existing = [s for s in preferred if s in sub['策略'].unique()]
        rest = sorted(s for s in sub['策略'].unique() if s not in preferred)
        strategies = existing + rest

    lines = [
        f"",
        f" {'─'*50}",
        f" 〖{lottery_name} 最近 {window} 期表现｜按策略拆分〗",
        f" {'─'*50}",
    ]

    for st in strategies:
        st_sub = sub[sub['策略'] == st].copy()
        lines.extend(summarize_strategy(st_sub, st, window))

    lines.append(f" {'─'*50}")
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='复盘表现摘要（按策略拆分）')
    parser.add_argument('--window', type=int, default=30,
                        help='统计窗口（默认30期）')
    parser.add_argument('--lottery', choices=['pls', 'd3'],
                        help='仅统计指定彩种')
    parser.add_argument('--strategy', choices=['default', 'conservative', 'diversity', 'all'],
                        default='all',
                        help='统计指定策略，默认 all')
    args = parser.parse_args()

    if not HISTORY_PATH.exists():
        print(f"\n  暂无复盘数据: {HISTORY_PATH}")
        print(f"  开奖后运行: python scripts/compare_result.py --lottery pls")
        return

    df = pd.read_csv(HISTORY_PATH, dtype=str, encoding='utf-8-sig')
    total_rows = len(df)

    # 计算唯一彩种+期号数（不是按策略膨胀后的行数）
    if {'彩种', '期号'}.issubset(df.columns):
        total_issues = len(df.drop_duplicates(subset=['彩种', '期号']))
    else:
        total_issues = total_rows

    print(f"\n{'='*55}")
    print(f"  📊 复盘表现摘要（按策略拆分）")
    print(f"{'='*55}")
    print(f"  数据来源: {HISTORY_PATH}")
    print(f"  总复盘记录数: {total_rows}（{total_issues} 个彩种期号）")
    print(f"  统计窗口: 最近 {args.window} 期")

    lotteries = [args.lottery] if args.lottery else ['pls', 'd3']
    for lt in lotteries:
        print(summarize(df, lt, args.window, args.strategy))

    print(f"\n{'='*55}\n")


if __name__ == '__main__':
    main()
