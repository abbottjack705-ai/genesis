"""Windows OS-level confinement primitives for the protected research worker
(ADR-0004).

This is a **least-privilege sandbox** for the repository's own research worker
process -- the same pattern browsers and security tools use to run untrusted code
under an operating-system boundary. It exists so the protected research callback
runs where the OS, not merely a cooperating Python audit hook, denies the
network, denies new processes, restricts the filesystem to an explicit set of
paths, restricts inherited handles, caps memory, and tears the process tree down
deterministically. It attacks nothing, injects into nothing, and evades nothing:
every primitive here only *restricts* the child the worker itself launches.

Activation is still gated. These primitives are wired only into the local
checkpoint/test path and only when a caller explicitly opts in; real protected
campaign activation stays disabled behind the launcher guard, and confinement
fails closed -- if any step cannot be established, the worker is not launched
unconfined.

This module holds the Job Object tier: a kernel Job Object with a hard
active-process limit of one (no escaping child processes), a per-job memory cap,
and ``KILL_ON_JOB_CLOSE`` so closing the job handle terminates the whole tree.
The security-context tier (AppContainer, no-network capability set, filesystem
ACLs, restricted inherited handles, suspended launch) builds on it.
"""

from __future__ import annotations

import ctypes
import msvcrt
import os
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path


class ConfinementUnavailable(RuntimeError):
    """A required OS confinement primitive could not be established.

    Callers treat this as fatal and fail closed: the research worker must never
    run outside the boundary it was promised.
    """


if sys.platform == "win32":  # pragma: no cover - exercised only on Windows
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
else:  # pragma: no cover - primitives are Windows-only
    _kernel32 = None


# --- Job Object limit structures (64-bit layouts) --------------------------

class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
        ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.POINTER(ctypes.c_ulong)),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


# JobObjectExtendedLimitInformation
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
# LimitFlags
_JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
_JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
_JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
# Breakaway flags are deliberately NOT set: a child cannot detach from the job.


def _check(result, _func, _args):
    if not result:
        raise ctypes.WinError(ctypes.get_last_error())
    return result


if _kernel32 is not None:  # pragma: no cover - Windows-only bindings
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _kernel32.CreateJobObjectW.errcheck = _check
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
    ]
    _kernel32.SetInformationJobObject.errcheck = _check
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.AssignProcessToJobObject.errcheck = _check
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


class ConfinementJob:
    """A kernel Job Object that confines the research process tree.

    On creation it sets, in one call, three limits ADR-0004 requires:

    * ``ActiveProcessLimit = 1`` -- the confined worker cannot create a second
      process (no shelling out, no helper spawn), and breakaway is not permitted.
    * ``JobMemoryLimit`` / ``ProcessMemoryLimit`` -- a hard committed-memory cap.
    * ``KILL_ON_JOB_CLOSE`` -- when this object's handle is closed (deliberately,
      on error, or on trusted-parent death), the kernel terminates every process
      in the job. Teardown is therefore deterministic and needs no cooperation
      from the confined process.

    The object is a context manager; leaving the ``with`` block closes the handle
    and so kills the tree. It never launches a process itself.
    """

    def __init__(self, *, memory_limit_bytes: int, active_process_limit: int = 1):
        if _kernel32 is None:
            raise ConfinementUnavailable("Job Object confinement requires Windows")
        if memory_limit_bytes <= 0 or active_process_limit <= 0:
            raise ValueError("confinement limits must be positive")
        self._handle: int | None = None
        try:
            handle = _kernel32.CreateJobObjectW(None, None)
        except OSError as exc:
            raise ConfinementUnavailable(f"CreateJobObject failed: {exc}") from exc
        self._handle = handle
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = (
            _JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            | _JOB_OBJECT_LIMIT_PROCESS_MEMORY
            | _JOB_OBJECT_LIMIT_JOB_MEMORY
            | _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        info.BasicLimitInformation.ActiveProcessLimit = active_process_limit
        info.ProcessMemoryLimit = memory_limit_bytes
        info.JobMemoryLimit = memory_limit_bytes
        try:
            _kernel32.SetInformationJobObject(
                handle,
                _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
        except OSError as exc:
            self.close()
            raise ConfinementUnavailable(f"SetInformationJobObject failed: {exc}") from exc

    @property
    def handle(self) -> int:
        if self._handle is None:
            raise ConfinementUnavailable("Job Object handle is closed")
        return self._handle

    def assign(self, process_handle: int) -> None:
        """Place an already-created process into the job before it runs code."""

        try:
            _kernel32.AssignProcessToJobObject(self.handle, process_handle)
        except OSError as exc:
            raise ConfinementUnavailable(f"AssignProcessToJobObject failed: {exc}") from exc

    def terminate(self, exit_code: int = 1) -> None:
        """Explicitly terminate every process in the job now."""

        if self._handle is not None:
            _kernel32.TerminateJobObject(self._handle, exit_code)

    def close(self) -> None:
        """Close the job handle; with KILL_ON_JOB_CLOSE this kills the tree."""

        if self._handle is not None:
            _kernel32.CloseHandle(self._handle)
            self._handle = None

    def __enter__(self) -> "ConfinementJob":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


# --- AppContainer security context (least-privilege principal) --------------
#
# An AppContainer is a per-launch, low-privilege security principal. A process
# running under one starts with access to *nothing* of the user's except what is
# granted to its container SID (or to ALL APPLICATION PACKAGES), and -- crucially
# for ADR-0004 -- it has network access only if the container was created with a
# network *capability*. We create the container with an EMPTY capability set, so
# the confined worker cannot reach the network at the OS level; Windows' built-in
# AppContainer network isolation enforces this regardless of what the Python
# layer allows. The container SID is also the principal we grant explicit,
# revocable read/execute (import roots, runtime) and read/write (workdir) ACLs
# to; every other path stays denied by default.

if sys.platform == "win32":  # pragma: no cover - Windows-only bindings
    _userenv = ctypes.WinDLL("userenv", use_last_error=True)
    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    _ole32 = ctypes.WinDLL("ole32", use_last_error=True)
else:  # pragma: no cover
    _userenv = _advapi32 = _ole32 = None

_ERROR_ALREADY_EXISTS = 0x800700B7  # HRESULT_FROM_WIN32(ERROR_ALREADY_EXISTS)


def _hresult_ok(hresult: int) -> bool:
    return hresult >= 0


if _userenv is not None:  # pragma: no cover - Windows-only bindings
    _userenv.CreateAppContainerProfile.restype = ctypes.c_long  # HRESULT
    _userenv.CreateAppContainerProfile.argtypes = [
        wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
        wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
    ]
    _userenv.DeriveAppContainerSidFromAppContainerName.restype = ctypes.c_long
    _userenv.DeriveAppContainerSidFromAppContainerName.argtypes = [
        wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p),
    ]
    _userenv.DeleteAppContainerProfile.restype = ctypes.c_long
    _userenv.DeleteAppContainerProfile.argtypes = [wintypes.LPCWSTR]
    _advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    _advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR),
    ]
    _advapi32.IsValidSid.restype = wintypes.BOOL
    _advapi32.IsValidSid.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = wintypes.HLOCAL
    _kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    _ole32.CoTaskMemFree.restype = None
    _ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]


class _SECURITY_CAPABILITIES(ctypes.Structure):
    _fields_ = [
        ("AppContainerSid", ctypes.c_void_p),
        ("Capabilities", ctypes.c_void_p),   # NULL: no capabilities (no network)
        ("CapabilityCount", wintypes.DWORD),
        ("Reserved", wintypes.DWORD),
    ]


