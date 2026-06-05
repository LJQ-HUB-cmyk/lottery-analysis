#!/usr/bin/env python3
"""
多窗口统计分析 + 理论分布对比
==============================
对特征数据做多窗口统计分析，并与理论分布做对比。
输出统计结果 JSON 供 scoring_engine 使用。

用法：
    python stats_engine.py --lottery pls
    python stats_engine.py --lottery d3
"""

import argparse
import json
from pathlib import Path

import pandas as pd
import numpy as np


# ==========================================
#  理论分布
# ==========================================

_cached_theory = None


def generate_theoretical_distribution() -> dict:
    """
    计算000-999全部1000个号码的理论分布。
    返回每个特征的理论频率字典。结果缓存到模块级变量。
    """
    global _cached_theory
    if _cached_theory is not None:
        return _cached_theory

    all_nums = np.array([(a, b, c) for a in range(10) for b in range(10) for c in range(10)])
    r1, r2, r3 = all_nums[:, 0], all_nums[:, 1], all_nums[:, 2]
    
    theory = {}
    
    # 和值分布（0-27）
    sums = r1 + r2 + r3
    sum_counts = np.bincount(sums, minlength=28)
    theory['和值'] = {int(k): int(v) for k, v in enumerate(sum_counts)}
    theory['和值_pct'] = {int(k): round(v/1000*100, 2) for k, v in enumerate(sum_counts)}
    
    # 跨度分布（0-9）
    spans = np.max(all_nums, axis=1) - np.min(all_nums, axis=1)
    span_counts = np.bincount(spans, minlength=10)
    theory['跨度'] = {int(k): int(v) for k, v in enumerate(span_counts)}
    theory['跨度_pct'] = {int(k): round(v/1000*100, 2) for k, v in enumerate(span_counts)}
    
    # 形态分布
    same_ab = (r1 == r2).astype(int)
    same_bc = (r2 == r3).astype(int)
    same_ac = (r1 == r3).astype(int)
    total_same = same_ab + same_bc + same_ac
    
    baozi = np.sum(total_same == 3)  # 10种
    zusan = np.sum(total_same == 1)  # 270种
    zuliu = 1000 - baozi - zusan     # 720种
    
    theory['形态'] = {'豹子': int(baozi), '组三': int(zusan), '组六': int(zuliu)}
    theory['形态_pct'] = {
        '豹子': round(baozi/1000*100, 2),
        '组三': round(zusan/1000*100, 2),
        '组六': round(zuliu/1000*100, 2),
    }
    
    # 奇偶分布
    odd_cnt = (r1 % 2) + (r2 % 2) + (r3 % 2)
    odd_counts = np.bincount(odd_cnt, minlength=4)
    theory['奇数'] = {int(k): int(v) for k, v in enumerate(odd_counts)}
    
    # 大小分布
    big_cnt = (r1 >= 5).astype(int) + (r2 >= 5).astype(int) + (r3 >= 5).astype(int)
    big_counts = np.bincount(big_cnt, minlength=4)
    theory['大号'] = {int(k): int(v) for k, v in enumerate(big_counts)}
    
    # 012路个数分布
    r0_cnt = (r1 % 3 == 0).astype(int) + (r2 % 3 == 0).astype(int) + (r3 % 3 == 0).astype(int)
    r1_cnt = (r1 % 3 == 1).astype(int) + (r2 % 3 == 1).astype(int) + (r3 % 3 == 1).astype(int)
    r2_cnt = (r1 % 3 == 2).astype(int) + (r2 % 3 == 2).astype(int) + (r3 % 3 == 2).astype(int)
    
    for label, cnt in [('0路数', r0_cnt), ('1路数', r1_cnt), ('2路数', r2_cnt)]:
        cnts = np.bincount(cnt, minlength=4)
        theory[label] = {int(k): int(v) for k, v in enumerate(cnts)}
    
    # 分位数字分布（每位0-9理论上各100次）
    for pos, col in [('百位', r1), ('十位', r2), ('个位', r3)]:
        digit_counts = np.bincount(col, minlength=10)
        theory[f'{pos}数字'] = {int(k): int(v) for k, v in enumerate(digit_counts)}
    
    # 和值分区
    theory['sum_zone'] = {
        '低区(0-9)': int(np.sum((sums >= 0) & (sums <= 9))),
        '中区(10-17)': int(np.sum((sums >= 10) & (sums <= 17))),
        '高区(18-27)': int(np.sum((sums >= 18) & (sums <= 27))),
    }
    
    # 跨度分区
    theory['span_zone'] = {
        '小跨(0-3)': int(np.sum((spans >= 0) & (spans <= 3))),
        '中跨(4-6)': int(np.sum((spans >= 4) & (spans <= 6))),
        '大跨(7-9)': int(np.sum((spans >= 7) & (spans <= 9))),
    }

    _cached_theory = theory
    return theory


