"""Closed-schema validator for provider payloads (design section 10.1).

A small, dependency-free checker. Every object on a semantic path is closed: a key that is
not listed (as required, optional or explicitly ``inert``) is drift. Findings carry a stable
``scope`` saying which entities the drift affects, and never any payload value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, Mapping

from genesis.repro import canonical_json, sha256_bytes

SCOPES = ("BOOK", "EVENT_BOOKMAKER", "EVENT", "RESPONSE")
TYPE_NAMES = frozenset({"int", "str", "bool", "number", "null", "object", "object_map", "array"})
_FIELD_KEYS = frozenset({"type", "required", "inert", "identity", "timestamp", "ref", "values"})
_MAP_KEY = re.compile(r"^[A-Za-z0-9_.:-]{1,64}\Z")
_CONTAINER_TYPES = frozenset({"object", "object_map", "array"})

Kind = Literal["UNKNOWN_KEY", "WRONG_TYPE", "MISSING_REQUIRED", "UNKNOWN_ENUM"]
Scope = Literal["BOOK", "EVENT_BOOKMAKER", "EVENT", "RESPONSE"]


class SchemaDefinitionError(ValueError):
    """A schema file that is itself malformed."""


@dataclass(frozen=True)
class DriftFinding:
    """One deviation. ``trail`` holds the path as separate components (list indexes as ``int``,
    object keys as ``str``) so a caller can attribute the finding to an entity without parsing
    ``path``; it does not take part in equality, hashing or ordering."""

    path: str
    kind: Kind
    scope: Scope
    trail: tuple = field(default=(), compare=False)


@dataclass(frozen=True)
class FieldSpec:
    name: str
    types: tuple[str, ...]
    required: bool
    inert: bool
    identity: bool
    timestamp: bool
    ref: str | None
    values: tuple | None


@dataclass(frozen=True)
class ObjectSchema:
    name: str
    scope: str
    keys: Mapping[str, FieldSpec]


@dataclass(frozen=True)
class ClosedSchema:
    schema_id: str
    root_ref: str
    objects: Mapping[str, ObjectSchema]
    digest: str = field(compare=False)


def load_closed_schema(schema_id: str, body: Any) -> ClosedSchema:
    """Validate a schema definition and return the compiled :class:`ClosedSchema`."""

    if type(body) is not dict or set(body) != {"root", "objects"}:
        raise SchemaDefinitionError("schema needs exactly 'root' and 'objects'")
    root = body["root"]
    if type(root) is not dict or set(root) != {"type", "ref"} or root["type"] != "array":
        raise SchemaDefinitionError("root must be an array of a named object")
    objects_raw = body["objects"]
    if type(objects_raw) is not dict or not objects_raw:
        raise SchemaDefinitionError("objects must be a non-empty mapping")
    compiled: dict[str, ObjectSchema] = {}
    for name, definition in objects_raw.items():
        if type(definition) is not dict or set(definition) != {"scope", "keys"}:
            raise SchemaDefinitionError(f"object {name}: needs exactly 'scope' and 'keys'")
        if definition["scope"] not in SCOPES:
            raise SchemaDefinitionError(f"object {name}: unknown scope")
        if type(definition["keys"]) is not dict:
            raise SchemaDefinitionError(f"object {name}: keys must be a mapping")
        keys: dict[str, FieldSpec] = {}
        for key, raw in definition["keys"].items():
            keys[key] = _compile_field(name, key, raw)
        compiled[name] = ObjectSchema(name, definition["scope"], keys)
    for obj in compiled.values():
        for spec in obj.keys.values():
            if spec.ref is not None and spec.ref not in compiled:
                raise SchemaDefinitionError(f"{obj.name}.{spec.name}: unknown ref")
    if root["ref"] not in compiled:
        raise SchemaDefinitionError("root ref is unknown")
    digest = sha256_bytes(canonical_json({"schema_id": schema_id, "body": _plain(body)}))
    return ClosedSchema(schema_id, root["ref"], compiled, digest)


def _plain(value):
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _compile_field(obj: str, key: str, raw: Any) -> FieldSpec:
    where = f"{obj}.{key}"
    if type(raw) is not dict or not set(raw) <= _FIELD_KEYS or "type" not in raw:
        raise SchemaDefinitionError(f"{where}: malformed field spec")
    declared = raw["type"]
    types = (declared,) if type(declared) is str else tuple(declared) if type(declared) is list else None
    if not types or any(type(t) is not str or t not in TYPE_NAMES for t in types):
        raise SchemaDefinitionError(f"{where}: unknown type")
    containers = [t for t in types if t in _CONTAINER_TYPES]
    if containers and len(types) != 1:
        raise SchemaDefinitionError(f"{where}: container types cannot be unions")
    ref = raw.get("ref")
    if containers and type(ref) is not str:
        raise SchemaDefinitionError(f"{where}: container types need a ref")
    if not containers and ref is not None:
        raise SchemaDefinitionError(f"{where}: only container types take a ref")
    for flag in ("required", "inert", "identity", "timestamp"):
        if flag in raw and type(raw[flag]) is not bool:
            raise SchemaDefinitionError(f"{where}: {flag} must be a boolean")
    values = raw.get("values")
    if values is not None:
        if type(values) is not list or not values or not set(types) <= {"int", "str"}:
            raise SchemaDefinitionError(f"{where}: values need int/str types and a non-empty list")
        values = tuple(values)
    return FieldSpec(key, types, bool(raw.get("required")), bool(raw.get("inert")),
                     bool(raw.get("identity")), bool(raw.get("timestamp")), ref, values)


def _matches(value: Any, type_name: str) -> bool:
    if type_name == "int":
        return type(value) is int
    if type_name == "str":
        return type(value) is str
    if type_name == "bool":
        return type(value) is bool
    if type_name == "number":
        return type(value) is int or type(value) is Decimal
    if type_name == "null":
        return value is None
    if type_name in ("object", "object_map"):
        return type(value) is dict
    return type(value) is list


def validate_closed(value: Any, schema: ClosedSchema) -> tuple[DriftFinding, ...]:
    """Every deviation of ``value`` from the closed ``schema``, sorted by (path, kind)."""

    findings: set[DriftFinding] = set()
    if type(value) is not list:
        findings.add(DriftFinding("$", "WRONG_TYPE", "RESPONSE", ()))
    else:
        root = schema.objects[schema.root_ref]
        for index, item in enumerate(value):
            _object(item, root, f"$[{index}]", (index,), schema, "RESPONSE", findings)
    return tuple(sorted(findings, key=lambda f: (f.path, f.kind, f.scope)))


def _object(value: Any, obj: ObjectSchema, path: str, trail: tuple, schema: ClosedSchema,
            container_scope: str, findings: set[DriftFinding]) -> None:
    if type(value) is not dict:
        findings.add(DriftFinding(path, "WRONG_TYPE", container_scope, trail))
        return
    for key in sorted(value):
        if key not in obj.keys:
            findings.add(DriftFinding(f"{path}.{key}", "UNKNOWN_KEY", obj.scope, trail + (key,)))
    for key, spec in obj.keys.items():
        if key not in value:
            if spec.required:
                findings.add(DriftFinding(f"{path}.{key}", "MISSING_REQUIRED",
                                          "RESPONSE" if spec.identity else obj.scope, trail + (key,)))
            continue
        _field(value[key], spec, f"{path}.{key}", trail + (key,), obj.scope, schema, findings)


def _field(value: Any, spec: FieldSpec, path: str, trail: tuple, scope: str, schema: ClosedSchema,
           findings: set[DriftFinding]) -> None:
    matched = [t for t in spec.types if _matches(value, t)]
    if not matched:
        findings.add(DriftFinding(path, "WRONG_TYPE", "RESPONSE" if spec.identity else scope, trail))
        return
    kind = matched[0]
    if spec.values is not None and kind in ("int", "str") and value not in spec.values:
        findings.add(DriftFinding(path, "UNKNOWN_ENUM", "RESPONSE" if spec.identity else scope, trail))
    if kind == "object":
        _object(value, schema.objects[spec.ref], path, trail, schema, scope, findings)
    elif kind == "object_map":
        inner = schema.objects[spec.ref]
        for key in sorted(value):
            if not _MAP_KEY.match(key):
                findings.add(DriftFinding(f"{path}.{key}", "UNKNOWN_KEY", scope, trail + (key,)))
            _object(value[key], inner, f"{path}.{key}", trail + (key,), schema, scope, findings)
    elif kind == "array":
        inner = schema.objects[spec.ref]
        for index, item in enumerate(value):
            _object(item, inner, f"{path}[{index}]", trail + (index,), schema, scope, findings)
