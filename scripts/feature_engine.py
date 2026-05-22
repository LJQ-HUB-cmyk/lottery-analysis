#!/usr/bin/env python3
"""
特征工程 v3 —— 含数据检查 + 分位遗漏 + group_number + 冷热
===========================================================

用法：
    # 排列三（data_fetcher标准CSV）
    python feature_engine.py --input data/raw/pls_raw.csv --output data/processed/pls_feat.csv --lottery pls
    # 排列三（KittenCN/500.com双表头CSV：skiprows=2）
    python feature_engine.py --input data/raw/pls_raw.csv --output data/processed/pls_feat.csv --lottery pls --skiprows 2
    
    # 福彩3D（konglr格式）
    python feature_engine.py --input data/raw/d3_raw.csv --output data/processed/d3_feat.csv --lottery d3
"""

import argparse
import sys
import json
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np


# ==========================================
#  0. 号码清洗工具
# ==========================================

def normalize_number(value) -> str:
    """清洗号码为3位数字字符串：去空格/去非数字/补零/截断

    "4 8 2" → "482"
    "40"    → "040"
    "020"   → "020"
    "7,8,5" → "785"
    """
    s = str(value).strip()
    digits = ''.join(ch for ch in s if ch.isdigit())
    if len(digits) < 3:
        digits = digits.zfill(3)
    return digits[:3]


# ==========================================
#  1. 数据检查
# ==========================================

def check_data(df: pd.DataFrame, lottery_name: str) -> dict:
    """数据质量检查，返回检查报告"""
    report = {
        '彩种': lottery_name,
        '检查时间': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        '总行数': len(df),
        '异常': [],
        '警告': [],
        '通过': True,
    }
    
    # 1.1 空值检查
    null_counts = df.isnull().sum()
    null_cols = null_counts[null_counts > 0]
    if len(null_cols) > 0:
        for col, cnt in null_cols.items():
            if col == '日期':
                report['警告'].append(
                    f"日期 有 {cnt} 个空值"
                    f"（历史种子数据格式问题，已按期号排序继续处理，不影响评分）"
                )
            else:
                report['异常'].append(f"{col} 有 {cnt} 个空值")
    
    # 1.2 期号检查
    if '期数' in df.columns:
        # 重复期号
        dup = df['期数'].duplicated()
        if dup.any():
            dup_issues = df[dup]['期数'].tolist()[:5]
            report['异常'].append(f"重复期号: {dup_issues}{'...' if len(dup_issues)==5 else ''}")
        
        # 缺失期号（检查连续性）
        issues = df['期数'].values
        if len(issues) > 1:
            gaps = []
            for i in range(1, len(issues)):
                expected = issues[i-1] + 1
                # 处理跨年（期号格式 YYDDD：如 25358→26001，差≫1）
                if issues[i] - issues[i-1] > 100:
                    continue
                if issues[i] != expected:
                    gaps.append((issues[i-1], issues[i]))
            if len(gaps) > 5:
                report['异常'].append(f"存在 {len(gaps)} 处断期（前5: {gaps[:5]}）")
        
        report['期号范围'] = f"{int(df['期数'].min())} ~ {int(df['期数'].max())}"
    
    # 1.3 位数范围检查（0-9）
    for col in ['红球1', '红球2', '红球3']:
        if col in df.columns:
            out_of_range = df[(df[col] < 0) | (df[col] > 9)]
            if len(out_of_range) > 0:
                report['异常'].append(f"{col} 有 {len(out_of_range)} 个不在 0-9 范围内")
    
    # 1.4 排序检查（应按时序排序）
    if '期数' in df.columns:
        if not df['期数'].is_monotonic_increasing:
            report['异常'].append("期号未按升序排列")
    
    # 汇总
    report['异常数'] = len(report['异常'])
    report['警告数'] = len(report['警告'])
    report['通过'] = len(report['异常']) == 0
    
    return report


