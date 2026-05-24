#!/usr/bin/env python3
"""
人工开奖修正应用脚本
====================
读取 data/manual/draw_overrides.csv，将 enabled=1 的修正数据写入对应原始 CSV。

用法：
    python scripts/apply_draw_overrides.py          # 应用所有 enabled=1 的修正
    python scripts/apply_draw_overrides.py --dry-run  # 只检查不修改

设计：
- 不改动原始抓取逻辑，只修补 raw CSV
- 每次覆盖写入 override_audit.jsonl 审计日志
- enabled=0 的行被忽略（保留修正历史但不生效）
"""

import argparse
import csv
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OVERRIDE_PATH = BASE / "data" / "manual" / "draw_overrides.csv"
AUDIT_PATH = BASE / "data" / "manual" / "override_audit.jsonl"

RAW_PLS = BASE / "data" / "raw" / "pls_raw.csv"
RAW_D3 = BASE / "data" / "raw" / "d3_raw.csv"
KL8_HISTORY = BASE / "data" / "kl8" / "kl8_history.csv"
KL8_LATEST = BASE / "data" / "kl8" / "kl8_latest.json"

CN_TZ = timezone(timedelta(hours=8))

RAW_MAP = {
    "pls": {"path": RAW_PLS, "issue_col": "期号", "num_col": "号码"},
    "d3": {"path": RAW_D3, "issue_col": "期号", "num_col": "号码"},
    "kl8": {"path": KL8_HISTORY, "issue_col": "issue", "num_col": "numbers"},
}


def now_ts() -> str:
    return datetime.now(CN_TZ).strftime("%Y-%m-%dT%H:%M:%S%z")


def load_overrides():
    """读取修正表，返回 enabled=1 的行列表。"""
    if not OVERRIDE_PATH.exists():
        return []
    rows = []
    with open(OVERRIDE_PATH, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("enabled", "").strip() == "1":
                rows.append(row)
    return rows


def append_audit(lottery: str, issue: str, draw: str, action: str, detail: str = ""):
    """追加审计日志。"""
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "time": now_ts(),
        "lottery": lottery,
        "issue": issue,
        "draw": draw,
        "action": action,
        "detail": detail,
    }
    with open(AUDIT_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def apply_raw_csv(lottery: str, issue: str, draw: str, dry_run: bool = False) -> bool:
    """将修正数据写入原始 CSV。返回 True=成功。"""
    cfg = RAW_MAP.get(lottery)
    if not cfg:
        print(f"  [WARN] 未知彩种: {lottery}", file=sys.stderr)
        return False

    path = cfg["path"]
    issue_col = cfg["issue_col"]
    num_col = cfg["num_col"]

    if not path.exists():
        print(f"  [WARN] 原始文件不存在: {path}", file=sys.stderr)
        return False

    # 读取全部行
    rows = []
    found = False
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            if str(row.get(issue_col, "")).strip() == str(issue).strip():
                old_draw = row.get(num_col, "")
                row[num_col] = draw
                found = True
                print(f"  {'[DRY-RUN]' if dry_run else '[OK]'} "
                      f"{lottery} {issue}: {old_draw} → {draw}"
                      f"{' (新增)' if not found else ''}", file=sys.stderr)
            rows.append(row)

    # 如果期号不存在，追加一行
    if not found:
        new_row = {k: "" for k in fieldnames}
        new_row[issue_col] = issue
        new_row[num_col] = draw
        rows.insert(0, new_row)  # 新开奖放最前面
        print(f"  {'[DRY-RUN]' if dry_run else '[OK]'} "
              f"{lottery} {issue}: (新增) → {draw}", file=sys.stderr)

    if dry_run:
        return True

    # 写回
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    action = "updated" if found else "appended"
    append_audit(lottery, issue, draw, action, f"dry_run={dry_run}")
    return True


def apply_kl8_latest(issue: str, draw: str, dry_run: bool = False) -> bool:
    """同步更新 kl8_latest.json。"""
    if not KL8_LATEST.exists():
        return True
    import json as _json
    try:
        data = _json.loads(KL8_LATEST.read_text(encoding="utf-8"))
        if str(data.get("issue", "")) == str(issue):
            if dry_run:
                print(f"  [DRY-RUN] kl8_latest {issue}: "
                      f"{data.get('numbers','')} → {draw}", file=sys.stderr)
                return True
            data["numbers"] = draw
            KL8_LATEST.write_text(_json.dumps(data, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
            print(f"  [OK] kl8_latest {issue} 同步更新", file=sys.stderr)
    except Exception as e:
        print(f"  [WARN] kl8_latest 更新失败: {e}", file=sys.stderr)
    return True


def main():
    parser = argparse.ArgumentParser(description="应用人工开奖修正")
    parser.add_argument("--dry-run", action="store_true", help="只检查不修改")
    args = parser.parse_args()

    overrides = load_overrides()
    if not overrides:
        print("  无待应用的人工修正（draw_overrides.csv 为空或无 enabled=1 行）", file=sys.stderr)
        return

    print(f"\n  应用人工开奖修正 {'[DRY-RUN]' if args.dry_run else ''}", file=sys.stderr)
    print(f"  {'─'*40}", file=sys.stderr)

    applied = 0
    for row in overrides:
        lottery = row.get("lottery", "").strip()
        issue = row.get("issue", "").strip()
        draw = row.get("draw", "").strip()
        if not lottery or not issue or not draw:
            print(f"  [WARN] 跳过不完整行: {row}", file=sys.stderr)
            continue

        ok = apply_raw_csv(lottery, issue, draw, args.dry_run)
        if ok:
            applied += 1
            # KL8 额外同步 latest JSON
            if lottery == "kl8":
                apply_kl8_latest(issue, draw, args.dry_run)

    print(f"  {'─'*40}", file=sys.stderr)
    print(f"  应用完成: {applied}/{len(overrides)} 条修正", file=sys.stderr)


if __name__ == "__main__":
    main()
