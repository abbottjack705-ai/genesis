"""Fresh-interpreter, label-free worker for protected research callbacks."""

from __future__ import annotations

import builtins
import decimal
import dis
import gc
import importlib.abc
import inspect
import os
import sys
import types
from decimal import Decimal
from enum import Enum
from pathlib import Path
from types import FunctionType, ModuleType
from typing import Any, BinaryIO


SRC_ROOT = Path(__file__).resolve().parents[1]
TRUSTED_RUNTIME_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC_ROOT))

from genesis.evaluation import EvaluationRequest  # noqa: E402
from genesis.labels import DecisionFact, DecisionFrame, FutureOutcomeLabel  # noqa: E402
from genesis.protected import (  # noqa: E402
    MAX_IPC_BYTES,
    RESEARCH_BOUNDARY_SCHEMA,
    RESEARCH_LAUNCH_SCHEMA,
    FrozenPredictionArtifact,
    ResearchProgramRef,
    SealedFrameSet,
    decode_ipc_message,
)
from genesis.provenance import AvailabilityClass, ProvenanceRef  # noqa: E402
from genesis.repro import canonical_json, sha256_bytes  # noqa: E402


def _send(stream: BinaryIO, payload: dict[str, Any], *, verify=None) -> None:
    raw = canonical_json(payload)
    if len(raw) > MAX_IPC_BYTES:
        raise ValueError("research IPC response exceeds limit")
    # Optional last check on the exact bytes' worth of state before any byte is
    # written (E11 re-audit finding 3 / defence-in-depth): building `payload` or
    # serializing it can transitively re-enter research-controlled code (a dunder
    # on a returned value, a rebound trusted callable), so verify AFTER
    # serialization but BEFORE emitting, so a contaminating side effect fails the
    # response instead of shipping it.
    if verify is not None:
        verify()
    stream.write(raw)
    stream.flush()


def _recv(stream: BinaryIO) -> dict[str, Any]:
    raw = stream.readline(MAX_IPC_BYTES + 1)
    if not raw:
        raise ValueError("research IPC request is invalid")
    return decode_ipc_message(raw)


def _provenance_from_dict(value: Any) -> ProvenanceRef:
    required = set(ProvenanceRef.__dataclass_fields__)
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("sealed provenance payload is invalid")
    fields = dict(value)
    fields["availability_class"] = AvailabilityClass(fields["availability_class"])
    return ProvenanceRef(**fields)


def _frame_from_dict(value: Any) -> DecisionFrame:
    required = {"decision_id", "entity_id", "decision_at", "facts", "dataset_version", "config_digest"}
    if not isinstance(value, dict) or set(value) != required or not isinstance(value["facts"], list):
        raise ValueError("sealed decision frame payload is invalid")
    facts: list[DecisionFact] = []
    for item in value["facts"]:
        if not isinstance(item, dict) or set(item) != {
            "key",
            "value",
            "available_at",
            "ready_at",
            "source_ref",
        }:
            raise ValueError("sealed decision fact payload is invalid")
        facts.append(
            DecisionFact(
                key=item["key"],
                value=item["value"],
                available_at=item["available_at"],
                ready_at=item["ready_at"],
                source_ref=_provenance_from_dict(item["source_ref"]),
            )
        )
    return DecisionFrame(
        decision_id=value["decision_id"],
        entity_id=value["entity_id"],
        decision_at=value["decision_at"],
        facts=tuple(facts),
        dataset_version=value["dataset_version"],
        config_digest=value["config_digest"],
    )