# ==========================================
#  多窗口统计
# ==========================================

WINDOWS = {
    '近5期': 5,
    '近10期': 10,
    '近30期': 30,
    '近50期': 50,
    '近100期': 100,
}


def compute_window_stats(df_window: pd.DataFrame) -> dict:
    """计算一个窗口内的统计数据"""
    stats = {}
    
    # 数字频率（全位）
    all_digits = pd.concat([df_window['红球1'], df_window['红球2'], df_window['红球3']])
    digit_freq = all_digits.value_counts().reindex(range(10), fill_value=0)
    stats['全位数字频率'] = {int(k): int(v) for k, v in digit_freq.items()}
    
    # 分位频率
    for pos, col in [('百位', '红球1'), ('十位', '红球2'), ('个位', '红球3')]:
        freq = df_window[col].value_counts().reindex(range(10), fill_value=0)
        stats[f'{pos}数字频率'] = {int(k): int(v) for k, v in freq.items()}
    
    # 和值分布
    sum_freq = df_window['和值'].value_counts().reindex(range(28), fill_value=0)
    stats['和值频率'] = {int(k): int(v) for k, v in sum_freq.items()}
    stats['和值均值'] = round(float(df_window['和值'].mean()), 1)
    stats['和值中位数'] = int(df_window['和值'].median())
    stats['和值标准差'] = round(float(df_window['和值'].std()), 1)
    
    # 高频和值区间（覆盖80%）
    sums_sorted = sum_freq.sort_values(ascending=False)
    cumulative = 0
    high_freq_sums = []
    for s, cnt in sums_sorted.items():
        cumulative += cnt
        high_freq_sums.append(int(s))
        if cumulative >= len(df_window) * 0.8:
            break
    stats['高频和值'] = sorted(high_freq_sums)
    stats['高频和值区间'] = f"{min(high_freq_sums)}-{max(high_freq_sums)}"
    
    # 跨度分布
    span_freq = df_window['跨度'].value_counts().reindex(range(10), fill_value=0)
    stats['跨度频率'] = {int(k): int(v) for k, v in span_freq.items()}
    stats['跨度均值'] = round(float(df_window['跨度'].mean()), 1)
    
    spans_sorted = span_freq.sort_values(ascending=False)
    cumulative = 0
    high_freq_spans = []
    for s, cnt in spans_sorted.items():
        cumulative += cnt
        high_freq_spans.append(int(s))
        if cumulative >= len(df_window) * 0.8:
            break
    stats['高频跨度'] = sorted(high_freq_spans)
    
    # 奇偶比例
    odd_freq = df_window['奇数'].value_counts().reindex(range(4), fill_value=0)
    stats['奇数频率'] = {int(k): int(v) for k, v in odd_freq.items()}
    
    # 大小比例
    big_freq = df_window['大号'].value_counts().reindex(range(4), fill_value=0)
    stats['大号频率'] = {int(k): int(v) for k, v in big_freq.items()}
    
    # 012路比例
    for r in ['0路数', '1路数', '2路数']:
        freq = df_window[r].value_counts().reindex(range(4), fill_value=0)
        stats[f'{r}频率'] = {int(k): int(v) for k, v in freq.items()}
    
    # 形态比例
    morph_freq = df_window['形态'].value_counts()
    for m in ['豹子', '组三', '组六']:
        stats[f'形态_{m}'] = int(morph_freq.get(m, 0))
        stats[f'形态_{m}_pct'] = round(morph_freq.get(m, 0) / len(df_window) * 100, 1)
    
    # 和值分区
    zone_freq = df_window['sum_zone'].value_counts()
    stats['sum_zone'] = {k: int(v) for k, v in zone_freq.items()}
    
    # 跨度分区
    span_zone_freq = df_window['span_zone'].value_counts()
    stats['span_zone'] = {k: int(v) for k, v in span_zone_freq.items()}
    
    # 遗漏概况
    miss_cols = [f'遗漏_{d}' for d in range(10)]
    latest = df_window.iloc[0]
    stats['当前遗漏'] = {int(d): int(latest[f'遗漏_{d}']) for d in range(10)}
    stats['平均遗漏'] = round(float(latest[miss_cols].mean()), 1)
    stats['最大遗漏'] = int(latest[miss_cols].max())
    stats['遗漏Top3'] = sorted(range(10), key=lambda d: latest[f'遗漏_{d}'], reverse=True)[:3]
    stats['超过平均遗漏'] = [int(d) for d in range(10) if latest[f'遗漏_{d}'] > stats['平均遗漏']]
    
    return stats


