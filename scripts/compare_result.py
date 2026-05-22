#!/usr/bin/env python3
"""
预测 vs 开奖对比脚本
====================
读取最新预测 JSON，对比最新期开奖结果，生成差异报告。

用法：
    python scripts/compare_result.py --lottery pls
    python scripts/compare_result.py --lottery d3
    python scripts/compare_result.py --lottery pls --prediction output/predictions/pls_predict_26125.json
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent.parent


def load_prediction(lottery, prediction_path=None, strategy='default', issue=None):
    """加载预测 JSON，支持多策略文件。优先按期号查找对应预测。"""
    if prediction_path:
        p = Path(prediction_path)
        path = p if p.is_absolute() else BASE_DIR / p
    else:
        prefix = f'{lottery}_{strategy}' if strategy != 'default' else lottery
        pred_dir = BASE_DIR / 'output' / 'predictions'

        if issue:
            issue_path = pred_dir / f'{prefix}_predict_{issue}.json'
            if issue_path.exists():
                path = issue_path
            else:
                path = pred_dir / f'latest_{prefix}.json'
        else:
            path = pred_dir / f'latest_{prefix}.json'

    if not path.exists():
        print(f"[错误] 预测文件不存在: {path}")
        sys.exit(2)

    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_latest_draw(lottery):
    """从特征 CSV 读取最新一期开奖"""
    path = BASE_DIR / 'data' / 'processed' / f'{lottery}_feat.csv'
    if not path.exists():
        print(f"[错误] 特征数据不存在: {path}")
        print(f"  请先运行: python run_daily.py {lottery}")
        sys.exit(2)

    df = pd.read_csv(path, encoding='utf-8-sig')
    latest = df.iloc[0]
    a, b, c = int(latest['红球1']), int(latest['红球2']), int(latest['红球3'])
    number = f"{a}{b}{c}"
    group = ''.join(sorted(number))
    return {
        '期号': int(latest['期数']),
        '开奖号码': number,
        '组选': group,
        '红球1': a, '红球2': b, '红球3': c,
        '和值': int(latest['和值']),
        '跨度': int(latest['跨度']),
        '形态': latest['形态'],
    }


def compare(predictions, actual):
    """逐注对比预测与开奖"""
    actual_num = actual['开奖号码']
    actual_group = actual['组选']
    actual_sum = actual['和值']
    actual_span = actual['跨度']
    actual_morph = actual['形态']

    rows = []
    for pred in predictions:
        num = pred['号码']
        group = pred.get('group_number', ''.join(sorted(num)))
        pred_sum = pred['和值']
        pred_span = pred['跨度']
        pred_morph = pred['形态']

        rows.append({
            '排名': pred['排名'],
            '预测号码': num,
            '直选命中': num == actual_num,
            '组选命中': group == actual_group,
            '和值差': abs(pred_sum - actual_sum),
            '跨度差': abs(pred_span - actual_span),
            '形态一致': pred_morph == actual_morph,
            '预测和值': pred_sum,
            '预测跨度': pred_span,
            '预测形态': pred_morph,
        })

    return rows


def build_report(pred_json, actual, rows):
    """生成对比报告"""
    # 期号不匹配时分类处理
    pred_issue = str(pred_json.get('预测期号', ''))
    actual_issue = str(actual['期号'])
    if pred_issue != actual_issue:
        try:
            pred_num = int(pred_issue)
            actual_num = int(actual_issue)
        except (ValueError, TypeError):
            return {
                '错误': '期号格式无法解析',
                '预测期号': pred_json.get('预测期号'),
                '实际期号': actual['期号'],
                '预测期号匹配': False,
                '对比时间': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                '彩种': pred_json.get('彩种', ''),
            }
        if pred_num > actual_num:
            return {
                '状态': 'waiting_actual',
                '预测期号': pred_json.get('预测期号'),
                '实际期号': actual['期号'],
                '预测期号匹配': False,
                '对比时间': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                '彩种': pred_json.get('彩种', ''),
                '说明': '预测期号 > 实际开奖期号，等待数据源更新开奖数据',
            }
        else:
            return {
                '错误': '缺少对应期号预测文件（预测期号 < 开奖期号）',
                '预测期号': pred_json.get('预测期号'),
                '实际期号': actual['期号'],
                '预测期号匹配': False,
                '对比时间': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                '彩种': pred_json.get('彩种', ''),
            }

    direct_hit = any(r['直选命中'] for r in rows)
    group_hit = any(r['组选命中'] for r in rows)

    best_direct = next((r for r in rows if r['直选命中']), None)
    best_group = next((r for r in rows if r['组选命中']), None)
    min_sum_diff = min(rows, key=lambda r: r['和值差'])
    min_span_diff = min(rows, key=lambda r: r['跨度差'])
    morph_matches = [r for r in rows if r['形态一致']]

    # 一句话摘要（供 cron/Hermes 直接读取）
    if direct_hit:
        one_line = f"开奖 {actual['开奖号码']} | 直选命中第{best_direct['排名']}名 | 和值{actual['和值']} 跨度{actual['跨度']}"
    elif group_hit:
        one_line = f"开奖 {actual['开奖号码']} | 组选命中第{best_group['排名']}名 | 和值{actual['和值']} 跨度{actual['跨度']}"
    else:
        one_line = f"开奖 {actual['开奖号码']} | 未命中 最近和差{min_sum_diff['和值差']}跨差{min_span_diff['跨度差']} | 形态一致{morph_matches.__len__()}/{rows.__len__()}注"

    return {
        '一句话摘要': one_line,
        '对比时间': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        '彩种': pred_json.get('彩种', ''),
        '预测期号': pred_json.get('预测期号', ''),
        '实际期号': actual['期号'],
        '预测期号匹配': pred_json.get('预测期号') == actual['期号'],
        '开奖号码': actual['开奖号码'],
        '开奖详情': {
            '号码': actual['开奖号码'],
            '组选': actual['组选'],
            '和值': actual['和值'],
            '跨度': actual['跨度'],
            '形态': actual['形态'],
        },
        '命中情况': {
            '直选命中': direct_hit,
            '组选命中': group_hit,
            '直选最佳排名': best_direct['排名'] if best_direct else None,
            '组选最佳排名': best_group['排名'] if best_group else None,
        },
        '最佳逼近': {
            '最小和值差': min_sum_diff['和值差'],
            '最小和值差排名': min_sum_diff['排名'],
            '最小和值差号码': min_sum_diff['预测号码'],
            '最小跨度差': min_span_diff['跨度差'],
            '最小跨度差排名': min_span_diff['排名'],
            '最小跨度差号码': min_span_diff['预测号码'],
            '形态一致数': len(morph_matches),
            '形态一致排名': [r['排名'] for r in morph_matches[:5]],
        },
        '逐注对比': rows,
    }


def print_report(report):
    """终端打印对比摘要"""
    if report.get('状态') == 'waiting_actual':
        print(f"\n{'='*55}")
        print(f"  ⏳ 等待开奖数据更新")
        print(f"  预测期号: {report['预测期号']} | 实际期号: {report['实际期号']}")
        print(f"  {report.get('说明', '')}")
        print(f"{'='*55}\n")
        return

    if report.get('错误'):
        print(f"\n{'='*55}")
        print(f"  ⚠️  {report['错误']}")
        print(f"  预测期号: {report['预测期号']} | 实际期号: {report['实际期号']}")
        print(f"{'='*55}\n")
        return

    actual = report['开奖详情']
    hit = report['命中情况']
    best = report['最佳逼近']

    number = actual['号码']

    # 顶部醒目的开奖号码
    print(f"\n{'='*55}")
    print(f"  🎰 今日开奖号码")
    print(f"{'='*55}")
    print(f"")
    print(f"         {number[0]}    {number[1]}    {number[2]}")
    print(f"        {'━'*13}")
    print(f"          {actual['形态']}  |  和值 {actual['和值']}  |  跨度 {actual['跨度']}")
    print(f"")

    # 预测对比
    print(f"  📋 {report['彩种']} 预测对比 (预测期号 {report['预测期号']})")

    if hit['直选命中']:
        print(f"  🎯 直选命中！排名第 {hit['直选最佳排名']} 位")
    elif hit['组选命中']:
        print(f"  🏅 组选命中！排名第 {hit['组选最佳排名']} 位（直选未中）")
    else:
        print(f"  ❌ 未命中 — 最佳逼近: 和值差{best['最小和值差']} | 跨度差{best['最小跨度差']}"
              f" | 形态一致 {best['形态一致数']}/{len(report['逐注对比'])} 注")

    print(f"  {'─'*55}")
    print(f"  {'排名':>4} {'预测':>6} {'直选':>4} {'组选':>4} {'和差':>4} {'跨差':>4} {'形态':>4}")
    for r in report['逐注对比'][:10]:
        print(f"  {r['排名']:>4} {r['预测号码']:>6} "
              f"{'✅' if r['直选命中'] else '  ' :>4} "
              f"{'✅' if r['组选命中'] else '  ' :>4} "
              f"{r['和值差']:>4} {r['跨度差']:>4} "
              f"{'✅' if r['形态一致'] else '  ' :>4}")
    print(f"{'='*55}\n")


def append_to_history(report, lottery, strategy='default'):
    """将本期复盘追加到长期复盘总表"""
    if report.get('错误') or report.get('状态') == 'waiting_actual':
        reason = report.get('错误') or report.get('说明', '等待开奖')
        print(f"  ⚠️  跳过写入 review_history（{reason}）")
        return

    history_dir = BASE_DIR / 'output' / 'reviews'
    history_dir.mkdir(parents=True, exist_ok=True)
    history_path = history_dir / 'review_history.csv'

    top1 = report['逐注对比'][0] if report['逐注对比'] else {}
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 计算各范围命中情况
    all_rows = report.get('逐注对比', [])
    it_top5 = [r for r in all_rows if r['排名'] <= 5]
    it_top10 = [r for r in all_rows if r['排名'] <= 10]

    def hit_info(rows):
        direct = next((r for r in rows if r['直选命中']), None)
        if direct:
            return ('直选', direct['预测号码'], direct['排名'])
        group = next((r for r in rows if r['组选命中']), None)
        if group:
            return ('组选', group['预测号码'], group['排名'])
        return (None, '', '')

    hit_top5_type, hit_top5_num, hit_top5_rank = hit_info(it_top5)
    hit_top10_type, hit_top10_num, hit_top10_rank = hit_info(it_top10)

    hit_all = next((r for r in all_rows if r['直选命中']), None)
    if not hit_all:
        hit_all = next((r for r in all_rows if r['组选命中']), None)

    if hit_top5_type:
        hit_range = 'Top5'
    elif hit_top10_type:
        hit_range = 'Top10'
    elif hit_all:
        hit_range = 'Top30'
    else:
        hit_range = '未命中'

    row = {
        '策略': strategy,
        '彩种': report['彩种'],
        '期号': str(report['实际期号']),
        '开奖号码': report['开奖号码'],
        '预测Top1': top1.get('预测号码', ''),
        '直选命中Top30': report['命中情况']['直选命中'],
        '组选命中Top30': report['命中情况']['组选命中'],
        '命中范围': hit_range,
        '命中号码': hit_all['预测号码'] if hit_all else '',
        '命中排名': str(hit_all['排名']) if hit_all else '',
        'Top5直选': hit_top5_type == '直选',
        'Top5组选': hit_top5_type == '组选',
        'Top1和值误差': top1.get('和值差', ''),
        'Top1跨度误差': top1.get('跨度差', ''),
        'Top1形态一致': top1.get('形态一致', ''),
        '复盘时间': now,
    }

    columns = list(row.keys())
    new_df = pd.DataFrame([row])

    if history_path.exists():
        old_df = pd.read_csv(history_path, dtype=str, encoding='utf-8-sig')
        # 同彩种+同期号+同策略只保留最新（三策略独立记录）
        merged = pd.concat([old_df, new_df], ignore_index=True)
        merged = merged.drop_duplicates(subset=['彩种', '期号', '策略'], keep='last')
        merged = merged[columns]
    else:
        merged = new_df

    merged.to_csv(history_path, index=False, encoding='utf-8-sig')
    print(f"  📊 复盘总表: {history_path} (累计 {len(merged)} 条)")


def main():
    parser = argparse.ArgumentParser(description='预测 vs 开奖对比')
    parser.add_argument('--lottery', required=True, choices=['pls', 'd3'],
                        help='彩种')
    parser.add_argument('--prediction', help='预测JSON路径（默认 latest）')
    parser.add_argument('--strategy', default='default',
                        choices=['default', 'conservative', 'diversity'],
                        help='策略名称（默认default，用于加载对应预测文件）')
    args = parser.parse_args()

    actual = load_latest_draw(args.lottery)
    pred_json = load_prediction(args.lottery, args.prediction, args.strategy, issue=str(actual['期号']))
    rows = compare(pred_json.get('推荐', []), actual)
    report = build_report(pred_json, actual, rows)

    print_report(report)

    # 保存报告
    output_dir = BASE_DIR / 'output' / 'reports'
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = f'_{args.strategy}' if args.strategy != 'default' else ''
    output_path = output_dir / f'{args.lottery}_compare{suffix}_latest.json'

    if report.get('状态') == 'waiting_actual':
        # 写单独文件，不覆盖 latest（保留上次有效对比结果）
        waiting_path = output_dir / f'{args.lottery}_compare{suffix}_waiting.json'
        with open(waiting_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"  ⏳ 等待开奖: {waiting_path}")
        sys.exit(0)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"  💾 对比报告: {output_path}")

    # 追加到长期复盘总表
    append_to_history(report, args.lottery, args.strategy)

    # 真错误时 exit 1，便于 daily_review 检测失败
    if report.get('错误'):
        sys.exit(2)


if __name__ == '__main__':
    main()
