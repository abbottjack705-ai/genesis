"""Deterministic serialization, hashing, and immutable publication helpers."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


class ImmutableConflict(ValueError):
    """Raised when an existing path is asked to hold different bytes."""


def canonical_json(value: Any) -> bytes:
    """Return one deterministic, strict JSON representation."""

    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_digest(path: str | Path) -> str:
    """Hash a file or directory, including relative paths and file hashes."""

    root = Path(path)
    if root.is_file():
        return sha256_file(root)
    if not root.is_dir():
        return "MISSING"
    digest = hashlib.sha256()
    for child in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(child.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256_file(child)))
    return digest.hexdigest()


def immutable_write(path: str | Path, data: bytes) -> None:
    """Publish bytes atomically and never overwrite evidence.

    Re-publishing identical bytes is idempotent.  A differing payload is a
    conflict and must be represented as a new content-addressed artifact.
    """

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_bytes() != data:
            raise ImmutableConflict(f"immutable path differs: {destination}")
        return

    fd, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".pending", dir=str(destination.parent)
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        # A hard link makes publication one-way: it cannot replace a prior
        # evidence file if another process won the race.
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if destination.read_bytes() != data:
                raise ImmutableConflict(f"immutable path differs: {destination}")
        finally:
            Path(temporary).unlink(missing_ok=True)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))

