"""共享工具函数：读取 JSON/CSV 文件。"""

import csv
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent


def read_json(path):
    """读取 JSON 文件，不存在或损坏返回空字典。"""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_review_csv():
    """读取 review_history.csv，返回列表。"""
    path = BASE / "output" / "reviews" / "review_history.csv"
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def read_kl8_review_csv():
    """读取 kl8_review_history.csv，返回列表。"""
    path = BASE / "output" / "kl8" / "kl8_review_history.csv"
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []
