"""Host-wide serialisation and a memory gate for heavy validation.

At most one heavy validation runs on the host at a time, across every worktree of the repository. The
lock is an exclusive OS byte-range lock (msvcrt on Windows, flock elsewhere) on a file in the shared git
directory. The OS drops the lock when its holder exits or crashes, so a crashed run never blocks a later one.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .state import WorkflowError, utc_now

try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None
try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

HEAVY_LOCK = "genesis-heavy.lock"
OWNER_FILE = "genesis-heavy.owner.json"


class ExclusiveFileLock:
    """Non-blocking exclusive lock on one byte of a file. Raises WorkflowError(code) when held elsewhere."""

    def __init__(self, path: Path, code: str, held_message: str):
        self.path = Path(path)
        self.code = code
        self.held_message = held_message
        self.fh = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+b")
        try:
            fh.seek(0, os.SEEK_END)
            if fh.tell() == 0:
                fh.write(b"\0")
                fh.flush()
            fh.seek(0)
            if msvcrt is not None:
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            fh.close()
            raise WorkflowError(self.code, self.held_message) from exc
        self.fh = fh
        return self

    def __exit__(self, *exc_info):
        try:
            self.fh.seek(0)
            if msvcrt is not None:
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        finally:
            self.fh.close()
        return False


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def available_memory_mib() -> int:
    """Physical memory available for allocation, in MiB. Unknown memory is a refusal, not a pass."""
    if sys.platform == "win32":
        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise WorkflowError("MEMORY_UNKNOWN", "GlobalMemoryStatusEx failed")
        return int(status.ullAvailPhys // (1024 * 1024))
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError):
        pass
    raise WorkflowError("MEMORY_UNKNOWN", "available memory cannot be read on this host")


def run_heavy(common_dir: Path, *, purpose: str, min_available_mib: int, action,
              wait_seconds: float = 300.0, poll_seconds: float = 5.0, memory_reader=available_memory_mib):
    """Run ``action`` while holding the host-wide heavy lock, once the memory gate passes.

    Waits up to ``wait_seconds`` for another heavy run to finish. Raises WorkflowError(HEAVY_BUSY) if it
    never does, and WorkflowError(MEMORY_GATE) if memory is below ``min_available_mib`` (checked under the lock).
    """
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            lock = ExclusiveFileLock(Path(common_dir) / HEAVY_LOCK, "HEAVY_BUSY",
                                     "another heavy validation holds the host-wide lock")
            lock.__enter__()
            break
        except WorkflowError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(poll_seconds)
    try:
        available = memory_reader()
        if available < min_available_mib:
            raise WorkflowError("MEMORY_GATE", f"{available} MiB available; {min_available_mib} MiB required "
                                               f"before a heavy run")
        owner = {"pid": os.getpid(), "purpose": purpose, "started_utc": utc_now(),
                 "available_mib_at_start": available}
        (Path(common_dir) / OWNER_FILE).write_text(json.dumps(owner, sort_keys=True) + "\n", encoding="utf-8")
        return action()
    finally:
        lock.__exit__(None, None, None)


# ----------------------------------------------------------------------------- process tree ownership
#
# The heavy lock is released when the engine process dies. Without more, a validation child could outlive
# its engine and keep running, so a second heavy run would overlap it. On Windows each check runs inside a
# kill-on-close Job Object: when the engine's handle closes, the OS terminates every process in the job.

if sys.platform == "win32":
    import ctypes.wintypes as _wt

    class _BasicLimit(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", ctypes.c_ulong), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_ulong),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_ulong),
                    ("SchedulingClass", ctypes.c_ulong)]

    class _IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in
                    ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                     "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _ExtendedLimit(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _BasicLimit), ("IoInfo", _IoCounters),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.CreateJobObjectW.restype = ctypes.c_void_p
    _k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    _k32.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong]
    _k32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    _k32.OpenProcess.restype = ctypes.c_void_p
    _k32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    _k32.CloseHandle.argtypes = [ctypes.c_void_p]
    _k32.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]


class KillOnCloseJob:
    """A Job Object whose members die with it. Closing the last handle, even after a crash, terminates them."""

    def __init__(self):
        self.handle = _k32.CreateJobObjectW(None, None)
        if not self.handle:
            raise WorkflowError("JOB_UNAVAILABLE", "cannot create a Job Object for the validation tree")
        info = _ExtendedLimit()
        info.BasicLimitInformation.LimitFlags = 0x2000          # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not _k32.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            _k32.CloseHandle(self.handle)
            raise WorkflowError("JOB_UNAVAILABLE", "cannot set kill-on-close on the Job Object")

    def assign(self, pid: int) -> None:
        process = _k32.OpenProcess(0x0100 | 0x0001, False, pid)   # PROCESS_SET_QUOTA | PROCESS_TERMINATE
        if not process:
            raise WorkflowError("JOB_UNAVAILABLE", f"cannot open validation process {pid}")
        try:
            if not _k32.AssignProcessToJobObject(self.handle, process):
                raise WorkflowError("JOB_UNAVAILABLE", "cannot place the validation process in its Job Object")
        finally:
            _k32.CloseHandle(process)

    def terminate(self) -> None:
        _k32.TerminateJobObject(self.handle, 1)

    def close(self) -> None:
        _k32.CloseHandle(self.handle)


def run_in_job(argv: list[str], *, cwd: str, env: dict, timeout: float) -> tuple[int, bytes, bytes]:
    """Run one validation check so that nothing it starts can outlive it (or the engine that owns it)."""
    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    job = KillOnCloseJob() if sys.platform == "win32" else None
    try:
        if job is not None:
            job.assign(proc.pid)
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out, err
    except subprocess.TimeoutExpired:
        if job is not None:
            job.terminate()
        else:
            proc.kill()
        out, err = proc.communicate()
        return 124, out or b"", (err or b"") + f"\nTIMEOUT after {timeout:.0f}s".encode()
    finally:
        if job is not None:
            job.close()
