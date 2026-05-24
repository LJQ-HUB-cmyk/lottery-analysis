#!/usr/bin/env python3
"""查看自动调参结果和灰度观察状态。"""

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
TUNING_DIR = BASE_DIR / "output" / "tuning"


def load_json(path):
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def print_one(lottery):
    path = TUNING_DIR / f"{lottery}_tuning_latest.json"
    data = load_json(path)

    print(f"\n=== {lottery.upper()} 自动调参状态 ===")
    if not data:
        print("  暂无调参报告")
        return

    print(f"  生成时间: {data.get('generated_at')}")
    print(f"  Best value: {data.get('best_value')}")
    print(f"  YAML: {data.get('yaml_path')}")

    stability = data.get("stability", {})
    print(f"  稳定性通过: {stability.get('pass')}")

    for win in ["50", "100", "200"]:
        if win not in stability:
            continue
        s = stability[win]
        print(f"  {win}期 | "
              f"直选 {s.get('direct_hits')}/{s.get('periods')}={s.get('direct_%')}% | "
              f"组选 {s.get('group_hits')}/{s.get('periods')}={s.get('group_%')}% | "
              f"和差 {s.get('avg_sum_diff')} | "
              f"跨差 {s.get('avg_span_diff')} | "
              f"连未 {s.get('max_miss')}")


def main():
    print_one("pls")
    print_one("d3")


if __name__ == "__main__":
    main()