def print_check_report(report: dict):
    """打印数据检查报告"""
    print(f"\n{'='*50}")
    print(f"  📋 数据检查报告 - {report['彩种']}")
    print(f"{'='*50}")
    print(f"  检查时间: {report['检查时间']}")
    print(f"  总行数:   {report['总行数']}")
    if '期号范围' in report:
        print(f"  期号:     {report['期号范围']}")
    
    if report['异常数'] > 0:
        print(f"\n  ❌ 发现 {report['异常数']} 个异常:")
        for e in report['异常']:
            print(f"     - {e}")
        print(f"\n  ⚠️  建议检查数据源后重试")
    else:
        print(f"\n  ✅ 数据检查通过，无异常")

    if report['警告数'] > 0:
        print(f"\n  ⚠️  {report['警告数']} 个警告（不影响评分）:")
        for w in report['警告']:
            print(f"     - {w}")
    print(f"{'='*50}\n")


# ==========================================
#  2. 特征计算
# ==========================================

def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """计算所有特征"""
    r1, r2, r3 = df['红球1'], df['红球2'], df['红球3']
    nums = pd.concat([r1, r2, r3], axis=1)
    
    # ---- 基础特征 ----
    df['number'] = r1.astype(str) + r2.astype(str) + r3.astype(str)
    df['和值'] = r1 + r2 + r3
    df['跨度'] = nums.max(axis=1) - nums.min(axis=1)
    df['奇数'] = ((r1 % 2 == 1).astype(int) + (r2 % 2 == 1).astype(int) + (r3 % 2 == 1).astype(int))
    df['偶数'] = 3 - df['奇数']
    df['大号'] = ((r1 >= 5).astype(int) + (r2 >= 5).astype(int) + (r3 >= 5).astype(int))
    df['小号'] = 3 - df['大号']
    df['最大'] = nums.max(axis=1)
    df['最小'] = nums.min(axis=1)
    
    # ---- 012路 ----
    df['路_百'] = r1 % 3
    df['路_十'] = r2 % 3
    df['路_个'] = r3 % 3
    df['0路数'] = ((df['路_百'] == 0).astype(int) + (df['路_十'] == 0).astype(int) + (df['路_个'] == 0).astype(int))
    df['1路数'] = ((df['路_百'] == 1).astype(int) + (df['路_十'] == 1).astype(int) + (df['路_个'] == 1).astype(int))
    df['2路数'] = ((df['路_百'] == 2).astype(int) + (df['路_十'] == 2).astype(int) + (df['路_个'] == 2).astype(int))
    
    # ---- 形态 ----
    same_ab = (r1 == r2).astype(int)
    same_bc = (r2 == r3).astype(int)
    same_ac = (r1 == r3).astype(int)
    total_same = same_ab + same_bc + same_ac
    
    df['形态'] = '组六'
    df.loc[total_same == 3, '形态'] = '豹子'
    df.loc[total_same == 1, '形态'] = '组三'
    
    # 形态编码
    df['type_code'] = 0  # 组六
    df.loc[df['形态'] == '组三', 'type_code'] = 1
    df.loc[df['形态'] == '豹子', 'type_code'] = 2
    
    # ---- group_number（组选归一化） ----
    sorted_nums = np.sort(nums.values, axis=1)
    # 使用 np.char.add 代替 + 操作符，兼容 numpy 2.x
    df['group_number'] = np.char.add(
        np.char.add(sorted_nums[:, 0].astype(str),
                     sorted_nums[:, 1].astype(str)),
        sorted_nums[:, 2].astype(str)
    )
    
    # ---- 组三的重复数字 ----
    df['pair_digit'] = -1
    mask_group3 = df['形态'] == '组三'
    df.loc[mask_group3, 'pair_digit'] = np.where(
        r1[mask_group3] == r2[mask_group3], r1[mask_group3],
        np.where(r2[mask_group3] == r3[mask_group3], r2[mask_group3], r1[mask_group3])
    )
    
    # ---- 和值分区 ----
    df['sum_zone'] = '中区'  # 10-17
    df.loc[df['和值'] <= 9, 'sum_zone'] = '低区'   # 0-9
    df.loc[df['和值'] >= 18, 'sum_zone'] = '高区'  # 18-27
    
    # ---- 跨度分区 ----
    df['span_zone'] = '中跨'  # 4-6
    df.loc[df['跨度'] <= 3, 'span_zone'] = '小跨'  # 0-3
    df.loc[df['跨度'] >= 7, 'span_zone'] = '大跨'  # 7-9
    
    return df


