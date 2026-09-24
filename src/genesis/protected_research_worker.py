"""Fresh-interpreter, label-free worker for protected research callbacks."""

from __future__ import annotations

import inspect
import json
import os
import sys
import types
from decimal import Decimal
from enum import Enum
from pathlib import Path
from types import FunctionType, ModuleType
from typing import Any, BinaryIO


SRC_ROOT = Path(__file__).resolve().parents[1]
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
)
from genesis.provenance import AvailabilityClass, ProvenanceRef  # noqa: E402
from genesis.repro import canonical_json, sha256_bytes  # noqa: E402


def _send(stream: BinaryIO, payload: dict[str, Any]) -> None:
    raw = canonical_json(payload)
    if len(raw) > MAX_IPC_BYTES:
        raise ValueError("research IPC response exceeds limit")
    stream.write(raw)
    stream.flush()


def _recv(stream: BinaryIO) -> dict[str, Any]:
    raw = stream.readline(MAX_IPC_BYTES + 1)
    if not raw or len(raw) > MAX_IPC_BYTES or not raw.endswith(b"\n"):
        raise ValueError("research IPC request is invalid")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("research IPC request must be an object")
    return value


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


def _inside(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path.is_relative_to(root) for root in roots)


def _module_path(module: ModuleType) -> Path | None:
    value = vars(module).get("__file__")
    if not isinstance(value, str):
        return None
    try:
        return Path(value).resolve(strict=True)
    except (OSError, RuntimeError):
        return None


def _program_module_path(module_name: str, roots: tuple[Path, ...]) -> Path:
    """Resolve one exact source origin without importing untrusted target code."""

    relative = Path(*module_name.split("."))
    candidates: set[Path] = set()
    for root in roots:
        for unresolved in (
            root / relative.with_suffix(".py"),
            root / relative / "__init__.py",
        ):
            try:
                candidate = unresolved.resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            if not candidate.is_file() or not candidate.is_relative_to(root):
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
            try:
                if _inside(Path(module_path_value).resolve(strict=True), roots):
                    raise ValueError("custom imported function capability is unsupported")
            except (OSError, RuntimeError):
                raise ValueError("imported function origin is uninspectable") from None
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
        path = _module_path(value)
        if path is not None and _inside(path, roots):
            raise ValueError("custom imported module capability is unsupported")
        namespace = vars(value)
        for name in referenced_names:
            if name in namespace:
                _audit_capability(
                    namespace[name], seen=seen, roots=roots,
                    program_module=program_module, referenced_names=frozenset(),
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


def _resolve_program(program: ResearchProgramRef, roots: tuple[Path, ...]) -> FunctionType:
    module_path = _program_module_path(program.module, roots)
    source = module_path.read_bytes()
    if sha256_bytes(source) != program.module_artifact_hash:
        raise ValueError("research program module artifact mismatch")
    code = compile(source, str(module_path), "exec", dont_inherit=True)
    module = ModuleType(program.module)
    module.__file__ = str(module_path)
    module.__package__ = program.module.rpartition(".")[0]
    if module_path.name == "__init__.py":
        module.__package__ = program.module
        module.__path__ = [str(module_path.parent)]  # type: ignore[attr-defined]
    exec(code, module.__dict__)

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
        for root in reversed(roots):
            sys.path.insert(0, str(root))
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

    while True:
        try:
            message = _recv(ipc_input)
            operation = message.get("op")
            if operation == "shutdown" and set(message) == {"op"}:
                _send(ipc_output, {"status": "closed"})
                return 0
            if operation != "predict" or set(message) != {"op", "request", "program"}:
                raise ValueError("unsupported research operation")
            if not isinstance(message["request"], dict) or not isinstance(message["program"], dict):
                raise ValueError("research request payload is invalid")
            request = EvaluationRequest.from_dict(message["request"])
            program = ResearchProgramRef.from_dict(message["program"])
            if request.strategy_digest != program.program_digest:
                raise ValueError("research request/program digest mismatch")
            callback = _resolve_program(program, roots)
            predictions = {
                frame.decision_id: callback(frame)
                for frame in sealed.frames
            }
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
                },
            )
        except Exception:
            _send(ipc_output, {"status": "error", "message": "protected evaluation failed"})


if __name__ == "__main__":
    raise SystemExit(_main())
