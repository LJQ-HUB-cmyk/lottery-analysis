#!/usr/bin/env python3
"""feature_engine 单元测试"""
import numpy as np
import pandas as pd
import pytest


def test_normalize_number():
    from feature_engine import normalize_number
    assert normalize_number("4 8 2") == "482"
    assert normalize_number("40") == "040"
    assert normalize_number("020") == "020"
    assert normalize_number("7,8,5") == "785"
    assert normalize_number("123") == "123"
    assert normalize_number("007") == "007"


def test_add_features_basic():
    from feature_engine import add_features
    df = pd.DataFrame({
        '红球1': [1, 4, 0],
        '红球2': [2, 5, 0],
        '红球3': [3, 6, 0],
    })
    result = add_features(df)
    # 和值
    assert result.iloc[0]['和值'] == 6
    assert result.iloc[1]['和值'] == 15
    assert result.iloc[2]['和值'] == 0
    # 跨度
    assert result.iloc[0]['跨度'] == 2
    assert result.iloc[1]['跨度'] == 2
    assert result.iloc[2]['跨度'] == 0
    # 形态
    assert result.iloc[0]['形态'] == '组六'
    assert result.iloc[2]['形态'] == '豹子'
    # number
    assert result.iloc[0]['number'] == '123'
    # group_number
    assert result.iloc[0]['group_number'] == '123'


def test_add_features_zusan():
    from feature_engine import add_features
    df = pd.DataFrame({
        '红球1': [1, 5],
        '红球2': [1, 6],
        '红球3': [2, 7],
    })
    result = add_features(df)
    assert result.iloc[0]['形态'] == '组三'
    assert result.iloc[1]['形态'] == '组六'
    assert result.iloc[0]['group_number'] == '112'


def test_add_missing_features():
    from feature_engine import add_missing_features
    # 3 行数据：第1行含0，第2/3行不含0
    df = pd.DataFrame({
        '红球1': [0, 5, 6],
        '红球2': [1, 6, 7],
        '红球3': [2, 7, 8],
    })
    result = add_missing_features(df)
    # 第一行 (0,1,2): 数字 0 出现 → 遗漏=0
    assert result.iloc[0]['遗漏_0'] == 0
    # 第二行 (5,6,7): 数字 0 未出现 → 遗漏=1
    assert result.iloc[1]['遗漏_0'] == 1
    # 第三行 (6,7,8): 数字 0 连续2期未出现 → 遗漏=2
    assert result.iloc[2]['遗漏_0'] == 2
    # 数字 5: 第一行未出现(遗漏=1)，第二行出现(遗漏=0)，第三行未出现(遗漏=1)
    assert result.iloc[0]['遗漏_5'] == 1
    assert result.iloc[1]['遗漏_5'] == 0
    assert result.iloc[2]['遗漏_5'] == 1
    # 检查分位遗漏列存在
    assert 'miss_bai_0' in result.columns
    assert 'miss_shi_0' in result.columns
    assert 'miss_ge_0' in result.columns
    # 检查平均/最大遗漏列存在
    assert 'avg_miss_全位' in result.columns
    assert 'max_miss_全位' in result.columns


def test_add_hot_cold():
    from feature_engine import add_hot_cold
    # 需要全部 10 个遗漏列 (遗漏_0 ~ 遗漏_9) + 分位遗漏列
    # 值选择：0=热(<=3), 5=温(>3且<=6), 10=冷(>6)
    data = {}
    for d in range(10):
        data[f'遗漏_{d}'] = [0, 10, 5]
        data[f'miss_bai_{d}'] = [0, 10, 5]
        data[f'miss_shi_{d}'] = [0, 10, 5]
        data[f'miss_ge_{d}'] = [0, 10, 5]
    df = pd.DataFrame(data)
    result = add_hot_cold(df, cold_threshold=6)
    assert len(result) == 3
    assert '冷热_0' in result.columns
    # 用 ord 比较避免 Windows 控制台编码问题
    # 遗漏_0=0 → 热(28909), 遗漏_0=10 → 冷(20919), 遗漏_0=5 → 温(28201)
    val0 = ord(str(result.iloc[0]['冷热_0']))
    val1 = ord(str(result.iloc[1]['冷热_0']))
    val2 = ord(str(result.iloc[2]['冷热_0']))
    assert val0 == 28909  # 热
    assert val1 == 20919  # 冷
    assert val2 == 28201  # 温