def add_missing_features(df: pd.DataFrame) -> pd.DataFrame:
    """遗漏值计算（含分位遗漏）—— 向量化版本"""
    n = len(df)
    r1, r2, r3 = df['红球1'].values, df['红球2'].values, df['红球3'].values
    
    # ---- 全位遗漏：任一位置出现就算 ----
    prefix = '遗漏'
    for d in range(10):
        df[f'{prefix}_{d}'] = 0
    current_miss = np.zeros(10, dtype=np.int32)
    for i in range(n):
        appeared = {r1[i], r2[i], r3[i]}
        for d in range(10):
            if d in appeared:
                current_miss[d] = 0
            else:
                current_miss[d] += 1
        for d in range(10):
            df.iloc[i, df.columns.get_loc(f'{prefix}_{d}')] = current_miss[d]
    
    # ---- 分位遗漏 ---- 
    miss_cols_info = {  # (列名, 前缀, values)
        'miss_bai': ('红球1', 'miss_bai', r1),
        'miss_shi': ('红球2', 'miss_shi', r2),
        'miss_ge':  ('红球3', 'miss_ge', r3),
    }
    for prefix, (col_name, pre, vals) in miss_cols_info.items():
        for d in range(10):
            df[f'{pre}_{d}'] = 0
        current_miss = np.zeros(10, dtype=np.int32)
        for i in range(n):
            vi = int(vals[i])
            for d in range(10):
                if d == vi:
                    current_miss[d] = 0
                else:
                    current_miss[d] += 1
            for d in range(10):
                df.iloc[i, df.columns.get_loc(f'{pre}_{d}')] = current_miss[d]
    
    # ---- 平均/最大遗漏 ----
    for label, pre in [('全位', '遗漏'), ('百位', 'miss_bai'), ('十位', 'miss_shi'), ('个位', 'miss_ge')]:
        miss_cols = [f'{pre}_{d}' for d in range(10)]
        df[f'avg_miss_{label}'] = df[miss_cols].mean(axis=1)
        df[f'max_miss_{label}'] = df[miss_cols].max(axis=1)
    
    return df


def add_hot_cold(df: pd.DataFrame) -> pd.DataFrame:
    """冷热分类（含分位）"""
    for label, prefix in [('全位', '遗漏'), ('百位', 'miss_bai'), ('十位', 'miss_shi'), ('个位', 'miss_ge')]:
        for d in range(10):
            col_miss = f'{prefix}_{d}'
            col_hc = f'hotcold_{label[:2]}_{d}' if label != '全位' else f'冷热_{d}'
            df[col_hc] = '温'
            df.loc[df[col_miss] <= 3, col_hc] = '热'
            df.loc[df[col_miss] > 8, col_hc] = '冷'
    
    return df


def add_rolling_features(df: pd.DataFrame) -> pd.DataFrame:
    """滚动统计特征（近5/10/30期均值）"""
    for window in [5, 10, 30]:
        df[f'和值_ma{window}'] = df['和值'].rolling(window=window, min_periods=1).mean().round(1)
        df[f'跨度_ma{window}'] = df['跨度'].rolling(window=window, min_periods=1).mean().round(1)
    return df


# ==========================================
#  3. 主流程
# ==========================================