def _sealed_from_dict(value: Any) -> SealedFrameSet:
    required = {
        "schema_version",
        "campaign_id",
        "dataset_version",
        "frames",
        "frame_ids",
        "frame_hashes",
        "frame_manifest_hash",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("sealed frame launch payload is invalid")
    if not all(isinstance(value[name], list) for name in ("frames", "frame_ids", "frame_hashes")):
        raise ValueError("sealed frame launch lists are invalid")
    return SealedFrameSet(
        campaign_id=value["campaign_id"],
        dataset_version=value["dataset_version"],
        frames=tuple(_frame_from_dict(item) for item in value["frames"]),
        frame_ids=tuple(value["frame_ids"]),
        frame_hashes=tuple(value["frame_hashes"]),
        frame_manifest_hash=value["frame_manifest_hash"],
        schema_version=value["schema_version"],
    )


_ATOMIC_CAPABILITIES = (
    str,
    bytes,
    bytearray,
    int,
    float,
    complex,
    bool,
    type(None),
    Decimal,
    Enum,
    range,
    slice,
)
_CONTAINER_CAPABILITIES = (tuple, list, set, frozenset)
_FORBIDDEN_REFLECTION_NAMES = frozenset({
    "__builtins__",
    "__dict__",
    "__getattribute__",
    "__import__",
    "compile",
    "delattr",
    "eval",
    "exec",
    "getattr",
    "globals",
    "locals",
    "setattr",
    "vars",
})


# Research imports are governed by a fail-closed ALLOWLIST (F-A / reopened
# F-1/E3). A denylist of dangerous modules is unsound: the set of stdlib
# extension modules that can create a process, load native code or open the
# network is open-ended, and some reach those sinks through primitives that
# raise no audit event at all (e.g. a `_tkinter` Tcl interpreter's `exec`, or
# `_sqlite3` extension loading), so no runtime hook can see the call. A module
# must therefore not become reachable merely by having been omitted from an
# enumeration. Research code may import only the modules in
# `_RESEARCH_IMPORT_ALLOWLIST` (vetted trusted runtime with no boundary-crossing
# capability, or whose process sinks are covered by the runtime hook) plus the
# Genesis package that this worker itself runs from; everything else fails
# closed at the static program audit and the guarded `__import__`.
#
# `_CONTROL_MODULES` is retained as belt-and-suspenders: the runtime audit hook
# refuses these import events regardless of the allowlist. The native
# process/OS and native-extension modules below are named explicitly because
# their primitives create processes or load native code (notably
# `_winapi.CreateProcess`, `_posixsubprocess`, `_sqlite3` extension loading and
# `_tkinter`'s Tcl `exec`), several raising no audit event, so refusing the
# import is the only sound defense even though the allowlist already excludes
# them.
_CONTROL_MODULES = frozenset({
    "__main__", "_ast", "_ctypes", "_frozen_importlib", "_frozen_importlib_external",
    "_imp", "_pickle", "_posixsubprocess", "_socket", "_sqlite3", "_thread",
    "_tkinter", "_weakref", "_winapi",
    "ast", "asyncio", "atexit", "builtins",
    "code", "codeop", "concurrent", "copyreg", "ctypes", "dis", "faulthandler", "gc",
    "imp", "importlib", "inspect", "marshal", "msvcrt", "multiprocessing", "nt",
    "pickle", "pkgutil",
    "runpy", "signal", "site", "sitecustomize", "socket", "sqlite3", "ssl",
    "subprocess", "symtable", "sys",
    "sysconfig", "threading", "tkinter", "tracemalloc", "types", "usercustomize",
    "weakref", "winreg", "zipimport",
})
_CONTROL_MODULE_NAMES = frozenset({"genesis.protected_research_worker"})
# The only imports research code may perform. Each root is vetted to expose no
# process/native-load/network capability, or (os/pathlib/io) only sinks the
# runtime hook already refuses. `__future__` is required for
# `from __future__ import annotations`.
_RESEARCH_IMPORT_ALLOWLIST = frozenset({
    "__future__",
    "abc", "array", "bisect", "calendar", "cmath", "collections", "copy",
    "datetime", "decimal", "enum", "fractions", "functools", "heapq",
    "io", "itertools", "json", "math", "numbers", "operator", "os",
    "pathlib", "random", "re", "statistics", "string", "struct", "time",
})
# The Genesis import surface is a NARROW positive allowlist, not "any genesis.*".
# The wide surface (E11 re-audit finding 1) let research reach
# `genesis.protected` -> `multiprocessing.reduction._winapi.CreateProcess` (a
# native process loader) purely by attribute. Research may reference only the
# data-type layer below (frames, labels, provenance, reasons, time) -- pure
# dataclasses/enums that the worker already loads and that expose no process,
# native-load or network capability. `genesis.protected`, this worker module and
# every heavier Genesis module (risk, execution, selection, ledger, ...) fail
# closed by omission.
_RESEARCH_GENESIS_ALLOWLIST = frozenset({
    "genesis",
    "genesis.evaluation",
    "genesis.labels",
    "genesis.provenance",
    "genesis.reasons",
    "genesis.time",
})
def _is_trusted_definition_module(name: str) -> bool:
    """Modules whose top-level definitions (classes AND functions, plus the exact
    built-in containers nested in their namespaces) are integrity-checked for
    in-place mutation (E11 re-audit finding 3).

    The scope is broad on purpose -- **every** loaded Genesis module, `pathlib`
    (whose `PurePath`/`Path` methods the worker's OWN post-callback enforcement
    dispatches through, so rebinding one would subvert the checker while the
    module-level identity is unchanged), and this worker module. The narrowed
    import surface and the reachability closure already stop research from
    reaching most of these, so covering them is defence in depth: even if some
    other route reached a Genesis definition, an in-place mutation of it is still
    caught. Their namespaces are stable under the worker's own use (no lazy
    class-level caches), so the check does not false-positive. The stdlib beyond
    `pathlib` is deliberately excluded: it has mutating caches (`re._cache`,
    `functools`, ...) that would false-positive, which is exactly why an
    unbounded snapshot of everything is unsound.
    """

    return name == __name__ or name == "pathlib" or name.startswith("genesis.")


def _import_allowed(name: object) -> bool:
    """Fail-closed: only allowlisted trusted-runtime roots and a narrow set of
    Genesis data modules (never this worker module or `genesis.protected`) may be
    imported by research code."""

    if not isinstance(name, str) or not name:
        return False
    root = name.partition(".")[0]
    if root in _RESEARCH_IMPORT_ALLOWLIST:
        return True
    if root == "genesis":
        return name in _RESEARCH_GENESIS_ALLOWLIST
    return False


def _preload_research_allowlist() -> None:
    """Import every allowlisted module once, in the trusted worker before any
    research runs, so a later research `import` of one is a cache hit that pulls
    in no further (possibly denied) transitive module during research mode."""

    for name in _RESEARCH_IMPORT_ALLOWLIST:
        if name == "__future__":
            continue
        try:
            importlib.import_module(name)
        except Exception:
            # A platform-absent optional module simply stays unavailable; the
            # allowlist is an upper bound, not a requirement.
            pass


# Names that reach code, frames, the import system or unbound objects through
# attribute or string indirection. Checked in every code object of the hashed
# module, including module top level, class bodies and nested functions.
_FORBIDDEN_PROGRAM_NAMES = frozenset({
    "__base__", "__bases__", "__builtins__", "__class__", "__closure__", "__code__",
    "__dict__", "__func__", "__getattribute__", "__globals__", "__import__",
    "__loader__", "__mro__", "__reduce__", "__reduce_ex__", "__self__", "__spec__",
    "__subclasses__", "_getframe", "addressof", "ag_frame", "attrgetter",
    "breakpoint", "builtins", "compile", "cr_frame", "ctypes", "delattr", "eval",
    "exec", "exec_module", "f_back", "f_builtins", "f_code", "f_globals", "f_locals",
    "enable_load_extension", "find_loader", "find_spec", "from_address",
    "get_objects", "get_referents",
    "get_referrers", "getattr", "getattr_static", "gi_code", "gi_frame", "globals",
    "import_module", "importlib", "load_extension", "load_module", "locals",
    "methodcaller",
    "module_from_spec", "modules", "pythonapi", "reload", "run_module", "run_path",
    "setattr", "socket", "spec_from_file_location", "sqlite3", "subprocess",
    "sys", "tb_frame", "tb_next", "vars",
})
_REMOVED_BUILTINS = frozenset({
    "__import__", "breakpoint", "compile", "delattr", "eval", "exec", "getattr",
    "globals", "help", "input", "locals", "setattr", "vars",
})
_HAVE_GC = 1 << 14


class ResearchProcessContaminated(RuntimeError):
    """Research left state that later computations could not be bound to."""


def _install_runtime_audit_hook(roots: tuple[Path, ...]):
    """Install a permanent audit hook enforcing the research boundary.

    The hook is defense in depth, not a replacement for the static program
    audit or the post-execution interpreter-state checks.  Its mutable state is
    closure-captured and the hook itself is registered permanently with CPython.

    Two tiers of policy:

    * A **permanent** tier is refused in *every* phase, independent of `mode`:
      forbidden sinks (process/native/socket creation, enforcement subversion),
      native-capability events (`_winapi.*`, `_posixsubprocess.*`, `ctypes.*`),
      and the fail-closed **import allowlist**.  Trusted worker code performs
      none of these after this hook is installed (imports are pre-loaded before
      it is installed), so keeping them refused while `mode` is None costs
      trusted activity nothing and closes the re-entry window (E11 re-audit
      finding 2): research-controlled code that regains execution during trusted
      conversion, cleanup or shutdown -- through a `__del__` or other finalizer,
      a generator `close`/`finally`, a GC-driven callback, or a dunder method
      touched while the interpreter state is scanned, the result is converted or
      the artifact is serialized -- still cannot import a forbidden module or
      reach a native capability, because these denials never switch off.  Python
      cannot stop such code from *running*; the boundary guarantees that whenever
      it runs, the operations that would breach it stay refused.
    * A **research** tier applies only while a research `mode` is active (module
      exec / callback).  It is **default-deny**: only a small vetted set of
      benign, non-boundary-crossing events is admitted (compile/exec of trusted
      code, non-sensitive attribute reads, and filesystem access), and every
      other event fails closed by omission.  Because benign predictor compute
      raises no audit event at all, this positive policy does not restrict
      legitimate research, yet it refuses any native/process/network/
      introspection capability reached by *any* route -- including one reached by
      attribute traversal rather than by an import statement (E11 re-audit
      finding 1) -- since exercising it raises an audit event that is not on the
      benign allowlist.  It cannot be default-deny in the trusted (`mode` is
      None) phases, whose own housekeeping legitimately raises `builtins.id`,
      `object.__getattr__`, `gc.get_objects`, `compile` and `open`.
    """

    research_roots = tuple(Path(os.path.realpath(root)) for root in roots)
    trusted_runtime_root = Path(os.path.realpath(TRUSTED_RUNTIME_ROOT))
    code_type = types.CodeType
    sensitive_attrs = frozenset({
        "f_back", "f_builtins", "f_code", "f_globals", "f_locals",
        "tb_frame", "tb_next", "gi_code", "gi_frame", "cr_frame", "ag_frame",
    })
    # Forbidden sinks: operations with an external or irreversible effect, or
    # that grant new native/execution capability, or that would subvert
    # enforcement itself.  Refused in every phase (see the permanent tier above).
    forbidden_events = frozenset({
        "builtins.breakpoint",
        "os.fork",
        "os.forkpty",
        "os.kill",
        "os.posix_spawn",
        "os.startfile",
        "os.system",
        "socket.__new__",
        "sqlite3.enable_load_extension",
        "sqlite3.load_extension",
        "subprocess.Popen",
        "sys.addaudithook",
        "sys.setprofile",
        "sys.settrace",
    })
    # Native-capability event families denied in every phase.  `_winapi.*` and
    # `_posixsubprocess.*` are the low-level process/handle primitives that
    # multiprocessing exposes and that E11 reached by attribute
    # (`genesis.protected.multiprocessing.reduction._winapi.CreateProcess`); their
    # events (e.g. `_winapi.CreateProcess`) were previously undenied.  Trusted
    # worker housekeeping raises no `_winapi`/`_posixsubprocess`/`ctypes` event.
    forbidden_prefixes = (
        "os.exec", "os.spawn", "ctypes.", "_winapi.", "_posixsubprocess.",
    )
    # The only events research-controlled code may raise while a research `mode`
    # is active; everything else fails closed.  `builtins.id` is pure identity
    # introspection (dataclass `repr` raises it via `reprlib.recursive_repr`) and
    # cannot cross the boundary on its own -- the memory-address tricks it once
    # enabled all route through `ctypes`, whose events are refused above.  `open`
    # is legitimate file access; `os.scandir`/`os.listdir` let a non-preloaded
    # allowlisted import load.  None crosses the process/native/network boundary
    # (that surface is the deferred OS-level confinement layer's, per ADR-0003),
    # so admitting them here does not weaken the boundary this hook protects.
    research_benign_events = frozenset({
        "builtins.id",
        "open",
        "os.listdir",
        "os.scandir",
    })
    state: dict[str, Any] = {"mode": None, "allowed_exec": None}

    def _trusted_origin(value: object) -> bool:
        if not isinstance(value, str) or not value or value.startswith("<"):
            return False
        try:
            path = Path(os.path.realpath(value))
        except (OSError, ValueError):
            return False
        if path.is_relative_to(trusted_runtime_root):
            return True
        return not any(path.is_relative_to(root) for root in research_roots)

    def _hook(event: str, args: tuple[Any, ...]) -> None:
        # -- Permanent tier: refused in EVERY phase, independent of `mode`. --
        if event in forbidden_events or event.startswith(forbidden_prefixes):
            raise RuntimeError("research runtime operation is unsupported")
        if event == "import":
            # Fail-closed positive allowlist, enforced in every phase so a
            # re-entrant import during conversion/cleanup/shutdown cannot load a
            # forbidden module (E11 re-audit finding 2).  The `import` event fires
            # inside the import system, which trusted worker code never reaches
            # after startup (all allowlisted modules are pre-loaded), so an
            # always-on allowlist costs trusted activity nothing.
            name = args[0] if args else None
            if not _import_allowed(name):
                raise RuntimeError("research runtime operation is unsupported")
            return
        # -- Research tier: default-deny while a research `mode` is active. --
        if state["mode"] is None:
            return
        if event == "exec":
            code = args[0] if args else None
            if code is state["allowed_exec"]:
                return
            if isinstance(code, code_type) and _trusted_origin(code.co_filename):
                return
            raise RuntimeError("research runtime operation is unsupported")
        if event == "compile":
            filename = args[1] if len(args) > 1 else None
            if _trusted_origin(filename):
                return
            raise RuntimeError("research runtime operation is unsupported")
        if event == "object.__getattr__":
            attribute = args[1] if len(args) > 1 else None
            if attribute in sensitive_attrs:
                raise RuntimeError("research runtime operation is unsupported")
            return
        if event in research_benign_events:
            return
        # Default-deny: any other event (native/process/network/introspection
        # capability, however reached) fails closed.
        raise RuntimeError("research runtime operation is unsupported")

    sys.addaudithook(_hook)

    def enter_module(code: types.CodeType) -> None:
        state["allowed_exec"] = code
        state["mode"] = "module"

    def enter_callback() -> None:
        state["allowed_exec"] = None
        state["mode"] = "callback"

    def leave() -> None:
        state["mode"] = None
        state["allowed_exec"] = None

    return enter_module, enter_callback, leave


def _inside(path: Path, roots: tuple[Path, ...]) -> bool:
    """True only for unhashed research-root code; trusted runtime is exempt."""

    if path.is_relative_to(TRUSTED_RUNTIME_ROOT):
        return False
    return any(path.is_relative_to(root) for root in roots)


def _real_path(value: object) -> Path | None:
    if not isinstance(value, str) or not value or value.startswith("<"):
        return None
    try:
        return Path(os.path.realpath(value))
    except (OSError, ValueError):
        return None


def _resolve_strict_confined(unresolved: Path) -> Path | None:
    """Strictly resolve an existing path, tolerating the ADR-0004 OS confinement.

    Unconfined this is exactly ``Path.resolve(strict=True)``. Inside the
    AppContainer, strict resolution (``GetFinalPathNameByHandle``) is denied for a
    granted-but-arbitrarily-located path, because it must read the *names* of the
    ancestor directories, and the container is granted only the leaf roots it
    needs, by design -- granting the ancestor chain would let it enumerate the
    user's home and appdata, defeating "explicit filesystem access only". On that
    ``PermissionError`` we fall back to a best-effort resolve and require the path
    to still exist.

    This does not weaken the boundary. The point of the strict resolve is to stop
    a symlink inside an import root from pointing the containment check outside
    it; under the OS confinement that attack is already impossible -- the import
    root is granted read-only, the container cannot create a symlink, and it can
    reach no path outside its explicit grants -- so the import-root containment
    check the caller performs still holds. Unconfined, strict resolution always
    succeeds here, so the fallback is never taken and behaviour is unchanged.
    """

    try:
        return unresolved.resolve(strict=True)
    except PermissionError:
        candidate = unresolved.resolve(strict=False)
        try:
            exists = candidate.exists()
        except OSError:
            return None
        return candidate if exists else None
    except (OSError, RuntimeError):
        return None


def _audit_program_code(code: types.CodeType) -> None:
    """Reject unbound code paths anywhere in the hashed module before it runs."""

    pending = [(code, True)]
    while pending:
        current, top_level = pending.pop()
        names = set(current.co_names)
        strings = {value for value in current.co_consts if isinstance(value, str)}
        if names & _FORBIDDEN_PROGRAM_NAMES or strings & _FORBIDDEN_PROGRAM_NAMES:
            raise ValueError("research program uses an unbound dynamic capability")
        previous: list[dis.Instruction] = []
        for instruction in dis.get_instructions(current):
            if instruction.opname == "IMPORT_NAME":
                name = instruction.argval
                level = previous[-2].argval if len(previous) >= 2 else None
                if (
                    not top_level
                    or not isinstance(name, str)
                    or level != 0
                    or not _import_allowed(name)
                ):
                    raise ValueError("research program import is unsupported")
            previous.append(instruction)
        for value in current.co_consts:
            if isinstance(value, types.CodeType):
                pending.append((value, False))


def _trusted_spec(spec: Any, roots: tuple[Path, ...]) -> bool:
    locations = [spec.origin] if spec.origin not in (None, "built-in", "frozen") else []
    locations.extend(spec.submodule_search_locations or ())
    for location in locations:
        path = _real_path(location)
        if path is None or _inside(path, roots):
            return False
    return True


class _ResearchOriginGuard(importlib.abc.MetaPathFinder):
    """Refuse any module under a research root before its code can execute."""

    def __init__(self, roots: tuple[Path, ...]):
        self.roots = roots

    def find_spec(self, fullname, path, target=None):  # noqa: ANN001 - finder protocol
        for finder in sys.meta_path:
            if finder is self:
                continue
            find = getattr(finder, "find_spec", None)
            if find is None:
                continue
            spec = find(fullname, path, target)
            if spec is not None:
                if not _trusted_spec(spec, self.roots):
                    raise ImportError("untrusted research module origin")
                return spec
        return None


def _guarded_import(real_import):
    def research_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
        if level != 0 or not _import_allowed(name):
            raise ImportError("research program import is unsupported")
        return real_import(name, globals, locals, fromlist, level)

    return research_import


def _decimal_context_state() -> tuple:
    context = decimal.getcontext()
    return (
        context.prec, context.rounding, context.Emin, context.Emax,
        context.capitals, context.clamp,
        tuple(sorted((signal.__name__, bool(value)) for signal, value in context.traps.items())),
    )


class _TrustedDefinitionSnapshot:
    """Detect in-place mutation of already-loaded trusted definitions
    (E11 re-audit finding 3).

    The module-binding scan detects *rebinding* a module's top-level attribute
    but not an in-place mutation one level deeper -- adding or rebinding a member
    of a trusted class, mutating a trusted function's defaults/annotations, or
    changing a built-in container nested in a definition namespace -- because the
    top-level identity is unchanged. This snapshot supplements it with exactly
    that bounded extra level.

    It reads only exact built-in containers and definition namespaces and never
    calls user equality, hashing, repr, iteration protocols or arbitrary
    properties (it reads the real class namespace via
    ``type.__dict__['__dict__'].__get__`` rather than ``value.__dict__``), so the
    scan itself cannot re-enter research-controlled code. It is not a snapshot of
    every runtime object and is not an OS sandbox.

    Scope is ``_is_trusted_definition_module`` -- every loaded Genesis module,
    the ``pathlib`` types the worker's own enforcement dispatches through, and
    this worker module (defence in depth beyond what research can reach).
    Original objects are retained (``_retained``) so object-id reuse cannot
    masquerade as unchanged state; verification is therefore effectively by
    identity, not by a reusable ``id()``.
    """

    def __init__(self, modules: dict[str, ModuleType]):
        self.definitions = tuple(
            value
            for name, module in modules.items()
            if _is_trusted_definition_module(name) and isinstance(module, ModuleType)
            for value in vars(module).values()
            if isinstance(value, (FunctionType, type))
            and _is_trusted_definition_module(getattr(value, "__module__", ""))
        )
        self._retained: list[Any] = []
        self.expected = self._state(self._retained)

    @classmethod
    def _capture(cls, value: Any, seen: set[int], retained=None) -> tuple:
        identity = id(value)
        if identity in seen:
            return ("ref", identity)
        seen.add(identity)
        if retained is not None:
            retained.append(value)
        kind = type(value)
        # A mappingproxy may wrap a user-defined mapping; do not dispatch it.
        if kind is dict:
            return ("mapping", identity, tuple(
                (cls._capture(key, seen, retained), cls._capture(item, seen, retained))
                for key, item in value.items()
            ))
        if kind is tuple or kind is list:
            return ("sequence", identity, tuple(
                cls._capture(item, seen, retained) for item in value
            ))
        if kind is set or kind is frozenset:
            return ("set", identity, tuple(
                cls._capture(item, seen, retained) for item in sorted(value, key=id)
            ))
        if kind is FunctionType:
            return ("function", identity, cls._capture(value.__code__, seen, retained),
                    cls._capture(value.__dict__, seen, retained),
                    cls._capture(value.__defaults__, seen, retained),
                    cls._capture(value.__kwdefaults__, seen, retained),
                    cls._capture(value.__annotations__, seen, retained))
        if issubclass(kind, type):
            # Read the real class namespace; a metaclass __dict__ property or a
            # user mappingproxy must never be dispatched during the scan.
            namespace = type.__dict__["__dict__"].__get__(value)
            return ("type", identity, tuple(
                (cls._capture(key, seen, retained), cls._capture(item, seen, retained))
                for key, item in namespace.items()
            ))
        if kind is staticmethod or kind is classmethod:
            return ("method", identity, cls._capture(value.__func__, seen, retained))
        if kind is property:
            return ("property", identity, tuple(
                cls._capture(item, seen, retained) for item in (value.fget, value.fset, value.fdel)
            ))
        return ("leaf", identity)

    def _state(self, retained=None) -> tuple:
        seen: set[int] = set()
        return tuple(self._capture(value, seen, retained) for value in self.definitions)

    def require_clean(self) -> None:
        if self._state() != self.expected:
            raise ResearchProcessContaminated("trusted definition state changed")


class _InterpreterBaseline:
    """Exact module bindings and runtime state before any research executes."""

    _VOLATILE_KEYS = frozenset({"__warningregistry__"})

    def __init__(self, roots: tuple[Path, ...]):
        self.roots = roots
        self.modules = dict(sys.modules)
        self.bindings = {
            name: {key: id(value) for key, value in vars(module).items()}
            for name, module in self.modules.items()
            if isinstance(module, ModuleType)
        }
        # Authority snapshots are held in immutable views so the checker's own
        # reference state cannot be edited in place (E11 re-audit finding 3).
        self.builtins = types.MappingProxyType(dict(vars(builtins)))
        self.environment = types.MappingProxyType(dict(os.environ))
        self.decimal_context = _decimal_context_state()
        self.sys_path = list(sys.path)
        self.meta_path = list(sys.meta_path)
        self.path_hooks = list(sys.path_hooks)
        self.recursion_limit = sys.getrecursionlimit()
        random = self.modules.get("random")
        self.random_state = random.getstate() if random is not None else None
        # Nested-definition integrity for the trusted definitions research can
        # reach or the worker depends on (E11 re-audit finding 3). The top-level
        # id() snapshot in `bindings` detects *rebinding* a module attribute, but
        # not an in-place mutation one level deeper -- adding/rebinding a member of
        # a trusted class (e.g. `FutureOutcomeLabel`, or `pathlib.PurePath.
        # is_relative_to` which the scan itself dispatches through), mutating a
        # trusted function's defaults/annotations, or changing a container nested
        # in a definition namespace -- which leaves the module-level identity
        # unchanged and would otherwise persist into the next request in the reused
        # worker. This snapshot supplements it with exactly that bounded extra
        # level; it is not an unlimited recursive snapshot, which trusted lazy
        # caches would make both unbounded and unsound.
        self.definitions = _TrustedDefinitionSnapshot(self.modules)
        # Cache only containment of already-canonical paths across scans.  Each
        # scan still resolves the live source path afresh, so a symlink or path
        # that resolves differently cannot inherit an earlier classification.
        self._inside_cache: dict[Path, bool] = {}

    def _inside_research_root(self, path: Path) -> bool:
        try:
            return self._inside_cache[path]
        except KeyError:
            inside = _inside(path, self.roots)
            self._inside_cache[path] = inside
            return inside

    def research_builtins(self) -> dict[str, Any]:
        namespace = {
            key: value for key, value in self.builtins.items()
            if key not in _REMOVED_BUILTINS
        }
        namespace["__import__"] = _guarded_import(self.builtins["__import__"])
        return namespace

    @staticmethod
    def _added_submodule(owner: str, key: str, value: Any) -> bool:
        return isinstance(value, ModuleType) and value.__name__ == f"{owner}.{key}"

    def require_clean(self, program_path: Path | None) -> None:
        """Fail closed unless only the current program's code and no label exist."""

        # Verify nested trusted-definition integrity both before and after the
        # collection: a __del__ driven by gc.collect() could itself mutate a
        # trusted definition, so check on each side of it.
        self.definitions.require_clean()
        gc.unfreeze()
        gc.collect()
        self.definitions.require_clean()
        # One resolution and root classification per distinct source path per
        # scan. No research code runs during the scan, so equal path strings
        # classify equally; doing both per live function (thousands) made each
        # scan cost most of a second on Windows and pushed trivial requests past
        # the fixed research timeout under load.
        unbound: dict[str, bool] = {}

        def unbound_origin(value: object) -> bool:
            if not isinstance(value, str):
                return False
            if value not in unbound:
                origin = _real_path(value)
                unbound[value] = (
                    origin is not None and self._inside_research_root(origin)
                    and origin != program_path
                )
            return unbound[value]

        for item in gc.get_objects():
            if isinstance(item, FutureOutcomeLabel):
                raise ResearchProcessContaminated("raw label present in research process")
            if isinstance(item, FunctionType):
                source = item.__code__.co_filename
            elif isinstance(item, ModuleType):
                source = vars(item).get("__file__")
            else:
                continue
            if unbound_origin(source):
                raise ResearchProcessContaminated("unbound research code is live")
        for name, module in self.modules.items():
            if sys.modules.get(name) is not module:
                raise ResearchProcessContaminated("trusted module binding changed")
            expected = self.bindings.get(name)
            if expected is None:
                continue
            current = vars(module)
            for key, identity in expected.items():
                if key in self._VOLATILE_KEYS:
                    continue
                if key not in current or id(current[key]) != identity:
                    raise ResearchProcessContaminated(f"trusted module state changed: {name}.{key}")
            for key, value in current.items():
                if key not in expected and key not in self._VOLATILE_KEYS \
                        and not self._added_submodule(name, key, value):
                    raise ResearchProcessContaminated(f"trusted module state changed: {name}.{key}")
        if (
            dict(vars(builtins)) != self.builtins
            or dict(os.environ) != self.environment
            or _decimal_context_state() != self.decimal_context
            or sys.path != self.sys_path
            or sys.meta_path != self.meta_path
            or sys.path_hooks != self.path_hooks
            or sys.getrecursionlimit() != self.recursion_limit
        ):
            raise ResearchProcessContaminated("trusted runtime state changed")

    def restore_request_scope(self) -> None:
        """Forget modules and submodule bindings first loaded by the request."""

        for name in [name for name in sys.modules if name not in self.modules]:
            del sys.modules[name]
        for name, module in self.modules.items():
            expected = self.bindings.get(name)
            if expected is None:
                continue
            namespace = vars(module)
            for key in [key for key in namespace if key not in expected
                        and key not in self._VOLATILE_KEYS]:
                if self._added_submodule(name, key, namespace[key]):
                    del namespace[key]
        decimal.getcontext().clear_flags()
        random = self.modules.get("random")
        if random is not None and self.random_state is not None:
            random.setstate(self.random_state)


def _module_path(module: ModuleType) -> Path | None:
    value = vars(module).get("__file__")
    if not isinstance(value, str):
        return None
    return _resolve_strict_confined(Path(value))


def _program_module_path(module_name: str, roots: tuple[Path, ...]) -> Path:
    """Resolve one exact source origin without importing untrusted target code."""

    relative = Path(*module_name.split("."))
    candidates: set[Path] = set()
    for root in roots:
        for unresolved in (
            root / relative.with_suffix(".py"),
            root / relative / "__init__.py",
        ):
            candidate = _resolve_strict_confined(unresolved)
            if candidate is None or not candidate.is_file() or not candidate.is_relative_to(root):
                continue
            candidates.add(candidate)
    if len(candidates) != 1:
        raise ValueError("research program module origin is missing or ambiguous")
    return candidates.pop()


def _code_names(code: types.CodeType) -> frozenset[str]:
    names = set(code.co_names)
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            names.update(_code_names(value))
    return frozenset(names)


def _code_strings(code: types.CodeType) -> frozenset[str]:
    values = {value for value in code.co_consts if isinstance(value, str)}
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            values.update(_code_strings(value))
    return frozenset(values)


def _audit_function(
    value: FunctionType,
    *,
    seen: set[int],
    roots: tuple[Path, ...],
    program_module: str,
) -> None:
    _audit_capability(
        value.__dict__, seen=seen, roots=roots,
        program_module=program_module, referenced_names=frozenset(),
    )
    if value.__module__ != program_module:
        # Imported trusted functions are code capabilities, not research-owned
        # state. Their mutable function attributes were still checked above.
        module_path_value = value.__globals__.get("__file__")
        if isinstance(module_path_value, str):
            resolved = _resolve_strict_confined(Path(module_path_value))
            if resolved is None:
                raise ValueError("imported function origin is uninspectable")
            if _inside(resolved, roots):
                raise ValueError("custom imported function capability is unsupported")
        return
    if value.__closure__ is not None:
        raise ValueError("research function closure state is unsupported")
    names = _code_names(value.__code__)
    if names & _FORBIDDEN_REFLECTION_NAMES \
            or _code_strings(value.__code__) & _FORBIDDEN_REFLECTION_NAMES \
            or any(name.startswith("__") and name.endswith("__") for name in names):
        raise ValueError("dynamic research reflection is unsupported")
    for state in (value.__defaults__, value.__kwdefaults__, value.__annotations__):
        _audit_capability(
            state, seen=seen, roots=roots,
            program_module=program_module, referenced_names=names,
        )
    for name in names:
        if name == "__builtins__" or name not in value.__globals__:
            continue
        _audit_capability(
            value.__globals__[name], seen=seen, roots=roots,
            program_module=program_module, referenced_names=names,
        )


def _audit_type(
    value: type,
    *,
    seen: set[int],
    roots: tuple[Path, ...],
    program_module: str,
) -> None:
    if value.__module__ != program_module:
        owner = sys.modules.get(value.__module__)
        if not isinstance(owner, ModuleType):
            raise ValueError("imported type origin is uninspectable")
        exported: Any = owner
        for component in value.__qualname__.split("."):
            if component == "<locals>" or not isinstance(exported, (ModuleType, type)):
                raise ValueError("imported type origin is uninspectable")
            namespace = vars(exported)
            if component not in namespace:
                raise ValueError("imported type origin is uninspectable")
            exported = namespace[component]
        if exported is not value:
            raise ValueError("imported type origin is uninspectable")
        path = _module_path(owner)
        if path is None:
            spec = vars(owner).get("__spec__")
            if value.__module__ == "builtins" \
                    or getattr(spec, "origin", None) in {"built-in", "frozen"}:
                return
            raise ValueError("imported type origin is uninspectable")
        if _inside(path, roots):
            raise ValueError("custom imported type capability is unsupported")
        return

    for name, item in vars(value).items():
        if name in {"__dict__", "__weakref__", "__module__", "__doc__", "__slots__"}:
            continue
        _audit_capability(
            item, seen=seen, roots=roots,
            program_module=program_module, referenced_names=frozenset(),
        )


def _audit_object_state(
    value: Any,
    *,
    seen: set[int],
    roots: tuple[Path, ...],
    program_module: str,
    referenced_names: frozenset[str],
) -> None:
    _audit_capability(
        type(value), seen=seen, roots=roots,
        program_module=program_module, referenced_names=referenced_names,
    )
    inspectable = False
    try:
        state = object.__getattribute__(value, "__dict__")
    except (AttributeError, TypeError):
        state = None
    except Exception:
        raise ValueError("research global object state is uninspectable") from None
    if state is not None:
        if not isinstance(state, (dict, types.MappingProxyType)):
            raise ValueError("research global object dictionary is unsupported")
        inspectable = True
        _audit_capability(
            state, seen=seen, roots=roots,
            program_module=program_module, referenced_names=referenced_names,
        )

    for owner in type(value).__mro__:
        raw_slots = vars(owner).get("__slots__", ())
        if isinstance(raw_slots, str):
            slots = (raw_slots,)
        elif isinstance(raw_slots, (tuple, list)):
            slots = tuple(raw_slots)
        else:
            raise ValueError("research global slots are unsupported")
        for slot in slots:
            if slot in {"__dict__", "__weakref__"}:
                continue
            descriptor = vars(owner).get(slot)
            if not isinstance(descriptor, types.MemberDescriptorType):
                raise ValueError("research global slot descriptor is unsupported")
            inspectable = True
            try:
                item = descriptor.__get__(value, type(value))
            except AttributeError:
                continue
            except Exception:
                raise ValueError("research global slot is uninspectable") from None
            _audit_capability(
                item, seen=seen, roots=roots,
                program_module=program_module, referenced_names=referenced_names,
            )

    if not inspectable:
        raise ValueError("opaque research global capability is unsupported")


def _audit_capability(
    value: Any,
    *,
    seen: set[int],
    roots: tuple[Path, ...],
    program_module: str,
    referenced_names: frozenset[str],
) -> None:
    if isinstance(value, FutureOutcomeLabel):
        raise ValueError("research program contains a reachable raw label")
    if isinstance(value, _ATOMIC_CAPABILITIES):
        return
    identity = id(value)
    if identity in seen:
        return
    seen.add(identity)

    if isinstance(value, dict):
        for key, item in value.items():
            _audit_capability(
                key, seen=seen, roots=roots,
                program_module=program_module, referenced_names=referenced_names,
            )
            _audit_capability(
                item, seen=seen, roots=roots,
                program_module=program_module, referenced_names=referenced_names,
            )
        return
    if isinstance(value, types.MappingProxyType):
        _audit_capability(
            dict(value), seen=seen, roots=roots,
            program_module=program_module, referenced_names=referenced_names,
        )
        return
    if isinstance(value, _CONTAINER_CAPABILITIES):
        for item in value:
            _audit_capability(
                item, seen=seen, roots=roots,
                program_module=program_module, referenced_names=referenced_names,
            )
        return
    if isinstance(value, FunctionType):
        _audit_function(
            value, seen=seen, roots=roots, program_module=program_module,
        )
        return
    if isinstance(value, ModuleType):
        # Positive policy applied to an indirectly reachable module (E11 re-audit
        # finding 1): a module reached by attribute -- not only by an import
        # statement -- must itself satisfy the fail-closed import allowlist. Any
        # module that is not import-allowed (every control/native module, and any
        # non-allowlisted Genesis module reached e.g. via
        # genesis.protected.multiprocessing.reduction._winapi) fails closed.
        if not _import_allowed(value.__name__):
            raise ValueError("reachable module capability is unsupported")
        path = _module_path(value)
        if path is not None and _inside(path, roots):
            raise ValueError("custom imported module capability is unsupported")
        namespace = vars(value)
        for name in referenced_names:
            if name in namespace:
                # Propagate the referenced names to each recursion so an
                # indirectly reachable module several hops out is validated to its
                # leaf, not only at the first hop. `seen` bounds the walk.
                _audit_capability(
                    namespace[name], seen=seen, roots=roots,
                    program_module=program_module, referenced_names=referenced_names,
                )
        return
    if isinstance(value, type):
        _audit_type(
            value, seen=seen, roots=roots, program_module=program_module,
        )
        return
    if isinstance(value, staticmethod):
        _audit_capability(
            value.__func__, seen=seen, roots=roots,
            program_module=program_module, referenced_names=referenced_names,
        )
        return
    if isinstance(value, classmethod):
        _audit_capability(
            value.__func__, seen=seen, roots=roots,
            program_module=program_module, referenced_names=referenced_names,
        )
        return
    if isinstance(value, property):
        for item in (value.fget, value.fset, value.fdel):
            _audit_capability(
                item, seen=seen, roots=roots,
                program_module=program_module, referenced_names=referenced_names,
            )
        return
    if isinstance(value, types.MethodType):
        _audit_capability(
            value.__func__, seen=seen, roots=roots,
            program_module=program_module, referenced_names=referenced_names,
        )
        _audit_capability(
            value.__self__, seen=seen, roots=roots,
            program_module=program_module, referenced_names=referenced_names,
        )
        return
    if isinstance(value, (
        types.BuiltinFunctionType,
        types.BuiltinMethodType,
        types.CodeType,
        types.GetSetDescriptorType,
        types.MemberDescriptorType,
        types.MethodDescriptorType,
        types.WrapperDescriptorType,
    )):
        return
    if isinstance(value, BaseException):
        _audit_capability(
            value.args, seen=seen, roots=roots,
            program_module=program_module, referenced_names=referenced_names,
        )
        return
    _audit_object_state(
        value, seen=seen, roots=roots,
        program_module=program_module, referenced_names=referenced_names,
    )


def _resolve_program(
    program: ResearchProgramRef,
    roots: tuple[Path, ...],
    baseline: _InterpreterBaseline,
    state: dict[str, Any],
    audit_enter_module,
    audit_leave,
) -> FunctionType:
    module_path = _program_module_path(program.module, roots)
    source = module_path.read_bytes()
    if sha256_bytes(source) != program.module_artifact_hash:
        raise ValueError("research program module artifact mismatch")
    code = compile(source, str(module_path), "exec", dont_inherit=True)
    _audit_program_code(code)
    module = ModuleType(program.module)
    module.__file__ = str(module_path)
    module.__package__ = program.module.rpartition(".")[0]
    if module_path.name == "__init__.py":
        module.__package__ = program.module
        module.__path__ = [str(module_path.parent)]  # type: ignore[attr-defined]
    module.__dict__["__builtins__"] = baseline.research_builtins()
    state["program_path"] = Path(os.path.realpath(module_path))
    state["executed"] = True
    audit_enter_module(code)
    try:
        exec(code, module.__dict__)
    finally:
        audit_leave()
    baseline.require_clean(state["program_path"])

    target: Any = module
    for component in program.qualname.split("."):
        if isinstance(target, ModuleType):
            if component not in vars(target):
                raise ValueError("research program function is missing")
            target = vars(target)[component]
        else:
            target = inspect.getattr_static(target, component)
    if (
        not inspect.isfunction(target)
        or target.__module__ != program.module
        or target.__qualname__ != program.qualname
        or target.__closure__ is not None
        or target.__defaults__
        or target.__kwdefaults__
    ):
        raise ValueError("research program is not an exact stateless function")
    parameters = tuple(inspect.signature(target).parameters.values())
    if (
        len(parameters) != 1
        or parameters[0].kind
        not in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        or parameters[0].default is not inspect.Parameter.empty
    ):
        raise ValueError("research program must accept exactly one frame")
    _audit_function(
        target, seen=set(), roots=roots, program_module=program.module,
    )
    return target


def _main() -> int:
    ipc_input = sys.stdin.buffer
    ipc_fd = os.dup(sys.stdout.fileno())
    ipc_output = os.fdopen(ipc_fd, "wb", buffering=0)
    devnull = open(os.devnull, "wb", buffering=0)
    os.dup2(devnull.fileno(), sys.stdout.fileno())
    try:
        launch = _recv(ipc_input)
        if set(launch) != {
            "schema_version",
            "sealed_frame_manifest",
            "allowed_program_import_roots",
            "max_ipc_bytes",
        }:
            raise ValueError("research launch schema is invalid")
        if launch["schema_version"] != RESEARCH_LAUNCH_SCHEMA:
            raise ValueError("research launch version is unsupported")
        if launch["max_ipc_bytes"] != MAX_IPC_BYTES:
            raise ValueError("research launch IPC limit mismatch")
        roots_value = launch["allowed_program_import_roots"]
        if not isinstance(roots_value, list) or not roots_value:
            raise ValueError("research import roots are missing")
        roots = tuple(Path(item).resolve() for item in roots_value)
        if any(not root.is_absolute() or not root.is_dir() for root in roots):
            raise ValueError("research import root is invalid")
        # Roots locate exactly the hashed program; they are never import paths.
        if not FutureOutcomeLabel.__flags__ & _HAVE_GC:
            raise ValueError("raw label type cannot be audited in this runtime")
        sealed = _sealed_from_dict(launch["sealed_frame_manifest"])
        _send(
            ipc_output,
            {
                "status": "ready",
                "schema_version": RESEARCH_BOUNDARY_SCHEMA,
                "research_pid": os.getpid(),
                "frame_manifest_hash": sealed.frame_manifest_hash,
                "received_capabilities": [
                    "program_import_roots",
                    "research_ipc",
                    "research_workdir",
                    "sealed_frames",
                ],
            },
        )
    except Exception:
        try:
            _send(ipc_output, {"status": "error", "message": "protected research unavailable"})
        finally:
            return 2

    _preload_research_allowlist()
    sys.meta_path.insert(0, _ResearchOriginGuard(roots))
    baseline = _InterpreterBaseline(roots)
    audit_enter_module, audit_enter_callback, audit_leave = _install_runtime_audit_hook(roots)
    bound_program_digest: str | None = None
    poisoned = False
    while True:
        state: dict[str, Any] = {"executed": False, "program_path": None}
        nonce: str | None = None
        try:
            message = _recv(ipc_input)
            operation = message.get("op")
            if operation == "shutdown" and set(message) == {"op"}:
                _send(ipc_output, {"status": "closed"})
                return 0
            if operation != "predict" or set(message) != {"op", "request", "program", "nonce"}:
                raise ValueError("unsupported research operation")
            candidate = message.pop("nonce")
            if (
                not isinstance(candidate, str)
                or len(candidate) != 64
                or any(character not in "0123456789abcdef" for character in candidate)
            ):
                raise ValueError("research request nonce is invalid")
            nonce = candidate
            if not isinstance(message["request"], dict) or not isinstance(message["program"], dict):
                raise ValueError("research request payload is invalid")
            request = EvaluationRequest.from_dict(message["request"])
            program = ResearchProgramRef.from_dict(message["program"])
            if request.strategy_digest != program.program_digest:
                raise ValueError("research request/program digest mismatch")
            if bound_program_digest is None:
                bound_program_digest = program.program_digest
            elif bound_program_digest != program.program_digest:
                raise ValueError("research worker program identity mismatch")
            if poisoned:
                raise ResearchProcessContaminated("research process was contaminated earlier")
            callback = _resolve_program(
                program, roots, baseline, state, audit_enter_module, audit_leave,
            )
            audit_enter_callback()
            try:
                predictions = {
                    frame.decision_id: callback(frame)
                    for frame in sealed.frames
                }
            finally:
                audit_leave()
            del callback
            baseline.require_clean(state["program_path"])
            artifact = FrozenPredictionArtifact.create(
                request,
                sealed.frame_manifest_hash,
                predictions,
            )
            _send(
                ipc_output,
                {
                    "status": "artifact",
                    "artifact": artifact.to_dict(),
                    "research_pid": os.getpid(),
                    "nonce": nonce,
                },
                # Re-verify the whole baseline after the artifact is serialized
                # and before any byte leaves the worker: a side effect during
                # conversion/serialization fails the response instead of shipping.
                verify=lambda: baseline.require_clean(state["program_path"]),
            )
        except Exception as exc:
            if isinstance(exc, ResearchProcessContaminated):
                poisoned = True
            # The error stays generic; once the request's nonce is known the
            # error is bound to that request like any other reply.
            failure = {"status": "error", "message": "protected evaluation failed"}
            if nonce is not None:
                failure["nonce"] = nonce
            _send(ipc_output, failure)
        finally:
            if state.get("executed") and not poisoned:
                try:
                    state.clear()
                    baseline.restore_request_scope()
                    baseline.require_clean(None)
                except Exception:
                    poisoned = True


if __name__ == "__main__":
    raise SystemExit(_main())
