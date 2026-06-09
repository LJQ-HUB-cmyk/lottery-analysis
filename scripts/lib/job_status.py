#!/usr/bin/env python3
"""
统一任务状态管理
================
所有 job 通过此模块读写 output/status/*.json。
支持任务生命周期追踪：prediction → draw → review → push。

用法：
    from scripts.lib.job_status import TaskStatus, write, read

    # 创建任务
    task = TaskStatus("pls", 26151)
    task.set_prediction(path="predictions/pls_predict_26151.json")
    task.set_draw(actual="993")
    task.set_review(hit=True, hit_type="group", rank=5)
    task.set_push("predict")
    task.save()

    # 读取任务
    task = TaskStatus.load("pls", 26151)
    print(task.data["status"])  # "reviewed"
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

CN_TZ = timezone(timedelta(hours=8))
STATUS_DIR = Path(__file__).resolve().parent.parent.parent / "output" / "status"

# 状态枚举（兼容旧版）
READY = "ready"
PUSHED = "pushed"
SKIPPED_WAITING = "skipped_waiting"
SKIPPED_ALREADY_SENT = "skipped_already_sent"
ERROR = "error"

# 任务生命周期状态
STATUS_PREDICTION_DONE = "prediction_done"
STATUS_DRAW_WAITING = "waiting_draw"
STATUS_DRAW_DONE = "draw_done"
STATUS_REVIEW_DONE = "reviewed"
STATUS_PUSHED = "pushed"


def _now_str():
    return datetime.now(CN_TZ).strftime("%Y-%m-%dT%H:%M:%S%z")


class TaskStatus:
    """单个预测+复盘任务的生命周期管理。"""

    def __init__(self, lottery: str, issue: int):
        self.lottery = lottery
        self.issue = issue
        self.task_id = f"{lottery}_{issue}"
        self.path = STATUS_DIR / f"{self.task_id}.json"
        self.data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "task_id": self.task_id,
            "lottery": self.lottery,
            "issue": self.issue,
            "status": STATUS_DRAW_WAITING,
            "created_at": _now_str(),
            "prediction": {"generated": False, "pushed": False, "path": None},
            "draw": {"fetched": False, "actual": None},
            "review": {"generated": False, "pushed": False, "hit": False},
        }

    @classmethod
    def load(cls, lottery: str, issue: int) -> "TaskStatus":
        return cls(lottery, issue)

    def save(self):
        STATUS_DIR.mkdir(parents=True, exist_ok=True)
        self.data["updated_at"] = _now_str()
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ── 生命周期操作 ──────────────────────────────────────

    def set_prediction(self, path: str):
        """标记预测已生成。"""
        self.data["prediction"] = {
            "generated": True,
            "pushed": False,
            "path": path,
            "created_at": _now_str(),
        }
        self.data["status"] = STATUS_PREDICTION_DONE
        self.save()

    def set_prediction_pushed(self):
        """标记预测已推送。"""
        self.data["prediction"]["pushed"] = True
        self.data["prediction"]["pushed_at"] = _now_str()
        if self.data["status"] == STATUS_PREDICTION_DONE:
            self.data["status"] = STATUS_DRAW_WAITING
        self.save()

    def set_draw(self, actual: str):
        """标记开奖数据已获取。"""
        self.data["draw"] = {
            "fetched": True,
            "actual": actual,
            "fetched_at": _now_str(),
        }
        self.data["status"] = STATUS_DRAW_DONE
        self.save()

    def set_review(self, hit: bool, hit_type: str = "", rank: int = 0):
        """标记复盘已完成。"""
        self.data["review"] = {
            "generated": True,
            "pushed": False,
            "hit": hit,
            "hit_type": hit_type,
            "rank": rank,
            "reviewed_at": _now_str(),
        }
        self.data["status"] = STATUS_REVIEW_DONE
        self.save()

    def set_review_pushed(self):
        """标记复盘已推送。"""
        self.data["review"]["pushed"] = True
        self.data["review"]["pushed_at"] = _now_str()
        self.data["status"] = STATUS_PUSHED
        self.save()

    # ── 查询 ──────────────────────────────────────────────

    def is_prediction_done(self) -> bool:
        return self.data["prediction"]["generated"]

    def is_prediction_pushed(self) -> bool:
        return self.data["prediction"]["pushed"]

    def is_draw_fetched(self) -> bool:
        return self.data["draw"]["fetched"]

    def is_review_done(self) -> bool:
        return self.data["review"]["generated"]

    def is_review_pushed(self) -> bool:
        return self.data["review"]["pushed"]

    def get_actual(self) -> Optional[str]:
        return self.data["draw"].get("actual")

    def get_status(self) -> str:
        return self.data["status"]


# ── 兼容旧版 API ─────────────────────────────────────────

def write(name: str, data: dict[str, Any]) -> Path:
    """写入状态文件（兼容旧版 job 调用）。"""
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    data.setdefault("updated_at", _now_str())
    path = STATUS_DIR / f"{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read(name: str) -> dict[str, Any]:
    """读取状态文件（兼容旧版 job 调用）。"""
    path = STATUS_DIR / f"{name}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