def read_raw(input_path: str, skiprows: int, lottery: str) -> pd.DataFrame:
    """读取原始CSV"""
    path = Path(input_path)
    if not path.exists():
        print(f"[错误] 找不到文件: {input_path}")
        sys.exit(1)
    
    if lottery == 'pls':
        # 先尝试标准3列格式（期号,日期,号码），再回退到KittenCN/500.com格式
        df = pd.read_csv(input_path, nrows=0, encoding='utf-8-sig')
        if '号码' in df.columns:
            # 标准3列格式：从号码列拆出红球1,红球2,红球3
            df = pd.read_csv(input_path, encoding='utf-8-sig')
            nums = df['号码'].apply(normalize_number)
            df['红球1'] = nums.str[0].astype(int)
            df['红球2'] = nums.str[1].astype(int)
            df['红球3'] = nums.str[2].astype(int)
            if '期号' in df.columns:
                df = df.rename(columns={'期号': '期数'})
        else:
            # KittenCN/500.com格式：跳过前几行，按位置命名
            df = pd.read_csv(input_path, skiprows=skiprows, header=None,
                             names=['期数', '红球1', '红球2', '红球3'], encoding='utf-8-sig')
    else:
        # 支持两种格式：
        # A: zhcw格式（简洁3列：期号,日期,号码）
        # B: konglr格式（宽表：issue, frontWinningNum, ...）
        df = pd.read_csv(input_path, encoding='utf-8-sig')
        if '号码' in df.columns:
            # zhcw格式：从 号码 列拆出红球1,红球2,红球3
            nums = df['号码'].apply(normalize_number)
            df['红球1'] = nums.str[0].astype(int)
            df['红球2'] = nums.str[1].astype(int)
            df['红球3'] = nums.str[2].astype(int)
            # 统一列名为 期数
            if '期号' in df.columns and '期数' not in df.columns:
                df = df.rename(columns={'期号': '期数'})
            if '期数' not in df.columns:
                df = df.rename(columns={'issue': '期数'})
        elif 'issue' in df.columns and '期数' not in df.columns:
            df = df.rename(columns={'issue': '期数'})
        if 'frontWinningNum' in df.columns and '红球1' not in df.columns:
            parts = df['frontWinningNum'].str.split(' ', expand=True)
            df['红球1'] = pd.to_numeric(parts[0], errors='coerce')
            df['红球2'] = pd.to_numeric(parts[1], errors='coerce')
            df['红球3'] = pd.to_numeric(parts[2], errors='coerce')
    
    # 类型转换
    for c in ['红球1', '红球2', '红球3', '期数']:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    
    df = df.dropna(subset=['红球1', '红球2', '红球3', '期数'])
    df['期数'] = df['期数'].astype(int)
    df[['红球1', '红球2', '红球3']] = df[['红球1', '红球2', '红球3']].astype(int)
    df = df.sort_values('期数', ascending=True).reset_index(drop=True)
    
    return df


def main():
    parser = argparse.ArgumentParser(description='彩票特征工程 v3')
    parser.add_argument('--input', required=True, help='输入原始CSV路径')
    parser.add_argument('--output', required=True, help='输出特征CSV路径')
    parser.add_argument('--lottery', required=True, choices=['pls', 'd3'],
                        help='彩种：pls=排列三, d3=福彩3D')
    parser.add_argument('--skiprows', type=int, default=0,
                        help='跳过前N行（pls格式需要=2）')
    parser.add_argument('--check-only', action='store_true',
                        help='只做数据检查，不做特征工程')
    parser.add_argument('--force', action='store_true',
                        help='即使数据检查有异常也继续处理')
    args = parser.parse_args()
    
    lottery_name = '排列三' if args.lottery == 'pls' else '福彩3D'
    print(f"\n{'='*50}")
    print(f"  特征工程 v3 - {lottery_name}")
    print(f"{'='*50}")
    
    # 1. 读取原始数据
    df = read_raw(args.input, args.skiprows, args.lottery)
    
    # 2. 数据检查
    report = check_data(df, lottery_name)
    print_check_report(report)
    
    # 3. 保存检查报告
    base_dir = Path(__file__).resolve().parent.parent
    output_dir = base_dir / 'output' / 'reports'
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f'{args.lottery}_data_check.json'
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"  检查报告已保存: {report_path}")
    
    # 4. 如果检查异常且不强制，退出
    if not report['通过'] and not args.force:
        print("  数据检查未通过，停止处理。使用 --force 强制继续。")
        sys.exit(1)
    if args.check_only:
        return
    
    # 5. 特征计算
    df = add_features(df)
    print(f"  ✅ 基础特征计算完成")
    
    df = add_missing_features(df)
    print(f"  ✅ 遗漏特征计算完成")
    
    df = add_hot_cold(df)
    print(f"  ✅ 冷热分类完成")
    
    df = add_rolling_features(df)
    print(f"  ✅ 滚动特征计算完成")
    
    # 6. 输出（按期号降序）
    df_out = df.sort_values('期数', ascending=False).reset_index(drop=True)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(args.output, index=False, encoding='utf-8-sig')
    
    print(f"\n✅ 特征工程完成！")
    print(f"  输出: {args.output}")
    print(f"  总行数: {len(df_out)}")
    print(f"  特征数: {len(df_out.columns)}")
    print(f"  期号: {df_out.iloc[-1]['期数']} ~ {df_out.iloc[0]['期数']}")
    
    # 7. 保存特征列名清单
    cols_path = output_dir / f'{args.lottery}_columns.json'
    with open(cols_path, 'w', encoding='utf-8') as f:
        json.dump(list(df_out.columns), f, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
