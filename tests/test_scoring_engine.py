#!/usr/bin/env python3
"""scoring_engine 单元测试"""
import pytest


def test_load_weights_default():
    from scoring_engine import load_weights
    weights, params = load_weights()
    assert '和值' in weights
    assert '跨度' in weights
    assert '形态' in weights
    assert weights['和值'] > 0
    assert weights['跨度'] > 0


def test_generate_all_count():
    from scoring_engine import generate_all
    df = generate_all()
    assert len(df) == 1000
    assert '红球1' in df.columns
    assert '和值' in df.columns
    assert '形态' in df.columns
    assert 'group_number' in df.columns


def test_generate_all_cached():
    from scoring_engine import generate_all, _cached_all_df
    # 第一次调用填充缓存
    df1 = generate_all()
    assert _cached_all_df is not None
    # 返回的是副本，修改不影响缓存
    df1.iloc[0, 0] = 999
    df2 = generate_all()
    assert df2.iloc[0, 0] != 999


def test_score_number_basic():
    from scoring_engine import score_number, load_weights
    weights, params = load_weights()
    # 构造一个简单的 row
    row = {
        '和值': 13, '跨度': 5, '形态': '组六',
        '红球1': 4, '红球2': 5, '红球3': 4,
        '0路数': 1, '1路数': 1, '2路数': 1,
        '奇数': 2, '大号': 2,
        'group_number': '445',
    }
    stats = {
        '窗口': {
            '近30期': {'和值频率': {}, '跨度频率': {}, '当前遗漏': {}, '平均遗漏': 5},
            '近5期': {'和值频率': {}, '跨度频率': {}},
        }
    }
    theory = {
        '和值': {i: 100 for i in range(28)},
        '跨度': {i: 100 for i in range(10)},
    }
    result = score_number(row, stats, theory, weights, params)
    assert '总分' in result
    assert '明细' in result
    assert result['总分'] >= 0
    assert result['总分'] <= 100


def test_generate_predictions_returns_top_k():
    from scoring_engine import generate_all, generate_predictions, load_weights
    import json
    from pathlib import Path

    weights, params = load_weights()
    all_df = generate_all()

    # 使用默认 stats
    stats = {
        '窗口': {
            '近30期': {'和值频率': {}, '跨度频率': {}, '当前遗漏': {}, '平均遗漏': 5,
                      '形态_组六_pct': 70, '形态_组三_pct': 27, '形态_豹子_pct': 1},
            '近5期': {'和值频率': {}, '跨度频率': {}},
        },
        '理论分布': {},
    }
    theory = {
        '和值': {i: 100 for i in range(28)},
        '跨度': {i: 100 for i in range(10)},
    }

    top_k, all_scored = generate_predictions(
        all_df, stats, theory, weights, params, top_k=10)
    assert len(top_k) == 10
    assert len(all_scored) == 1000 - 10  # 默认排除豹子
    # 排序正确：第一个分数 >= 最后一个
    assert top_k[0]['总分'] >= top_k[-1]['总分']


def test_generate_predictions_exclude_set():
    from scoring_engine import generate_all, generate_predictions, load_weights

    weights, params = load_weights()
    all_df = generate_all()
    stats = {
        '窗口': {
            '近30期': {'和值频率': {}, '跨度频率': {}, '当前遗漏': {}, '平均遗漏': 5,
                      '形态_组六_pct': 70, '形态_组三_pct': 27, '形态_豹子_pct': 1},
            '近5期': {'和值频率': {}, '跨度频率': {}},
        },
        '理论分布': {},
    }
    theory = {
        '和值': {i: 100 for i in range(28)},
        '跨度': {i: 100 for i in range(10)},
    }

    exclude = {(1, 2, 3), (4, 5, 6)}
    top_k, all_scored = generate_predictions(
        all_df, stats, theory, weights, params,
        top_k=10, exclude_set=exclude)

    # 排除的号码不应出现在结果中
    result_nums = {tuple(int(c) for c in item['号码']) for item in top_k}
    assert (1, 2, 3) not in result_nums
    assert (4, 5, 6) not in result_nums


def test_apply_diversity_group_penalty():
    from scoring_engine import apply_diversity

    scored = [
        {'号码': '123', 'group_number': '123', '总分': 80, '跨度值': 2, '组选': '123', '评分明细': {}},
        {'号码': '132', 'group_number': '123', '总分': 70, '跨度值': 2, '组选': '123', '评分明细': {}},
        {'号码': '456', 'group_number': '456', '总分': 75, '跨度值': 2, '组选': '456', '评分明细': {}},
    ]
    weights = {'多样性': 10}
    params = {'group_penalty': 5, 'span_spread': 8}

    result = apply_diversity(scored, weights, params)
    # 132 (不是组选123中最高分) 应该被惩罚
    item_132 = next(c for c in result if c['号码'] == '132')
    item_123 = next(c for c in result if c['号码'] == '123')
    assert item_132['总分'] < item_123['总分']
