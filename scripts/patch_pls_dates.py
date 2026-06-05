#!/usr/bin/env python3
"""
排列三历史日期补全工具
======================
pls_raw.csv 中 26116 期往前缺少开奖日期。
此脚本通过 sporttery API 尝试补全近期日期。

用法：
  python scripts/patch_pls_dates.py --days 50
  python scripts/patch_pls_dates.py --dry-run
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"


def fetch_with_dates(days=50):
    """从 sporttery API 获取带日期的排列三数据。"""
    url = (
        "https://webapi.sporttery.cn/gateway/lottery/"
        f"getHistoryPageListV1.qry?gameNo=350133&provinceId=0"
        f"&pageSize={min(days, 100)}&is498=1"
    )
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/134.0.0.0 Safari/537.36',
    }
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[ERROR] API 请求失败: {e}")
        return {}

    result = {}
    for item in data.get('value', {}).get('list', []):
        nums = item['lotteryDrawResult'].split()
        if len(nums) >= 3:
            issue = item['lotteryDrawNum']
            date = item['lotteryDrawTime']
            result[issue] = date
    return result


def main():
    parser = argparse.ArgumentParser(description="排列三历史日期补全")
    parser.add_argument("--days", type=int, default=50, help="从API获取最近多少期")
    parser.add_argument("--dry-run", action="store_true", help="只显示差异，不写入")
    args = parser.parse_args()

    raw_path = RAW_DIR / "pls_raw.csv"
    if not raw_path.exists():
        print(f"[ERROR] {raw_path} 不存在")
        sys.exit(1)

    df = pd.read_csv(raw_path, dtype=str, encoding='utf-8-sig')
    if '期号' not in df.columns or '日期' not in df.columns:
        print("[ERROR] CSV 格式不正确（需要 期号,日期,号码）")
        sys.exit(1)

    # 获取 API 数据
    print(f"从 sporttery API 获取最近 {args.days} 期...")
    api_dates = fetch_with_dates(args.days)
    if not api_dates:
        print("[WARN] API 无数据返回")
        sys.exit(0)

    print(f"获取到 {len(api_dates)} 期带日期数据")

    # 匹配并补全
    patched = 0
    for idx, row in df.iterrows():
        issue = str(row['期号']).strip()
        current_date = str(row.get('日期', '')).strip()
        if issue in api_dates and (not current_date or current_date == 'nan' or current_date == ''):
            new_date = api_dates[issue]
            if args.dry_run:
                print(f"  [DRY] 期号 {issue}: 无日期 → {new_date}")
            else:
                df.at[idx, '日期'] = new_date
            patched += 1

    if patched == 0:
        print("无需补全（所有期号已有日期或 API 中无匹配）")
        return

    print(f"补全 {patched} 期日期")

    if not args.dry_run:
        df.to_csv(raw_path, index=False, encoding='utf-8-sig')
        print(f"已写入 {raw_path}")
    else:
        print("(dry-run 模式，未写入)")


if __name__ == "__main__":
    main()
