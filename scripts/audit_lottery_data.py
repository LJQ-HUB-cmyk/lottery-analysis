#!/usr/bin/env python3
"""数据审计脚本：检查 PLS/D3 原始开奖数据与特征数据是否存在明显问题。

用法：
  python scripts/audit_lottery_data.py --lottery pls
  python scripts/audit_lottery_data.py --lottery d3
  python scripts/audit_lottery_data.py --lottery all
"""

import argparse
import json
import re
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
OUT_DIR = BASE_DIR / "output" / "audit"


def _norm_issue(x):
    if pd.isna(x):
        return ""
    return str(x).strip()


def _norm_number(x):
    if pd.isna(x):
        return ""
    s = str(x).strip()
    if re.fullmatch(r"\d{1,3}", s):
        return s.zfill(3)
    return s


def audit_raw(lottery: str) -> dict:
    path = RAW_DIR / f"{lottery}_raw.csv"
    result = {
        "lottery": lottery,
        "raw_path": str(path.relative_to(BASE_DIR)),
        "exists": path.exists(),
        "errors": [],
        "warnings": [],
        "stats": {},
    }

    if not path.exists():
        result["errors"].append(f"原始文件不存在: {path}")
        return result

    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    result["stats"]["raw_rows"] = int(len(df))

    required = ["期号", "日期", "号码"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        result["errors"].append(f"缺少必要字段: {missing}")
        return result

    df["期号_norm"] = df["期号"].map(_norm_issue)
    df["号码_norm"] = df["号码"].map(_norm_number)
    df["日期_norm"] = df["日期"].fillna("").astype(str).str.strip()

    empty_issue = df[df["期号_norm"] == ""]
    if len(empty_issue):
        result["errors"].append(f"存在空期号: {len(empty_issue)} 行")

    empty_date = df[df["日期_norm"] == ""]
    if len(empty_date):
        result["warnings"].append(f"存在空日期: {len(empty_date)} 行")

    bad_numbers = df[~df["号码_norm"].str.fullmatch(r"\d{3}", na=False)]
    if len(bad_numbers):
        result["errors"].append(f"存在非3位开奖号: {len(bad_numbers)} 行")

    dup_issue = df[df.duplicated("期号_norm", keep=False)]
    if len(dup_issue):
        result["warnings"].append(f"存在重复期号记录: {len(dup_issue)} 行")
        diff = (
            dup_issue.groupby("期号_norm")["号码_norm"]
            .nunique()
            .reset_index(name="号码种类数")
        )
        conflict = diff[diff["号码种类数"] > 1]
        if len(conflict):
            result["errors"].append(f"同一期号存在不同开奖号: {len(conflict)} 个期号")

    try:
        issues = pd.to_numeric(df["期号_norm"], errors="coerce").dropna().astype(int)
        if len(issues) >= 2:
            result["stats"]["min_issue"] = int(issues.min())
            result["stats"]["max_issue"] = int(issues.max())
            result["stats"]["unique_issues"] = int(issues.nunique())
    except Exception as exc:
        result["warnings"].append(f"期号数值化失败: {exc}")

    return result


def audit_processed(lottery: str) -> dict:
    path = PROCESSED_DIR / f"{lottery}_feat.csv"
    result = {
        "processed_path": str(path.relative_to(BASE_DIR)),
        "exists": path.exists(),
        "errors": [],
        "warnings": [],
        "stats": {},
    }

    if not path.exists():
        result["warnings"].append(f"特征文件不存在: {path}")
        return result

    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    result["stats"]["processed_rows"] = int(len(df))

    required = ["期数", "红球1", "红球2", "红球3", "和值", "跨度", "形态"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        result["errors"].append(f"特征文件缺少字段: {missing}")

    for col in ["红球1", "红球2", "红球3"]:
        if col in df.columns:
            bad = pd.to_numeric(df[col], errors="coerce")
            cnt = int(((bad < 0) | (bad > 9) | bad.isna()).sum())
            if cnt:
                result["errors"].append(f"{col} 存在非法数字: {cnt} 行")

    if "期数" in df.columns:
        issues = pd.to_numeric(df["期数"], errors="coerce")
        if issues.isna().any():
            result["errors"].append(f"特征文件存在无法数值化期数: {int(issues.isna().sum())} 行")

    return result


def audit_one(lottery: str) -> dict:
    raw = audit_raw(lottery)
    proc = audit_processed(lottery)
    ok = not raw["errors"] and not proc["errors"]
    return {"lottery": lottery, "ok": ok, "raw": raw, "processed": proc}


def main():
    parser = argparse.ArgumentParser(description="彩票数据审计")
    parser.add_argument("--lottery", choices=["pls", "d3", "all"], required=True)
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lotteries = ["pls", "d3"] if args.lottery == "all" else [args.lottery]
    final = {}

    for lt in lotteries:
        report = audit_one(lt)
        final[lt] = report

        print(f"\n=== {lt} 数据审计 ===")
        print("状态:", "OK" if report["ok"] else "存在错误")
        for item in report["raw"]["errors"] + report["processed"]["errors"]:
            print("  [ERROR]", item)
        for item in report["raw"]["warnings"] + report["processed"]["warnings"]:
            print("  [WARN]", item)

        out = OUT_DIR / f"{lt}_audit_latest.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("  保存:", out)

    merged = OUT_DIR / "audit_latest.json"
    merged.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