class AppContainerProfile:
    """A per-launch AppContainer principal with NO capabilities (no network).

    The profile is created (or, if a prior run left it, re-derived) from a unique
    name; its container SID is exposed both as a raw pointer (for the launch
    security attributes) and as a string (for ACL provisioning). Deleting the
    profile is best-effort cleanup; the SID is stable for the name.
    """

    def __init__(self, name: str):
        if _userenv is None:
            raise ConfinementUnavailable("AppContainer confinement requires Windows")
        self.name = name
        self._sid = ctypes.c_void_p()
        self._owns_profile = False
        hr = _userenv.CreateAppContainerProfile(
            name, name, "Genesis protected research confinement (ADR-0004)",
            None, 0, ctypes.byref(self._sid),
        )
        if _hresult_ok(hr):
            self._owns_profile = True
        elif (hr & 0xFFFFFFFF) == _ERROR_ALREADY_EXISTS:
            hr2 = _userenv.DeriveAppContainerSidFromAppContainerName(
                name, ctypes.byref(self._sid),
            )
            if not _hresult_ok(hr2):
                raise ConfinementUnavailable(
                    f"DeriveAppContainerSidFromAppContainerName failed: 0x{hr2 & 0xFFFFFFFF:08X}"
                )
        else:
            raise ConfinementUnavailable(
                f"CreateAppContainerProfile failed: 0x{hr & 0xFFFFFFFF:08X}"
            )
        if not self._sid or not _advapi32.IsValidSid(self._sid):
            raise ConfinementUnavailable("AppContainer SID is invalid")

    @property
    def sid(self) -> ctypes.c_void_p:
        if not self._sid:
            raise ConfinementUnavailable("AppContainer SID is released")
        return self._sid

    def sid_string(self) -> str:
        out = wintypes.LPWSTR()
        if not _advapi32.ConvertSidToStringSidW(self.sid, ctypes.byref(out)):
            raise ConfinementUnavailable("ConvertSidToStringSid failed")
        try:
            return out.value
        finally:
            _kernel32.LocalFree(out)

    def security_capabilities(self) -> _SECURITY_CAPABILITIES:
        """Build the SECURITY_CAPABILITIES with an empty capability set."""

        caps = _SECURITY_CAPABILITIES()
        caps.AppContainerSid = self.sid
        caps.Capabilities = None
        caps.CapabilityCount = 0
        caps.Reserved = 0
        return caps

    def close(self) -> None:
        sid = self._sid
        self._sid = ctypes.c_void_p()
        if sid:
            _ole32.CoTaskMemFree(sid)
        if self._owns_profile:
            try:
                _userenv.DeleteAppContainerProfile(self.name)
            except OSError:
                pass
            self._owns_profile = False

    def __enter__(self) -> "AppContainerProfile":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


# --- Explicit, revocable filesystem grants for the container SID ------------
#
# An AppContainer starts with access to none of the user's files. ADR-0004's
# "explicit filesystem access only" is realised by granting the container SID
# read/execute on exactly the import roots (and, at deployment, the runtime it
# runs) and read/write on the dedicated per-launch working directory, and
# nothing else. Grants are made with `icacls` -- the standard Windows ACL tool --
# using the container's SID string, and are revoked on teardown so the boundary
# leaves no lasting access behind. Every other path stays denied by default.

_ICACLS = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "icacls.exe")


