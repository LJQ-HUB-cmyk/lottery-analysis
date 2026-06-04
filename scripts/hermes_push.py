#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hermes 推送脚本（两段式）
========================
  --mode predict : 下午推送今日预测（不含复盘）
  --mode review  : 晚间推送今日复盘（不含预测）
  --mode daily   : 旧版混合日报（保留兼容）

用法：
    python scripts/hermes_push.py --mode predict           # 推送预测
    python scripts/hermes_push.py --mode review            # 推送复盘
    python scripts/hermes_push.py --mode predict --force   # 强制补发
    python scripts/hermes_push.py --mode predict --write-only  # 只生成不推送
    python scripts/hermes_push.py --mode predict --stdout  # stdout模式（Hermes deliver=origin）
"""

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

BASE = Path(__file__).resolve().parent.parent

PRED_DIR = BASE / "output" / "predictions"
KL8_OUTPUT_DIR = BASE / "output" / "kl8"
KL8_DATA_DIR = BASE / "data" / "kl8"
REVIEW_HISTORY = BASE / "output" / "reviews" / "review_history.csv"
KL8_REVIEW_HISTORY = KL8_OUTPUT_DIR / "kl8_review_history.csv"
REPORT_DIR = BASE / "output" / "reports"
CACHE_DIR = BASE / "data" / "cache"
PUSH_DIR = BASE / "output" / "push"

PUSH_DIR.mkdir(parents=True, exist_ok=True)

CN_TZ = timezone(timedelta(hours=8))


# ── 安全类型转换 ──────────────────────────────────────

def safe_int(value, default=0):
    """安全转 int：处理 None、空字符串、NaN、异常字符串。"""
    try:
        if value is None:
            return default
        s = str(value).strip()
        if not s or s.lower() in {"nan", "none", "null"}:
            return default
        return int(float(s))
    except (ValueError, TypeError):
        return default


def safe_float(value, default=0.0):
    """安全转 float：处理 None、空字符串、NaN、异常字符串。"""
    try:
        if value is None:
            return default
        s = str(value).strip()
        if not s or s.lower() in {"nan", "none", "null"}:
            return default
        return float(s)
    except (ValueError, TypeError):
        return default


# ── 工具函数 ──────────────────────────────────────────

def now() -> datetime:
    return datetime.now(CN_TZ)


def today_str() -> str:
    return now().strftime("%Y-%m-%d")


def yesterday_str() -> str:
    return (now() - timedelta(days=1)).strftime("%Y-%m-%d")


# ═══════════════════════════════════════════
#  文件读取 & 工具函数
# ═══════════════════════════════════════════

def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[WARN] JSON 读取失败: {path} | {e}")
        return {}


def read_review_csv() -> list[dict[str, str]]:
    if not REVIEW_HISTORY.exists():
        return []
    try:
        with REVIEW_HISTORY.open("r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except Exception as e:
        print(f"[WARN] review_history 读取失败: {e}")
        return []


# calc_sum / calc_span / calc_shape 定义在下方工具函数区（约 L401 行）


def parse_bool(val: str) -> bool:
    return str(val).strip().lower() in {"true", "1", "yes", "y", "是", "命中", "✅"}


def hot_numbers(win: dict) -> list[str]:
    """从窗口统计提取热号（近10期出现最多的数字）"""
    freq = win.get("全位数字频率", {})
    if not freq:
        return []
    sorted_nums = sorted(freq.items(), key=lambda x: -x[1])
    return [str(k) for k, v in sorted_nums if v >= max(1, len(sorted_nums) / 3)]


def cold_numbers(win: dict) -> list[str]:
    """从窗口统计提取冷号（近期遗漏较长的数字）"""
    omission = win.get("当前遗漏", {})
    if not omission:
        return []
    avg = win.get("平均遗漏", 3)
    return [str(k) for k, v in sorted(omission.items(), key=lambda x: -x[1]) if v and v >= avg]


# ═══════════════════════════════════════════
#  昨日复盘格式化（升级版）
# ═══════════════════════════════════════════

def pick_latest_review(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """每个彩种取最新一期"""
    if not rows:
        return []
    latest: dict[str, int] = {}
    for row in rows:
        lottery = row.get("彩种", "")
        issue_str = row.get("期号", "")
        digits = "".join(c for c in issue_str if c.isdigit())
        if not digits:
            continue
        num = int(digits)
        if num > latest.get(lottery, -1):
            latest[lottery] = num
    return [r for r in rows
            if "".join(c for c in r.get("期号", "") if c.isdigit()) == str(latest.get(r.get("彩种", ""), ""))]


def format_review_section() -> str:
    """
    读取 review_history.csv → 拼接升级版复盘
    格式：
        【排列三 261XX】
        开奖号码：835
        形态：组六｜和值：16｜跨度：5

        策略表现：
        ✅ conservative：命中走势区间
          - 和值预测区间：14-18，实际 16，命中
          - 跨度预测区间：4-6，实际 5，命中
          - 和值差+跨度差：0，昨日最佳策略

        其他策略：
        - default：和值差+跨度差=2
        - diversity：和值差+跨度差=3

        复盘结论：昨日排列三走势落在中和值、中跨度、组六形态区间，conservative 策略判断最接近。
    """
    rows = pick_latest_review(read_review_csv())
    if not rows:
        return "【昨日复盘】\n暂无复盘数据"

    # 按 (彩种, 期号) 分组
    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        lottery = row.get("彩种", "未知")
        issue = row.get("期号", "未知")
        grouped.setdefault((lottery, issue), []).append(row)

    output_parts = ["━━━━━━━━━━━━━━\n一、昨日复盘\n━━━━━━━━━━━━━━"]

    for (lottery, issue), items in sorted(grouped.items()):
        actual = items[0].get("开奖号码", "未知")
        pattern = calc_shape(actual)
        total = calc_sum(actual)
        span = calc_span(actual)

        output_parts.append(f"\n【{lottery} {issue}】")
        output_parts.append(f"开奖号码：{actual}")
        output_parts.append(f"形态：{pattern}｜和值：{total}｜跨度：{span}")

        # 分策略表现
        strategy_results = []
        best_strategy = ""
        best_score = 9999

        for item in items:
            st = item.get("策略", "default")
            sum_err = safe_int(item.get("Top1和值误差"), 99)
            span_err = safe_int(item.get("Top1跨度误差"), 99)
            form_ok = parse_bool(item.get("Top1形态一致", ""))
            score = sum_err + span_err
            direct_hit = parse_bool(item.get("直选命中Top30", ""))
            group_hit = parse_bool(item.get("组选命中Top30", ""))

            strategy_results.append({
                "name": st,
                "sum_err": sum_err,
                "span_err": span_err,
                "score": score,
                "form_ok": form_ok,
                "direct_hit": direct_hit,
                "group_hit": group_hit,
            })
            if score < best_score:
                best_score = score
                best_strategy = st

        # 最佳策略详细展示
        best_entry = next((r for r in strategy_results if r["name"] == best_strategy), None)
        if best_entry:
            output_parts.append(f"\n策略表现：")
            hits = []
            if best_entry["direct_hit"]:
                hits.append("直选命中")
            if best_entry["group_hit"]:
                hits.append("组选命中")
            hit_str = f"（{' + '.join(hits)}）" if hits else ""
            output_parts.append(f"✅ {best_strategy}：命中走势区间{hit_str}")
            output_parts.append(f"  - 和值差={best_entry['sum_err']}，跨度差={best_entry['span_err']}")
            output_parts.append(f"  - 和值差+跨度差={best_score}，昨日最佳策略")

        # 其他策略
        others = [r for r in strategy_results if r["name"] != best_strategy]
        if others:
            output_parts.append(f"\n其他策略：")
            for r in others:
                hits_o = []
                if r["direct_hit"]:
                    hits_o.append("直选")
                if r["group_hit"]:
                    hits_o.append("组选")
                hit_o_str = f"（{' + '.join(hits_o)}命中）" if hits_o else "（未命中）"
                output_parts.append(f"- {r['name']}：和值差+跨度差={r['score']}{hit_o_str}")

        # 一句话复盘结论
        sum_comment = "低" if total <= 9 else ("高" if total >= 18 else "中")
        span_comment = "小" if span <= 3 else ("大" if span >= 7 else "中")
        output_parts.append(
            f"\n复盘结论：\n"
            f"昨日{lottery}走势落在{'低' if total <= 9 else '中' if total <= 17 else '高'}和值、"
            f"{span_comment}跨度、{pattern}形态区间，"
            f"{best_strategy} 策略判断最接近。"
        )

    return "\n".join(output_parts)


# ═══════════════════════════════════════════
#  今日预测格式化（升级版）
# ═══════════════════════════════════════════

def extract_top10(data: dict, key: str = "Top10号码") -> list[str]:
    summary = data.get("摘要", {})
    nums = summary.get(key, [])
    if nums:
        return [str(x).zfill(3) for x in nums[:10]]
    recommends = data.get("推荐", [])
    result = []
    for item in (recommends or [])[:10]:
        if isinstance(item, dict):
            n = item.get("号码", "")
            if n:
                result.append(str(n).zfill(3))
    return result[:10]


def extract_topn(data: dict, n: int = 30) -> list[str]:
    """从预测 JSON 提取 TopN 号码列表。依次尝试 Top30/Top20/Top10 字段。"""
    if not data:
        return []
    summary = data.get("摘要", {})
    nums = (
        summary.get("Top30号码")
        or summary.get("Top20号码")
        or summary.get("Top10号码")
        or []
    )
    return [str(x).zfill(3) for x in nums[:n]]


def format_ranked_numbers(nums: list[str], per_line: int = 10) -> str:
    """格式化带排名的号码列表，每行 per_line 个。"""
    if not nums:
        return "-"
    lines = []
    for i in range(0, len(nums), per_line):
        chunk = nums[i:i + per_line]
        line = " ".join(
            f"{i + j + 1:02d}.{num}"
            for j, num in enumerate(chunk)
        )
        lines.append(line)
    return "\n".join(lines)


def top_digits(recommends: list, k: int = 5) -> str:
    """从 Top30 推荐里统计数字频率，取前 k 个高频数字。"""
    from collections import Counter
    cnt = Counter()
    for item in (recommends or [])[:30]:
        num = item.get("号码", "") if isinstance(item, dict) else str(item)
        for d in str(num).zfill(3):
            if d.isdigit():
                cnt[d] += 1
    return "".join(d for d, _ in cnt.most_common(k))


def check_group_hit(digits_pool: str, draw: str) -> tuple[bool, list[str]]:
    """检查开奖号码是否全部落在数字池内。
    返回 (hit, missing_digits)。"""
    draw_set = set(str(draw).zfill(3))
    pool_set = set(digits_pool)
    missing = draw_set - pool_set
    return len(missing) == 0, sorted(missing)


def format_group_select(recommends: list) -> str:
    """生成五码/六码组选展示文本（预测用）。"""
    five = top_digits(recommends, 5)
    six = top_digits(recommends, 6)
    if not five or not six:
        return ""
    return (
        f"五码组选：{five}（组六10注+组三20注=30注）\n"
        f"六码组选：{six}（组六20注+组三30注=50注）"
    )


def format_group_review(recommends: list, draw: str) -> str:
    """生成五码/六码复盘展示文本（复盘用）。"""
    five = top_digits(recommends, 5)
    six = top_digits(recommends, 6)
    if not five or not six:
        return ""
    hit5, miss5 = check_group_hit(five, draw)
    hit6, miss6 = check_group_hit(six, draw)
    icon5 = "✅" if hit5 else f"❌ (缺{''.join(miss5)})"
    icon6 = "✅" if hit6 else f"❌ (缺{''.join(miss6)})"
    return f"五码 {five} {icon5} | 六码 {six} {icon6}"


# ── 展示工具 ────────────────────────────────────────

def normalize_strategy_name(name: str) -> str:
    """统一策略展示名称。"""
    mapping = {"默认": "标准", "default": "标准", "standard": "标准",
               "稳健": "稳健", "conservative": "稳健",
               "多样性": "多样性", "diversity": "多样性",
               "auto_tuned": "自动调参",
               "ensemble": "融合策略"}
    return mapping.get(name, name)


def _digits_of(num):
    return [int(x) for x in str(num).zfill(3)]


def calc_sum(num):
    return sum(_digits_of(num))


def calc_span(num):
    ds = _digits_of(num)
    return max(ds) - min(ds)


def calc_shape(num):
    ds = _digits_of(num)
    u = len(set(ds))
    if u == 1:
        return "豹子"
    if u == 2:
        return "组三"
    return "组六"


def calc_diff_metrics(pred_num, actual_num):
    return {
        "sum_diff": abs(calc_sum(pred_num) - calc_sum(actual_num)),
        "span_diff": abs(calc_span(pred_num) - calc_span(actual_num)),
        "shape_same": calc_shape(pred_num) == calc_shape(actual_num),
    }


def format_metrics(pred_num, actual_num):
    m = calc_diff_metrics(pred_num, actual_num)
    return (f"和值差{m['sum_diff']}｜跨度差{m['span_diff']}｜"
            f"形态{'一致' if m['shape_same'] else '不一致'}")


def format_number_grid(numbers, limit=None, line_size=5):
    """号码网格：每行5个，无编号。"""
    if not numbers:
        return "-"
    if limit is not None:
        numbers = numbers[:limit]
    clean = [str(x).zfill(3) for x in numbers]
    lines = []
    for i in range(0, len(clean), line_size):
        lines.append(" ".join(clean[i:i + line_size]))
    return "\n".join(lines)


def missing_digits_from_pool(actual_num, pool):
    actual_set = set(str(actual_num).zfill(3))
    pool_set = set(str(pool))
    return sorted(actual_set - pool_set)


def format_group_review_new(recommends, draw):
    """组选池展示 v2：每行一个池，清晰标注缺失数字。"""
    five = top_digits(recommends, 5)
    six = top_digits(recommends, 6)
    if not five or not six:
        return ""
    lines = ["组选池："]
    for label, pool in [("五码", five), ("六码", six)]:
        missing = missing_digits_from_pool(draw, pool)
        if missing:
            lines.append(f"{label} {pool} ❌ 缺数字{''.join(missing)}")
        else:
            lines.append(f"{label} {pool} ✅ 覆盖")
    return "\n".join(lines)


def load_stats_cache(lottery: str) -> dict:
    """加载统计缓存"""
    path = CACHE_DIR / f"{lottery}_stats_latest.json"
    return read_json(path)


def format_observation(stats: dict, label: str, pred_data: dict = None) -> list[str]:
    """生成核心观察文本（紧凑结构版）"""
    if not stats:
        return ["暂无统计缓存"]

    w10 = stats.get("窗口", {}).get("近10期", {})
    w30 = stats.get("窗口", {}).get("近30期", {})
    p5 = stats.get("窗口", {}).get("近5期", {})

    lines = []

    # 和值区间 + 跨度重点（一行搞定）
    high_sum_w10 = w10.get("高频和值", [])
    high_span_w10 = w10.get("高频跨度", [])
    sum_range = w10.get("高频和值区间", "")
    span_mean = w10.get("跨度均值", "?")

    # 结构倾向
    sum_parts = []
    if sum_range:
        sum_parts.append(f"和值区间：{sum_range}")
    if high_sum_w10:
        sum_parts.append(f"参考 {' '.join(str(s) for s in sorted(high_sum_w10)[:8])}")
    span_parts = []
    if high_span_w10:
        span_parts.append(f"跨度重点：{' '.join(str(s) for s in sorted(high_span_w10))}（均值{span_mean}）")

    if sum_parts:
        lines.append("结构倾向：")
        lines.append("  " + "、".join(sum_parts))
    if span_parts:
        lines.append("  " + span_parts[0])

    # 形态倾向
    lines.append("  形态倾向：组六为主，组三少量防守")

    # 冷热观察
    hot = hot_numbers(w10)
    cold = cold_numbers(w10)
    hot_str = f"热号 {' '.join(hot)}" if hot else ""
    cold_str = f"冷号 {' '.join(cold)}" if cold else ""
    if hot_str and cold_str:
        lines.append(f"  冷热：{hot_str} · {cold_str}")
    elif hot_str:
        lines.append(f"  冷热：{hot_str}")
    elif cold_str:
        lines.append(f"  冷热：{cold_str}")

    # 高分区分位数（从预测JSON读取）
    if pred_data:
        s = pred_data.get("摘要", {})
        p95_score = s.get("P95分数线")
        p95_count = s.get("P95候选数")
        if p95_score is not None:
            lines.append(f"  高分区：Top 5% 候选（≥{p95_score}分，{p95_count}注）")

    return lines


def format_prediction_section(lottery: str, label: str) -> str:
    """
    升级版预测格式化：
      核心观察（和值/跨度/形态/冷热）
      Top10 候选
      多策略共振号码
      重点关注 ⭐
      备选关注
    """
    path = PRED_DIR / f"latest_{lottery}.json"
    data = read_json(path)

    if not data:
        return f"【{label} 今日预测】\n暂无预测文件"

    issue = data.get("预测期号", "未知")
    top10 = extract_top10(data)

    # 核心观察
    stats = load_stats_cache(lottery)
    obs_lines = format_observation(stats, label, pred_data=data)

    # 多策略共振
    consensus_nums: dict[str, int] = {}
    for suffix, sname in [("", "default"), ("_conservative", "稳健"),
                           ("_diversity", "多样性"), ("_auto_tuned", "自动调参"),
                           ("_ensemble", "融合策略")]:
        sp = PRED_DIR / f"latest_{lottery}{suffix}.json"
        sd = read_json(sp)
        if sd:
            for n in extract_top10(sd)[:10]:
                consensus_nums[n] = consensus_nums.get(n, 0) + 1

    consensus = sorted([(n, c) for n, c in consensus_nums.items() if c >= 2],
                       key=lambda x: (-x[1], x[0]))

    # 共振号分档：多策略命中 vs 仅两策略
    triple = [n for n, c in consensus if c >= 3]
    double = [n for n, c in consensus if c >= 2 and c < 3]

    parts = [
        f"\n━━━━━━━━━━━━━━\n二、{label} 今日预测\n━━━━━━━━━━━━━━",
        f"预测期号：{issue}",
        "",
        "核心观察：",
    ]
    parts.extend("  " + line for line in obs_lines)
    parts.append("")
    parts.append(f"Top10候选：\n{' '.join(top10) if top10 else '暂无'}")

    if triple:
        parts.append(f"\n多策略共振（≥3策略交集）：\n{' '.join(triple)}")
    if double:
        parts.append(f"多策略共振（两策略交集）：\n{' '.join(double)}")

    # 重点关注（从推荐列表首部 + 共振取交集）
    # 从 default 推荐列表提取评分前几的号码作为"重点关注"
    recommends = data.get("推荐", [])
    top_scores = {}
    for item in (recommends or [])[:30]:
        if isinstance(item, dict):
            n = str(item.get("号码", "")).zfill(3)
            top_scores[n] = item.get("总分", 0)

    # 重点关注 = 多策略共振 + default 评分前15
    primary_candidates = set(triple)
    # 从评分前15抽和共振的交集，如果没有足够，从共振中补
    top15 = list(top_scores.keys())[:15]
    primary = [n for n in triple if n in top15]
    if not primary and triple:
        primary = triple[:3]

    secondary = [n for n in double if n not in primary]
    # 如果 secondary 不够，从 top10 补充不在共振的
    rest_top10 = [n for n in top10 if n not in primary and n not in secondary]
    secondary.extend(rest_top10[:4 - len(secondary)])

    if primary:
        parts.append(f"\n重点关注：\n{' '.join(primary[:3])}")
        # 给出理由
        reasons = []
        for n in primary[:3]:
            item = next((r for r in (recommends or []) if str(r.get("号码", "")).zfill(3) == n), None)
            if item:
                total = item.get("总分", 0)
                pattern = item.get("形态", "?")
                hv = item.get("和值", "?")
                sp = item.get("跨度", "?")
                reasons.append(f"  {n}：总分{total}，{pattern}，和值{hv}，跨度{sp}")
        if reasons:
            parts.append("理由：")
            parts.extend(reasons)

    if secondary:
        parts.append(f"\n备选关注：\n{' '.join(secondary[:5])}")

    # 五码/六码组选
    if recommends:
        gs = format_group_select(recommends)
        if gs:
            parts.append(f"\n{gs}")

    return "\n".join(parts)


# ═══════════════════════════════════════════
#  重点关注总表
# ═══════════════════════════════════════════

def build_summary_section() -> str:
    """生成今日重点关注总表"""
    parts = ["━━━━━━━━━━━━━━\n三、今日重点关注\n━━━━━━━━━━━━━━"]

    for lottery, label in [("pls", "排列三"), ("d3", "福彩3D")]:
        path = PRED_DIR / f"latest_{lottery}.json"
        data = read_json(path)
        if not data:
            continue

        top10 = extract_top10(data)

        # 共振
        consensus_nums: dict[str, int] = {}
        for suffix in ["", "_conservative", "_diversity", "_auto_tuned", "_ensemble"]:
            sp = PRED_DIR / f"latest_{lottery}{suffix}.json"
            sd = read_json(sp)
            if sd:
                for n in extract_top10(sd)[:10]:
                    consensus_nums[n] = consensus_nums.get(n, 0) + 1

        triple = [n for n, c in sorted(consensus_nums.items(), key=lambda x: (-x[1], x[0])) if c >= 3]
        double = [n for n, c in sorted(consensus_nums.items(), key=lambda x: (-x[1], x[0])) if c >= 2 and c < 3]

        primary = triple[:3] if triple else (double[:3] if double else top10[:3])
        secondary = [n for n in double if n not in primary][:4]
        if not secondary:
            secondary = [n for n in top10 if n not in primary][:4]

        parts.append(f"\n{label}：")
        parts.append(f"主看 {' '.join(primary)}")
        if secondary:
            parts.append(f"辅看 {' '.join(secondary)}")

    return "\n".join(parts)


# ═══════════════════════════════════════════
#  健康报告格式化（保持不变）
# ═══════════════════════════════════════════

def is_recent(path: Path, hours: int = 12) -> bool:
    if not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) <= hours * 3600


def format_health_section(override_issues=None, lottery_filter: str = "all") -> str:
    """数据源状态。override_issues 可传入本次复盘的期号/号码。
    lottery_filter: all=全部 / pls=只排列三 / d3=只福彩3D。"""
    health_path = REPORT_DIR / "source_health.json"
    override_issues = override_issues or {}

    lotto_pairs = [("pls", "排列三"), ("d3", "福彩3D")]
    if lottery_filter in ("pls", "d3"):
        lotto_pairs = [(lottery_filter, "排列三" if lottery_filter == "pls" else "福彩3D")]

    if is_recent(health_path):
        data = read_json(health_path)
        if data:
            lines = ["【数据源状态】"]
            for lottery, label in lotto_pairs:
                # 优先使用本次复盘数据
                override = override_issues.get(lottery, {})
                if override:
                    lines.append(f"  {label}：已拉取 {override.get('issue','?')}={override.get('number','?')}")
                else:
                    d = data.get(lottery, {}).get("data")
                    if d and "error" not in d:
                        lines.append(f"  {label}: 最新 {d['issue']}={d['number']} ({d['total_rows']}期)")
                for src_name, s in data.get(lottery, {}).get("sources", {}).items():
                    cd = s.get("cooldown_until")
                    fails = s.get("failures", 0)
                    rnd = s.get("cooldown_round", 0)
                    if cd:
                        rnd_str = f" 第{rnd}轮" if rnd > 1 else ""
                        lines.append(f"  🔒 {src_name} 冷却中{rnd_str} (HTTP{s.get('last_status','?')})")
                    elif fails > 0:
                        lines.append(f"  ⚠️  {src_name} 失败{fails}次")
                    else:
                        lines.append(f"  ✅ {src_name} 正常")
            q = data.get("quarantine", {})
            if q.get("recent_files", 0) > 0:
                lines.append(f"  ⚠️  隔离区最近24h: {q['recent_files']}条")
            return "\n".join(lines)

    # fallback
    status_path = CACHE_DIR / "source_status.json"
    data = read_json(status_path)
    if not data:
        return "【数据源状态】\n暂无记录"

    lines = ["【数据源状态】"]
    for name, item in data.items():
        if lottery_filter in ("pls", "d3") and not name.startswith(lottery_filter):
            continue
        cd = item.get("cooldown_until", "")
        fails = item.get("consecutive_failures", 0)
        if cd:
            lines.append(f"  🔒 {name} 冷却至 {cd}")
        elif fails > 0:
            lines.append(f"  ⚠️  {name} 失败 {fails} 次")
        else:
            lines.append(f"  ✅ {name} 正常")
    return "\n".join(lines)


# ═══════════════════════════════════════════
#  新版两段式推送
# ═══════════════════════════════════════════

def check_review_ready(lottery_filter: str = "all") -> tuple[bool, str]:
    """检查复盘数据是否就绪。返回 (ready, message)。
    lottery_filter: all=检查全部 / pls=只检查排列三 / d3=只检查福彩3D。
    """
    targets = ["pls", "d3"] if lottery_filter == "all" else [lottery_filter]

    has_valid_compare = False
    waiting_msgs = []
    for lottery in targets:
        path = REPORT_DIR / f"{lottery}_compare_latest.json"
        data = read_json(path)
        if not data:
            continue
        status = data.get("状态", "")
        error = data.get("错误", "")
        if status == "waiting_actual":
            waiting_msgs.append(f"{lottery} {data.get('说明', '')}")
            continue
        if not error:
            has_valid_compare = True

    if waiting_msgs:
        return False, f"等待开奖数据（{'; '.join(waiting_msgs)}）"

    if has_valid_compare:
        return True, ""

    # fallback: 检查 review_history 是否有记录（单彩种时只检查对应彩种）
    rows = read_review_csv()
    if lottery_filter != "all":
        lotto_map = {"pls": "排列三", "d3": "福彩3D"}
        rows = [r for r in rows if r.get("彩种", "") == lotto_map.get(lottery_filter, "")]
    if rows:
        return True, ""

    return False, "无复盘数据（review_history 为空）"


def build_review_performance(lottery_filter: str = "all") -> str:
    """从 review_history 计算最近策略表现摘要。
    lottery_filter: all=全部 / pls=只排列三 / d3=只福彩3D。"""
    rows = read_review_csv()
    if not rows:
        return "暂无复盘记录"

    lottery_data: dict[str, dict[str, list]] = {}
    for row in rows:
        lotto = row.get("彩种", "")
        st = row.get("策略", "default")
        lottery_data.setdefault(lotto, {}).setdefault(st, []).append(row)

    parts = ["━━━━━━━━━━━━━━\n三、近期策略表现\n━━━━━━━━━━━━━━"]
    label_map = {"default": "标准", "conservative": "稳健", "diversity": "多样性",
                 "auto_tuned": "自动调参", "ensemble": "融合策略"}
    # 统一"默认"→"标准"
    for i, row in enumerate(rows):
        if row.get("策略", "") == "默认":
            rows[i]["策略"] = "标准"

    lotto_map = {"pls": "排列三", "d3": "福彩3D"}
    wanted = ["排列三", "福彩3D"] if lottery_filter == "all" else [lotto_map.get(lottery_filter, lottery_filter)]

    for lotto in wanted:
        parts.append(f"\n【{lotto}】")
        for st in ["default", "conservative", "diversity", "auto_tuned", "ensemble"]:
            records = lottery_data.get(lotto, {}).get(st, [])
            if not records:
                continue
            recent = records[-30:]
            total = len(recent)
            direct_hits = sum(1 for r in recent if parse_bool(r.get("直选命中Top30", "")))
            group_hits = sum(1 for r in recent if parse_bool(r.get("组选命中Top30", "")))
            morph_hits = sum(1 for r in recent if parse_bool(r.get("Top1形态一致", "")))
            sum_errors = [safe_int(r.get("Top1和值误差"), 0) for r in recent]
            span_errors = [safe_int(r.get("Top1跨度误差"), 0) for r in recent]
            avg_sum = sum(sum_errors) / total if total else 0
            avg_span = sum(span_errors) / total if total else 0

            parts.append(
                f"  {label_map.get(st, st)}（近{total}期）："
                f"直选{direct_hits}/{total}，组选{group_hits}/{total}，"
                f"形态{morph_hits}/{total}，均和差{avg_sum:.1f}，均跨差{avg_span:.1f}"
            )

    return "\n".join(parts)


def build_predict_message() -> str:
    """生成预测推送（不含复盘）"""
    parts = [
        f"📊 彩票预测日报｜{today_str()}",
        "",
        format_prediction_section("pls", "排列三"),
        "",
        format_prediction_section("d3", "福彩3D"),
        "",
        build_summary_section(),
        "",
        format_health_section(),
        "",
        "",
        "⚠️ 彩票具有随机性，以上仅供数据分析与复盘参考，不构成投注建议。",
    ]
    txt = "\n".join(parts)
    return txt[:4000] + "\n\n……内容过长已截断" if len(txt) > 4000 else txt


def build_review_message(lottery_filter: str = "all") -> str:
    """生成复盘推送：开奖复盘（复盘的是前一天开奖，不是今天预测）。
    lottery_filter: all=排列三+福彩3D合并 / pls=只排列三 / d3=只福彩3D。
    """
    rows = pick_latest_review(read_review_csv())
    if not rows:
        return "\n".join([
            "📊 开奖复盘｜推送日 " + today_str(),
            "",
            "暂无复盘数据",
        ])

    # 提取各彩种复盘期号
    review_issues = {}
    for row in rows:
        lotto = row.get("彩种", "")
        issue = row.get("期号", "")
        if lotto and issue:
            review_issues[lotto] = issue

    pls_issue = review_issues.get("排列三", "?")
    d3_issue = review_issues.get("福彩3D", "?")

    # 彩种筛选
    lotto_map = {"pls": "排列三", "d3": "福彩3D"}
    if lottery_filter in lotto_map:
        wanted = [lotto_map[lottery_filter]]
        # 单彩种标题
        label = lotto_map[lottery_filter]
        issue = review_issues.get(label, "?")
        parts = [
            f"📊 开奖复盘｜{label}｜推送日 {today_str()}",
            f"复盘对象：{label} {issue}期预测数据",
            f"说明：已按 {issue}期开奖结果完成复盘。",
            "",
        ]
    else:
        wanted = ["排列三", "福彩3D"]
        parts = [
            f"📊 开奖复盘｜推送日 {today_str()}",
            f"复盘对象：排列三 {pls_issue}期 / 福彩3D {d3_issue}期预测数据",
            f"说明：已按对应期号开奖结果完成复盘。",
            "",
        ]

    # 按彩种分组获取今日实际开奖和命中情况
    grouped: dict[str, list] = {}
    for row in rows:
        lotto = row.get("彩种", "未知")
        grouped.setdefault(lotto, []).append(row)

    for lotto in wanted:
        items = grouped.get(lotto, [])
        if not items:
            continue
        actual = items[0].get("开奖号码", "未知")
        review_issue = items[0].get("期号", "未知")
        pattern = calc_shape(actual)
        total = calc_sum(actual)
        span = calc_span(actual)

        parts.append("━━━━━━━━━━━━━━")
        parts.append(f"{lotto} {review_issue}")
        parts.append("━━━━━━━━━━━━━━")
        parts.append(f"开奖号码：{actual}（{pattern}｜和值{total}｜跨度{span}）")
        parts.append("")

        lottery_key = "pls" if lotto == "排列三" else "d3"

        # 各策略对比 — 收集结果用于后续统一展示
        strategy_results = []
        default_recommends = []
        has_any_hit = False

        for st_key, label in [("default", "默认"), ("conservative", "稳健"),
                               ("diversity", "多样性"), ("auto_tuned", "自动调参"),
                               ("ensemble", "融合策略")]:
            item = next((r for r in items if r.get("策略", "") == st_key), None)
            if not item:
                continue

            # 读取预测文件
            issue_digits = "".join(c for c in review_issue if c.isdigit())
            prefix = f"{lottery_key}_{st_key}" if st_key != "default" else lottery_key
            issue_pred_path = PRED_DIR / f"{prefix}_predict_{issue_digits}.json"
            if issue_pred_path.exists():
                st_data = read_json(issue_pred_path)
            else:
                st_data = read_json(PRED_DIR / f"latest_{prefix}.json")
                if st_data:
                    pred_issue = str(st_data.get("预测期号", ""))
                    actual_issue = "".join(c for c in pred_issue if c.isdigit())
                    if actual_issue != issue_digits:
                        st_data = {}
            top30 = extract_topn(st_data, 30) if st_data else []

            if st_key == "default" and st_data:
                default_recommends = st_data.get("推荐", [])

            direct_hit = parse_bool(item.get("直选命中Top30", ""))
            group_hit = parse_bool(item.get("组选命中Top30", ""))
            hit_num = str(item.get("命中号码", "")).zfill(3) if item.get("命中号码") else ""
            hit_rank = item.get("命中排名", "")
            hit_range = item.get("命中范围", "")
            display_name = normalize_strategy_name(label)

            top1 = top30[0] if top30 else ""

            # 命中指标：命中时按命中号码算，未命中时按 Top1 算
            if direct_hit and hit_num:
                ref_num = hit_num
                ref_label = f"命中项：{hit_num}｜"
                has_any_hit = True
            elif group_hit and hit_num:
                ref_num = hit_num
                ref_label = f"命中项：{hit_num}｜"
                has_any_hit = True
            else:
                ref_num = top1
                ref_label = ""

            ref_metrics = format_metrics(ref_num, actual)

            # 策略结果行
            if direct_hit:
                parts.append(f"🎯 {display_name}：{hit_range}直选命中  {hit_num}（第{hit_rank}名）")
            elif group_hit:
                parts.append(f"✅ {display_name}：{hit_range}组选命中  {hit_num}（第{hit_rank}名）")
            else:
                parts.append(f"❌ {display_name}：未命中")

            if ref_label:
                parts.append(f"  {ref_label}{ref_metrics}")

            # 命中时 Top1 作为参考
            if (direct_hit or group_hit) and top1 and top1 != hit_num:
                parts.append(f"  Top1参考：{top1}｜{format_metrics(top1, actual)}")

            # 未命中时显示 Top1
            if not direct_hit and not group_hit and top1:
                parts.append(f"  Top1：{top1}｜{ref_metrics}")

            parts.append("")

            # 收集策略结果
            hit_type = None
            if direct_hit:
                hit_type = "direct"
            elif group_hit:
                rng = str(hit_range)
                if "Top5" in rng:
                    hit_type = "group_top5"
                elif "Top10" in rng:
                    hit_type = "group_top10"
                else:
                    hit_type = "group_top30"

            strategy_results.append({
                "name": display_name,
                "st_key": st_key,
                "top30": top30,
                "hit": bool(direct_hit or group_hit),
                "hit_type": hit_type,
                "hit_label": str(hit_range) if (direct_hit or group_hit) else None,
                "hit_number": hit_num,
                "rank": hit_rank,
            })

        # 五码/六码组选
        if default_recommends and actual and actual != "未知":
            gs = format_group_review_new(default_recommends, actual)
            if gs:
                parts.append(gs)
                parts.append("")

        # 命中/未命中 Top 展示
        if has_any_hit:
            # 选最佳命中策略展示 Top30
            best = None
            priority = {"direct": 0, "group_top5": 1, "group_top10": 2, "group_top30": 3}
            for r in strategy_results:
                if r["hit"]:
                    s = priority.get(r["hit_type"], 99)
                    if best is None or s < priority.get(best["hit_type"], 99):
                        best = r
            if best and best["top30"]:
                parts.append("━━━━━━━━━━━━━━")
                parts.append(f"命中策略 Top30｜{best['name']}")
                parts.append("━━━━━━━━━━━━━━")
                parts.append(format_number_grid(best["top30"], limit=30, line_size=5))
                parts.append("")
        else:
            # 未命中：各策略展示 Top10
            parts.append("━━━━━━━━━━━━━━")
            parts.append("未命中策略 Top10参考")
            parts.append("━━━━━━━━━━━━━━")
            for r in strategy_results:
                if r["top30"]:
                    parts.append(f"{r['name']}：")
                    parts.append(format_number_grid(r["top30"], limit=10, line_size=5))
                    parts.append("")

    # 数据源状态（传入本次复盘数据，避免显示旧期号）
    override_issues = {}
    for lotto in wanted:
        items = grouped.get(lotto, [])
        if items:
            actual = items[0].get("开奖号码", "未知")
            issue = items[0].get("期号", "未知")
            lt_key = "pls" if lotto == "排列三" else "d3"
            override_issues[lt_key] = {"issue": issue, "number": actual}

    # 近期表现
    parts.append(build_review_performance(lottery_filter))
    parts.append("")
    parts.append(format_health_section(override_issues, lottery_filter))
    parts.append("")
    parts.append("⚠️ 彩票具有随机性，以上仅供数据分析与复盘参考，不构成投注建议。")

    txt = "\n".join(parts)
    if len(txt) > 4000:
        txt = txt[:4000] + "\n\n……内容过长已截断"
    return txt


# ═══════════════════════════════════════════
#  快乐8 (KL8) 推送
# ═══════════════════════════════════════════

def build_kl8_predict_message() -> str:
    """生成快乐8预测推送（选四主推+候选池）"""
    data = read_json(KL8_OUTPUT_DIR / "kl8_predict_latest.json")
    if not data:
        return "🎯 快乐8预测\n暂无预测数据"

    pool = data.get("candidate_pool", [])
    play4 = data.get("recommended_play4", [])
    return "\n".join([
        f"🎯 快乐8预测日报｜{today_str()}",
        "",
        f"预测期号：{data.get('predicted_issue', '?')}",
        f"策略：{data.get('strategy', '?')}",
        "",
        f"【选四主推】{' '.join(f'{n:02d}' for n in play4)}（2元/注）",
        f"  官方奖级：中4=93元｜中3=5元｜中2=3元",
        "",
        f"【20码参考池】",
        f"  {' '.join(f'{n:02d}' for n in pool[:10])}",
        f"  {' '.join(f'{n:02d}' for n in pool[10:])}",
        "",
        f"分区：01-20:{data['zone_distribution']['01-20']}  "
        f"21-40:{data['zone_distribution']['21-40']}  "
        f"41-60:{data['zone_distribution']['41-60']}  "
        f"61-80:{data['zone_distribution']['61-80']}",
        "",
        "⚠️ 彩票具有随机性，选四推荐仅基于历史统计生成，小额娱乐。",
    ])


def build_kl8_review_message() -> str:
    """生成快乐8复盘推送（选四命中+盈亏）"""
    pred = read_json(KL8_OUTPUT_DIR / "kl8_predict_latest.json")
    data = read_json(KL8_OUTPUT_DIR / "kl8_review_latest.json")
    if not data:
        return "📊 快乐8开奖复盘\n暂无复盘数据"

    # 闸门：复盘期号必须等于预测期号，否则不推送（防止旧复盘被误推）
    target = str(pred.get("predicted_issue", ""))
    review_issue = str(data.get("issue", ""))
    if review_issue != target:
        print(f"[WAIT] KL8复盘未就绪：预测{target}，复盘{review_issue or '无'}",
              file=sys.stderr)
        return ""

    play4 = data.get("recommended_play4", [])
    play4_hit = data.get("play4_hit_numbers", [])
    parts = [
        f"📊 快乐8复盘｜{today_str()}",
        "",
        f"期号：{data.get('issue', '?')}  |  {data.get('date', '?')}",
        f"策略：{data.get('strategy', '?')}  |  玩法：{data.get('play_type', '?')}",
        "",
        f"【选四主推】{' '.join(f'{n:02d}' for n in play4)}",
        f"  命中：{data.get('play4_hit_count', 0)}/4 → {data.get('result_level', '?')}",
        f"  命中号码：{' '.join(f'{n:02d}' for n in play4_hit) if play4_hit else '无'}",
        f"  奖金：{data.get('prize', 0)}元 | 成本：{data.get('cost', 0)}元",
        f"  盈亏：{'+' if data.get('profit', 0) > 0 else ''}{data.get('profit', 0)}元",
        "",
        f"【20码池】命中：{data.get('pool_hit_count', 0)}/20",
        "",
    ]

    # 累计表现
    metrics_path = KL8_OUTPUT_DIR / "kl8_metrics.json"
    if metrics_path.exists():
        m = read_json(metrics_path)
        m7 = m.get("last7", {})
        if m7.get("days", 0) > 0:
            parts.append(f"【累计表现（近{m7['days']}期）】")
            parts.append(f"  成本：{m7['total_cost']}元 | "
                         f"奖金：{m7['total_prize']}元 | "
                         f"盈亏：{'+' if m7['total_profit'] > 0 else ''}{m7['total_profit']}元")
            parts.append(f"  中二：{m7['hit2_count']}次 | "
                         f"中三：{m7['hit3_count']}次 | "
                         f"中四：{m7['hit4_count']}次")
            parts.append(f"  池均命中：{m7['avg_pool_hit']}/20 | "
                         f"最长连挂：{m7['max_miss_streak']}期")
            parts.append("")

    parts.append("⚠️ 彩票具有随机性，以上仅供统计复盘参考。")
    return "\n".join(parts)


# ═══════════════════════════════════════════
#  日报拼接（7段结构，保留兼容）
# ═══════════════════════════════════════════

def build_daily_message() -> str:
    parts = [
        f"📊 每日彩票分析日报｜{today_str()}",
        "",
        format_review_section(),
        "",
        format_prediction_section("pls", "排列三"),
        "",
        format_prediction_section("d3", "福彩3D"),
        "",
        build_summary_section(),
        "",
        format_health_section(),
        "",
    ]

    # 期号一致性校验：最新复盘期号 vs 最新预测期号
    review_rows = pick_latest_review(read_review_csv())
    if review_rows:
        # 取复盘的最新期号
        review_issues = {}
        for row in review_rows:
            lotto = row.get("彩种", "")
            issue = row.get("期号", "")
            review_issues[lotto] = issue
        # 对比预测期号
        for lottery, label in [("pls", "排列三"), ("d3", "福彩3D")]:
            pred_data = read_json(PRED_DIR / f"latest_{lottery}.json")
            pred_issue = pred_data.get("预测期号", "")
            rev_issue = review_issues.get(label, "")
            rev_issue_digits = "".join(c for c in rev_issue if c.isdigit()) if rev_issue else ""
            if rev_issue_digits and str(pred_issue) != str(rev_issue_digits):
                parts.append(f"⚠️ {label}期号不匹配：预测 {pred_issue}，复盘 {rev_issue_digits}")
        if parts[-1].startswith("⚠️ "):
            parts.append("  本次复盘基于不同期号，命中数据仅供参考。")

    parts.append("")
    parts.append("⚠️ 彩票具有随机性，以上仅供数据分析与复盘参考，不构成投注建议。")
    text = "\n".join(parts)
    # 微信单条消息上限约 4096 字符，保守截断
    if len(text) > 4000:
        text = text[:4000] + "\n\n……内容过长已截断"
    return text


# ═══════════════════════════════════════════
#  推送 & 落盘 & 去重（保持不变）
# ═══════════════════════════════════════════

def msg_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def already_sent(kind: str, h: str) -> bool:
    log_path = PUSH_DIR / "send_log.jsonl"
    if not log_path.exists():
        return False
    today = today_str()
    try:
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if item.get("date") == today and item.get("kind") == kind and item.get("hash") == h and item.get("ok"):
                return True
    except Exception:
        pass
    return False


def already_sent_by_key(kind: str, dedup_key: str) -> bool:
    """业务键去重：同一 date+kind+dedup_key 只推一次，文本变化不绕过"""
    log_path = PUSH_DIR / "send_log.jsonl"
    if not log_path.exists():
        return False
    today = today_str()
    try:
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if (item.get("date") == today
                    and item.get("kind") == kind
                    and item.get("dedup_key") == dedup_key
                    and item.get("ok")):
                return True
    except Exception:
        pass
    return False


_LOCK_DIR = BASE / "output" / ".push_locks"
_LOCK_DIR.mkdir(parents=True, exist_ok=True)


def _push_lock(kind: str, h: str) -> str:
    """简易文件锁，防止并发重复推送。返回锁文件路径。"""
    os.makedirs(str(_LOCK_DIR), exist_ok=True)
    lock_path = _LOCK_DIR / f"{kind}_{h}.lock"
    return str(lock_path)


def acquire_push_lock(kind: str, h: str, timeout: float = 5.0,
                      stale_after: float = 600.0) -> bool:
    """获取推送锁。timeout=最大等待秒数，stale_after=锁文件超过多久视为残留。"""
    lock_file = _push_lock(kind, h)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w") as f:
                f.write(f"{kind}/{h} locked by pid {os.getpid()}\n")
            return True
        except FileExistsError:
            try:
                mtime = os.path.getmtime(lock_file)
                if time.time() - mtime > stale_after:
                    os.unlink(lock_file)
                    continue
            except OSError:
                pass
            time.sleep(0.2)
    return False


def release_push_lock(kind: str, h: str):
    """释放推送锁。"""
    lock_file = _push_lock(kind, h)
    try:
        os.unlink(lock_file)
    except OSError:
        pass


def append_log(kind: str, h: str, ok: bool, detail: str = "", dedup_key: str = ""):
    log_path = PUSH_DIR / "send_log.jsonl"
    item = {
        "time": now().strftime("%Y-%m-%d %H:%M:%S"),
        "date": today_str(),
        "kind": kind,
        "hash": h,
        "dedup_key": dedup_key,
        "ok": ok,
        "detail": detail,
    }
    try:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        print(f"[WARN] 写入发送日志失败: {e}")


def write_file(path: Path, text: str) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return True
    except Exception as e:
        print(f"[ERROR] 写入失败: {path} | {e}")
        return False


# ═══════════════════════════════════════════
#  推送通道（独立隔离，微信失败不拖垮飞书）
# ═══════════════════════════════════════════

WECHAT_COOLDOWN = 5       # 微信发送前固定冷却秒数
WECHAT_MAX_RETRIES = 3    # 限频时最大退避次数
WECHAT_BACKOFF = [30, 60, 120]  # 限频退避秒数


def send_feishu(text: str) -> tuple[bool, str]:
    """飞书 webhook（主通道）"""
    url = os.getenv("FEISHU_WEBHOOK_URL", "")
    if not url:
        return False, "FEISHU_WEBHOOK_URL not set"
    try:
        resp = requests.post(
            url,
            json={"msg_type": "text", "content": {"text": text}},
            timeout=15,
        )
        if resp.status_code == 200:
            body = resp.json()
            if body.get("code", -1) != 0:
                return False, f"feishu code={body.get('code')} msg={body.get('msg','')}"
            return True, "feishu ok"
        return False, f"feishu HTTP {resp.status_code}"
    except Exception as e:
        return False, f"feishu exception: {e}"


def send_wechat(text: str) -> tuple[bool, str]:
    """企业微信机器人（辅助通道，带限频退避）"""
    url = os.getenv("WECOM_WEBHOOK_URL", "")
    if not url:
        return False, "WECOM_WEBHOOK_URL not set"

    time.sleep(WECHAT_COOLDOWN)

    for i in range(WECHAT_MAX_RETRIES):
        try:
            resp = requests.post(
                url,
                json={"msgtype": "markdown", "markdown": {"content": text}},
                timeout=15,
            )
            if resp.status_code == 200:
                body = resp.json()
                errcode = body.get("errcode", -1)
                errmsg = body.get("errmsg", "")
                if errcode == 0:
                    return True, "wechat ok"
                if "rate" in errmsg.lower() and "limit" in errmsg.lower():
                    wait = WECHAT_BACKOFF[i] if i < len(WECHAT_BACKOFF) else 60
                    print(f"[WARN] 微信限频，等待 {wait}s 后重试 ({i+1}/{WECHAT_MAX_RETRIES})",
                          file=sys.stderr)
                    time.sleep(wait)
                    continue
                if errcode == 45009:  # 接口调用频率限制
                    wait = WECHAT_BACKOFF[i] if i < len(WECHAT_BACKOFF) else 60
                    time.sleep(wait)
                    continue
                return False, f"wechat errcode={errcode} {errmsg}"
            return False, f"wechat HTTP {resp.status_code}"
        except Exception as e:
            err = str(e)
            if "rate" in err.lower() and "limit" in err.lower():
                wait = WECHAT_BACKOFF[i] if i < len(WECHAT_BACKOFF) else 60
                time.sleep(wait)
                continue
            if i < WECHAT_MAX_RETRIES - 1:
                time.sleep(WECHAT_BACKOFF[i] if i < len(WECHAT_BACKOFF) else 30)
                continue
            return False, f"wechat exception: {e}"

    return False, f"wechat rate limited after {WECHAT_MAX_RETRIES} retries"


def send_generic(text: str) -> tuple[bool, str]:
    """通用 webhook（兜底通道）"""
    url = os.getenv("HERMES_WEBHOOK_URL", "")
    if not url:
        return False, "HERMES_WEBHOOK_URL not set"
    try:
        resp = requests.post(url, json={"text": text}, timeout=15)
        if resp.status_code == 200:
            return True, "generic ok"
        return False, f"generic HTTP {resp.status_code}"
    except Exception as e:
        return False, f"generic exception: {e}"


def push_to_all_channels(text: str, kind: str, force: bool = False) -> dict[str, str]:
    """推送到所有已配置通道，各通道独立隔离"""
    state = load_push_state()
    state_key = f"{today_str()}_{kind}"
    results = {}

    channels = [
        ("feishu", send_feishu, os.getenv("FEISHU_WEBHOOK_URL")),
        ("wechat", send_wechat, os.getenv("WECOM_WEBHOOK_URL")),
        ("generic", send_generic, os.getenv("HERMES_WEBHOOK_URL")),
    ]

    for ch_name, send_func, env_url in channels:
        if not env_url:
            continue

        ch_key = f"{state_key}_{ch_name}"
        # 去重：已成功推送的通道跳过
        if not force and state.get(ch_key) == "success":
            print(f"[跳过] {ch_name} 今日已推送成功", file=sys.stderr)
            results[ch_name] = "skipped (already sent)"
            continue
        # 限频失败的不重试（除非 --force）
        if not force and state.get(ch_key, "").startswith("failed_rate"):
            print(f"[跳过] {ch_name} 今日限频失败，不再重试", file=sys.stderr)
            results[ch_name] = "skipped (rate limited earlier)"
            continue

        ok, detail = send_func(text)
        results[ch_name] = "success" if ok else f"failed: {detail}"
        state[ch_key] = results[ch_name]
        if ok:
            print(f"[完成] {ch_name} 推送成功", file=sys.stderr)
        else:
            print(f"[失败] {ch_name}: {detail}", file=sys.stderr)

    save_push_state(state)
    return results


# push_state.json 读写
def load_push_state() -> dict:
    path = PUSH_DIR / "push_state.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_push_state(state: dict):
    path = PUSH_DIR / "push_state.json"
    try:
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[WARN] 写入 push_state 失败: {e}", file=sys.stderr)


def send_or_save(text: str, kind: str, force: bool = False, do_send: bool = True,
                 dedup_key: str = "") -> int:
    h = msg_hash(text)
    report_path = PUSH_DIR / f"{kind}_report.md"
    pending_path = PUSH_DIR / f"pending_{kind}_report.md"

    # 始终落盘
    if not write_file(report_path, text):
        append_log(kind, h, False, "write failed", dedup_key)
        return 3

    # 去重：业务键优先，hash 兜底
    if not force:
        if dedup_key and already_sent_by_key(kind, dedup_key):
            print(f"[跳过] 今日已发送相同 {kind} 消息（dedup_key={dedup_key}）")
            return 0
        if already_sent(kind, h):
            print(f"[跳过] 今日已发送相同 {kind} 消息")
            return 0

    if not do_send:
        try:
            print(text)
        except UnicodeEncodeError:
            print(text.encode("utf-8", errors="replace").decode("utf-8", errors="replace"))
        append_log(kind, h, True, "write only", dedup_key)
        return 0

    # 多通道推送（各通道独立隔离）
    results = push_to_all_channels(text, kind, force)
    success_count = sum(1 for v in results.values() if v == "success" or v.startswith("skipped"))
    fail_count = len(results) - success_count

    if success_count > 0:
        if pending_path.exists():
            pending_path.unlink()
        append_log(kind, h, True, f"channels: {results}", dedup_key)
        print(f"[完成] {kind} 推送: {results}")
        return 0

    # 全部通道失败
    write_file(pending_path, text)
    append_log(kind, h, False, f"all channels failed: {results}", dedup_key)
    print(f"[失败] {kind} 全部通道推送失败，已落盘: {pending_path}")
    return 2


# ═══════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Hermes 推送")
    parser.add_argument("--mode", choices=["daily", "predict", "review"], default="daily")
    parser.add_argument("--lottery", choices=["all", "pls", "d3", "kl8"], default="all",
                        help="彩种（默认all=排列三+福彩3D+快乐8）")
    parser.add_argument("--write-only", action="store_true", help="只生成不推送")
    parser.add_argument("--force", action="store_true", help="忽略今日去重，强制发送")
    parser.add_argument("--stdout", action="store_true",
                        help="只输出正文到stdout（供Hermes deliver=origin推送），日志走stderr")
    parser.add_argument("--complete-only", action="store_true",
                        help="复盘：两彩种都齐全才输出（21:35/22:05用）")
    parser.add_argument("--final-check", action="store_true",
                        help="复盘：未齐输出兜底通知（23:10用）")
    parser.add_argument("--dedup-key", default="",
                        help="业务去重键（job 层计算后传入，优先级高于自动计算）")
    args = parser.parse_args()

    lottery = args.lottery
    kind = f"{args.mode}_{lottery}" if lottery != "all" else args.mode

    # 计算业务去重键（按期号，不受文本微小变化影响）
    # --dedup-key 显式传入时优先使用；否则自动从数据文件推断
    dedup_key = args.dedup_key
    if not dedup_key and args.mode == "predict":
        if lottery == "kl8":
            pred = read_json(KL8_OUTPUT_DIR / "kl8_predict_latest.json")
            dedup_key = f"kl8_predict:{pred.get('predicted_issue', '?')}"
        else:
            pls = read_json(PRED_DIR / "latest_pls.json")
            d3 = read_json(PRED_DIR / "latest_d3.json")
            dedup_key = f"predict:{today_str()}:{pls.get('预测期号','?')}:{d3.get('预测期号','?')}"
    elif not dedup_key and args.mode == "review":
        if lottery == "kl8":
            rev = read_json(KL8_OUTPUT_DIR / "kl8_review_latest.json")
            dedup_key = f"kl8_review:{rev.get('issue', '?')}"
        else:
            rows = pick_latest_review(read_review_csv())
            issues = {}
            for row in rows:
                lotto = row.get("彩种", "")
                issue = "".join(c for c in row.get("期号", "") if c.isdigit())
                issues[lotto] = issue
            dedup_key = f"review:{today_str()}:{issues.get('排列三','?')}:{issues.get('福彩3D','?')}"

    if args.mode == "predict":
        if lottery == "kl8":
            text = build_kl8_predict_message()
        elif lottery in ("pls", "d3", "all"):
            text = build_predict_message()
        else:
            text = build_daily_message()
    elif args.mode == "review":
        if lottery == "kl8":
            text = build_kl8_review_message()
        elif lottery in ("pls", "d3", "all"):
            ready, ready_msg = check_review_ready(args.lottery)
            if not ready:
                if args.final_check:
                    text = f"⚠️ 无法完成复盘\n\n{ready_msg}\n\n请检查数据源是否正常更新。"
                    if args.stdout:
                        print(text)
                    sys.exit(0)
                print(f"[跳过] {ready_msg}", file=sys.stderr)
                sys.exit(0)
            text = build_review_message(args.lottery)
        else:
            text = build_daily_message()
    else:
        text = build_daily_message()

    if args.stdout:
        if not text.strip():
            print(f"[跳过] 无推送内容（{kind}）", file=sys.stderr)
            sys.exit(0)
        report_path = PUSH_DIR / f"{kind}_report.md"
        write_file(report_path, text)

        # 复盘报告按期号归档（避免日期覆盖导致旧复盘丢失）
        if kind == "review" and lottery in ("pls", "d3", "all"):
            try:
                rows = pick_latest_review(read_review_csv())
                issues = {}
                for row in rows:
                    lotto = row.get("彩种", "")
                    issue = row.get("期号", "")
                    if lotto and issue:
                        issues[lotto] = issue
                pls_i = issues.get("排列三", "unknown")
                d3_i = issues.get("福彩3D", "unknown")
                archive_dir = PUSH_DIR / "reviews" / today_str()
                archive_dir.mkdir(parents=True, exist_ok=True)
                archive_path = archive_dir / f"review_pls{pls_i}_d3{d3_i}.md"
                write_file(archive_path, text)
            except Exception:
                pass  # 归档失败不阻塞推送

        h = msg_hash(text)
        # 去重：业务键优先
        if not args.force:
            if dedup_key and already_sent_by_key(kind, dedup_key):
                print(f"[跳过] 今日已推送过（dedup_key={dedup_key}）", file=sys.stderr)
                sys.exit(0)
            if already_sent(kind, h):
                print(f"[跳过] 今日已推送过相同内容", file=sys.stderr)
                sys.exit(0)
        if not acquire_push_lock(kind, h, timeout=5.0):
            print(f"[跳过] 推送锁获取失败（可能正在推送中）", file=sys.stderr)
            sys.exit(0)
        try:
            # 再次检查（持有锁后二次确认）
            if not args.force:
                if dedup_key and already_sent_by_key(kind, dedup_key):
                    print(f"[跳过] 二次检查已推送过（dedup_key={dedup_key}）", file=sys.stderr)
                    sys.exit(0)
                if already_sent(kind, h):
                    print(f"[跳过] 二次检查已推送过", file=sys.stderr)
                    sys.exit(0)
            # 日志包含内容长度和预览摘要
            preview = text.replace("\n", "\\n")[:60]
            append_log(kind, h, True,
                       f"hermes deliver=origin | len={len(text)} | preview={preview}",
                       dedup_key)
            print(text)
        finally:
            release_push_lock(kind, h)
        sys.exit(0)

    code = send_or_save(text, kind=kind, force=args.force, do_send=not args.write_only,
                        dedup_key=dedup_key)
    sys.exit(code)


if __name__ == "__main__":
    main()
