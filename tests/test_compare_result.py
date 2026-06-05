#!/usr/bin/env python3
"""compare_result 单元测试"""
import pytest


def test_compare_direct_hit():
    from compare_result import compare
    predictions = [
        {'排名': 1, '号码': '123', 'group_number': '123', '和值': 6, '跨度': 2, '形态': '组六'},
        {'排名': 2, '号码': '456', 'group_number': '456', '和值': 15, '跨度': 2, '形态': '组六'},
    ]
    actual = {'开奖号码': '123', '组选': '123', '和值': 6, '跨度': 2, '形态': '组六'}
    rows = compare(predictions, actual)
    assert rows[0]['直选命中'] is True
    assert rows[1]['直选命中'] is False


def test_compare_group_hit():
    from compare_result import compare
    predictions = [
        {'排名': 1, '号码': '132', 'group_number': '123', '和值': 6, '跨度': 2, '形态': '组六'},
        {'排名': 2, '号码': '456', 'group_number': '456', '和值': 15, '跨度': 2, '形态': '组六'},
    ]
    actual = {'开奖号码': '123', '组选': '123', '和值': 6, '跨度': 2, '形态': '组六'}
    rows = compare(predictions, actual)
    assert rows[0]['直选命中'] is False
    assert rows[0]['组选命中'] is True


def test_compare_no_hit():
    from compare_result import compare
    predictions = [
        {'排名': 1, '号码': '789', 'group_number': '789', '和值': 24, '跨度': 2, '形态': '组六'},
    ]
    actual = {'开奖号码': '123', '组选': '123', '和值': 6, '跨度': 2, '形态': '组六'}
    rows = compare(predictions, actual)
    assert rows[0]['直选命中'] is False
    assert rows[0]['组选命中'] is False
    assert rows[0]['和值差'] == 18


def test_build_report_issue_mismatch_waiting():
    """预测期号 > 实际期号 → waiting_actual"""
    from compare_result import build_report
    pred_json = {'预测期号': 26200, '彩种': '排列三'}
    actual = {'期号': 26199, '开奖号码': '123', '组选': '123', '和值': 6, '跨度': 2, '形态': '组六'}
    rows = []
    report = build_report(pred_json, actual, rows)
    assert report.get('状态') == 'waiting_actual'


def test_build_report_issue_mismatch_error():
    """预测期号 < 实际期号 → 错误"""
    from compare_result import build_report
    pred_json = {'预测期号': 26198, '彩种': '排列三'}
    actual = {'期号': 26199, '开奖号码': '123', '组选': '123', '和值': 6, '跨度': 2, '形态': '组六'}
    rows = []
    report = build_report(pred_json, actual, rows)
    assert '错误' in report


def test_build_report_issue_type_consistency():
    """期号类型不一致（str vs int）应正确处理"""
    from compare_result import build_report
    # str 类型的预测期号 vs int 类型的实际期号
    pred_json = {'预测期号': '26199', '彩种': '排列三'}
    actual = {'期号': 26199, '开奖号码': '123', '组选': '123', '和值': 6, '跨度': 2, '形态': '组六'}
    rows = [
        {'排名': 1, '预测号码': '123', '直选命中': True, '组选命中': True,
         '和值差': 0, '跨度差': 0, '形态一致': True, '预测和值': 6, '预测跨度': 2, '预测形态': '组六'},
    ]
    report = build_report(pred_json, actual, rows)
    # 期号匹配时应正常生成报告（不进入 mismatch 分支）
    assert '错误' not in report
    assert '状态' not in report  # 不是 waiting_actual
    assert report.get('命中情况', {}).get('直选命中') is True
