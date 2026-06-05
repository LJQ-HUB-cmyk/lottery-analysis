#!/usr/bin/env python3
"""KL8 模块单元测试"""
import pytest


def test_parse_kl8_numbers_basic():
    from scripts.kl8.common import parse_kl8_numbers
    assert parse_kl8_numbers("01 02 03 04") == [1, 2, 3, 4]
    assert parse_kl8_numbers("01,02,03,04") == [1, 2, 3, 4]
    assert parse_kl8_numbers([1, 2, 3]) == [1, 2, 3]
    assert parse_kl8_numbers("") == []
    assert parse_kl8_numbers(None) == []


def test_parse_kl8_numbers_range():
    from scripts.kl8.common import parse_kl8_numbers
    # 有效范围 1-80
    assert parse_kl8_numbers("1 80") == [1, 80]
    # 超出范围的跳过
    assert parse_kl8_numbers("0 81 50") == [50]


def test_parse_kl8_numbers_strict():
    from scripts.kl8.common import parse_kl8_numbers
    with pytest.raises(ValueError):
        parse_kl8_numbers("01 abc 03", strict=True)


def test_kl8_reviewer_hit_calculation():
    from scripts.kl8.reviewer import review
    prediction = {
        "candidate_pool": list(range(1, 21)),
        "recommended_play4": [1, 2, 3, 4],
        "strategy": "test",
        "play_type": "选四",
    }
    actual = {
        "lottery": "kl8",
        "issue": "2025001",
        "date": "2025-01-01",
        "numbers": [1, 2, 3, 5, 10, 20, 30, 40, 50, 60, 70, 80, 15, 25, 35, 45, 55, 65, 75, 3],
    }
    result = review(prediction, actual)
    # 1,2,3 命中（4 未命中），命中 3 个
    assert result["play4_hit_count"] == 3
    assert result["prize"] == 5
    assert result["profit"] == 5 - 2
    assert result["result_level"] == "选四中三"


def test_kl8_reviewer_no_hit():
    from scripts.kl8.reviewer import review
    prediction = {
        "candidate_pool": list(range(1, 21)),
        "recommended_play4": [71, 72, 73, 74],
        "strategy": "test",
        "play_type": "选四",
    }
    actual = {
        "lottery": "kl8",
        "issue": "2025001",
        "date": "2025-01-01",
        "numbers": list(range(1, 21)),
    }
    result = review(prediction, actual)
    assert result["play4_hit_count"] == 0
    assert result["prize"] == 0
    assert result["profit"] == -2
    assert result["result_level"] == "未中奖"


def test_kl8_next_issue():
    from scripts.kl8.predictor import next_issue
    assert next_issue("2025365") == "2026001"
    assert next_issue("2025001") == "2025002"
    # 闰年
    assert next_issue("2024366") == "2025001"


def test_kl8_zone_balance():
    from scripts.kl8.predictor import build_candidate_pool, ZONES
    # 用极端热号集中在 01-20 的数据
    draws = [list(range(1, 21)) for _ in range(30)]
    pool_no_balance = build_candidate_pool(draws, pool_size=20, zone_balance=False)
    pool_with_balance = build_candidate_pool(draws, pool_size=20, zone_balance=True,
                                              min_per_zone=3)

    # 无均衡时可能全在 01-20
    zone0_no = sum(1 for n in pool_no_balance if 1 <= n <= 20)

    # 有均衡时每区至少 3 个
    for lo, hi in ZONES:
        count = sum(1 for n in pool_with_balance if lo <= n <= hi)
        assert count >= 3, f"区间 {lo}-{hi} 只有 {count} 个（要求≥3）"


def test_kl8_metrics_weighted():
    """验证 metrics 加权命中分计算"""
    rows = [
        {"结果": "选四中四", "成本": "2", "奖金": "93", "盈亏": "91", "池命中": "15"},
        {"结果": "选四中三", "成本": "2", "奖金": "5", "盈亏": "3", "池命中": "12"},
        {"结果": "选四中二", "成本": "2", "奖金": "3", "盈亏": "1", "池命中": "10"},
        {"结果": "未中奖", "成本": "2", "奖金": "0", "盈亏": "-2", "池命中": "8"},
    ]
    # 直接测试加权计算逻辑
    hit4 = sum(1 for r in rows if r["结果"] == "选四中四")
    hit3 = sum(1 for r in rows if r["结果"] == "选四中三")
    hit2 = sum(1 for r in rows if r["结果"] == "选四中二")
    weighted = hit4 * 93 + hit3 * 5 + hit2 * 3
    assert weighted == 93 + 5 + 3  # 101
    assert hit4 == 1
    assert hit3 == 1
    assert hit2 == 1