def _run_icacls(args: list[str]) -> None:
    result = subprocess.run(
        [_ICACLS, *args],
        capture_output=True, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0 or "Successfully processed" not in result.stdout:
        raise ConfinementUnavailable(
            f"icacls {args[:1]} failed (rc={result.returncode}): "
            f"{result.stdout.strip()} {result.stderr.strip()}"
        )


def grant_container_access(path: Path, sid_string: str, *, write: bool, recursive: bool) -> None:
    """Grant the container SID read/execute (or read/write) on one path.

    ``write`` selects modify vs read/execute; ``recursive`` (``/T``) materialises
    the inheritable grant across an existing tree (needed for a runtime directory
    whose files predate the grant). The grant is inheritable so files created
    later under the workdir are covered.
    """

    rights = "(OI)(CI)(M)" if write else "(OI)(CI)(RX)"
    args = [str(path), "/grant", f"*{sid_string}:{rights}", "/Q"]
    if recursive:
        args.append("/T")
    _run_icacls(args)


def revoke_container_access(path: Path, sid_string: str, *, recursive: bool) -> None:
    """Remove every ACE granted to the container SID from one path."""

    args = [str(path), "/remove:g", f"*{sid_string}", "/Q"]
    if recursive:
        args.append("/T")
    _run_icacls(args)


# --- Confined suspended launch of the repository's own worker ---------------
#
# The worker is created SUSPENDED, inside the AppContainer security context and
# with an explicit inherited-handle allowlist, then assigned to the Job Object,
# then resumed. Creating it suspended means the OS boundary (low-privilege
# AppContainer token, no network capability, restricted handles, job limits) is
# fully in force before the worker executes a single instruction; resuming only
# once it is confined leaves no window of unconfined execution. This launches the
# repository's own worker binary under restriction -- it manipulates no other
# process, writes no other process's memory, and creates no remote thread.

_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_CREATE_SUSPENDED = 0x00000004
_CREATE_NO_WINDOW = 0x08000000
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_STARTF_USESTDHANDLES = 0x00000100
_PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
_PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
_HANDLE_FLAG_INHERIT = 0x00000001
_INFINITE = 0xFFFFFFFF
_WAIT_OBJECT_0 = 0x00000000
_WAIT_TIMEOUT = 0x00000102
_STILL_ACTIVE = 259


class _SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", wintypes.LPVOID),
        ("bInheritHandle", wintypes.BOOL),
    ]


class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [
        ("StartupInfo", _STARTUPINFOW),
        ("lpAttributeList", ctypes.c_void_p),
    ]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


if _kernel32 is not None:  # pragma: no cover - Windows-only bindings
    _kernel32.CreatePipe.restype = wintypes.BOOL
    _kernel32.CreatePipe.argtypes = [
        ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(wintypes.HANDLE),
        ctypes.POINTER(_SECURITY_ATTRIBUTES), wintypes.DWORD,
    ]
    _kernel32.SetHandleInformation.restype = wintypes.BOOL
    _kernel32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
    _kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
    _kernel32.InitializeProcThreadAttributeList.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t),
    ]
    _kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL
    _kernel32.UpdateProcThreadAttribute.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t, ctypes.c_void_p,
        ctypes.c_size_t, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t),
    ]
    _kernel32.DeleteProcThreadAttributeList.restype = None
    _kernel32.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
    _kernel32.CreateProcessW.restype = wintypes.BOOL
    _kernel32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
        wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
        ctypes.c_void_p, ctypes.POINTER(_PROCESS_INFORMATION),
    ]
    _kernel32.ResumeThread.restype = wintypes.DWORD
    _kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    _kernel32.TerminateProcess.restype = wintypes.BOOL
    _kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    _kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]


def _env_block(environment: dict[str, str]) -> ctypes.Array:
    # A CREATE_UNICODE_ENVIRONMENT block is "K=V\0K=V\0...\0". It contains
    # embedded NULs, so it must be laid out byte-exactly in UTF-16LE rather than
    # via `create_unicode_buffer(str)`, whose `.value` assignment truncates at the
    # first NUL and would corrupt the block (CreateProcess -> ERROR_ENVVAR_NOT_FOUND).
    raw = "".join(f"{key}={value}\x00" for key, value in environment.items()) + "\x00"
    data = raw.encode("utf-16-le")
    buffer = ctypes.create_string_buffer(data, len(data))
    return buffer


if _kernel32 is not None:  # pragma: no cover - Windows-only bindings
    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(_SECURITY_ATTRIBUTES), wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]

_GENERIC_WRITE = 0x40000000
_FILE_SHARE_WRITE = 0x00000002
_FILE_SHARE_READ = 0x00000001
_OPEN_EXISTING = 3
_INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value


