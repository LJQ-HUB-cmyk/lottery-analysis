#!/usr/bin/env python3
"""快乐8多策略模块 —— 统一接口，便于回测对比"""
import random
from collections import Counter
from typing import Callable


def v0_random(pool_size: int = 4) -> list[int]:
    """随机基准：从1-80随机选N个"""
    return sorted(random.sample(range(1, 81), pool_size))


def v1_hot_cold(draws: list[list[int]], pool: list[int] = None,
                play_size: int = 4) -> list[int]:
    """热号+冷号混合：从候选池选近5期最活跃的N个"""
    if not draws:
        return v0_random(play_size)
    recent5 = Counter()
    target_pool = set(pool) if pool else set(range(1, 81))
    for nums in draws[:5]:
        for n in nums:
            if n in target_pool:
                recent5[n] += 1
    if recent5:
        return [n for n, _ in recent5.most_common(play_size)]
    return sorted(random.sample(list(target_pool), min(play_size, len(target_pool))))


def v2_zone_balance(draws: list[list[int]], play_size: int = 4) -> list[int]:
    """分区均衡：四个分区轮流向候选池各选1个近期活跃号码，直到达到 play_size"""
    if not draws:
        return v0_random(play_size)
    recent5 = Counter()
    for nums in draws[:5]:
        recent5.update(nums)
    zones = [(1, 20), (21, 40), (41, 60), (61, 80)]
    result = []
    # 按分区轮询取号，每轮各分区各取1个，直到满足 play_size
    per_zone = max(1, (play_size + 3) // 4)  # ceil(play_size / 4)
    for lo, hi in zones:
        candidates = [(n, recent5.get(n, 0)) for n in range(lo, hi + 1)]
        candidates.sort(key=lambda x: -x[1])
        taken = 0
        for n, _ in candidates:
            if n not in result:
                result.append(n)
                taken += 1
                if taken >= per_zone:
                    break
    return sorted(result[:play_size])


def v3_missing_rebound(draws: list[list[int]], play_size: int = 4,
                       max_miss: int = 10) -> list[int]:
    """遗漏回补：选近期遗漏中等(5-10期)的号码"""
    if not draws:
        return v0_random(play_size)
    missing = {}
    for num in range(1, 81):
        for i, nums in enumerate(draws):
            if num in nums:
                missing[num] = i
                break
        else:
            missing[num] = len(draws)
    # 选遗漏5-10期的号码（不太热也不太冷）
    mid_range = [n for n, m in missing.items() if 5 <= m <= max_miss]
    if len(mid_range) >= play_size:
        return sorted(random.sample(mid_range, play_size))
    # 不够则从遗漏<5的补
    recent = [n for n, m in missing.items() if m < 5 and n not in mid_range]
    result = mid_range + random.sample(recent, min(play_size - len(mid_range), len(recent)))
    return sorted(result[:play_size])


# 策略注册表
STRATEGIES: dict[str, Callable] = {
    "kl8_v0_random": v0_random,
    "kl8_v1_hot12_cold8": v1_hot_cold,
    "kl8_v1_hot_cold": v1_hot_cold,       # 兼容旧名
    "kl8_v2_zone_balance": v2_zone_balance,
    "kl8_v3_missing_rebound": v3_missing_rebound,
}

STRATEGY_LABELS = {
    "kl8_v0_random": "随机基准",
    "kl8_v1_hot_cold": "热号+冷号混合",
    "kl8_v2_zone_balance": "分区均衡",
    "kl8_v3_missing_rebound": "遗漏回补",
}


def get_strategy(name: str) -> Callable | None:
    return STRATEGIES.get(name)


def list_strategies() -> list[str]:
    return list(STRATEGIES.keys())
