#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
推送内容格式化模块
==================
从 hermes_push.py 拆分而来，负责预测/复盘/KL8/健康报告的内容生成。

用法（被 hermes_push.py 调用，不直接运行）：
    from push_formatter import build_predict_message, build_review_message, ...
"""

import csv
import json
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent.parent

PRED_DIR = BASE / "output" / "predictions"
KL8_OUTPUT_DIR = BASE / "output" / "kl8"
KL8_DATA_DIR = BASE / "data" / "kl8"
REVIEW_HISTORY = BASE / "output" / "reviews" / "review_history.csv"
KL8_REVIEW_HISTORY = KL8_OUTPUT_DIR / "kl8_review_history.csv"
REPORT_DIR = BASE / "output" / "reports"
CACHE_DIR = BASE / "data" / "cache"
PUSH_DIR = BASE / "output" / "push"

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

def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[WARN] JSON 读取失败: {path} | {e}", file=sys.stderr)
        return {}


def read_review_csv() -> list[dict[str, str]]:
    if not REVIEW_HISTORY.exists():
        return []
    try:
        with REVIEW_HISTORY.open("r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except Exception as e:
        print(f"[WARN] review_history 读取失败: {e}", file=sys.stderr)
        return []


def parse_bool(val: str) -> bool:
    return str(val).strip().lower() in {"true", "1", "yes", "y", "是", "命中", "✅"}


def _get_hit(row: dict, field: str) -> bool:
    """读取命中字段，兼容 Top10 和 Top30，处理 NaN/空值。"""
    for f in [f"{field}Top10", f"{field}Top30"]:
        val = row.get(f)
        if val is not None and str(val).strip().lower() not in ("nan", "none", "", "-"):
            return parse_bool(val)
    # 回退：从 命中范围 推断
    hit_range = str(row.get("命中范围", "")).strip()
    if hit_range in ("Top5", "Top10", "Top30"):
        return True
    return False


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


# ── 数字计算工具 ──────────────────────────────────────

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


def normalize_strategy_name(name: str) -> str:
    """统一策略展示名称。"""
    mapping = {"默认": "标准", "default": "标准", "standard": "标准",
               "稳健": "稳健", "conservative": "稳健",
               "多样性": "多样性", "diversity": "多样性",
               "auto_tuned": "自动调参",
               "ensemble": "融合策略"}
    return mapping.get(name, name)


# ── 号码提取工具 ──────────────────────────────────────

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
    """从预测 JSON 提取 TopN 号码列表。依次尝试 Top10/Top20/Top10 字段。"""
    if not data:
        return []
    summary = data.get("摘要", {})
    nums = (
        summary.get("Top10号码")
        or summary.get("Top10号码")
        or summary.get("Top10号码")
        or []
    )
    return [str(x).zfill(3) for x in nums[:n]]


def top_digits(recommends: list, k: int = 5) -> str:
    """从 Top10 推荐里统计数字频率，取前 k 个高频数字。"""
    cnt = Counter()
    for item in (recommends or [])[:30]:
        num = item.get("号码", "") if isinstance(item, dict) else str(item)
        for d in str(num).zfill(3):
            if d.isdigit():
                cnt[d] += 1
    return "".join(d for d, _ in cnt.most_common(k))


def check_group_hit(digits_pool: str, draw: str) -> tuple[bool, list[str]]:
    """检查开奖号码是否全部落在数字池内。"""
    draw_set = set(str(draw).zfill(3))
    pool_set = set(digits_pool)
    missing = draw_set - pool_set
    return len(missing) == 0, sorted(missing)


def missing_digits_from_pool(actual_num, pool):
    actual_set = set(str(actual_num).zfill(3))
    pool_set = set(str(pool))
    return sorted(actual_set - pool_set)


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


# ── 统计缓存 ─────────────────────────────────────────

def load_stats_cache(lottery: str) -> dict:
    """加载统计缓存"""
    path = CACHE_DIR / f"{lottery}_stats_latest.json"
    return read_json(path)


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
    """读取 review_history.csv → 拼接升级版复盘"""
    rows = pick_latest_review(read_review_csv())
    if not rows:
        return "【昨日复盘】\n暂无复盘数据"

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

        strategy_results = []
        best_strategy = ""
        best_score = 9999

        for item in items:
            st = item.get("策略", "default")
            sum_err = safe_int(item.get("Top1和值误差"), 99)
            span_err = safe_int(item.get("Top1跨度误差"), 99)
            form_ok = parse_bool(item.get("Top1形态一致", ""))
            score = sum_err + span_err
            direct_hit = _get_hit(item, "直选命中")
            group_hit = _get_hit(item, "组选命中")

            strategy_results.append({
                "name": st, "sum_err": sum_err, "span_err": span_err,
                "score": score, "form_ok": form_ok,
                "direct_hit": direct_hit, "group_hit": group_hit,
            })
            if score < best_score:
                best_score = score
                best_strategy = st

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
#  核心观察格式化
# ═══════════════════════════════════════════

def format_observation(stats: dict, label: str, pred_data: dict = None) -> list[str]:
    """生成核心观察文本（紧凑结构版）"""
    if not stats:
        return ["暂无统计缓存"]

    w10 = stats.get("窗口", {}).get("近10期", {})
    w30 = stats.get("窗口", {}).get("近30期", {})

    lines = []

    high_sum_w10 = w10.get("高频和值", [])
    sum_range = w10.get("高频和值区间", "")
    high_span_w10 = w10.get("高频跨度", [])
    span_mean = w10.get("跨度均值", "?")

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

    lines.append("  形态倾向：组六为主，组三少量防守")

    # 奇偶/大小/连号（从 w30 读取，若有的话）
    odd_freq = w30.get("奇数频率", {})
    big_freq = w30.get("大号频率", {})
    if odd_freq:
        # 取出现最多的奇数个数
        top_odd = max(odd_freq, key=odd_freq.get) if odd_freq else "?"
        lines.append(f"  奇偶倾向：近30期最常见 {top_odd}奇{3-int(top_odd) if str(top_odd).isdigit() else '?'}偶")
    if big_freq:
        top_big = max(big_freq, key=big_freq.get) if big_freq else "?"
        lines.append(f"  大小倾向：近30期最常见 {top_big}大{3-int(top_big) if str(top_big).isdigit() else '?'}小")

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

    if pred_data:
        s = pred_data.get("摘要", {})
        p95_score = s.get("P95分数线")
        p95_count = s.get("P95候选数")
        if p95_score is not None:
            lines.append(f"  高分区：Top 5% 候选（≥{p95_score}分，{p95_count}注）")

    return lines


# ═══════════════════════════════════════════
#  今日预测格式化（升级版）
# ═══════════════════════════════════════════

def format_prediction_section(lottery: str, label: str) -> str:
    """升级版预测格式化"""
    path = PRED_DIR / f"latest_{lottery}.json"
    data = read_json(path)

    if not data:
        return f"【{label} 今日预测】\n暂无预测文件"

    issue = data.get("预测期号", "未知")
    top10 = extract_top10(data)

    stats = load_stats_cache(lottery)
    obs_lines = format_observation(stats, label, pred_data=data)

    # 多策略共振
    consensus_nums: dict[str, int] = {}
    for suffix in ["", "_conservative", "_diversity", "_auto_tuned", "_enhanced", "_ensemble"]:
        sp = PRED_DIR / f"latest_{lottery}{suffix}.json"
        sd = read_json(sp)
        if sd:
            for n in extract_top10(sd)[:10]:
                consensus_nums[n] = consensus_nums.get(n, 0) + 1

    consensus = sorted([(n, c) for n, c in consensus_nums.items() if c >= 2],
                       key=lambda x: (-x[1], x[0]))
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

    recommends = data.get("推荐", [])
    top_scores = {}
    for item in (recommends or [])[:30]:
        if isinstance(item, dict):
            n = str(item.get("号码", "")).zfill(3)
            top_scores[n] = item.get("总分", 0)

    top15 = list(top_scores.keys())[:15]
    primary = [n for n in triple if n in top15]
    if not primary and triple:
        primary = triple[:3]

    secondary = [n for n in double if n not in primary]
    rest_top10 = [n for n in top10 if n not in primary and n not in secondary]
    secondary.extend(rest_top10[:4 - len(secondary)])

    if primary:
        parts.append(f"\n重点关注：\n{' '.join(primary[:3])}")
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

        consensus_nums: dict[str, int] = {}
        for suffix in ["", "_conservative", "_diversity", "_auto_tuned", "_enhanced", "_ensemble"]:
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
#  健康报告格式化
# ═══════════════════════════════════════════

def is_recent(path: Path, hours: int = 12) -> bool:
    if not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) <= hours * 3600


def format_health_section(override_issues=None, lottery_filter: str = "all") -> str:
    """数据源状态。"""
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
#  近期策略表现
# ═══════════════════════════════════════════

def check_review_ready(lottery_filter: str = "all") -> tuple[bool, str]:
    """检查复盘数据是否就绪。"""
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

    rows = read_review_csv()
    if lottery_filter != "all":
        lotto_map = {"pls": "排列三", "d3": "福彩3D"}
        rows = [r for r in rows if r.get("彩种", "") == lotto_map.get(lottery_filter, "")]
    if rows:
        return True, ""

    return False, "无复盘数据（review_history 为空）"


def build_review_performance(lottery_filter: str = "all") -> str:
    """从 review_history 计算最近策略表现摘要。"""
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
                 "auto_tuned": "自动调参", "enhanced": "增强策略",
                 "ensemble": "融合策略"}
    for i, row in enumerate(rows):
        if row.get("策略", "") == "默认":
            rows[i]["策略"] = "标准"

    lotto_map = {"pls": "排列三", "d3": "福彩3D"}
    wanted = ["排列三", "福彩3D"] if lottery_filter == "all" else [lotto_map.get(lottery_filter, lottery_filter)]

    for lotto in wanted:
        parts.append(f"\n【{lotto}】")
        for st in ["default", "conservative", "diversity", "auto_tuned", "enhanced", "ensemble"]:
            records = lottery_data.get(lotto, {}).get(st, [])
            if not records:
                continue
            recent = records[-30:]
            total = len(recent)
            direct_hits = sum(1 for r in recent if _get_hit(r, "直选命中"))
            group_hits = sum(1 for r in recent if _get_hit(r, "组选命中"))
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


# ═══════════════════════════════════════════
#  复盘推送格式化
# ═══════════════════════════════════════════

def build_review_message(lottery_filter: str = "all") -> str:
    """生成复盘推送。"""
    rows = pick_latest_review(read_review_csv())
    if not rows:
        return "\n".join([
            "📊 开奖复盘｜推送日 " + today_str(),
            "",
            "暂无复盘数据",
        ])

    review_issues = {}
    for row in rows:
        lotto = row.get("彩种", "")
        issue = row.get("期号", "")
        if lotto and issue:
            review_issues[lotto] = issue

    pls_issue = review_issues.get("排列三", "?")
    d3_issue = review_issues.get("福彩3D", "?")

    lotto_map = {"pls": "排列三", "d3": "福彩3D"}
    if lottery_filter in lotto_map:
        wanted = [lotto_map[lottery_filter]]
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

        strategy_results = []
        default_recommends = []
        has_any_hit = False

        for st_key, st_label in [("default", "默认"), ("conservative", "稳健"),
                               ("diversity", "多样性"), ("auto_tuned", "自动调参"),
                               ("enhanced", "增强策略"), ("ensemble", "融合策略")]:
            item = next((r for r in items if r.get("策略", "") == st_key), None)
            if not item:
                continue

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

            direct_hit = _get_hit(item, "直选命中")
            group_hit = _get_hit(item, "组选命中")
            hit_num = str(item.get("命中号码", "")).zfill(3) if item.get("命中号码") else ""
            hit_rank = item.get("命中排名", "")
            hit_range = item.get("命中范围", "")
            display_name = normalize_strategy_name(st_label)

            top1 = top30[0] if top30 else ""

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

            if direct_hit:
                parts.append(f"🎯 {display_name}：{hit_range}直选命中  {hit_num}（第{hit_rank}名）")
            elif group_hit:
                parts.append(f"✅ {display_name}：{hit_range}组选命中  {hit_num}（第{hit_rank}名）")
            else:
                parts.append(f"❌ {display_name}：未命中")

            if ref_label:
                parts.append(f"  {ref_label}{ref_metrics}")

            if (direct_hit or group_hit) and top1 and top1 != hit_num:
                parts.append(f"  Top1参考：{top1}｜{format_metrics(top1, actual)}")

            if not direct_hit and not group_hit and top1:
                parts.append(f"  Top1：{top1}｜{ref_metrics}")

            parts.append("")

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
                "name": display_name, "st_key": st_key, "top30": top30,
                "hit": bool(direct_hit or group_hit), "hit_type": hit_type,
                "hit_label": str(hit_range) if (direct_hit or group_hit) else None,
                "hit_number": hit_num, "rank": hit_rank,
            })

        if default_recommends and actual and actual != "未知":
            gs = format_group_review_new(default_recommends, actual)
            if gs:
                parts.append(gs)
                parts.append("")

        if has_any_hit:
            best = None
            priority = {"direct": 0, "group_top5": 1, "group_top10": 2, "group_top30": 3}
            for r in strategy_results:
                if r["hit"]:
                    s = priority.get(r["hit_type"], 99)
                    if best is None or s < priority.get(best["hit_type"], 99):
                        best = r
            if best and best["top30"]:
                parts.append("━━━━━━━━━━━━━━")
                parts.append(f"命中策略 Top10｜{best['name']}")
                parts.append("━━━━━━━━━━━━━━")
                parts.append(format_number_grid(best["top30"], limit=30, line_size=5))
                parts.append("")
        else:
            parts.append("━━━━━━━━━━━━━━")
            parts.append("未命中策略 Top10参考")
            parts.append("━━━━━━━━━━━━━━")
            for r in strategy_results:
                if r["top30"]:
                    parts.append(f"{r['name']}：")
                    parts.append(format_number_grid(r["top30"], limit=10, line_size=5))
                    parts.append("")

    override_issues = {}
    for lotto in wanted:
        items = grouped.get(lotto, [])
        if items:
            actual = items[0].get("开奖号码", "未知")
            issue = items[0].get("期号", "未知")
            lt_key = "pls" if lotto == "排列三" else "d3"
            override_issues[lt_key] = {"issue": issue, "number": actual}

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
#  预测推送格式化
# ═══════════════════════════════════════════

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


# ═══════════════════════════════════════════
#  快乐8 (KL8) 推送格式化
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

    target = str(pred.get("predicted_issue", "")).strip()
    review_issue = str(data.get("issue", "")).strip()
    if not target or review_issue != target:
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

    review_rows = pick_latest_review(read_review_csv())
    if review_rows:
        review_issues = {}
        for row in review_rows:
            lotto = row.get("彩种", "")
            issue = row.get("期号", "")
            review_issues[lotto] = issue
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
    if len(text) > 4000:
        text = text[:4000] + "\n\n……内容过长已截断"
    return text