class ConfinedWorkerProcess:
    """A ``subprocess.Popen``-compatible view of the confined worker.

    Exposes only what the trusted orchestrator uses -- ``stdin``/``stdout``
    binary streams over the request/reply pipes, ``pid``, ``poll``, ``wait`` and
    ``kill`` -- so the existing IPC and reader-thread plumbing is unchanged. The
    process's lifetime is ultimately bounded by the Job Object (kill-on-close);
    these methods are for the same explicit control paths the unconfined launch
    used.
    """

    def __init__(self, process_handle: int, thread_handle: int, pid: int, stdin, stdout):
        self._process = process_handle
        self._thread = thread_handle
        self.pid = pid
        self.stdin = stdin
        self.stdout = stdout
        self.returncode: int | None = None

    def poll(self) -> int | None:
        if self.returncode is not None:
            return self.returncode
        code = wintypes.DWORD()
        if not _kernel32.GetExitCodeProcess(self._process, ctypes.byref(code)):
            return None
        if code.value == _STILL_ACTIVE:
            return None
        self.returncode = int(code.value)
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        ms = _INFINITE if timeout is None else int(timeout * 1000)
        status = _kernel32.WaitForSingleObject(self._process, ms)
        if status == _WAIT_TIMEOUT:
            raise subprocess.TimeoutExpired("protected-research-worker", timeout)
        return self.poll() if self.poll() is not None else 0

    def kill(self) -> None:
        if self.poll() is None:
            _kernel32.TerminateProcess(self._process, 1)

    terminate = kill

    def _close_handles(self) -> None:
        if self._thread:
            _kernel32.CloseHandle(self._thread)
            self._thread = 0
        if self._process:
            _kernel32.CloseHandle(self._process)
            self._process = 0