def compute_stats(df: pd.DataFrame, theory: dict) -> dict:
    """对所有窗口计算统计"""
    total = len(df)
    result = {
        '彩种': '',
        '总期数': total,
        '最新期号': int(df.iloc[0]['期数']),
        '统计时间': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S'),
        '理论分布': theory,
        '窗口': {},
    }
    
    for window_name, window_size in WINDOWS.items():
        df_window = df.head(min(window_size, total))
        window_stats = compute_window_stats(df_window)
        
        # 加入偏差计算（实际频率 - 理论频率百分比）
        window_pct = len(df_window)
        for feature in ['和值', '跨度']:
            if feature in theory:
                actual = window_stats.get(f'{feature}频率', {})
                expected_pct = theory.get(f'{feature}_pct', {})
                deviation = {}
                for k in range(28 if feature == '和值' else 10):
                    a = actual.get(k, 0) / window_pct * 100 if window_pct > 0 else 0
                    e = expected_pct.get(k, 0)
                    deviation[int(k)] = round(a - e, 2)
                window_stats[f'{feature}_deviation'] = deviation
        
        result['窗口'][window_name] = window_stats
    
    return result


# ==========================================
#  主流程
# ==========================================

def main():
    parser = argparse.ArgumentParser(description='多窗口统计分析')
    parser.add_argument('--lottery', required=True, choices=['pls', 'd3'],
                        help='彩种')
    parser.add_argument('--data', default='',
                        help='特征CSV路径（默认 data/processed/）')
    args = parser.parse_args()
    
    base_dir = Path(__file__).resolve().parent.parent
    lottery_name = '排列三' if args.lottery == 'pls' else '福彩3D'
    
    data_path = args.data or str(base_dir / 'data' / 'processed' / f'{args.lottery}_feat.csv')
    
    print(f"\n{'='*50}")
    print(f"  统计引擎 - {lottery_name}")
    print(f"{'='*50}")
    
    # 1. 加载数据（强制按期号降序，新→旧）
    df = pd.read_csv(data_path, encoding='utf-8-sig')
    df = df.sort_values('期数', ascending=False).reset_index(drop=True)
    print(f"  📊 数据: {data_path}")
    print(f"  总期数: {len(df)}")
    
    # 2. 计算理论分布
    print(f"  📐 计算理论分布...")
    theory = generate_theoretical_distribution()
    print(f"    和值: 0({theory['和值'][0]})~27({theory['和值'][27]})")
    print(f"    形态: 豹子{theory['形态']['豹子']} 组三{theory['形态']['组三']} 组六{theory['形态']['组六']}")
    
    # 3. 窗口统计
    result = compute_stats(df, theory)
    result['彩种'] = lottery_name
    
    for wname, wdata in result['窗口'].items():
        print(f"\n  📈 {wname} ({len(df.head(WINDOWS[wname]))}期):")
        print(f"    和值: 均值={wdata['和值均值']}, 高频区间={wdata['高频和值区间']}")
        if '形态_组六_pct' in wdata:
            print(f"    形态: 组六{wdata['形态_组六_pct']}% 组三{wdata['形态_组三_pct']}%")
        if '遗漏Top3' in wdata:
            print(f"    遗漏Top3: {wdata['遗漏Top3']}")
    
    # 4. 输出
    cache_dir = base_dir / 'data' / 'cache'
    cache_dir.mkdir(parents=True, exist_ok=True)
    output_path = cache_dir / f'{args.lottery}_stats_latest.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 统计完成！输出: {output_path}")
    
    # 也保存可读版报告
    report_dir = base_dir / 'output' / 'reports'
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f'{args.lottery}_stats_report.json'
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
