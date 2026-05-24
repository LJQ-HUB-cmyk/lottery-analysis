#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
彩票分析每日一键运行脚本
==========================
支持排列三 + 福彩3D 全流程：
  数据更新 → 特征工程 → 统计引擎 → 评分预测 → 可视化

用法：
    python run_daily.py                     # 跑两个彩种（默认Top-30）
    python run_daily.py pls                 # 只跑排列三
    python run_daily.py d3                  # 只跑福彩3D
    python run_daily.py --top-k 10          # 推荐10注
    python run_daily.py pls --top-k 20 --exclude-recent 3
"""

import argparse
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

BASE = Path(__file__).resolve().parent


def run_cmd(cmd, desc, timeout=300):
    """执行命令并记录日志，返回是否成功"""
    logger.info(f"▶️  {desc}")
    logger.debug(f"   $ {' '.join(cmd)}")
    try:
        env = os.environ.copy()
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, cwd=str(BASE),
            text=True, encoding='utf-8', errors='replace',
            env=env,
        )
        if result.returncode == 0:
            logger.info(f"✅ {desc}")
            lines = [l for l in result.stdout.split('\n') if l.strip()]
            if lines:
                for line in lines[-2:]:
                    logger.info(f"   {line.strip()}")
            return True
        else:
            logger.error(f"❌ {desc} 失败")
            for line in result.stderr.strip().split('\n')[-5:]:
                logger.error(f"   {line}")
            return False
    except subprocess.TimeoutExpired:
        logger.error(f"⏰ {desc} 超时 ({timeout}s)")
        return False
    except Exception as e:
        logger.error(f"💥 {desc} 异常: {e}")
        return False


def ensure_seed_data(lottery):
    """如果 raw 文件不存在，从 archived 初始化并标准化为标准三列格式"""
    raw_file = BASE / f"data/raw/{lottery}_raw.csv"
    archived_file = BASE / f"data/archived/{lottery}_history.csv"

    if raw_file.exists() or not archived_file.exists():
        return

    raw_file.parent.mkdir(parents=True, exist_ok=True)

    # 读取归档并自动识别格式（标准三列 or 旧KittenCN格式）
    for skiprows in (0, 2):
        try:
            df = pd.read_csv(archived_file, dtype=str, encoding='utf-8-sig', skiprows=skiprows,
                             on_bad_lines='skip')
        except Exception:
            continue
        cols = set(str(c) for c in df.columns)

        # 标准格式：已迁移完毕
        if {'期号', '日期', '号码'}.issubset(cols):
            df = df[['期号', '日期', '号码']].copy()
            break

        # 旧 KittenCN 格式：期数,红球_1,红球_2,红球_3
        if {'期数', '红球_1', '红球_2', '红球_3'}.issubset(cols):
            out = pd.DataFrame()
            out['期号'] = df['期数'].astype(str).str.extract(r'(\d+)', expand=False)
            out['号码'] = (
                df['红球_1'].astype(str).str.extract(r'(\d)', expand=False).fillna('') +
                df['红球_2'].astype(str).str.extract(r'(\d)', expand=False).fillna('') +
                df['红球_3'].astype(str).str.extract(r'(\d)', expand=False).fillna('')
            )
            out['日期'] = ''
            out = out[out['期号'].notna() & out['号码'].str.match(r'^\d{3}$')]
            df = out[['期号', '日期', '号码']].copy()
            break
    else:
        logger.error(f"无法识别种子数据格式: {archived_file}")
        return

    df.to_csv(raw_file, index=False, encoding='utf-8-sig')
    logger.info(f"已从归档数据初始化并标准化: {raw_file} ({len(df)} 条)")


def pipeline(lottery, label, skiprows=0, top_k=30, exclude_recent=5, strategy='default'):
    """单个彩种的完整流水线，任一步骤失败则停止"""
    ensure_seed_data(lottery)
    raw_file = f"data/raw/{lottery}_raw.csv"
    feat_file = f"data/processed/{lottery}_feat.csv"

    py = sys.executable

    # 1. 数据更新
    if not run_cmd(
        [py, "scripts/data_fetcher.py", "--lottery", lottery],
        f"{label} 数据更新",
        timeout=180,
    ):
        logger.warning(f"⚠️ {label} 数据更新失败，继续使用现有数据")

    # 2. 特征工程
    feat_cmd = [py, "scripts/feature_engine.py", "--input", raw_file,
                "--output", feat_file, "--lottery", lottery, "--force"]
    if lottery == 'pls':
        feat_cmd.extend(["--skiprows", str(skiprows)])
    if not run_cmd(feat_cmd, f"{label} 特征工程", timeout=300):
        return

    # 3. 统计引擎
    if not run_cmd(
        [py, "scripts/stats_engine.py", "--lottery", lottery],
        f"{label} 统计引擎",
        timeout=120,
    ):
        return

    # 4. 评分预测（支持多策略）
    strategy_configs = {
        'default':      {'weights': None,                    'name': ''},
        'conservative': {'weights': 'rules/scoring_weights_conservative.yaml', 'name': 'conservative'},
        'diversity':    {'weights': 'rules/scoring_weights_diversity.yaml',    'name': 'diversity'},
        'auto_tuned':   {'weights': f'rules/scoring_weights_auto_{lottery}.yaml', 'name': 'auto_tuned'},
    }

    strategies = [strategy] if strategy != 'all' else ['default', 'conservative', 'diversity', 'auto_tuned']

    for st in strategies:
        cfg = strategy_configs[st]
        wpath = Path(cfg['weights']) if cfg['weights'] else None
        if wpath and not wpath.exists():
            print(f"  [SKIP] {st} 权重文件不存在: {wpath}", file=sys.stderr)
            continue
        score_cmd = [py, "scripts/scoring_engine.py", "--lottery", lottery,
                     "--top-k", str(top_k), "--exclude-recent", str(exclude_recent)]
        if cfg['weights']:
            score_cmd.extend(["--weights", cfg['weights']])
        if cfg['name']:
            score_cmd.extend(["--output-name", cfg['name']])
        desc = f"{label} 评分预测 [{st}] (top-k={top_k})"
        if not run_cmd(score_cmd, desc, timeout=120):
            if strategy != 'all':
                return

    # 5. 可视化（可选依赖，失败不影响预测）
    charts_dir = BASE / 'output' / 'charts'
    charts_dir.mkdir(parents=True, exist_ok=True)
    try:
        import matplotlib  # noqa: F401
        run_cmd(
            [py, "scripts/visualize.py", "--lottery", lottery, "--chart", "trend", "--output-format", "html"],
            f"{label} 可视化",
            timeout=120,
        )
    except ImportError:
        logger.info(f"   ℹ️ {label} 可视化跳过（matplotlib未安装）")


def main():
    parser = argparse.ArgumentParser(description='彩票分析每日一键运行')
    parser.add_argument('lotteries', nargs='*', default=['pls', 'd3'],
                        help='彩种：pls d3（默认全部）')
    parser.add_argument('--top-k', type=int, default=30,
                        help='推荐注数（默认30）')
    parser.add_argument('--exclude-recent', type=int, default=5,
                        help='排除近N期已出号码（默认5）')
    parser.add_argument('--strategy', choices=['default', 'conservative', 'diversity', 'auto_tuned', 'all'],
                        default='default',
                        help='评分策略：default/conservative/diversity/auto_tuned/all（默认default）')
    args = parser.parse_args()

    today = datetime.now().strftime('%Y-%m-%d %H:%M')
    logger.info(f"{'='*50}")
    logger.info(f"  彩票分析每日任务  {today}")
    s_display = '全部三套' if args.strategy == 'all' else args.strategy
    logger.info(f"  策略: {s_display} | Top-K: {args.top_k} | 排除近{args.exclude_recent}期")
    logger.info(f"{'='*50}")

    lotteries = {
        'pls': ('排列三', 0),
        'd3': ('福彩3D', 0),
    }

    for key in args.lotteries:
        if key in lotteries:
            label, skip = lotteries[key]
            logger.info(f"")
            logger.info(f"── {label} ──")
            pipeline(key, label, skip, top_k=args.top_k,
                     exclude_recent=args.exclude_recent, strategy=args.strategy)

    logger.info(f"")
    logger.info(f"{'='*50}")
    logger.info(f"  ✅ 全部任务完成！")
    logger.info(f"  预测文件: {BASE / 'output' / 'predictions/'}")
    logger.info(f"{'='*50}")


if __name__ == '__main__':
    main()