def launch_confined_worker(
    argv: list[str],
    *,
    environment: dict[str, str],
    cwd: str,
    job: ConfinementJob,
    security_capabilities: _SECURITY_CAPABILITIES,
) -> ConfinedWorkerProcess:
    """Create the worker SUSPENDED inside the AppContainer + Job Object, with a
    restricted inherited-handle set, then assign it to the job and resume it.

    Fail-closed: if any step fails, any partially-created process is terminated
    and every handle is closed before raising, so no worker ever runs outside the
    boundary it was promised.
    """

    if _kernel32 is None:
        raise ConfinementUnavailable("confined launch requires Windows")

    inherit_sa = _SECURITY_ATTRIBUTES(
        nLength=ctypes.sizeof(_SECURITY_ATTRIBUTES), lpSecurityDescriptor=None, bInheritHandle=True,
    )
    stdin_read = wintypes.HANDLE()
    stdin_write = wintypes.HANDLE()
    stdout_read = wintypes.HANDLE()
    stdout_write = wintypes.HANDLE()
    stderr_handle = wintypes.HANDLE(0)
    attr_list = None
    pi = _PROCESS_INFORMATION()
    created = False
    parent_stdin = parent_stdout = None
    try:
        if not _kernel32.CreatePipe(ctypes.byref(stdin_read), ctypes.byref(stdin_write), ctypes.byref(inherit_sa), 0):
            raise ConfinementUnavailable("CreatePipe (stdin) failed")
        if not _kernel32.CreatePipe(ctypes.byref(stdout_read), ctypes.byref(stdout_write), ctypes.byref(inherit_sa), 0):
            raise ConfinementUnavailable("CreatePipe (stdout) failed")
        # Only the child ends may be inherited; the parent ends must not be.
        _kernel32.SetHandleInformation(stdin_write, _HANDLE_FLAG_INHERIT, 0)
        _kernel32.SetHandleInformation(stdout_read, _HANDLE_FLAG_INHERIT, 0)
        _kernel32.SetHandleInformation(stdin_read, _HANDLE_FLAG_INHERIT, _HANDLE_FLAG_INHERIT)
        _kernel32.SetHandleInformation(stdout_write, _HANDLE_FLAG_INHERIT, _HANDLE_FLAG_INHERIT)
        # Child stderr goes to NUL (inheritable), matching the unconfined launch.
        stderr_handle = _kernel32.CreateFileW(
            "NUL", _GENERIC_WRITE, _FILE_SHARE_WRITE | _FILE_SHARE_READ,
            ctypes.byref(inherit_sa), _OPEN_EXISTING, 0, None,
        )
        if stderr_handle in (0, _INVALID_HANDLE_VALUE):
            raise ConfinementUnavailable("opening NUL for stderr failed")

        # Proc-thread attribute list: the AppContainer security capabilities and
        # an explicit inherited-handle allowlist (ONLY the three std handles).
        size = ctypes.c_size_t(0)
        _kernel32.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
        buf = ctypes.create_string_buffer(size.value)
        attr_list = ctypes.cast(buf, ctypes.c_void_p)
        if not _kernel32.InitializeProcThreadAttributeList(attr_list, 2, 0, ctypes.byref(size)):
            raise ConfinementUnavailable("InitializeProcThreadAttributeList failed")
        if not _kernel32.UpdateProcThreadAttribute(
            attr_list, 0, _PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
            ctypes.byref(security_capabilities), ctypes.sizeof(security_capabilities), None, None,
        ):
            raise ConfinementUnavailable("UpdateProcThreadAttribute (security capabilities) failed")
        handle_array = (wintypes.HANDLE * 3)(stdin_read, stdout_write, stderr_handle)
        if not _kernel32.UpdateProcThreadAttribute(
            attr_list, 0, _PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
            handle_array, ctypes.sizeof(handle_array), None, None,
        ):
            raise ConfinementUnavailable("UpdateProcThreadAttribute (handle list) failed")

        si = _STARTUPINFOEXW()
        si.StartupInfo.cb = ctypes.sizeof(_STARTUPINFOEXW)
        si.StartupInfo.dwFlags = _STARTF_USESTDHANDLES
        si.StartupInfo.hStdInput = stdin_read
        si.StartupInfo.hStdOutput = stdout_write
        si.StartupInfo.hStdError = stderr_handle
        si.lpAttributeList = attr_list

        cmdline = subprocess.list2cmdline(argv)
        flags = (
            _CREATE_SUSPENDED | _EXTENDED_STARTUPINFO_PRESENT
            | _CREATE_NO_WINDOW | _CREATE_UNICODE_ENVIRONMENT
        )
        if not _kernel32.CreateProcessW(
            argv[0], ctypes.create_unicode_buffer(cmdline), None, None, True, flags,
            _env_block(environment), cwd, ctypes.byref(si), ctypes.byref(pi),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        created = True

        # Confine BEFORE the worker runs an instruction: assign to the job while
        # still suspended, then resume.
        job.assign(pi.hProcess)
        if _kernel32.ResumeThread(pi.hThread) == 0xFFFFFFFF:
            raise ConfinementUnavailable("ResumeThread failed")

        # Bridge the parent pipe ends to binary streams for the IPC layer.
        parent_stdin = os.fdopen(msvcrt.open_osfhandle(stdin_write.value, 0), "wb", buffering=0)
        stdin_write = wintypes.HANDLE()  # ownership transferred to the fd
        parent_stdout = os.fdopen(msvcrt.open_osfhandle(stdout_read.value, os.O_RDONLY), "rb", buffering=0)
        stdout_read = wintypes.HANDLE()  # ownership transferred to the fd

        return ConfinedWorkerProcess(pi.hProcess, pi.hThread, pi.dwProcessId, parent_stdin, parent_stdout)
    except BaseException:
        # Fail closed: destroy any partial process and release the parent-side
        # handles (the child ends are always released in `finally`).
        if created and pi.hProcess:
            _kernel32.TerminateProcess(pi.hProcess, 1)
            _kernel32.CloseHandle(pi.hProcess)
        if created and pi.hThread:
            _kernel32.CloseHandle(pi.hThread)
        if parent_stdin is not None:
            parent_stdin.close()
        elif stdin_write.value:
            _kernel32.CloseHandle(stdin_write.value)
        if parent_stdout is not None:
            parent_stdout.close()
        elif stdout_read.value:
            _kernel32.CloseHandle(stdout_read.value)
        raise
    finally:
        # Child ends and the attribute list are never retained by the parent.
        for handle in (stdin_read, stdout_write, stderr_handle):
            value = getattr(handle, "value", handle)
            if value:
                _kernel32.CloseHandle(value)
        if attr_list is not None:
            _kernel32.DeleteProcThreadAttributeList(attr_list)
