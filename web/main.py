#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
彩票分析 Web 仪表板
====================
FastAPI + Jinja2 + ECharts，从现有 JSON/CSV 文件读取数据。

启动：python run.py
访问：http://127.0.0.1:8000
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

BASE = Path(__file__).resolve().parent.parent
WEB_DIR = Path(__file__).resolve().parent

app = FastAPI(title="彩票分析仪表板")

# 静态文件 & 模板
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

# 注册路由
from web.routes import pls, d3, kl8, backtest, metrics  # noqa: E402

app.include_router(pls.router, prefix="/api/pls", tags=["排列三"])
app.include_router(d3.router, prefix="/api/d3", tags=["福彩3D"])
app.include_router(kl8.router, prefix="/api/kl8", tags=["快乐8"])
app.include_router(backtest.router, prefix="/api/backtest", tags=["回测"])
app.include_router(metrics.router, prefix="/api/metrics", tags=["命中率"])


# ── 页面路由 ─────────────────────────────────────────

@app.get("/")
async def index(request: Request):
    """首页：三个彩种概览"""
    from web.routes.helpers import read_json, read_review_csv
    from scripts.push_formatter import build_predict_message, build_review_message
    import csv

    # 加载预测数据
    pls_pred = read_json(BASE / "output" / "predictions" / "latest_pls.json")
    d3_pred = read_json(BASE / "output" / "predictions" / "latest_d3.json")
    kl8_pred = read_json(BASE / "output" / "kl8" / "kl8_predict_latest.json")

    # 加载最新复盘
    pls_compare = read_json(BASE / "output" / "reports" / "pls_compare_latest.json")
    d3_compare = read_json(BASE / "output" / "reports" / "d3_compare_latest.json")

    # 加载命中率指标
    metrics_dir = BASE / "output" / "metrics"
    pls_metrics = read_json(metrics_dir / "pls_metrics.json")
    d3_metrics = read_json(metrics_dir / "d3_metrics.json")

    # 计算命中率（从 review_history）
    history = read_review_csv()
    stats = {}
    for lt_name, lt_key in [("排列三", "pls"), ("福彩3D", "d3")]:
        rows = [r for r in history if r.get("彩种") == lt_name and r.get("策略") == "default"]
        recent = rows[-30:]
        n = len(recent) or 1
        direct = sum(1 for r in recent if str(r.get("直选命中Top10", r.get("直选命中Top30", ""))).lower() in ("true", "1"))
        group = sum(1 for r in recent if str(r.get("组选命中Top10", r.get("组选命中Top30", ""))).lower() in ("true", "1"))
        morph = sum(1 for r in recent if r.get("Top1形态一致", "").lower() in ("true", "1"))
        stats[lt_key] = {
            "n": len(recent),
            "direct_rate": round(direct / n * 100, 1),
            "group_rate": round(group / n * 100, 1),
            "morph_rate": round(morph / n * 100, 1),
        }

    # 生成推送预览文本
    try:
        push_predict = build_predict_message()
    except Exception:
        push_predict = "生成失败"
    try:
        push_review = build_review_message()
    except Exception:
        push_review = "生成失败"

    return templates.TemplateResponse(
        request=request, name="index.html",
        context={
            "pls_pred": pls_pred,
            "d3_pred": d3_pred,
            "kl8_pred": kl8_pred,
            "pls_compare": pls_compare,
            "pls_metrics": pls_metrics,
            "d3_metrics": d3_metrics,
            "d3_compare": d3_compare,
            "stats": stats,
            "push_predict": push_predict,
            "push_review": push_review,
        },
    )


@app.get("/lottery/{lottery}")
async def lottery_page(request: Request, lottery: str):
    """彩种详情页：预测 + 复盘 + 历史"""
    if lottery not in ("pls", "d3"):
        return templates.TemplateResponse(request=request, name="404.html", status_code=404)

    from web.routes.helpers import read_json, read_review_csv
    from scripts.push_formatter import format_prediction_section, build_review_message

    pred = read_json(BASE / "output" / "predictions" / f"latest_{lottery}.json")
    compare = read_json(BASE / "output" / "reports" / f"{lottery}_compare_latest.json")

    history = read_review_csv()
    lt_name = "排列三" if lottery == "pls" else "福彩3D"
    lt_history = [r for r in history if r.get("彩种") == lt_name]

    # 推送预览
    try:
        push_pred = format_prediction_section(lottery, lt_name)
    except Exception:
        push_pred = "生成失败"
    try:
        push_review = build_review_message(lottery)
    except Exception:
        push_review = "生成失败"

    return templates.TemplateResponse(
        request=request, name="lottery.html",
        context={
            "lottery": lottery,
            "lottery_name": lt_name,
            "pred": pred,
            "compare": compare,
            "history": lt_history[-30:],
            "push_pred": push_pred,
            "push_review": push_review,
        },
    )


@app.get("/kl8")
async def kl8_page(request: Request):
    """快乐8页面"""
    from web.routes.helpers import read_json

    pred = read_json(BASE / "output" / "kl8" / "kl8_predict_latest.json")
    review = read_json(BASE / "output" / "kl8" / "kl8_review_latest.json")
    metrics = read_json(BASE / "output" / "kl8" / "kl8_metrics.json")
    stats = read_json(BASE / "output" / "kl8" / "kl8_stats.json")

    return templates.TemplateResponse(
        request=request, name="kl8.html",
        context={
            "pred": pred,
            "review": review,
            "metrics": metrics,
            "stats": stats,
        },
    )


@app.get("/backtest")
async def backtest_page(request: Request):
    """回测中心"""
    from web.routes.helpers import read_json

    # 回测文件带时间戳，取最新的
    bt_dir = BASE / "output" / "backtests"
    pls_files = sorted(bt_dir.glob("pls_backtest_*.json"), reverse=True)
    d3_files = sorted(bt_dir.glob("d3_backtest_*.json"), reverse=True)
    pls_bt = read_json(pls_files[0]) if pls_files else {}
    d3_bt = read_json(d3_files[0]) if d3_files else {}
    kl8_bt = read_json(BASE / "output" / "kl8" / "kl8_backtest.json")

    return templates.TemplateResponse(
        request=request, name="backtest.html",
        context={
            "pls_bt": pls_bt,
            "d3_bt": d3_bt,
            "kl8_bt": kl8_bt,
        },
    )
