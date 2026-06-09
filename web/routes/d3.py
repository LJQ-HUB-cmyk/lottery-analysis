"""福彩3D API 路由。"""

from pathlib import Path

from fastapi import APIRouter

from web.routes.helpers import read_json, read_review_csv

BASE = Path(__file__).resolve().parent.parent.parent
router = APIRouter()


@router.get("/predict")
def get_predict():
    return read_json(BASE / "output" / "predictions" / "latest_d3.json")


@router.get("/predict/{issue}")
def get_predict_by_issue(issue: str):
    return read_json(BASE / "output" / "predictions" / f"d3_predict_{issue}.json")


@router.get("/review")
def get_review():
    return read_json(BASE / "output" / "reports" / "d3_compare_latest.json")


@router.get("/history")
def get_history():
    rows = [r for r in read_review_csv() if r.get("彩种") == "福彩3D"]
    return rows[-30:]
