#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hermes 推送脚本（两段式，薄 CLI 入口）
========================================
内容格式化逻辑在 push_formatter.py，发送/去重/锁在 push_sender.py。

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
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

# 从拆分模块导入
from push_formatter import (  # noqa: E402
    build_daily_message,
    build_kl8_predict_message,
    build_kl8_review_message,
    build_predict_message,
    build_review_message,
    check_review_ready,
    pick_latest_review,
    read_json,
    read_review_csv,
    today_str,
)
from push_sender import (  # noqa: E402
    acquire_push_lock,
    already_sent,
    already_sent_by_key,
    append_log,
    msg_hash,
    release_push_lock,
    send_or_save,
    write_file,
)

PRED_DIR = BASE / "output" / "predictions"
KL8_OUTPUT_DIR = BASE / "output" / "kl8"
PUSH_DIR = BASE / "output" / "push"

CN_TZ = timezone(timedelta(hours=8))


def now() -> datetime:
    return datetime.now(CN_TZ)


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

    # 计算业务去重键
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

        # 复盘报告按期号归档
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
                pass

        h = msg_hash(text)
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
            if not args.force:
                if dedup_key and already_sent_by_key(kind, dedup_key):
                    print(f"[跳过] 二次检查已推送过（dedup_key={dedup_key}）", file=sys.stderr)
                    sys.exit(0)
                if already_sent(kind, h):
                    print(f"[跳过] 二次检查已推送过", file=sys.stderr)
                    sys.exit(0)
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
