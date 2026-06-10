#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
彩票分析每日一键运行脚本
==========================
支持排列三 + 福彩3D 全流程：
  数据更新 → 特征工程 → 统计引擎 → 复盘对比 → 评分预测 → 可视化

用法：
    python run_daily.py                     # 跑两个彩种（默认Top-10，仅预测）
    python run_daily.py --mode review       # 仅复盘
    python run_daily.py --mode all          # 复盘 + 预测（开奖后一条命令搞定）
    python run_daily.py pls --mode all      # 仅排列三，复盘+预测
    python run_daily.py --top-k 10          # 推荐10注
    python run_daily.py pls --top-k 20 --exclude-recent 3
"""

import argparse
import json
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


def pipeline(lottery, label, skiprows=0, top_k=30, exclude_recent=5,
             strategy='default', mode='predict'):
    """单个彩种的完整流水线，任一步骤失败则停止

    mode:
      predict — 仅预测（默认）
      review  — 仅复盘
      all     — 复盘 + 预测（开奖后一条命令搞定）
    """
    ensure_seed_data(lottery)
    raw_file = f"data/raw/{lottery}_raw.csv"
    feat_file = f"data/processed/{lottery}_feat.csv"

    py = sys.executable
    data_fresh = True  # 追踪数据是否为最新

    # 1. 数据更新
    if not run_cmd(
        [py, "scripts/data_fetcher.py", "--lottery", lottery],
        f"{label} 数据更新",
        timeout=180,
    ):
        data_fresh = False
        logger.warning(f"⚠️ {label} 数据更新失败，继续使用现有数据（预测基于旧数据）")

    # 2. 特征工程
    feat_cmd = [py, "scripts/feature_engine.py", "--input", raw_file,
                "--output", feat_file, "--lottery", lottery, "--force"]
    if lottery == 'pls':
        feat_cmd.extend(["--skiprows", str(skiprows)])
    if not run_cmd(feat_cmd, f"{label} 特征工程", timeout=300):
        return False

    # 3. 统计引擎
    if not run_cmd(
        [py, "scripts/stats_engine.py", "--lottery", lottery],
        f"{label} 统计引擎",
        timeout=120,
    ):
        return False

    # ── 复盘步骤（review/all 模式）──
    if mode in ('review', 'all'):
        # 4a. 多策略对比复盘
        available_strategies = ['default']
        pred_dir = BASE / 'output' / 'predictions'
        for st in ['conservative', 'diversity', 'auto_tuned', 'enhanced', 'ensemble']:
            suffix = '' if st == 'default' else f'_{st}'
            if (pred_dir / f'latest_{lottery}{suffix}.json').exists():
                available_strategies.append(st)

        for st in available_strategies:
            run_cmd(
                [py, "scripts/compare_result.py", "--lottery", lottery, "--strategy", st],
                f"{label} 复盘对比 [{st}]",
                timeout=60,
            )

    # ── 预测步骤（predict/all 模式）──
    if mode in ('predict', 'all'):
        # 4b. 评分预测（支持多策略）
        strategy_configs = {
            'default':      {'weights': None,                    'name': ''},
            'conservative': {'weights': 'rules/scoring_weights_conservative.yaml', 'name': 'conservative'},
            'diversity':    {'weights': 'rules/scoring_weights_diversity.yaml',    'name': 'diversity'},
            'auto_tuned':   {'weights': f'rules/scoring_weights_auto_{lottery}.yaml', 'name': 'auto_tuned'},
            'enhanced':     {'weights': None,                    'name': 'enhanced'},
        }

        all_strategies = ['default', 'conservative', 'diversity', 'auto_tuned', 'enhanced', 'coverage']
        strategies = [strategy] if strategy != 'all' else all_strategies

        for st in strategies:
            cfg = strategy_configs[st]
            # enhanced 策略使用独立的增强预测器
            if st == 'enhanced':
                enhanced_cmd = [py, "scripts/enhanced_predictor.py", "--lottery", lottery,
                               "--top-k", str(top_k), "--exclude-recent", str(exclude_recent)]
                desc = f"{label} 增强预测 [enhanced] (top-k={top_k})"
                if not run_cmd(enhanced_cmd, desc, timeout=120):
                    if strategy != 'all':
                        return data_fresh
                continue
            # coverage 策略使用覆盖率优化器
            if st == 'coverage':
                coverage_cmd = [py, "scripts/coverage_optimizer.py", "--lottery", lottery,
                                "--strategy", "balanced", "--top-k", str(top_k)]
                desc = f"{label} 覆盖率优化 [coverage] (top-k={top_k})"
                if not run_cmd(coverage_cmd, desc, timeout=120):
                    if strategy != 'all':
                        return data_fresh
                continue
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
                    return data_fresh

        # 5. 策略融合（共识投票加权，生成 ensemble 预测）
        if strategy == 'all':
            run_cmd(
                [py, "scripts/build_ensemble_predictions.py", "--lottery", lottery],
                f"{label} 策略融合 [ensemble]",
                timeout=60,
            )

    # 6. 可视化（可选依赖，失败不影响预测）
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

    # 写入流水线状态
    status_dir = BASE / 'output' / 'status'
    status_dir.mkdir(parents=True, exist_ok=True)
    pipeline_status = {
        'lottery': lottery,
        'mode': mode,
        'data_fresh': data_fresh,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    with open(status_dir / f'{lottery}_pipeline.json', 'w', encoding='utf-8') as f:
        json.dump(pipeline_status, f, ensure_ascii=False, indent=2)

    return data_fresh


def main():
    parser = argparse.ArgumentParser(description='彩票分析每日一键运行')
    parser.add_argument('lotteries', nargs='*', default=['pls', 'd3'],
                        help='彩种：pls d3（默认全部）')
    parser.add_argument('--mode', choices=['predict', 'review', 'all'],
                        default='predict',
                        help='运行模式：predict=仅预测 / review=仅复盘 / all=复盘+预测（默认predict）')
    parser.add_argument('--top-k', type=int, default=10,
                        help='推荐注数（默认10）')
    parser.add_argument('--exclude-recent', type=int, default=5,
                        help='排除近N期已出号码（默认5）')
    parser.add_argument('--strategy', choices=['default', 'conservative', 'diversity', 'auto_tuned', 'enhanced', 'coverage', 'all'],
                        default='default',
                        help='评分策略：default/conservative/diversity/auto_tuned/enhanced/all（默认default）')
    args = parser.parse_args()

    py = sys.executable
    today = datetime.now().strftime('%Y-%m-%d %H:%M')
    mode_label = {'predict': '仅预测', 'review': '仅复盘', 'all': '复盘+预测'}
    logger.info(f"{'='*50}")
    logger.info(f"  彩票分析每日任务  {today}")
    logger.info(f"  模式: {mode_label[args.mode]} | 策略: {args.strategy} | Top-K: {args.top_k}")
    logger.info(f"{'='*50}")

    lotteries = {
        'pls': ('排列三', 0),
        'd3': ('福彩3D', 0),
    }

    stale_lotteries = []
    for key in args.lotteries:
        if key in lotteries:
            label, skip = lotteries[key]
            logger.info(f"")
            logger.info(f"── {label} ──")
            fresh = pipeline(key, label, skip, top_k=args.top_k,
                             exclude_recent=args.exclude_recent,
                             strategy=args.strategy, mode=args.mode)
            if fresh is False:
                stale_lotteries.append(label)

    # 复盘摘要（review/all 模式）
    if args.mode in ('review', 'all'):
        logger.info(f"")
        logger.info(f"── 复盘摘要 ──")
        run_cmd([py, "scripts/review_summary.py"], "复盘表现摘要", timeout=30)
        run_cmd([py, "scripts/metrics.py"], "命中率统计", timeout=30)

    logger.info(f"")
    logger.info(f"{'='*50}")
    if stale_lotteries:
        logger.warning(f"  ⚠️ 数据未更新: {', '.join(stale_lotteries)}（预测基于旧数据）")
    logger.info(f"  ✅ 全部任务完成！")
    if args.mode in ('predict', 'all'):
        logger.info(f"  预测文件: {BASE / 'output' / 'predictions/'}")
    if args.mode in ('review', 'all'):
        logger.info(f"  复盘报告: {BASE / 'output' / 'reports/'}")
        logger.info(f"  复盘总表: {BASE / 'output' / 'reviews/'}")
    logger.info(f"  可视化: python run_web.py → http://127.0.0.1:8000")
    logger.info(f"{'='*50}")


if __name__ == '__main__':
    main()
