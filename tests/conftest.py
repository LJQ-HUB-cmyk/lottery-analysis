#!/usr/bin/env python3
"""共享测试配置：确保 scripts/ 在 import 路径中。"""
import sys
from pathlib import Path

# 项目根目录
ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

# 确保 scripts/ 可以被 import
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
