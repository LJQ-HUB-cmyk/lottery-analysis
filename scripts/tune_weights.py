#!/usr/bin/env python3
"""
权重自动调优（随机搜索 + 贝叶斯优化）
===================================
用过去 N 期 walk-forward 回测，搜索最优权重组合。

用法：
    python scripts/tune_weights.py --lottery pls                        # 随机搜索
    python scripts/tune_weights.py --lottery pls --method optuna         # 贝叶斯优化(需pip install optuna)
    python scripts/tune_weights.py --lottery d3 --trials 50 --periods 80

前置条件：output/reviews/review_history.csv 至少积累 15 期复盘数据。
"""

import argparse
import json
import random
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import numpy as np
import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
HISTORY_PATH = BASE_DIR / 'output' / 'reviews' / 'review_history.csv'
MIN_REVIEW_ROWS = 15


# ── 搜索空间 ──────────────────────────────────────────

SEARCH_SPACE = {
    '和值':       (12, 22),
    '跨度':       (10, 20),
    '形态':       (8, 16),
    '冷热':       (5, 15),
    '多样性':     (5, 20),
    'cold_threshold':  (5, 9),
    'group_penalty':   (3, 12),
    'span_spread':     (5, 15),
    'overheat_high':   (40, 70),    # ×0.01
    'overheat_medium': (60, 90),    # ×0.01
}

FIXED = {'奇偶': 8, '大小': 8, '012路': 7, '遗漏': 7, '组三六偏向': 8}


# ── 权重采样 ──────────────────────────────────────────

def sample_weights():
    """从搜索空间随机采样一组权重"""
    w = {}
    for k, (lo, hi) in SEARCH_SPACE.items():
        if k.startswith('overheat'):
            w[k] = round(random.randint(lo, hi) / 100.0, 2)
        elif k.startswith('cold') or k.startswith('group') or k.startswith('span'):
            w[k] = random.randint(lo, hi)
        else:
            w[k] = random.randint(lo, hi)
    return w


def build_yaml(sample):
    """将采样结果写成 YAML 字符串"""
    return yaml.dump({
        'weights': {
            '和值': sample['和值'],
            '跨度': sample['跨度'],
            '形态': sample['形态'],
            '奇偶': FIXED['奇偶'],
            '大小': FIXED['大小'],
            '012路': FIXED['012路'],
            '冷热': sample['冷热'],
            '遗漏': FIXED['遗漏'],
            '组三六偏向': FIXED['组三六偏向'],
            '多样性': sample['多样性'],
        },
        'hot_cold': {
            'cold_threshold': sample['cold_threshold'],
            'hot_threshold': 3,
        },
        'diversity': {
            'group_penalty': sample['group_penalty'],
            'span_spread': sample['span_spread'],
        },
        'overheat_decay': {
            'high': sample['overheat_high'],
            'medium': sample['overheat_medium'],
        },
    }, allow_unicode=True, sort_keys=False)


# ── 评分 ──────────────────────────────────────────────

def composite_score(result: dict, periods: int, baseline: dict = None) -> float:
    """综合分 = 命中率加权 + ROI - 连未惩罚 + 止损护栏扣分。

    止损护栏：
    - ROI < 随机中位数 → -5
    - ROI < -10% → -10
    - 最大连续未中 > 20 → -3
    """
    sr = result.get('动态评分', {})
    direct = float(sr.get('直选命中', 0)) / periods
    group = float(sr.get('组选命中', 0)) / periods
    max_miss = int(sr.get('最大连续未中', 0))

    roi_str = sr.get('ROI', '0%').replace('%', '')
    try:
        roi = float(roi_str)
    except (ValueError, TypeError):
        roi = 0.0

    base = direct * 30 + group * 20 - max_miss * 2 + roi / 5
    penalty = 0

    if baseline and baseline.get('median') is not None:
        if roi < baseline['median']:
            penalty -= 5

    if roi < -10:
        penalty -= 10

    if max_miss > 20:
        penalty -= 3

    return base + penalty


