#!/usr/bin/env python3
"""快乐8数据抓取 —— 官方API拉取历史开奖 + 标准化校验 + 数据完整性检查"""
import argparse
import csv
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.kl8.common import parse_kl8_numbers

import requests

BASE = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE / "data" / "kl8"

CN_TZ = timezone(timedelta(hours=8))


def validate(numbers: list[int]) -> None:
    """严格校验：20个号码、1-80、不重复"""
    if len(numbers) != 20:
        raise ValueError(f"应为20个号码，实际{len(numbers)}")
    if min(numbers) < 1 or max(numbers) > 80:
        raise ValueError(f"号码范围1-80，实际{numbers}")
    if len(set(numbers)) != 20:
        raise ValueError(f"号码有重复: {numbers}")


def fetch_official(page_size: int = 30, max_pages: int = 10) -> list[dict]:
    """从官方API拉取快乐8开奖数据"""
    url = "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.cwl.gov.cn/"}
    all_rows = []

    for page in range(max_pages):
        params = {
            "name": "kl8", "issueCount": "", "issueStart": "", "issueEnd": "",
            "dayStart": "", "dayEnd": "", "pageNo": page + 1,
            "pageSize": page_size, "week": "", "systemType": "PC",
        }
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=15)
            if resp.status_code != 200:
                print(f"[WARN] API返回{resp.status_code}，停止抓取", file=sys.stderr)
                break
            data = resp.json()
            items = data.get("result", [])
            if not items:
                break
            for item in items:
                code = item.get("code", "")
                red = item.get("red", "")
                date_raw = item.get("date", "")
                if not code or not red:
                    continue
                nums = [int(x) for x in red.split(",")]
                try:
                    validate(nums)
                except ValueError as e:
                    print(f"[WARN] 跳过异常号码 期号{code}: {e}", file=sys.stderr)
                    continue
                date_clean = date_raw.split("(")[0] if "(" in date_raw else date_raw
                all_rows.append({"issue": code, "date": date_clean, "numbers": sorted(nums)})
            if len(items) < page_size:
                break
        except Exception as e:
            print(f"[WARN] 抓取第{page+1}页失败: {e}", file=sys.stderr)
            break
    return all_rows


def save_history(rows: list[dict]) -> Path:
    p = DATA_DIR / "kl8_history.csv"
    existed = {}
    if p.exists():
        with open(p, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                existed[r["issue"]] = r
    for r in rows:
        existed[r["issue"]] = {"issue": r["issue"], "date": r["date"],
                               "numbers": " ".join(f"{n:02d}" for n in r["numbers"])}
    sorted_rows = sorted(existed.values(), key=lambda x: x["issue"], reverse=True)
    with open(p, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["issue", "date", "numbers"])
        w.writeheader()
        w.writerows(sorted_rows)
    return p


def save_latest(row: dict) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    p = DATA_DIR / "kl8_latest.json"
    data = {
        "lottery": "kl8", "issue": row["issue"], "date": row["date"],
        "numbers": row["numbers"],
        "fetched_at": datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S"),
    }
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def check_integrity() -> list[str]:
    """数据完整性检查：扫描历史CSV，返回问题列表"""
    p = DATA_DIR / "kl8_history.csv"
    if not p.exists():
        return ["kl8_history.csv 不存在"]
    with open(p, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return ["kl8_history.csv 为空"]
    warnings = []
    seen_issues = set()
    for r in rows:
        issue = r.get("issue", "")
        nums_str = r.get("numbers", "")
        nums = parse_kl8_numbers(nums_str) if nums_str.strip() else []
        try:
            validate(nums)
        except ValueError as e:
            warnings.append(f"期号{issue}数据异常: {e}")
        if issue in seen_issues:
            warnings.append(f"重复期号: {issue}")
        seen_issues.add(issue)

    sorted_issues = sorted(seen_issues, reverse=True)
    if sorted_issues:
        print(f"  📋 {len(sorted_issues)} 期数据，"
              f"范围 {sorted_issues[-1]} ~ {sorted_issues[0]}")
    else:
        print(f"  📋 0 期有效数据")
        return warnings

    # 缺期检测（按年份分组，避免跨年误报）
    if len(sorted_issues) >= 2:
        try:
            # 按年份分组检测
            from collections import defaultdict
            by_year = defaultdict(list)
            for issue in sorted_issues:
                year = issue[:4]
                by_year[year].append(int(issue))
            for year, issues_in_year in sorted(by_year.items()):
                if len(issues_in_year) >= 2:
                    first_y = max(issues_in_year)
                    last_y = min(issues_in_year)
                    expected_y = first_y - last_y + 1
                    if len(issues_in_year) < expected_y:
                        warnings.append(f"⚠️ {year}年缺期：应有{expected_y}期，实际{len(issues_in_year)}期")
        except (ValueError, IndexError):
            pass
    return warnings


def main():
    parser = argparse.ArgumentParser(description="快乐8数据抓取")
    parser.add_argument("--pages", type=int, default=3, help="抓取页数(每页30期)")
    parser.add_argument("--check", action="store_true", help="仅运行数据完整性检查")
    args = parser.parse_args()

    if args.check:
        warnings = check_integrity()
        if warnings:
            for w in warnings:
                print(w)
            sys.exit(2)
        print("✅ 数据完整性检查通过")
        sys.exit(0)

    rows = fetch_official(page_size=30, max_pages=args.pages)
    if not rows:
        print("[ERROR] 未抓取到任何数据", file=sys.stderr)
        sys.exit(2)

    hpath = save_history(rows)
    lpath = save_latest(rows[0])
    print(f"✅ 快乐8: {len(rows)} 期")
    print(f"   最新: {rows[0]['issue']} | "
          f"{' '.join(f'{n:02d}' for n in rows[0]['numbers'][:5])}...")
    print(f"   历史: {hpath}")
    print(f"   latest: {lpath}")

    # 抓取后顺便跑一次完整性检查
    warnings = check_integrity()
    if warnings:
        for w in warnings:
            print(w, file=sys.stderr)


if __name__ == "__main__":
    main()
