# AI-assisted
"""A6 Windows Job Object 限额器（P2a 计划 §Task 11.2 / 红线 R2）。

对沙箱子进程整组（进程树）施加：
- 每进程内存上限（默认 1024MB，JOB_OBJECT_LIMIT_PROCESS_MEMORY）；
- KILL_ON_JOB_CLOSE：父进程退出或句柄关闭时整组进程被终止，杜绝孤儿沙箱；
- BELOW_NORMAL 优先级（软性让出 CPU，防挤占引擎宿主进程）；
- CPU rate 硬限额【降级说明】：本机 pywin32 312 的 win32job 未实现
  JOBOBJECT_CPU_RATE_CONTROL_INFORMATION（SetInformationJobObject 抛
  NotImplementedError），故暂以"BELOW_NORMAL 优先级 + runner 的 timeout 墙钟强杀"
  替代，已在工单 T-011 偏离项记录；待 pywin32 支持后补 CPU rate 硬限。

内存上限取值说明【与计划 §Task 11.2 的 512MB 偏离，已记工单】：实测本机栈
（Python 3.10 + pandas 2.3.3）子进程仅 import pandas 的提交内存（commit charge）
就超过 512MB（512MB 必现 MemoryError，768MB 通过），故默认取 1024MB 留足余量；
限额依然有效约束逃逸代码的内存膨胀。

降级路径（计划明确允许，不阻塞交付）：pywin32 不可用（未安装/非 Windows/创建失败）
时 create_job_limiter() 返回 None，runner 仅保留 timeout 墙钟限制并向结果追加 warning。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("a07.sandbox")

try:  # pywin32 缺失时整个模块仍可导入（runner 据此降级）
    import win32api
    import win32job
    import win32process

    HAS_JOB_OBJECT = True
except ImportError:  # pragma: no cover - 仅在无 pywin32 环境触发
    win32api = None  # type: ignore[assignment]
    win32job = None  # type: ignore[assignment]
    win32process = None  # type: ignore[assignment]
    HAS_JOB_OBJECT = False

# 计划 §Task 11.2 原定 512MB；实测 pandas import 提交内存已超 512MB（见模块文档），
# 上调为 1024MB——偏离项已记工单 T-011。
PROCESS_MEMORY_LIMIT_MB = 1024


class WindowsJobLimiter:
    """一个沙箱一次一个 Job 对象；assign() 后子进程及其后代全部受限额约束。"""

    def __init__(self, memory_mb: int = PROCESS_MEMORY_LIMIT_MB) -> None:
        if not HAS_JOB_OBJECT:
            raise RuntimeError("pywin32 不可用，无法创建 Job Object")
        self.handle = win32job.CreateJobObject(None, "a07-sandbox")
        info = win32job.QueryInformationJobObject(
            self.handle, win32job.JobObjectExtendedLimitInformation
        )
        info["ProcessMemoryLimit"] = int(memory_mb) * 1024 * 1024
        info["BasicLimitInformation"]["LimitFlags"] |= (
            win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY
            | win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            | win32job.JOB_OBJECT_LIMIT_PRIORITY_CLASS
        )
        info["BasicLimitInformation"]["PriorityClass"] = win32process.BELOW_NORMAL_PRIORITY_CLASS
        win32job.SetInformationJobObject(
            self.handle, win32job.JobObjectExtendedLimitInformation, info
        )

    def assign(self, proc: Any) -> None:
        """把子进程加入 Job（须在等待其退出前调用；失败由 runner 降级处理）。"""
        win32job.AssignProcessToJobObject(self.handle, int(proc._handle))

    def close(self) -> None:
        """终止作业内残余进程并关闭句柄（KILL_ON_JOB_CLOSE 兜底；幂等可重复调用）。"""
        if self.handle is None:
            return
        try:
            win32job.TerminateJobObject(self.handle, 1)
        except Exception:  # 作业内进程已全部退出时可能报错，忽略
            pass
        try:
            win32api.CloseHandle(self.handle)
        except Exception:  # pragma: no cover - 句柄已失效时忽略
            pass
        self.handle = None


def create_job_limiter(memory_mb: int | None = None) -> WindowsJobLimiter | None:
    """创建 Job Object 限额器；不可用时返回 None（runner 降级为 timeout-only）。

    memory_mb 缺省用 PROCESS_MEMORY_LIMIT_MB（1024MB）；A7 ML 模板执行时由 runner
    传入更大值（sklearn 全栈 import 提交内存实测 ~1.4GB，1024MB 必现 MemoryError）。
    """
    if not HAS_JOB_OBJECT:
        logger.warning("sandbox_job_object_unavailable reason=pywin32_missing degrade=timeout_only")
        return None
    try:
        return WindowsJobLimiter(memory_mb=int(memory_mb) if memory_mb else PROCESS_MEMORY_LIMIT_MB)
    except Exception as exc:
        logger.warning("sandbox_job_object_create_failed error=%s degrade=timeout_only", exc)
        return None
