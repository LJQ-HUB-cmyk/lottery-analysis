#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
彩票分析 Web 仪表板启动器
==========================
启动命令：python run_web.py
访问地址：http://127.0.0.1:8000
"""

import argparse
import sys
import webbrowser
from pathlib import Path

# 确保项目根目录在 sys.path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description="彩票分析 Web 仪表板")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=8000, help="端口（默认 8000）")
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError:
        print("需要安装 uvicorn：pip install uvicorn")
        sys.exit(1)

    url = f"http://{args.host}:{args.port}"
    print(f"\n{'='*50}")
    print(f"  📊 彩票分析仪表板")
    print(f"  地址: {url}")
    print(f"{'='*50}\n")

    if not args.no_open and args.host in ("127.0.0.1", "localhost"):
        webbrowser.open(url)

    uvicorn.run("web.main:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
