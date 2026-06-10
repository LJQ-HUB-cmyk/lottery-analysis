#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
命中率统计模块
==============
读取 review_history.csv，计算多维度、多窗口命中率。
输出 metrics JSON 供 Web 仪表板使用。

用法：
    python scripts/metrics.py
    python scripts/metrics.py --lottery pls
    python scripts/metrics.py --windows 7,30,90,180
"""

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
HISTORY_PATH = BASE / 'output' / 'reviews' / 'review_history.csv'
METRICS_DIR = BASE / 'output' / 'metrics'


def read_history():
    if not HISTORY_PATH.exists():
        return []
    with HISTORY_PATH.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def safe_int(val, default=0):
    try:
        return int(str(val).strip() or default)
    except (ValueError, TypeError):
        return default


def safe_bool(val):
    if val is None:
        return False
    s = str(val).strip().lower()
    return s in ('true', '1', 'yes')


def get_hit(row, field):
    """读取命中字段，兼容新旧数据格式。

    新数据：直选命中Top10 = True/False
    旧数据：命中范围 = Top5/Top10/Top30（布尔字段为空）
    """
    # 优先读新格式布尔字段
    for f in [f'{field}Top10', f'{field}Top30']:
        val = row.get(f)
        if val is not None and str(val).strip().lower() not in ('nan', 'none', '', '-'):
            return safe_bool(val)

    # 回退：从 命中范围 推断
    hit_range = str(row.get('命中范围', '')).strip()
    if hit_range in ('Top5', 'Top10', 'Top30'):
        return True
    return False


def compute_metrics(rows, windows=None):
    """计算多窗口命中率统计。

    rows: list of dict (from CSV)
    windows: list of int (e.g., [7, 30, 90])
    """
    if windows is None:
        windows = [7, 30, 90]

    results = {}
    for w in windows:
        recent = rows[-w:]
        n = len(recent)
        if n == 0:
            continue

        direct = sum(1 for r in recent if get_hit(r, '直选命中'))
        group = sum(1 for r in recent if get_hit(r, '组选命中'))

        # 形态命中：优先读字段，回退到 Top1形态一致
        morph = sum(1 for r in recent if (
            safe_bool(r.get('形态命中', '')) or
            safe_bool(r.get('Top1形态一致', ''))
        ))

        # 和值命中：优先读字段，回退到 Top1和值误差 ≤ 2
        sum_hit = sum(1 for r in recent if (
            safe_bool(r.get('和值命中', '')) or
            safe_int(r.get('Top1和值误差'), 99) <= 2
        ))

        # 跨度命中：优先读字段，回退到 Top1跨度误差 ≤ 1
        span_hit = sum(1 for r in recent if (
            safe_bool(r.get('跨度命中', '')) or
            safe_int(r.get('Top1跨度误差'), 99) <= 1
        ))

        # 胆码命中
        danma_single = sum(1 for r in recent if safe_int(r.get('胆码命中', 0)) == 1)
        danma_double = sum(1 for r in recent if safe_int(r.get('胆码命中', 0)) >= 2)
        danma_triple = sum(1 for r in recent if safe_int(r.get('胆码命中', 0)) >= 3)

        # 和值误差
        sum_errors = [safe_int(r.get('Top1和值误差'), 0) for r in recent]
        span_errors = [safe_int(r.get('Top1跨度误差'), 0) for r in recent]

        # 和值差≤2 / 跨度差≤1 的比例（比"命中率"更有参考价值）
        sum_close = sum(1 for e in sum_errors if e <= 2)
        span_close = sum(1 for e in span_errors if e <= 1)

        results[str(w)] = {
            '期数': n,
            '直选命中': direct,
            '直选命中率': round(direct / n * 100, 1),
            '组选命中': group,
            '组选命中率': round(group / n * 100, 1),
            '形态命中': morph,
            '形态命中率': round(morph / n * 100, 1),
            '和值命中': sum_hit,
            '和值命中率': round(sum_hit / n * 100, 1),
            '跨度命中': span_hit,
            '跨度命中率': round(span_hit / n * 100, 1),
            '和值差近': sum_close,
            '和值差近率': round(sum_close / n * 100, 1),
            '跨度差近': span_close,
            '跨度差近率': round(span_close / n * 100, 1),
            '胆码单中': danma_single,
            '胆码单中率': round(danma_single / n * 100, 1),
            '胆码双中': danma_double,
            '胆码双中率': round(danma_double / n * 100, 1),
            '胆码三中': danma_triple,
            '平均和值差': round(sum(sum_errors) / n, 1) if n else 0,
            '平均跨度差': round(sum(span_errors) / n, 1) if n else 0,
        }

    return results


def compute_trend(rows, window=30):
    """计算每期滚动命中率趋势。

    返回 list of dict，每期一个数据点。
    """
    trend = []
    n = len(rows)

    for i in range(window, n):
        recent = rows[i - window:i]
        period = rows[i]

        direct = sum(1 for r in recent if get_hit(r, '直选命中'))
        group = sum(1 for r in recent if get_hit(r, '组选命中'))
        morph = sum(1 for r in recent if safe_bool(r.get('Top1形态一致', '')))
        sum_hit = sum(1 for r in recent if safe_bool(r.get('和值命中', '')))
        span_hit = sum(1 for r in recent if safe_bool(r.get('跨度命中', '')))
        danma_double = sum(1 for r in recent if safe_int(r.get('胆码命中', 0)) >= 2)

        trend.append({
            '期号': period.get('期号', ''),
            '彩种': period.get('彩种', ''),
            '策略': period.get('策略', 'default'),
            '直选命中率': round(direct / window * 100, 1),
            '组选命中率': round(group / window * 100, 1),
            '形态命中率': round(morph / window * 100, 1),
            '和值命中率': round(sum_hit / window * 100, 1),
            '跨度命中率': round(span_hit / window * 100, 1),
            '胆码双中率': round(danma_double / window * 100, 1),
        })

    return trend


def main():
    parser = argparse.ArgumentParser(description='命中率统计')
    parser.add_argument('--lottery', choices=['pls', 'd3', 'all'], default='all')
    parser.add_argument('--strategy', default='default')
    parser.add_argument('--windows', default='7,30,90,180',
                        help='时间窗口，逗号分隔（默认 7,30,90,180）')
    parser.add_argument('--trend-window', type=int, default=10,
                        help='趋势图滚动窗口（默认 10）')
    args = parser.parse_args()

    windows = [int(w.strip()) for w in args.windows.split(',') if w.strip()]
    lt_map = {'pls': '排列三', 'd3': '福彩3D'}

    rows = read_history()
    if not rows:
        print('暂无复盘数据')
        return

    METRICS_DIR.mkdir(parents=True, exist_ok=True)

    lotteries = [lt_map[args.lottery]] if args.lottery != 'all' else ['排列三', '福彩3D']

    for lt_name in lotteries:
        lt_rows = [r for r in rows if r.get('彩种') == lt_name and r.get('策略') == args.strategy]
        if not lt_rows:
            # 尝试所有策略
            lt_rows = [r for r in rows if r.get('彩种') == lt_name]

        if not lt_rows:
            print(f'{lt_name}: 暂无数据')
            continue

        lt_key = 'pls' if lt_name == '排列三' else 'd3'

        # 计算多窗口指标
        metrics = compute_metrics(lt_rows, windows)
        metrics['彩种'] = lt_name
        metrics['策略'] = args.strategy
        metrics['更新时间'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 计算趋势
        trend = compute_trend(lt_rows, args.trend_window)

        # 保存
        metrics_path = METRICS_DIR / f'{lt_key}_metrics.json'
        trend_path = METRICS_DIR / f'{lt_key}_trend.json'

        with open(metrics_path, 'w', encoding='utf-8') as f:
            json.dump(metrics, f, ensure_ascii=False, indent=2)
        with open(trend_path, 'w', encoding='utf-8') as f:
            json.dump(trend, f, ensure_ascii=False, indent=2)

        print(f'\n=== {lt_name} ({args.strategy}) ===')
        for w, m in metrics.items():
            if isinstance(m, dict):
                print(f'  近{w}期: 直选{m["直选命中率"]}% 组选{m["组选命中率"]}% '
                      f'形态{m["形态命中率"]}% 和值{m["和值命中率"]}% '
                      f'胆码双中{m["胆码双中率"]}%')

        print(f'  趋势数据: {len(trend)} 点 → {trend_path}')
        print(f'  指标数据: → {metrics_path}')


if __name__ == '__main__':
    main()