def benchmark_random(df, theory, top_k, periods, lottery, seeds=100):
    """随机策略多 seed 基线：跑 N 次随机选号回测，输出 ROI 分布百分位。

    返回 dict: {mean, median, p25, p75, max_miss_p75, seeds, raw_rois}
    """
    try:
        from backtest import walk_forward
    except ImportError:
        print("  [错误] 无法导入 backtest 模块")
        return {'mean': 0, 'median': 0, 'p25': 0, 'p75': 0, 'max_miss_p75': 0, 'seeds': 0}

    rois = []
    max_misses = []
    print(f"  随机基线: 跑 {seeds} seed...", end="", flush=True)

    for s in range(seeds):
        bt = walk_forward(df, theory, top_k=top_k,
                          test_periods=periods, train_window=100,
                          lottery_code=lottery, weight_path=None,
                          seed=s)
        sr = bt.get('随机策略', bt.get('动态评分', {}))
        roi_str = sr.get('ROI', '0%').replace('%', '')
        try:
            roi = float(roi_str)
        except (ValueError, TypeError):
            roi = 0.0
        rois.append(roi)
        max_misses.append(int(sr.get('最大连续未中', 0)))

    rois = sorted(rois)
    n = len(rois)
    result = {
        'mean': round(sum(rois) / n, 1),
        'median': round(rois[n // 2], 1),
        'p25': round(rois[n // 4], 1),
        'p75': round(rois[3 * n // 4], 1),
        'max_miss_p75': int(sorted(max_misses)[3 * n // 4]),
        'seeds': seeds,
        'raw_rois': rois,
    }
    print(f" 中位数={result['median']}% P25={result['p25']}% P75={result['p75']}%")
    return result


def run_one_trial(sample, df, theory, top_k, periods, lottery, baseline=None):
    """执行单次回测试验，返回 (score, backtest_result)"""
    yaml_str = build_yaml(sample)
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.yaml', encoding='utf-8', delete=False
    ) as f:
        f.write(yaml_str)
        tmp_path = f.name
    try:
        from backtest import walk_forward
        bt = walk_forward(df, theory, top_k=top_k,
                          test_periods=periods, train_window=100,
                          lottery_code=lottery, weight_path=tmp_path)
        score = composite_score(bt, periods, baseline)
    except Exception:
        score = -999
        bt = {}
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return score, bt


def search_random(df, theory, args, baseline=None):
    """随机搜索"""
    random.seed(args.seed)
    np.random.seed(args.seed)

    results = []
    best_score = -999
    best_sample = None

    for i in range(args.trials):
        sample = sample_weights()
        score, bt = run_one_trial(sample, df, theory, args.top_k, args.periods,
                                   args.lottery, baseline)
        results.append({'trial': i + 1, 'weights': sample, 'score': score, 'backtest': bt})

        if score > best_score:
            best_score = score
            best_sample = sample

        if (i + 1) % 10 == 0:
            print(f"  进度: {i+1}/{args.trials} | 当前最佳分: {best_score:.1f}")

    return results, best_sample


def search_optuna(df, theory, args, baseline=None):
    """贝叶斯优化搜索（Optuna）"""
    import optuna

    def objective(trial):
        sample = {}
        for k, (lo, hi) in SEARCH_SPACE.items():
            if k.startswith('overheat'):
                sample[k] = round(trial.suggest_int(k, lo, hi) / 100.0, 2)
            else:
                sample[k] = trial.suggest_int(k, lo, hi)

        score, _ = run_one_trial(sample, df, theory, args.top_k, args.periods,
                                  args.lottery, baseline)
        return score

    study = optuna.create_study(
        direction='maximize',
        sampler=optuna.samplers.TPESampler(seed=args.seed),
    )

    print(f"  优化器: TPE (Tree-structured Parzen Estimator)")
    study.optimize(objective, n_trials=args.trials, show_progress_bar=False)

    # 转换为相同格式
    results = []
    for i, t in enumerate(study.trials):
        if t.state == optuna.trial.TrialState.COMPLETE:
            results.append({
                'trial': i + 1,
                'weights': {k: t.params.get(k, (lo+hi)//2) for k, (lo, hi) in SEARCH_SPACE.items()},
                'score': t.value,
                'backtest': {},
            })

    return results, study.best_params


# ── 主流程 ────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='权重自动调优（随机搜索 + 贝叶斯优化）')
    parser.add_argument('--lottery', required=True, choices=['pls', 'd3'],
                        help='彩种')
    parser.add_argument('--method', choices=['random', 'optuna'], default='random',
                        help='搜索方法：random(随机采样) / optuna(贝叶斯优化，需pip install optuna)')
    parser.add_argument('--trials', type=int, default=30,
                        help='搜索次数（默认30）')
    parser.add_argument('--periods', type=int, default=50,
                        help='回测期数（默认50）')
    parser.add_argument('--top-k', type=int, default=30,
                        help='推荐注数（默认30）')
    parser.add_argument('--seed', type=int, default=42,
                        help='随机种子（默认42）')
    parser.add_argument('--baseline-seeds', type=int, default=100,
                        help='随机基准采样次数（默认100）')
    parser.add_argument('--no-baseline', action='store_true',
                        help='跳过随机基准（加速测试）')
    args = parser.parse_args()

    # ── 门槛守卫 ──
    if not HISTORY_PATH.exists():
        print(f"\n  ⛔ 复盘总表不存在: {HISTORY_PATH}")
        print(f"  请先积累复盘数据。开奖后运行:")
        print(f"    python scripts/compare_result.py --lottery {args.lottery}")
        return

    hist = pd.read_csv(HISTORY_PATH, dtype=str, encoding='utf-8-sig')
    n_rows = len(hist)
    if n_rows < MIN_REVIEW_ROWS:
        print(f"\n  ⏳ 复盘数据不足: {n_rows} 期 < {MIN_REVIEW_ROWS} 期")
        print(f"  需要至少 {MIN_REVIEW_ROWS} 期复盘数据才能启动调参，当前还需 {MIN_REVIEW_ROWS - n_rows} 期。")
        print(f"  继续运行每日流程即可自动积累。")
        return

    # ── Optuna 可用性检查 ──
    if args.method == 'optuna':
        try:
            import optuna  # noqa: F401
        except ImportError:
            print(f"\n  ⛔ Optuna 未安装。请执行: pip install optuna")
            print(f"  或使用随机搜索: python scripts/tune_weights.py --lottery {args.lottery} --method random")
            return

    print(f"\n  ✅ 复盘数据达标: {n_rows} 期 >= {MIN_REVIEW_ROWS} 期，开始调参。")

    # ── 加载数据 ──
    lottery_name = '排列三' if args.lottery == 'pls' else '福彩3D'
    data_path = BASE_DIR / 'data' / 'processed' / f'{args.lottery}_feat.csv'
    if not data_path.exists():
        print(f"\n  [错误] 特征数据不存在: {data_path}")
        sys.exit(1)

    df = pd.read_csv(data_path, encoding='utf-8-sig')
    df = df.sort_values('期数', ascending=False).reset_index(drop=True)

    from stats_engine import generate_theoretical_distribution
    theory = generate_theoretical_distribution()

    # ── 随机基准 ──
    baseline = None
    if not args.no_baseline:
        print(f"\n{'='*60}")
        print(f"  📊 随机策略基准")
        print(f"{'='*60}")
        baseline = benchmark_random(df, theory, args.top_k, args.periods,
                                     args.lottery, args.baseline_seeds)
        print(f"  ROI: 均值={baseline['mean']}% 中位数={baseline['median']}% "
              f"P25={baseline['p25']}% P75={baseline['p75']}%")
        print(f"  最长连未 P75: {baseline['max_miss_p75']} 期")

    # ── 搜索 ──
    method_label = '贝叶斯优化(Optuna TPE)' if args.method == 'optuna' else '随机搜索'

    print(f"\n{'='*60}")
    print(f"  🔧 {lottery_name} 权重调优 [{method_label}]")
    print(f"{'='*60}")
    print(f"  数据: {len(df)} 期 | 回测窗口: {args.periods} 期 | 搜索: {args.trials} 次")
    if baseline:
        print(f"  止损: ROI<{baseline['median']}% -5 | ROI<-10% -10 | 连未>20 -3")
    print(f"  {'─'*60}")

    if args.method == 'optuna':
        results, best_sample = search_optuna(df, theory, args, baseline)
    else:
        results, best_sample = search_random(df, theory, args, baseline)

    # ── 排序输出 ──
    results.sort(key=lambda x: x['score'], reverse=True)

    print(f"\n  {'─'*60}")
    print(f"  🏆 Top-5 权重组合")
    print(f"  {'─'*60}")

    for rank, r in enumerate(results[:5], 1):
        w = r['weights']
        bt = r.get('backtest', {})
        sr = bt.get('动态评分', {})
        print(f"\n  #{rank} 综合分: {r['score']:.1f}")
        print(f"     和值={w['和值']} 跨度={w['跨度']} 形态={w['形态']} "
              f"冷热={w['冷热']} 多样性={w['多样性']}")
        print(f"     冷阈值={w['cold_threshold']} 组惩罚={w['group_penalty']} "
              f"跨促进={w['span_spread']} 过热={w['overheat_high']}/{w['overheat_medium']}")
        if sr:
            print(f"     直选{sr.get('直选命中','?')}/{args.periods} | "
                  f"组选{sr.get('组选命中','?')}/{args.periods} | "
                  f"ROI={sr.get('ROI','?')} | 最长连未={sr.get('最大连续未中','?')}期")

    # ── 上线门槛 ──
    deployable = True
    if best_sample:
        bt_best = (results[0].get('backtest', {}) if args.method != 'optuna'
                   else run_one_trial(best_sample, df, theory, args.top_k,
                                       args.periods, args.lottery, baseline)[1])
        sr_best = bt_best.get('动态评分', {})
        best_roi_str = sr_best.get('ROI', '0%').replace('%', '')
        try:
            best_roi = float(best_roi_str)
        except (ValueError, TypeError):
            best_roi = 0.0

        if baseline and best_roi < baseline['median']:
            print(f"\n  ⛔ 上线驳回: 最佳ROI({best_roi}%) < 随机中位数({baseline['median']}%)")
            deployable = False
        elif best_roi < -10:
            print(f"\n  ⛔ 上线驳回: ROI严重亏损 ({best_roi}%)")
            deployable = False

    # ── 保存最佳（候选人文件，不覆盖正式权重）──
    if best_sample:
        log_dir = BASE_DIR / 'output' / 'tuning'
        log_dir.mkdir(parents=True, exist_ok=True)

        # 候选权重 → output/tuning/（不写入 rules/，防止意外上线）
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        candidate_path = log_dir / f'scoring_weights_{args.lottery}_candidate_{ts}.yaml'
        candidate_yaml = build_yaml(best_sample)
        candidate_path.write_text(candidate_yaml, encoding='utf-8')
        status = '候选（待人工审核）' if deployable else '候选（不推荐上线）'
        print(f"\n  💾 候选权重已保存 [{status}]: {candidate_path}")

        # 搜索记录
        log_path = log_dir / f'{args.lottery}_tuning_{ts}.json'
        serializable = []
        for r in results[:10]:
            serializable.append({
                'trial': r['trial'],
                'score': r['score'],
                'weights': {k: (float(v) if isinstance(v, (int, float)) else v) for k, v in r['weights'].items()},
                'backtest_summary': {k: v for k, v in r.get('backtest', {}).get('动态评分', {}).items()},
            })
        if baseline:
            serializable.append({'random_baseline': baseline})
        with open(log_path, 'w', encoding='utf-8') as f:
            json.dump(serializable, f, ensure_ascii=False, indent=2)
        print(f"  💾 搜索记录: {log_path}")

    # ── 稳定性分析 ──
    if best_sample and len(df) >= args.periods * 2:
        print(f"\n  {'─'*60}")
        print(f"  🔍 参数稳定性分析")
        print(f"  {'─'*60}")

        best_yaml_str = build_yaml(best_sample)
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', encoding='utf-8', delete=False
        ) as f:
            f.write(best_yaml_str)
            tmp_path = f.name

        windows = [
            ('最近{}期'.format(args.periods), 0),
            ('往前{}-{}期'.format(args.periods + 1, args.periods * 2), args.periods),
        ]

        scores = []
        try:
            from backtest import walk_forward
            for wname, offset in windows:
                sub_df = df.iloc[offset:offset + args.periods].copy()
                if len(sub_df) < args.periods:
                    continue
                bt = walk_forward(sub_df, theory, top_k=args.top_k,
                                  test_periods=min(args.periods, len(sub_df) - 30),
                                  train_window=min(100, len(sub_df) // 2),
                                  lottery_code=args.lottery, weight_path=tmp_path)
                sc = composite_score(bt, min(args.periods, len(sub_df) - 30))
                scores.append((wname, sc, bt))
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        if len(scores) == 2:
            diff = abs(scores[0][1] - scores[1][1])
            avg = (scores[0][1] + scores[1][1]) / 2
            rel_change = diff / abs(avg) * 100 if abs(avg) > 0.01 else 0

            for wname, sc, _ in scores:
                print(f"  {wname}: 综合分 {sc:.1f}")

            if rel_change > 50:
                stability = '⚠️ 不稳定（差异 {:.0f}%）— 最佳权重可能过拟合'.format(rel_change)
                deployable = False
            elif rel_change > 25:
                stability = '🟡 一般（差异 {:.0f}%）— 权重尚可但不够稳健'.format(rel_change)
            else:
                stability = '✅ 稳定（差异 {:.0f}%）— 权重跨时间段表现一致'.format(rel_change)

            print(f"  → {stability}")

    # ── 最终结论 ──
    print(f"\n{'='*60}")
    if deployable and best_sample:
        print(f"  ✅ 候选权重通过全部检查，可人工审核后上线")
        print(f"  上线方法: cp {candidate_path} rules/scoring_weights_{args.lottery}_tuned.yaml")
    elif best_sample:
        print(f"  ⚠️  候选权重未通过安全检查，请勿上线")
    else:
        print(f"  ⛔ 未找到有效权重")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    main()
