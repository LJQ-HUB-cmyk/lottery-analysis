"""排列三 API 路由。"""

from pathlib import Path

from fastapi import APIRouter

from web.routes.helpers import read_json, read_review_csv

BASE = Path(__file__).resolve().parent.parent.parent
router = APIRouter()


@router.get("/predict")
def get_predict():
    """最新预测。"""
    return read_json(BASE / "output" / "predictions" / "latest_pls.json")


@router.get("/predict/{issue}")
def get_predict_by_issue(issue: str):
    """按期号查预测。"""
    return read_json(BASE / "output" / "predictions" / f"pls_predict_{issue}.json")


@router.get("/review")
def get_review():
    """最新复盘对比。"""
    return read_json(BASE / "output" / "reports" / "pls_compare_latest.json")


@router.get("/history")
def get_history():
    """最近 30 期复盘记录。"""
    rows = [r for r in read_review_csv() if r.get("彩种") == "排列三"]
    return rows[-30:]
