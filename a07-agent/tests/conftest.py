# AI-assisted
"""pytest 引导：保证 `from app...` 导入在任意工作目录下可用（rootdir=a07-agent）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
