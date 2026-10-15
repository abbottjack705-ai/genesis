"""Immutable evidence: SHA-256 manifests over run and record directories, checked before reuse.

A manifest lists every file under a directory (except itself and pycache) with its SHA-256. The engine
verifies the manifest before it relies on evidence, so a changed, missing or extra file fails closed.
"""

from __future__ import annotations

import json
from pathlib import Path

from .state import WorkflowError, sha256_bytes

MANIFEST = "MANIFEST.json"


def _files(root: Path):
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if path.is_file() and path.name != MANIFEST and "pycache" not in rel.parts:
            yield path, rel.as_posix()


def _hashes(root: Path) -> dict:
    return {rel: sha256_bytes(path.read_bytes()) for path, rel in _files(root)}


def write_manifest(root: Path, label: str, extra: dict | None = None) -> str:
    """Write MANIFEST.json for ``root`` and return the SHA-256 of the manifest bytes."""
    doc = {"label": label, "files": _hashes(root), **(extra or {})}
    data = (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8")
    (root / MANIFEST).write_bytes(data)
    return sha256_bytes(data)


def verify_manifest(root: Path, expected_sha: str | None = None) -> dict:
    path = root / MANIFEST
    if not path.exists():
        raise WorkflowError("EVIDENCE_MISSING", f"{root.name} has no manifest")
    data = path.read_bytes()
    if expected_sha is not None and sha256_bytes(data) != expected_sha:
        raise WorkflowError("EVIDENCE_MISMATCH", f"manifest of {root.name} changed since it was recorded")
    doc = json.loads(data.decode("utf-8"))
    if _hashes(root) != doc.get("files"):
        raise WorkflowError("EVIDENCE_MISMATCH", f"files under {root.name} changed, are missing or were added")
    return doc
