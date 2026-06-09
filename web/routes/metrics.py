"""命中率统计 API 路由。"""

from pathlib import Path

from fastapi import APIRouter

from web.routes.helpers import read_json

BASE = Path(__file__).resolve().parent.parent.parent
METRICS_DIR = BASE / "output" / "metrics"

router = APIRouter()


@router.get("/pls")
def get_pls_metrics():
    return read_json(METRICS_DIR / "pls_metrics.json")


@router.get("/d3")
def get_d3_metrics():
    return read_json(METRICS_DIR / "d3_metrics.json")


@router.get("/pls/trend")
def get_pls_trend():
    path = METRICS_DIR / "pls_trend.json"
    if path.exists():
        import json
        return json.loads(path.read_text(encoding="utf-8"))
    return []


@router.get("/d3/trend")
def get_d3_trend():
    path = METRICS_DIR / "d3_trend.json"
    if path.exists():
        import json
        return json.loads(path.read_text(encoding="utf-8"))
    return []
