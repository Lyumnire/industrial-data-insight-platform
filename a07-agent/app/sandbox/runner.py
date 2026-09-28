# AI-assisted
"""A6 沙箱 Python 分析执行器（P2a 计划 §Task 11.3 / docs/03 §3.3 A6 / 红线 R2）。

run_python(code, input_csv_path, timeout_s) -> SandboxResult：
- 子进程 = 当前解释器 + `-I -B` 运行固定包装器（_WRAPPER_TEMPLATE）；
  工作目录 = 系统临时目录下唯一子目录（前缀 a07_sandbox_），用后清理（含输入 CSV 副本）。
- 协议：包装器预置 `df = pd.read_csv(input.csv)`（无输入时为空 DataFrame）与 `result = {}`，
  用户代码在此命名空间 exec；结束后把 `result`（DataFrame→{columns, rows≤100}、numpy 标量→
  Python 标量、其余 str 兜底）与用户 print 的限幅尾巴打包为 JSON，写到真实 stdout 的
  `<<<RESULT>>>` 定界符之后，父进程解析。
- import 白名单钩子（pandas/numpy/json/math/statistics/datetime/re）：**用户代码**中
  白名单外的 import（含 `__import__()` 直呼）一律 ImportError（红线 R2）；pandas/numpy
  自身的延迟导入（如 numpy 内部 `import warnings`）不算用户代码，放行以免破坏其运行。
- 用户 print 经 _CappedStdout 限幅捕获（只保留末尾 STDOUT_CAP_CHARS 字符），
  大输出既不撑爆管道也不撑爆父进程内存，超出时在尾巴头部标注截断。
- 限额：Windows Job Object（内存 1GB + KILL_ON_JOB_CLOSE，见 limits_win.py；pywin32
  不可用/加入失败时降级为 timeout-only 并在 warnings 注明）+ timeout 墙钟强杀。
- 错误：stderr 取 Traceback 尾部拼为可读错误；超时给出明确提示。
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.sandbox.limits_win import create_job_limiter

logger = logging.getLogger("a07.sandbox")

RESULT_MARKER = "<<<RESULT>>>"
STDOUT_CAP_CHARS = 8192       # 用户 print 捕获上限（字符）
DEFAULT_TIMEOUT_SECONDS = 30.0
TEMP_PREFIX = "a07_sandbox_"
WRAPPER_FILE = "_a07_wrapper.py"
USER_CODE_FILE = "_a07_user_code.py"
INPUT_CSV_NAME = "input.csv"

ALLOWED_MODULES: tuple[str, ...] = (
    "pandas", "numpy", "json", "math", "statistics", "datetime", "re",
    # T-012（P2a §Task 12.2）：A7 ML 模板需要 sklearn/joblib 在沙箱内训练模型
    "sklearn", "joblib",
)
USER_CODE_FILENAME = "<a07-sandbox-user-code>"  # exec 伪文件名，供 import 钩子识别用户帧

_WRAPPER_TEMPLATE = '''# AI-assisted: A07 沙箱子进程包装器（由 app/sandbox/runner.py 生成，勿手工运行）
"""协议见 app/sandbox/runner.py 模块文档；本文件在 -I 隔离模式的子进程中执行。"""
import builtins as _builtins
import json as _json
import math as _math
import sys as _sys
from collections import deque as _deque

import numpy as _np
import pandas as _pd
import statistics as _statistics
import datetime as _datetime
import re as _re

_WORKDIR = _sys.argv[1]
_CODE_PATH = _sys.argv[2]
_INPUT_CSV = _sys.argv[3] if len(_sys.argv) > 3 and _sys.argv[3] != "-" else None
_STDOUT_CAP = @STDOUT_CAP@
_RESULT_MARKER = "@RESULT_MARKER@"
_USER_CODE_FILENAME = "@USER_FILENAME@"

for _stream in (_sys.stdout, _sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
_real_stdout = _sys.stdout


class _CappedStdout:
    """用户 print 的限幅捕获器：只保留末尾 _STDOUT_CAP 字符，防大输出撑爆管道。"""

    def __init__(self, cap: int) -> None:
        self._cap = cap
        self._buf = _deque()
        self._size = 0
        self._total = 0

    def write(self, s):
        s = str(s)
        self._total += len(s)
        if s:
            self._buf.append(s)
            self._size += len(s)
        while self._size > self._cap:
            overflow = self._size - self._cap
            head = self._buf[0]
            if len(head) <= overflow:
                self._buf.popleft()
                self._size -= len(head)
            else:
                self._buf[0] = head[overflow:]
                self._size -= overflow
        return len(s)

    def flush(self):
        return None

    def text(self) -> str:
        out = "".join(self._buf)
        if self._total > self._cap:
            out = "[沙箱] 标准输出超过 %d 字符上限，已截断（共输出 %d 字符）\\n%s" % (
                self._cap, self._total, out)
        return out


# ---- import 白名单钩子（红线 R2：用户代码白名单外一律 ImportError）----
# 只对"直接调用方是用户代码帧"的 import 强制白名单；pandas/numpy 内部的延迟导入
# （调用方是其自身模块）放行，否则沙箱会破坏其运行时（如 numpy 的 import warnings）。
_ALLOWED_MODULES = frozenset(@ALLOWED_MODULES@)
_USER_FILENAME = "@USER_FILENAME@"
_real_import = _builtins.__import__


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    root = str(name).split(".")[0]
    if root in _ALLOWED_MODULES:
        return _real_import(name, globals, locals, fromlist, level)
    caller = _sys._getframe(1)
    if caller is not None and caller.f_code.co_filename == _USER_FILENAME:
        raise ImportError(
            "沙箱白名单限制：禁止 import %r（仅允许 %s）"
            % (name, ", ".join(sorted(_ALLOWED_MODULES)))
        )
    return _real_import(name, globals, locals, fromlist, level)


_builtins.__import__ = _guarded_import

with open(_CODE_PATH, encoding="utf-8") as _f:
    _user_code = _f.read()

_sys.stdout = _CappedStdout(_STDOUT_CAP)


def _serialize(obj, _depth: int = 0):
    """result 的 JSON 化：DataFrame→{columns,rows≤100}、numpy 标量→Python 标量、其余 str 兜底。"""
    if _depth > 6:
        return str(obj)
    if obj is None or isinstance(obj, (bool, int, str)):
        return obj
    if isinstance(obj, float):
        return obj if _math.isfinite(obj) else None
    if isinstance(obj, _np.generic):
        return _serialize(obj.item(), _depth + 1)
    if isinstance(obj, _pd.DataFrame):
        frame = obj.head(100)
        rows = []
        for _, _row in frame.iterrows():
            rows.append({str(k): (None if _pd.isna(v) else _serialize(v, _depth + 1))
                         for k, v in _row.items()})
        return {"__type__": "dataframe", "columns": [str(c) for c in obj.columns],
                "rows": rows, "row_count": int(len(obj))}
    if isinstance(obj, _pd.Series):
        return _serialize(obj.tolist(), _depth + 1)
    if isinstance(obj, _np.ndarray):
        return _serialize(obj.tolist(), _depth + 1)
    if isinstance(obj, dict):
        return {str(k): _serialize(v, _depth + 1) for k, v in list(obj.items())[:1000]}
    if isinstance(obj, (list, tuple, set)):
        return [_serialize(v, _depth + 1) for v in list(obj)[:1000]]
    try:
        import datetime as _dt
        if isinstance(obj, (_dt.date, _dt.datetime, _dt.time)):
            return obj.isoformat()
    except Exception:
        pass
    return str(obj)


df = _pd.read_csv(_INPUT_CSV) if _INPUT_CSV else _pd.DataFrame()
result = {}

_ns = {
    "__name__": "__a07_sandbox__", "__builtins__": __builtins__,
    "df": df, "result": result,
    # 白名单模块的常用别名，省去用户/模板代码重复 import（import 本身也放行）
    "pd": _pd, "np": _np, "json": _json, "math": _math,
    "statistics": _statistics, "datetime": _datetime, "re": _re,
}
exec(compile(_user_code, _USER_CODE_FILENAME, "exec"), _ns)

_payload = {"result": _serialize(_ns.get("result", result)), "stdout": _sys.stdout.text()}
_real_stdout.write("\\n" + _RESULT_MARKER + "\\n"
                   + _json.dumps(_payload, ensure_ascii=False, default=str))
_real_stdout.flush()
'''


@dataclass
class SandboxResult:
    """沙箱执行结果（计划 §Task 11.3 契约 + 运行元信息）。

    ok=子进程正常结束且结果信封解析成功；stats=result 中除 tables/scatter 外的全部键；
    error=可读错误（失败原因）；warnings=限额降级等非致命提示。
    """

    ok: bool = False
    tables: list[Any] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    stdout_tail: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    returncode: int | None = None


def run_python(
    code: str,
    input_csv_path: str | Path | None = None,
    timeout_s: float | None = None,
    copy_out: dict[str, str] | None = None,
    memory_mb: int | None = None,
) -> SandboxResult:
    """在隔离子进程中执行用户分析代码并解析结果（协议见模块文档）。

    copy_out：{沙箱工作目录内相对文件名 → 目标绝对路径}。子进程结束后（成败皆可）、
    工作目录清理前，把存在的文件复制到目标路径——A7 ML 模板的 joblib 模型由此"收走"
    （沙箱内只写工作目录相对路径，绝不写持久路径，红线 R2）；文件不存在则跳过。
    memory_mb：Job Object 每进程内存上限（MB），缺省 1024；A7 ML 模板执行时传入
    2048（sklearn 全栈 import 提交内存实测 ~1.4GB，1024MB 必现 MemoryError）。
    """
    timeout = float(timeout_s) if timeout_s and float(timeout_s) > 0 else DEFAULT_TIMEOUT_SECONDS
    started = time.perf_counter()
    result = SandboxResult()
    workdir = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
    limiter = create_job_limiter(memory_mb)
    if limiter is None:
        result.warnings.append(
            "沙箱限额降级：Job Object 不可用（pywin32 未安装或创建失败），仅保留 timeout 墙钟限制"
        )
    try:
        result.warnings.extend(
            _prepare_and_run(code, input_csv_path, timeout, workdir, limiter, result, copy_out)
        )
    finally:
        if limiter is not None:
            limiter.close()
        shutil.rmtree(workdir, ignore_errors=True)
        result.duration_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "sandbox_run ok=%s duration_ms=%d timeout_s=%s rc=%s",
            result.ok, int(result.duration_ms), timeout, result.returncode,
        )
    return result


def _prepare_and_run(
    code: str,
    input_csv_path: str | Path | None,
    timeout: float,
    workdir: Path,
    limiter: Any,
    result: SandboxResult,
    copy_out: dict[str, str] | None = None,
) -> list[str]:
    """装配工作目录与包装器、执行子进程、解析信封；返回追加的 warnings。"""
    warnings: list[str] = []
    if not isinstance(code, str) or not code.strip():
        result.error = "沙箱输入代码为空"
        return warnings

    def _collect_copy_out() -> None:
        """子进程结束后收走指定产物（模型等）；文件缺失跳过，复制失败只告警。"""
        for name, dest in (copy_out or {}).items():
            src = workdir / name
            if not src.is_file():
                continue
            try:
                Path(dest).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dest)
            except OSError as exc:
                logger.warning("sandbox_copy_out_failed name=%s dest=%s error=%s", name, dest, exc)

    csv_arg = "-"
    if input_csv_path:
        src = Path(input_csv_path)
        if not src.exists():
            result.error = f"沙箱输入数据文件不存在：{input_csv_path}"
            return warnings
        shutil.copyfile(src, workdir / INPUT_CSV_NAME)
        csv_arg = str(workdir / INPUT_CSV_NAME)

    wrapper_path = workdir / WRAPPER_FILE
    wrapper_path.write_text(_build_wrapper(), encoding="utf-8")
    code_path = workdir / USER_CODE_FILE
    code_path.write_text(code, encoding="utf-8")

    proc = subprocess.Popen(  # noqa: S603 - 固定解释器 + 固定包装器，参数无 shell
        [sys.executable, "-I", "-B", str(wrapper_path), str(workdir), str(code_path), csv_arg],
        cwd=str(workdir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if limiter is not None:
        try:
            limiter.assign(proc)
        except Exception as exc:
            logger.warning("sandbox_job_assign_failed error=%s degrade=timeout_only", exc)
            warnings.append(
                "沙箱限额降级：子进程加入 Job Object 失败，仅保留 timeout 墙钟限制"
            )

    try:
        out_bytes, err_bytes = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out_bytes, err_bytes = proc.communicate()
        _collect_copy_out()
        result.returncode = proc.returncode
        result.stdout_tail = _decode(out_bytes)[-2000:]
        result.error = (
            f"沙箱执行超时：代码在 {timeout:g}s 内未完成，已强制终止"
            "（可简化计算或缩小数据范围后重试）"
        )
        return warnings

    _collect_copy_out()
    result.returncode = proc.returncode
    out, err = _decode(out_bytes), _decode(err_bytes)
    if proc.returncode != 0:
        result.error = _readable_error(err, fallback=f"沙箱子进程异常退出（exit={proc.returncode}）")
        result.stdout_tail = out[-2000:]
        return warnings

    marker_idx = out.rfind(RESULT_MARKER)
    if marker_idx < 0:
        result.error = "沙箱输出协议异常：未找到结果定界符 <<<RESULT>>>（子进程未按约定格式结束）"
        result.stdout_tail = out[-2000:]
        return warnings

    envelope_text = out[marker_idx + len(RESULT_MARKER):].strip()
    try:
        envelope = json.loads(envelope_text)
        if not isinstance(envelope, dict):
            raise ValueError("结果信封必须是 JSON 对象")
    except ValueError as exc:
        result.error = f"沙箱结果 JSON 解析失败：{exc}"
        result.stdout_tail = out[:marker_idx][-1000:] + out[marker_idx + len(RESULT_MARKER):][-1000:]
        return warnings

    raw_result = envelope.get("result")
    result.result = raw_result if isinstance(raw_result, dict) else {}
    tables = result.result.get("tables")
    result.tables = tables if isinstance(tables, list) else []
    result.stats = {k: v for k, v in result.result.items() if k not in ("tables", "scatter")}
    result.stdout_tail = str(envelope.get("stdout") or "")
    result.ok = True
    return warnings


def _build_wrapper() -> str:
    """用替换令牌（避免 f-string/花括号转义地狱）生成包装器源码。"""
    return (
        _WRAPPER_TEMPLATE
        .replace("@STDOUT_CAP@", str(STDOUT_CAP_CHARS))
        .replace("@RESULT_MARKER@", RESULT_MARKER)
        .replace("@ALLOWED_MODULES@", repr(list(ALLOWED_MODULES)))
        .replace("@USER_FILENAME@", USER_CODE_FILENAME)
    )


def _decode(raw: bytes | None) -> str:
    return (raw or b"").decode("utf-8", errors="replace")


def _readable_error(stderr: str, *, fallback: str) -> str:
    """把子进程 stderr 转为用户可读错误：Traceback 的最后一行即"异常类型: 消息"。"""
    lines = [line for line in (stderr or "").strip().splitlines() if line.strip()]
    if not lines:
        return fallback
    tb_idx = max((i for i, ln in enumerate(lines) if ln.strip().startswith("Traceback")), default=-1)
    if tb_idx < 0:
        return f"{fallback}：{lines[-1][:300]}"
    return f"[沙箱] 代码执行失败：{lines[-1].strip()[:300]}"
