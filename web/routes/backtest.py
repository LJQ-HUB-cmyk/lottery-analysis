"""回测 API 路由。"""

from pathlib import Path

from fastapi import APIRouter

from web.routes.helpers import read_json

BASE = Path(__file__).resolve().parent.parent.parent
router = APIRouter()


@router.get("/pls")
def get_pls_backtest():
    """排列三回测结果。"""
    # 读取最新的回测文件
    bt_dir = BASE / "output" / "backtests"
    files = sorted(bt_dir.glob("pls_backtest_*.json"), reverse=True)
    if files:
        return read_json(files[0])
    return {}


@router.get("/d3")
def get_d3_backtest():
    """福彩3D回测结果。"""
    bt_dir = BASE / "output" / "backtests"
    files = sorted(bt_dir.glob("d3_backtest_*.json"), reverse=True)
    if files:
        return read_json(files[0])
    return {}


@router.get("/kl8")
def get_kl8_backtest():
    """快乐8回测结果。"""
    return read_json(BASE / "output" / "kl8" / "kl8_backtest.json")
