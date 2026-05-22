#!/usr/bin/env python3
"""快乐8 共享工具函数。"""


def parse_kl8_numbers(value, *, strict=False):
    """
    解析快乐8号码字段。
    支持：'01 02 03'、'01,02,03'、list[int]。
    strict=True 时遇到坏值直接 raise；默认跳过坏值。

    返回 list[int]。
    """
    if value is None:
        return []

    if isinstance(value, list):
        raw_parts = value
    else:
        text = str(value).replace(",", " ").replace("，", " ").strip()
        raw_parts = text.split()

    nums = []
    bad = []

    for x in raw_parts:
        try:
            n = int(str(x).strip())
            if 1 <= n <= 80:
                nums.append(n)
            else:
                bad.append(x)
        except (ValueError, TypeError):
            bad.append(x)

    if strict and bad:
        raise ValueError(f"快乐8号码存在非法值: {bad}")

    return nums
