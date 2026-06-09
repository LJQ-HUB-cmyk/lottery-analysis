"""快乐8 API 路由。"""

from pathlib import Path

from fastapi import APIRouter

from web.routes.helpers import read_json, read_kl8_review_csv

BASE = Path(__file__).resolve().parent.parent.parent
router = APIRouter()


@router.get("/predict")
def get_predict():
    return read_json(BASE / "output" / "kl8" / "kl8_predict_latest.json")


@router.get("/review")
def get_review():
    return read_json(BASE / "output" / "kl8" / "kl8_review_latest.json")


@router.get("/metrics")
def get_metrics():
    return read_json(BASE / "output" / "kl8" / "kl8_metrics.json")


@router.get("/stats")
def get_stats():
    return read_json(BASE / "output" / "kl8" / "kl8_stats.json")


@router.get("/history")
def get_history():
    return read_kl8_review_csv()[-30:]
