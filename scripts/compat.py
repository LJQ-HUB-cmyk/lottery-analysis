#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""兼容性工具：处理新旧字段名过渡。"""


def get_hit_field(row: dict, field: str) -> str:
    """读取命中字段，兼容 Top10 和 Top30 两种字段名。

    field: '直选命中' 或 '组选命中'
    """
    val = row.get(f'{field}Top10', '')
    if val:
        return str(val)
    return str(row.get(f'{field}Top30', ''))
