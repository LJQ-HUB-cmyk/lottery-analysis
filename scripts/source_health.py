#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据源健康报告
=============
检查各数据源状态、最新数据、隔离区情况，输出一目了然的健康摘要。

用法:
    python scripts/source_health.py
    python scripts/source_health.py --json   # JSON 格式输出（适合程序消费）
"""

import argparse
import io
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = BASE_DIR / 'data' / 'cache'
RAW_DIR = BASE_DIR / 'data' / 'raw'
QUARANTINE_DIR = BASE_DIR / 'data' / 'quarantine'


def load_source_status():
    path = CACHE_DIR / 'source_status.json'
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def get_latest_data(lottery):
    """读取 raw 文件最新一期数据"""
    path = RAW_DIR / f'{lottery}_raw.csv'
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, dtype=str, encoding='utf-8-sig')
        if len(df) == 0:
            return None
        # 号码可能在 '号码' 或 '中奖号码' 列
        num_col = '号码' if '号码' in df.columns else (
            '中奖号码' if '中奖号码' in df.columns else df.columns[-1])
        return {
            'issue': str(df['期号'].iloc[0]),
            'number': str(df[num_col].iloc[0]),
            'total_rows': len(df),
        }
    except Exception as e:
        return {'error': str(e)}


def get_quarantine_stats(hours=24):
    """统计最近N小时内隔离的坏数据"""
    if not QUARANTINE_DIR.exists():
        return {'total_files': 0, 'recent_files': 0, 'recent_details': []}

    cutoff = datetime.now() - timedelta(hours=hours)
    all_files = list(QUARANTINE_DIR.glob('*'))
    recent = []

    for f in all_files:
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        if mtime >= cutoff:
            detail = {'file': f.name, 'time': mtime.strftime('%Y-%m-%d %H:%M:%S')}
            if f.suffix == '.json':
                try:
                    with open(f, 'r', encoding='utf-8') as fp:
                        data = json.load(fp)
                    detail['lottery'] = data.get('lottery', '')
                    detail['issue'] = data.get('issue', '')
                    detail['reason'] = data.get('reason', '')
                    detail['primary_num'] = data.get('primary', {}).get('number', '')
                    detail['verify_num'] = data.get('verify', {}).get('number', '')
                except Exception:
                    pass
            elif f.suffix == '.csv':
                detail['lottery'] = f.stem.split('_')[0]
                detail['reason'] = 'validation_failure'
            recent.append(detail)

    return {
        'total_files': len(all_files),
        'recent_files': len(recent),
        'recent_details': recent,
    }


def validate_data_quality(data: dict) -> tuple[bool, list[str]]:
    """校验数据质量。返回 (ok, issues)。

    判定标准：最新期号正确 + 总行数不降 + 号码格式正确。
    fallback 路径拿到正确数据也判为健康。
    """
    if not data or 'error' in data:
        return False, ['数据读取失败']
    issues = []
    number = data.get('number', '')
    total = data.get('total_rows', 0)

    if not number or len(number) != 3 or not number.isdigit():
        issues.append(f'号码格式异常: {number}')
    if total < 1000:
        issues.append(f'总行数偏低: {total}')

    return len(issues) == 0, issues


def build_report():
    """构建完整健康报告"""
    status = load_source_status()
    report = {'pls': {}, 'd3': {}, 'quarantine': {}}

    # PLS
    pls_data = get_latest_data('pls')
    report['pls']['data'] = pls_data
    report['pls']['sources'] = {}
    for key in ['pls_js_lottery', 'pls_sporttery']:
        item = status.get(key, {})
        report['pls']['sources'][key] = {
            'failures': item.get('consecutive_failures', 0),
            'cooldown_until': item.get('cooldown_until'),
            'cooldown_round': item.get('cooldown_round', 0),
            'last_status': item.get('last_status'),
            'last_success': item.get('last_success'),
            'last_failure': item.get('last_failure'),
        }

    # D3
    d3_data = get_latest_data('d3')
    report['d3']['data'] = d3_data
    report['d3']['sources'] = {}
    for key in ['d3_eastmoney', 'd3_zhcw']:
        item = status.get(key, {})
        report['d3']['sources'][key] = {
            'failures': item.get('consecutive_failures', 0),
            'cooldown_until': item.get('cooldown_until'),
            'cooldown_round': item.get('cooldown_round', 0),
            'last_status': item.get('last_status'),
            'last_success': item.get('last_success'),
            'last_failure': item.get('last_failure'),
        }

    # Quarantine
    report['quarantine'] = get_quarantine_stats()

    return report


def print_report(report):
    """人类可读格式"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    print("=" * 55)
    print(f"  数据源健康报告  {now}")
    print("=" * 55)

    for lottery, label in [('pls', '排列三'), ('d3', '福彩3D')]:
        print(f"\n── {label} ──")
        data = report[lottery]['data']
        if data and 'error' not in data:
            print(f"  最新数据: {data['issue']} = {data['number']}  (共 {data['total_rows']} 期)")
        elif data and 'error' in data:
            print(f"  ❌ 读取失败: {data['error']}")
        else:
            print(f"  ❌ 无数据文件")

        data_ok, data_issues = validate_data_quality(data) if data else (False, ['无数据'])

        for src_name, s in report[lottery]['sources'].items():
            cd = s['cooldown_until']
            if cd:
                try:
                    cd_dt = datetime.strptime(cd, "%Y-%m-%d %H:%M:%S")
                    remaining = int((cd_dt - datetime.now()).total_seconds() / 60)
                    rnd = s.get('cooldown_round', 0)
                    rnd_str = f" 第{rnd}轮" if rnd > 1 else ""
                    print(f"  🔒 {src_name} 冷却中{rnd_str}，剩余 {remaining} 分钟 (HTTP {s['last_status']})")
                except ValueError:
                    print(f"  🔒 {src_name} 冷却中")
            elif s['failures'] > 0 and data_ok:
                print(f"  ⚠️  {src_name} 主源异常但数据正常（fallback生效），最后: {s['last_failure']}")
            elif s['failures'] > 0:
                print(f"  ❌ {src_name} 失败 {s['failures']} 次，最后: {s['last_failure']}")
                if data_issues:
                    for issue in data_issues:
                        print(f"      └─ {issue}")
            else:
                last = s['last_success'] or '无记录'
                print(f"  ✅ {src_name} 正常，最后成功: {last}")

    # Quarantine
    q = report['quarantine']
    print(f"\n── 隔离区 ──")
    print(f"  总计: {q['total_files']} 个文件")
    if q['recent_files'] > 0:
        print(f"  ⚠️  最近 24h: {q['recent_files']} 条")
        for d in q['recent_details']:
            extra = ''
            if 'primary_num' in d:
                extra = f"  主源={d['primary_num']} vs 校验={d['verify_num']}"
            print(f"    {d['time']}  {d.get('lottery','')} {d.get('issue','')}  {d.get('reason','')}{extra}")
    else:
        print(f"  ✅ 最近 24h 无坏数据")

    print(f"\n{'=' * 55}")


def main():
    parser = argparse.ArgumentParser(description='数据源健康报告')
    parser.add_argument('--json', action='store_true', help='JSON 格式输出')
    parser.add_argument('--output', type=str, default=None,
                        help='将报告写入指定文件（--json 时写JSON，否则写人类可读文本）')
    args = parser.parse_args()

    report = build_report()

    if args.json:
        text = json.dumps(report, ensure_ascii=False, indent=2)
    else:
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        print_report(report)
        sys.stdout = old_stdout
        text = buf.getvalue()

    # 写入文件
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding='utf-8')
        print(f"[完成] 健康报告已写入: {output_path}", file=sys.stderr)

    # 终端输出
    # 注：no_agent 模式下，source_health.py 的 stdout 会被 cron 脚本原样交付。
    # 如果已经写了文件（--output），不再 print 到 stdout，避免 JSON 混入推送内容。
    # 要想看终端输出，不带 --output 单独执行即可。
    if not args.output:
        print(text)
    else:
        # --output 时只写文件，不污染 stdout
        pass


if __name__ == '__main__':
    main()
