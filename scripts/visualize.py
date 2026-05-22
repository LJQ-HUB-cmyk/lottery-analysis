#!/usr/bin/env python3
"""
可视化工具（可选）
=================
生成走势图、遗漏图、热力图，不参与核心决策。

输出两种格式：
- PNG: 静态图（matplotlib，适合快速查看）
- HTML: 交互式图（plotly，支持悬停/缩放，适合分享链接）

用法：
    python visualize.py --lottery pls
    python visualize.py --lottery d3 --chart heatmap
    python visualize.py --lottery pls --output-format html
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# 探测中文字体，优先使用系统已安装的
_CJK_FONTS = ['SimHei', 'Microsoft YaHei', 'WenQuanYi Micro Hei',
              'Noto Sans CJK SC', 'Source Han Sans SC',
              'PingFang SC', 'Hiragino Sans GB', 'sans-serif']
from matplotlib.font_manager import FontManager
_available = {f.name for f in FontManager().ttflist}
_found = next((f for f in _CJK_FONTS if f in _available), None)
if _found:
    plt.rcParams['font.sans-serif'] = [_found, 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False

# plotly 可选
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False


def plot_trend(df: pd.DataFrame, lottery_name: str, output_dir: Path, periods: int = 50):
    """和值/跨度走势图"""
    df = df.head(periods).sort_values('期数', ascending=True)
    
    fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)
    
    # 和值走势
    axes[0].plot(df['期数'].astype(str), df['和值'], 'b-o', markersize=3, linewidth=1)
    axes[0].axhline(y=df['和值'].mean(), color='r', linestyle='--', alpha=0.5, label=f"均值={df['和值'].mean():.1f}")
    axes[0].set_ylabel('和值')
    axes[0].set_title(f'{lottery_name} 和值走势 (近{periods}期)')
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)
    
    # 跨度走势
    axes[1].plot(df['期数'].astype(str), df['跨度'], 'g-s', markersize=3, linewidth=1)
    axes[1].axhline(y=df['跨度'].mean(), color='r', linestyle='--', alpha=0.5, label=f"均值={df['跨度'].mean():.1f}")
    axes[1].set_ylabel('跨度')
    axes[1].set_title('跨度走势')
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)
    
    # 形态分布
    morph_colors = {'组六': 'blue', '组三': 'orange', '豹子': 'red'}
    morph_series = df['形态'].map(morph_colors)
    axes[2].scatter(range(len(df)), [1]*len(df), c=morph_series, s=30, alpha=0.6)
    axes[2].set_yticks([])
    axes[2].set_ylabel('形态')
    axes[2].set_title('形态分布 (蓝=组六, 橙=组三, 红=豹子)')
    axes[2].set_xlabel('期号')
    
    plt.xticks(rotation=45, fontsize=8)
    plt.tight_layout()
    
    path = output_dir / f'{lottery_name}_trend.png'
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  ✅ 走势图: {path}")


def plot_missing(df: pd.DataFrame, lottery_name: str, output_dir: Path):
    """遗漏柱状图"""
    df = df.sort_values('期数', ascending=False).reset_index(drop=True)
    latest = df.iloc[0]
    digits = list(range(10))
    miss_values = [int(latest[f'遗漏_{d}']) for d in digits]
    
    colors = ['#4CAF50' if v <= 3 else '#FFC107' if v <= 8 else '#F44336' for v in miss_values]
    
    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.bar(digits, miss_values, color=colors, edgecolor='white', linewidth=1.2)
    
    for bar, v in zip(bars, miss_values):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                str(v), ha='center', va='bottom', fontsize=11)
    
    ax.axhline(y=sum(miss_values)/10, color='gray', linestyle='--', alpha=0.7, label=f"平均={sum(miss_values)/10:.1f}")
    ax.set_xlabel('数字')
    ax.set_ylabel('遗漏期数')
    ax.set_title(f'{lottery_name} 当前遗漏 (绿=热, 黄=温, 红=冷)')
    ax.set_xticks(digits)
    ax.legend()
    ax.grid(True, alpha=0.3, axis='y')
    
    plt.tight_layout()
    path = output_dir / f'{lottery_name}_missing.png'
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  ✅ 遗漏图: {path}")


def plot_heatmap(df: pd.DataFrame, lottery_name: str, output_dir: Path, periods: int = 100):
    """分位热力图"""
    df = df.sort_values('期数', ascending=False).reset_index(drop=True)
    df_window = df.head(periods)
    
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    
    for idx, (pos, col) in enumerate([('百位', '红球1'), ('十位', '红球2'), ('个位', '红球3')]):
        freq = df_window[col].value_counts().reindex(range(10), fill_value=0)
        freq_pct = freq / len(df_window) * 100
        
        ax = axes[idx]
        bars = ax.bar(range(10), freq_pct.values, color='steelblue', edgecolor='white')
        
        for bar, v in zip(bars, freq_pct.values):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                    f'{v:.1f}%', ha='center', va='bottom', fontsize=8)
        
        ax.axhline(y=10, color='r', linestyle='--', alpha=0.5, label='理论值(10%)')
        ax.set_xlabel('数字')
        ax.set_ylabel('出现频率 (%)')
        ax.set_title(f'{pos} (近{periods}期)')
        ax.set_xticks(range(10))
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3, axis='y')
    
    plt.suptitle(f'{lottery_name} 分位数字频率', fontsize=14)
    plt.tight_layout()
    path = output_dir / f'{lottery_name}_heatmap.png'
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  ✅ 热力图: {path}")


# ==========================================
#  Plotly 交互图（HTML 输出）
# ==========================================

def plotly_trend(df: pd.DataFrame, lottery_name: str, output_dir: Path, periods: int = 50):
    """Plotly 交互式走势图（和值 + 跨度）"""
    if not HAS_PLOTLY:
        print("  ⚠️  plotly 未安装，跳过 HTML 交互图")
        return

    df = df.head(periods).sort_values('期数', ascending=True)
    issues = df['期数'].astype(str).tolist()

    fig = make_subplots(rows=2, cols=1, subplot_titles=("和值走势", "跨度走势"))

    fig.add_trace(
        go.Scatter(x=issues, y=df['和值'], mode='lines+markers',
                    name='和值', line=dict(color='blue'), marker=dict(size=5)),
        row=1, col=1
    )
    fig.add_hline(y=df['和值'].mean(), line_dash="dash", line_color="red",
                  annotation_text=f"均值={df['和值'].mean():.1f}", row=1, col=1)

    fig.add_trace(
        go.Scatter(x=issues, y=df['跨度'], mode='lines+markers',
                    name='跨度', line=dict(color='green'), marker=dict(size=5)),
        row=2, col=1
    )
    fig.add_hline(y=df['跨度'].mean(), line_dash="dash", line_color="red",
                  annotation_text=f"均值={df['跨度'].mean():.1f}", row=2, col=1)

    fig.update_layout(
        title=f"{lottery_name} 走势（交互式，近{periods}期）",
        height=600, hovermode='x unified'
    )
    fig.update_xaxes(tickangle=45, tickfont=dict(size=9))

    path = output_dir / f'{lottery_name}_trend_interactive.html'
    fig.write_html(str(path))
    print(f"  ✅ 交互走势图: {path}")


def plotly_heatmap(df: pd.DataFrame, lottery_name: str, output_dir: Path, periods: int = 100):
    """Plotly 交互式热力图（分位数字频率）"""
    if not HAS_PLOTLY:
        return

    df_window = df.head(periods)
    positions = ['百位', '十位', '个位']
    cols = ['红球1', '红球2', '红球3']

    fig = make_subplots(rows=1, cols=3, subplot_titles=[f"{p} (近{periods}期)" for p in positions])

    for idx, (pos, col) in enumerate(zip(positions, cols), 1):
        freq = df_window[col].value_counts().reindex(range(10), fill_value=0)
        freq_pct = freq / len(df_window) * 100

        fig.add_trace(
            go.Bar(x=list(range(10)), y=freq_pct.values,
                    name=pos, text=[f"{v:.1f}%" for v in freq_pct.values],
                    textposition='outside', marker_color='steelblue'),
            row=1, col=idx
        )
        fig.add_hline(y=10, line_dash="dash", line_color="red",
                      annotation_text="理论值10%", row=1, col=idx)

    fig.update_layout(
        title=f"{lottery_name} 分位数字频率（交互式）",
        height=400, showlegend=False
    )

    path = output_dir / f'{lottery_name}_heatmap_interactive.html'
    fig.write_html(str(path))
    print(f"  ✅ 交互热力图: {path}")


def plotly_top_distribution(df: pd.DataFrame, lottery_name: str, output_dir: Path):
    """Plotly Top-50 推荐号码和值分布"""
    if not HAS_PLOTLY or '总分' not in df.columns:
        return

    top = df.nlargest(50, '总分')
    fig = go.Figure()
    fig.add_trace(go.Histogram(x=top['和值'], nbinsx=15,
                                marker_color='coral', name='Top50 推荐'))
    fig.update_layout(
        title=f"{lottery_name} Top50 推荐号码和值分布",
        xaxis_title="和值", yaxis_title="出现次数",
        height=400
    )

    path = output_dir / f'{lottery_name}_top_distribution.html'
    fig.write_html(str(path))
    print(f"  ✅ 推荐分布图: {path}")


# ==========================================
#  主流程
# ==========================================

def main():
    parser = argparse.ArgumentParser(description='可视化工具')
    parser.add_argument('--lottery', required=True, choices=['pls', 'd3'])
    parser.add_argument('--chart', choices=['trend', 'missing', 'heatmap', 'all'], default='all',
                        help='图表类型')
    parser.add_argument('--periods', type=int, default=50,
                        help='趋势图显示期数')
    parser.add_argument('--output-format', choices=['png', 'html', 'both'], default='both',
                        help='输出格式（默认两种都输出）')
    args = parser.parse_args()
    
    base_dir = Path(__file__).resolve().parent.parent
    lottery_name = '排列三' if args.lottery == 'pls' else '福彩3D'
    
    data_path = base_dir / 'data' / 'processed' / f'{args.lottery}_feat.csv'
    if not data_path.exists():
        print(f"[错误] 特征数据不存在: {data_path}")
        print(f"  请先运行: python run_daily.py {args.lottery}")
        sys.exit(1)
    df = pd.read_csv(data_path, encoding='utf-8-sig')
    
    output_dir = base_dir / 'output' / 'charts'
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"\n{'='*50}")
    print(f"  可视化 - {lottery_name}")
    print(f"{'='*50}")
    
    # PNG 静态图（matplotlib）
    if args.output_format in ('png', 'both'):
        if args.chart in ('trend', 'all'):
            plot_trend(df, lottery_name, output_dir, args.periods)
        if args.chart in ('missing', 'all'):
            plot_missing(df, lottery_name, output_dir)
        if args.chart in ('heatmap', 'all'):
            plot_heatmap(df, lottery_name, output_dir)
    
    # HTML 交互图（plotly）
    if args.output_format in ('html', 'both'):
        if args.chart in ('trend', 'all'):
            plotly_trend(df, lottery_name, output_dir, args.periods)
        if args.chart in ('heatmap', 'all'):
            plotly_heatmap(df, lottery_name, output_dir)
        if args.chart in ('all',):
            plotly_top_distribution(df, lottery_name, output_dir)


if __name__ == '__main__':
    main()
