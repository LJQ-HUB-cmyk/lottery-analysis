#!/usr/bin/env python3
"""统一状态文件读写工具。所有 job 通过此模块写入 output/status/*.json。"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

CN_TZ = timezone(timedelta(hours=8))

STATUS_DIR = Path(__file__).resolve().parent.parent.parent / "output" / "status"

# 状态枚举
READY = "ready"
PUSHED = "pushed"
SKIPPED_WAITING = "skipped_waiting"
SKIPPED_ALREADY_SENT = "skipped_already_sent"
ERROR = "error"


def write(name: str, data: dict[str, Any]) -> Path:
    """写入状态文件。自动创建目录并补时间戳。"""
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    data.setdefault("updated_at", datetime.now(CN_TZ).strftime("%Y-%m-%dT%H:%M:%S%z"))
    path = STATUS_DIR / f"{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read(name: str) -> dict[str, Any]:
    """读取状态文件。不存在或损坏返回 {}。"""
    path = STATUS_DIR / f"{name}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
