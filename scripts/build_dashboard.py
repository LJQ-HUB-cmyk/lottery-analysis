#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
可视化仪表板生成器
==================
读取所有输出文件，生成一个自包含 HTML 仪表板。
浏览器打开 output/dashboard.html 即可查看。

用法：
    python scripts/build_dashboard.py
    python scripts/build_dashboard.py --open    # 生成后自动打开浏览器
"""

import argparse
import csv
import json
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE / 'output'


def read_json(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def read_review_csv():
    path = OUTPUT_DIR / 'reviews' / 'review_history.csv'
    if not path.exists():
        return []
    try:
        with path.open(encoding='utf-8-sig', newline='') as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def load_all_data():
    """加载所有需要的数据。"""
    data = {}

    # 预测
    for lt in ['pls', 'd3']:
        data[f'{lt}_predict'] = read_json(OUTPUT_DIR / 'predictions' / f'latest_{lt}.json')
        data[f'{lt}_enhanced'] = read_json(OUTPUT_DIR / 'predictions' / f'latest_{lt}_enhanced.json')

    # 复盘
    for lt in ['pls', 'd3']:
        data[f'{lt}_compare'] = read_json(OUTPUT_DIR / 'reports' / f'{lt}_compare_latest.json')

    # KL8
    data['kl8_predict'] = read_json(OUTPUT_DIR / 'kl8' / 'kl8_predict_latest.json')
    data['kl8_review'] = read_json(OUTPUT_DIR / 'kl8' / 'kl8_review_latest.json')
    data['kl8_metrics'] = read_json(OUTPUT_DIR / 'kl8' / 'kl8_metrics.json')

    # 复盘历史
    data['review_history'] = read_review_csv()

    return data


def build_prediction_table(pred_data, label):
    """生成预测号码表格 HTML。"""
    if not pred_data:
        return f'<p class="empty">暂无 {label} 预测数据</p>'

    issue = pred_data.get('预测期号', '?')
    time_str = pred_data.get('评分时间', '?')
    recommends = pred_data.get('推荐', [])

    rows = ''
    for r in recommends[:30]:
        rows += f'''<tr>
            <td class="rank">{r.get('排名','')}</td>
            <td class="num">{r.get('号码','')}</td>
            <td>{r.get('group_number','')}</td>
            <td>{r.get('和值','')}</td>
            <td>{r.get('跨度','')}</td>
            <td>{r.get('形态','')}</td>
            <td class="score">{r.get('总分','')}</td>
        </tr>'''

    return f'''
    <div class="pred-card">
        <h3>{label} <span class="issue">期号 {issue}</span> <span class="time">{time_str}</span></h3>
        <table class="pred-table">
            <thead><tr>
                <th>#</th><th>号码</th><th>组选</th><th>和值</th><th>跨度</th><th>形态</th><th>总分</th>
            </tr></thead>
            <tbody>{rows}</tbody>
        </table>
    </div>'''


def build_kl8_section(kl8_pred, kl8_review, kl8_metrics):
    """生成 KL8 区域 HTML。"""
    parts = ['<div class="section"><h2>🎯 快乐8</h2>']

    if kl8_pred:
        pool = kl8_pred.get('candidate_pool', [])
        play4 = kl8_pred.get('recommended_play4', [])
        z = kl8_pred.get('zone_distribution', {})
        parts.append(f'''
        <div class="kl8-card">
            <h3>预测期号 {kl8_pred.get('predicted_issue','?')}</h3>
            <p><strong>选四主推：</strong>
                {' '.join(f'<span class="kl8-play4">{n:02d}</span>' for n in play4)}</p>
            <p><strong>20码池：</strong>
                {' '.join(f'{n:02d}' for n in pool[:10])}<br>
                {' '.join(f'{n:02d}' for n in pool[10:])}</p>
            <p><strong>分区：</strong>
                01-20:{z.get('01-20',0)} &nbsp; 21-40:{z.get('21-40',0)} &nbsp;
                41-60:{z.get('41-60',0)} &nbsp; 61-80:{z.get('61-80',0)}</p>
        </div>''')

    if kl8_metrics:
        m7 = kl8_metrics.get('last7', {})
        if m7.get('days', 0) > 0:
            profit = m7.get('total_profit', 0)
            profit_cls = 'positive' if profit >= 0 else 'negative'
            parts.append(f'''
            <div class="kl8-card">
                <h3>累计表现（近{m7["days"]}期）</h3>
                <div class="metrics-grid">
                    <div class="metric"><span class="label">成本</span><span class="value">{m7.get("total_cost",0)}元</span></div>
                    <div class="metric"><span class="label">奖金</span><span class="value">{m7.get("total_prize",0)}元</span></div>
                    <div class="metric"><span class="label">盈亏</span><span class="value {profit_cls}">{'+' if profit>0 else ''}{profit}元</span></div>
                    <div class="metric"><span class="label">中二/中三/中四</span><span class="value">{m7.get("hit2_count",0)}/{m7.get("hit3_count",0)}/{m7.get("hit4_count",0)}</span></div>
                </div>
            </div>''')

    parts.append('</div>')
    return '\n'.join(parts)


def build_review_section(history):
    """生成复盘历史区域 HTML（含 plotly 图表数据）。"""
    if not history:
        return '<div class="section"><h2>📊 复盘历史</h2><p class="empty">暂无复盘数据</p></div>'

    # 按彩种+策略分组
    groups = {}
    for r in history:
        lt = r.get('彩种', '')
        st = r.get('策略', 'default')
        groups.setdefault((lt, st), []).append(r)

    # 准备 plotly 数据
    chart_traces = []
    summary_rows = []

    for (lt, st), rs in sorted(groups.items()):
        recent = rs[-30:]
        n = len(recent)
        if n == 0:
            continue

        direct = sum(1 for r in recent if r.get('直选命中Top10', r.get('直选命中Top30', '').lower() in ('true', '1'))
        group = sum(1 for r in recent if r.get('组选命中Top10', r.get('组选命中Top30', '').lower() in ('true', '1'))
        morph = sum(1 for r in recent if r.get('Top1形态一致', '').lower() in ('true', '1'))

        sum_errs = [int(r.get('Top1和值误差', 0) or 0) for r in recent]
        span_errs = [int(r.get('Top1跨度误差', 0) or 0) for r in recent]
        avg_sum = sum(sum_errs) / n
        avg_span = sum(span_errs) / n

        summary_rows.append({
            'lottery': lt, 'strategy': st, 'n': n,
            'direct': direct, 'group': group, 'morph': morph,
            'avg_sum': round(avg_sum, 1), 'avg_span': round(avg_span, 1),
        })

        # 累计命中率曲线
        cumulative_hit = []
        running = 0
        for i, r in enumerate(recent):
            if r.get('组选命中Top10', r.get('组选命中Top30', '').lower() in ('true', '1'):
                running += 1
            cumulative_hit.append(round(running / (i + 1) * 100, 1))

        chart_traces.append({
            'x': [r.get('期号', '') for r in recent],
            'y': cumulative_hit,
            'name': f'{lt} {st}',
            'type': 'scatter',
            'mode': 'lines+markers',
        })

    # 汇总表格
    table_rows = ''
    for s in summary_rows:
        table_rows += f'''<tr>
            <td>{s["lottery"]}</td><td>{s["strategy"]}</td><td>{s["n"]}</td>
            <td>{s["direct"]}/{s["n"]}={s["direct"]/s["n"]*100:.0f}%</td>
            <td>{s["group"]}/{s["n"]}={s["group"]/s["n"]*100:.0f}%</td>
            <td>{s["morph"]}/{s["n"]}={s["morph"]/s["n"]*100:.0f}%</td>
            <td>{s["avg_sum"]}</td><td>{s["avg_span"]}</td>
        </tr>'''

    chart_json = json.dumps(chart_traces, ensure_ascii=False)

    return f'''
    <div class="section">
        <h2>📊 复盘历史</h2>
        <div id="review-chart" style="width:100%;height:350px;"></div>
        <table class="review-table">
            <thead><tr>
                <th>彩种</th><th>策略</th><th>期数</th>
                <th>直选</th><th>组选</th><th>形态</th>
                <th>均和差</th><th>均跨差</th>
            </tr></thead>
            <tbody>{table_rows}</tbody>
        </table>
    </div>
    <script>
    Plotly.newPlot('review-chart', {chart_json}, {{
        title: '累计组选命中率趋势',
        xaxis: {{title: '期号'}},
        yaxis: {{title: '命中率 %', range: [0, 60]}},
        legend: {{orientation: 'h', y: -0.2}},
        margin: {{t: 40, b: 80}},
    }});
    </script>'''


def build_hit_chart(history):
    """生成最近命中情况的柱状图。"""
    if not history:
        return ''

    # 只看 default 策略
    pls = [r for r in history if r.get('彩种') == '排列三' and r.get('策略') == 'default'][-20:]
    d3 = [r for r in history if r.get('彩种') == '福彩3D' and r.get('策略') == 'default'][-20:]

    def make_bars(rs, name):
        x = [r.get('期号', '') for r in rs]
        sum_errs = [int(r.get('Top1和值误差', 0) or 0) for r in rs]
        span_errs = [int(r.get('Top1跨度误差', 0) or 0) for r in rs]
        return [
            {'x': x, 'y': sum_errs, 'name': f'{name} 和值差', 'type': 'bar'},
            {'x': x, 'y': span_errs, 'name': f'{name} 跨度差', 'type': 'bar'},
        ]

    traces = make_bars(pls, 'PLS') + make_bars(d3, 'D3')
    chart_json = json.dumps(traces, ensure_ascii=False)

    return f'''
    <div class="section">
        <h2>📈 近期误差分析</h2>
        <div id="error-chart" style="width:100%;height:300px;"></div>
    </div>
    <script>
    Plotly.newPlot('error-chart', {chart_json}, {{
        barmode: 'group',
        xaxis: {{title: '期号'}},
        yaxis: {{title: '差值'}},
        legend: {{orientation: 'h', y: -0.2}},
        margin: {{t: 30, b: 80}},
    }});
    </script>'''


def build_compare_section(pls_compare, d3_compare):
    """生成最新复盘对比区域。"""
    parts = ['<div class="section"><h2>🎰 最新复盘</h2><div class="compare-grid">']

    for lt, label, compare in [('pls', '排列三', pls_compare), ('d3', '福彩3D', d3_compare)]:
        if not compare or compare.get('错误') or compare.get('状态') == 'waiting_actual':
            parts.append(f'<div class="compare-card"><h3>{label}</h3><p class="empty">等待开奖</p></div>')
            continue

        draw = compare.get('开奖详情', {})
        hit = compare.get('命中情况', {})
        best = compare.get('最佳逼近', {})

        direct_icon = '✅' if hit.get('直选命中') else '❌'
        group_icon = '✅' if hit.get('组选命中') else '❌'

        parts.append(f'''
        <div class="compare-card">
            <h3>{label} {compare.get('实际期号','?')}</h3>
            <div class="draw-number">
                <span>{draw.get('号码','?')[0]}</span>
                <span>{draw.get('号码','?')[1]}</span>
                <span>{draw.get('号码','?')[2]}</span>
            </div>
            <p>{draw.get('形态','')} | 和值 {draw.get('和值','')} | 跨度 {draw.get('跨度','')}</p>
            <div class="hit-info">
                <div>{direct_icon} 直选{'命中 #'+str(hit.get('直选最佳排名','')) if hit.get('直选命中') else '未命中'}</div>
                <div>{group_icon} 组选{'命中 #'+str(hit.get('组选最佳排名','')) if hit.get('组选命中') else '未命中'}</div>
                <div>最佳逼近: 和差{best.get('最小和值差','?')} 跨差{best.get('最小跨度差','?')}</div>
            </div>
        </div>''')

    parts.append('</div></div>')
    return '\n'.join(parts)


def generate_html(data):
    """生成完整 HTML。"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M')

    # 预测表格
    pls_pred = build_prediction_table(data.get('pls_predict', {}), '排列三')
    d3_pred = build_prediction_table(data.get('d3_predict', {}), '福彩3D')

    # KL8
    kl8_html = build_kl8_section(
        data.get('kl8_predict'), data.get('kl8_review'), data.get('kl8_metrics'))

    # 复盘对比
    compare_html = build_compare_section(
        data.get('pls_compare'), data.get('d3_compare'))

    # 复盘历史图表
    review_html = build_review_section(data.get('review_history', []))

    # 误差分析图表
    error_html = build_hit_chart(data.get('review_history', []))

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>彩票分析仪表板</title>
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, "Microsoft YaHei", sans-serif; background: #0f172a; color: #e2e8f0; padding: 20px; }}
.header {{ text-align: center; padding: 20px 0 10px; }}
.header h1 {{ font-size: 24px; color: #38bdf8; }}
.header .sub {{ color: #94a3b8; font-size: 14px; margin-top: 5px; }}
.section {{ margin: 20px 0; }}
.section h2 {{ font-size: 18px; color: #38bdf8; border-bottom: 1px solid #1e293b; padding-bottom: 8px; margin-bottom: 15px; }}
.pred-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
@media (max-width: 900px) {{ .pred-grid {{ grid-template-columns: 1fr; }} }}
.pred-card {{ background: #1e293b; border-radius: 10px; padding: 15px; }}
.pred-card h3 {{ font-size: 16px; color: #f1f5f9; margin-bottom: 10px; }}
.pred-card .issue {{ color: #38bdf8; font-weight: normal; font-size: 14px; }}
.pred-card .time {{ color: #64748b; font-size: 12px; float: right; }}
.pred-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
.pred-table th {{ background: #334155; color: #94a3b8; padding: 6px 8px; text-align: center; }}
.pred-table td {{ padding: 5px 8px; text-align: center; border-bottom: 1px solid #1e293b; }}
.pred-table tr:hover {{ background: #334155; }}
.pred-table .rank {{ color: #64748b; width: 30px; }}
.pred-table .num {{ font-weight: bold; color: #fbbf24; font-size: 15px; }}
.pred-table .score {{ color: #34d399; font-weight: bold; }}
.compare-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
.compare-card {{ background: #1e293b; border-radius: 10px; padding: 15px; text-align: center; }}
.compare-card h3 {{ margin-bottom: 10px; }}
.draw-number {{ display: flex; justify-content: center; gap: 10px; margin: 15px 0; }}
.draw-number span {{ background: #dc2626; color: white; width: 50px; height: 50px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center; font-size: 24px; font-weight: bold; }}
.hit-info {{ text-align: left; font-size: 14px; margin-top: 10px; }}
.hit-info div {{ padding: 3px 0; }}
.kl8-card {{ background: #1e293b; border-radius: 10px; padding: 15px; margin-bottom: 15px; }}
.kl8-play4 {{ background: #7c3aed; color: white; padding: 3px 10px; border-radius: 12px; font-weight: bold; margin: 0 2px; }}
.metrics-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-top: 10px; }}
.metric {{ text-align: center; }}
.metric .label {{ display: block; font-size: 12px; color: #64748b; }}
.metric .value {{ font-size: 18px; font-weight: bold; color: #f1f5f9; }}
.positive {{ color: #34d399 !important; }}
.negative {{ color: #ef4444 !important; }}
.review-table {{ width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 15px; }}
.review-table th {{ background: #334155; color: #94a3b8; padding: 8px; text-align: center; }}
.review-table td {{ padding: 6px 8px; text-align: center; border-bottom: 1px solid #1e293b; }}
.empty {{ color: #64748b; font-style: italic; padding: 20px; text-align: center; }}
.footer {{ text-align: center; color: #475569; font-size: 12px; padding: 30px 0 10px; }}
</style>
</head>
<body>
<div class="header">
    <h1>📊 彩票分析仪表板</h1>
    <div class="sub">生成时间: {now}</div>
</div>

{compare_html}

<div class="section">
    <h2>🎯 排列三 / 福彩3D 预测</h2>
    <div class="pred-grid">
        {pls_pred}
        {d3_pred}
    </div>
</div>

{kl8_html}
{review_html}
{error_html}

<div class="footer">
    ⚠️ 彩票具有随机性，以上仅供数据分析与复盘参考，不构成投注建议。
</div>
</body>
</html>'''


def main():
    parser = argparse.ArgumentParser(description='生成可视化仪表板')
    parser.add_argument('--open', action='store_true', help='生成后自动打开浏览器')
    args = parser.parse_args()

    print('正在加载数据...')
    data = load_all_data()

    print('正在生成仪表板...')
    html = generate_html(data)

    output_path = OUTPUT_DIR / 'dashboard.html'
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding='utf-8')
    print(f'✅ 仪表板已生成: {output_path}')

    if args.open:
        webbrowser.open(str(output_path))


if __name__ == '__main__':
    main()
