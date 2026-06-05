#!/usr/bin/env python3
"""push_formatter 单元测试"""
import pytest


def test_calc_sum():
    from push_formatter import calc_sum
    assert calc_sum("123") == 6
    assert calc_sum("000") == 0
    assert calc_sum("999") == 27


def test_calc_span():
    from push_formatter import calc_span
    assert calc_span("123") == 2
    assert calc_span("000") == 0
    assert calc_span("089") == 9


def test_calc_shape():
    from push_formatter import calc_shape
    assert calc_shape("111") == "豹子"
    assert calc_shape("112") == "组三"
    assert calc_shape("123") == "组六"
    assert calc_shape("000") == "豹子"


def test_normalize_strategy_name():
    from push_formatter import normalize_strategy_name
    assert normalize_strategy_name("default") == "标准"
    assert normalize_strategy_name("conservative") == "稳健"
    assert normalize_strategy_name("diversity") == "多样性"
    assert normalize_strategy_name("ensemble") == "融合策略"
    assert normalize_strategy_name("unknown") == "unknown"


def test_safe_int():
    from push_formatter import safe_int
    assert safe_int(None) == 0
    assert safe_int("") == 0
    assert safe_int("nan") == 0
    assert safe_int("42") == 42
    assert safe_int("3.7") == 3
    assert safe_int("abc", default=-1) == -1


def test_top_digits():
    from push_formatter import top_digits
    recommends = [
        {"号码": "123"},
        {"号码": "145"},
        {"号码": "167"},
    ]
    result = top_digits(recommends, 3)
    assert "1" in result  # 出现 3 次
    assert len(result) == 3


def test_check_group_hit():
    from push_formatter import check_group_hit
    hit, missing = check_group_hit("12345", "123")
    assert hit is True
    assert missing == []

    hit, missing = check_group_hit("12345", "126")
    assert hit is False
    assert "6" in missing


def test_extract_top10():
    from push_formatter import extract_top10
    data = {
        "摘要": {"Top10号码": ["001", "002", "003", "004", "005",
                              "006", "007", "008", "009", "010"]},
        "推荐": [],
    }
    result = extract_top10(data)
    assert len(result) == 10
    assert result[0] == "001"


def test_extract_top10_fallback_to_recommends():
    from push_formatter import extract_top10
    data = {
        "摘要": {},
        "推荐": [
            {"号码": "123"},
            {"号码": "456"},
        ],
    }
    result = extract_top10(data)
    assert len(result) == 2
    assert result[0] == "123"
