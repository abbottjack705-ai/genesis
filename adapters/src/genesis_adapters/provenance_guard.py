"""Runtime module-provenance guard (design section 2.4, FRZ-09).

Tree SHAs prove what is *committed*. This guard proves what Python actually *loaded*: a
``PYTHONPATH`` entry, a ``.pth`` file, a competing ``genesis`` package or a stale bytecode
file could otherwise make the adapter run against a different foundation.

This module deliberately imports nothing from ``genesis`` so it can run before the frozen
package is imported. Every failure raises :class:`ModuleProvenanceError` with a stable
``code`` (never file contents).
"""

from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import site
import subprocess
import sys
import zipfile
from pathlib import Path

MANIFEST_SCHEMA = "genesis.adapters.frozen-modules.v1"
FROZEN_PACKAGE = "genesis"
ADAPTER_PACKAGE = "genesis_adapters"


class ModuleProvenanceError(RuntimeError):
    """Fail-closed provenance failure; ``code`` is a stable machine-readable reason."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def blob_sha1(data: bytes) -> str:
    """Git blob object ID of ``data``."""

    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def _canonical(value) -> bytes:
    # Identical to genesis.repro.canonical_json (kept local: no genesis import here).
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _norm(path) -> str:
    return os.path.normcase(os.path.realpath(str(path)))


def _git(repo: Path, *args: str, binary: bool = False):
    result = subprocess.run(["git", "--no-replace-objects", "-C", str(repo), *args],
                            capture_output=True, check=False)
    if result.returncode != 0:
        raise ModuleProvenanceError("GIT_FAILURE", args[0])
    return result.stdout if binary else result.stdout.decode("utf-8")


def _ls_tree(repo: Path, tree: str) -> dict[str, str]:
    listing = _git(repo, "ls-tree", "-r", tree)
    blobs: dict[str, str] = {}
    for line in listing.splitlines():
        meta, path = line.split("\t", 1)
        blobs[path] = meta.split()[2]
    return blobs


def generate_manifest(repo: Path, src_tree: str) -> bytes:
    """Canonical manifest bytes for every ``.py`` file of the frozen ``src`` tree."""

    entries = {}
    for path, blob in sorted(_ls_tree(repo, src_tree).items()):
        if not path.endswith(".py"):
            continue
        data = _git(repo, "cat-file", "blob", blob, binary=True)
        if blob_sha1(data) != blob:
            raise ModuleProvenanceError("GIT_FAILURE", "blob identity")
        entries[path] = {"blob_sha1": blob, "sha256": sha256_hex(data)}
    return _canonical({"schema": MANIFEST_SCHEMA, "src_tree": src_tree, "entries": entries})


def _has_package(directory: str, name: str) -> bool:
    """True if ``directory`` (a folder or zip file) can provide a top-level ``name``."""

    if os.path.isdir(directory):
        base = Path(directory)
        if (base / name).exists() or (base / f"{name}.py").exists():
            return True
        return any(base.glob(f"{name}.*.pyd")) or any(base.glob(f"{name}.*.so")) \
            or any(base.glob(f"{name}.*.dll"))
    if os.path.isfile(directory) and zipfile.is_zipfile(directory):
        with zipfile.ZipFile(directory) as archive:
            names = archive.namelist()
        return any(item == f"{name}.py" or item.startswith(f"{name}/") for item in names)
    return False


def _default_site_dirs() -> list[Path]:
    dirs: list[str] = []
    try:
        dirs += list(site.getsitepackages())
    except AttributeError:
        pass
    try:
        dirs.append(site.getusersitepackages())
    except AttributeError:
        pass
    return [Path(item) for item in dirs if item]


def _inside(child: str, parent: str) -> bool:
    return child == parent or child.startswith(parent.rstrip(os.sep) + os.sep)


def _load_manifest(manifest_path: Path, expected_sha256: str | None) -> tuple[dict, str]:
    raw = Path(manifest_path).read_bytes()
    digest = sha256_hex(raw)
    if expected_sha256 is not None and digest != expected_sha256:
        raise ModuleProvenanceError("MANIFEST_PIN", "manifest bytes differ from the pinned digest")
    try:
        manifest = json.loads(raw)
    except ValueError as exc:
        raise ModuleProvenanceError("MANIFEST_SHAPE", "not JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA \
            or set(manifest) != {"schema", "src_tree", "entries"} \
            or not isinstance(manifest["entries"], dict) or not manifest["entries"]:
        raise ModuleProvenanceError("MANIFEST_SHAPE", "unexpected manifest schema")
    for path, entry in manifest["entries"].items():
        if not isinstance(entry, dict) or set(entry) != {"blob_sha1", "sha256"} \
                or not path.startswith(f"{FROZEN_PACKAGE}/") or not path.endswith(".py"):
            raise ModuleProvenanceError("MANIFEST_SHAPE", "unexpected manifest entry")
    if _canonical(manifest) != raw:
        raise ModuleProvenanceError("MANIFEST_SHAPE", "manifest is not canonical")
    return manifest, digest


def verify_loaded_genesis_modules(
    repo: Path, *, manifest_path: Path, expected_manifest_sha256: str | None = None,
    site_dirs: list[Path] | None = None, require_isolated_bytecode: bool = True,
    check_git: bool = True,
) -> dict:
    """Fail closed unless every loaded ``genesis.*`` module is the frozen source. Returns the verdict."""

    repo = Path(_norm(repo))
    src = repo / "src"
    src_norm = _norm(src)
    genesis_dir = _norm(src / FROZEN_PACKAGE)
    manifest, manifest_digest = _load_manifest(manifest_path, expected_manifest_sha256)

    if check_git and (repo / ".git").exists():
        actual = _ls_tree(repo, manifest["src_tree"])
        wanted = {path: entry["blob_sha1"] for path, entry in manifest["entries"].items()}
        listed = {path: blob for path, blob in actual.items() if path.endswith(".py")}
        if listed != wanted:
            raise ModuleProvenanceError("MANIFEST_GIT_MISMATCH", "manifest differs from git ls-tree")

    # 6. bytecode isolation
    flags = {"dont_write_bytecode": bool(sys.flags.dont_write_bytecode),
             "pycache_prefix": sys.pycache_prefix, "isolated": bool(sys.flags.isolated),
             "safe_path": bool(getattr(sys.flags, "safe_path", False))}
    if require_isolated_bytecode:
        if not sys.flags.dont_write_bytecode or not sys.pycache_prefix:
            raise ModuleProvenanceError("BYTECODE_NOT_ISOLATED", "run with -B and PYTHONPYCACHEPREFIX")
        prefix = Path(sys.pycache_prefix)
        if prefix.exists() and any(prefix.rglob("*.pyc")):
            raise ModuleProvenanceError("BYTECODE_NOT_ISOLATED", "pycache prefix is not fresh")

    # 1. origin and single search location
    spec = importlib.util.find_spec(FROZEN_PACKAGE)
    if spec is None or spec.origin is None or _norm(spec.origin) != _norm(
            src / FROZEN_PACKAGE / "__init__.py"):
        raise ModuleProvenanceError("GENESIS_ORIGIN", "genesis does not resolve to the frozen src")
    locations = [_norm(item) for item in (spec.submodule_search_locations or [])]
    if locations != [genesis_dir]:
        raise ModuleProvenanceError("GENESIS_ORIGIN", "genesis has unexpected search locations")

    # 3. no competing genesis / genesis_adapters on any sys.path entry
    adapters_src = _norm(repo / "adapters" / "src")
    for entry in sys.path:
        real = _norm(entry or os.getcwd())
        if real != src_norm and _has_package(real, FROZEN_PACKAGE):
            raise ModuleProvenanceError("COMPETING_GENESIS", "a second genesis is importable")
        if real != adapters_src and _has_package(real, ADAPTER_PACKAGE):
            raise ModuleProvenanceError("COMPETING_ADAPTERS", "a second genesis_adapters is importable")

    # 2. every loaded genesis.* module is the frozen file, loaded by a plain SourceFileLoader
    modules = []
    for name in sorted(name for name in list(sys.modules)
                       if name == FROZEN_PACKAGE or name.startswith(FROZEN_PACKAGE + ".")):
        module = sys.modules[name]
        if module is None or getattr(module, "__file__", None) is None:
            raise ModuleProvenanceError("MODULE_NOT_FILE", "loaded module has no source file")
        real = _norm(module.__file__)
        if not _inside(real, genesis_dir):
            raise ModuleProvenanceError("MODULE_OUTSIDE_FROZEN_SRC", "module file is outside src/genesis")
        loader = getattr(getattr(module, "__spec__", None), "loader", None)
        if type(loader) is not importlib.machinery.SourceFileLoader:
            raise ModuleProvenanceError("LOADER_TYPE", "loader is not a plain SourceFileLoader")
        relative = Path(real).relative_to(_norm(src)).as_posix()
        entry = manifest["entries"].get(relative)
        if entry is None:
            # normcase may lower-case on Windows: compare case-insensitively as a fallback
            for path, value in manifest["entries"].items():
                if path.lower() == relative.lower():
                    relative, entry = path, value
                    break
        if entry is None:
            raise ModuleProvenanceError("MODULE_NOT_IN_MANIFEST", "module is not a frozen file")
        data = Path(module.__file__).read_bytes()
        if blob_sha1(data) != entry["blob_sha1"] or sha256_hex(data) != entry["sha256"]:
            raise ModuleProvenanceError("MODULE_HASH_MISMATCH", "module bytes differ from the frozen blob")
        modules.append({"name": name, "path": relative, "blob_sha1": entry["blob_sha1"],
                        "sha256": entry["sha256"]})

    # 4. .pth files
    dirs = _default_site_dirs() if site_dirs is None else [Path(item) for item in site_dirs]
    repo_norm = _norm(repo)
    listed_paths = {_norm(entry or os.getcwd()) for entry in sys.path}
    for directory in dirs:
        if not directory.is_dir():
            continue
        for pth in sorted(directory.glob("*.pth")):
            try:
                lines = pth.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError as exc:
                raise ModuleProvenanceError("PTH_REFERENCE", "unreadable .pth file") from exc
            for line in lines:
                text = line.strip()
                if not text or text.startswith("#"):
                    continue
                if text.startswith(("import ", "import\t")):
                    if "genesis" in text.lower() or repo_norm.lower() in text.lower():
                        raise ModuleProvenanceError("PTH_REFERENCE", ".pth import line names the project")
                    continue
                target = _norm(directory / text)
                if target == src_norm:
                    if target not in listed_paths:
                        raise ModuleProvenanceError("PTH_REFERENCE", ".pth adds an unrecorded src path")
                    continue
                if _inside(target, repo_norm) or _has_package(target, FROZEN_PACKAGE) \
                        or _has_package(target, ADAPTER_PACKAGE):
                    raise ModuleProvenanceError("PTH_REFERENCE", ".pth references the repo or a genesis package")

    # 5. genesis_adapters resolves to the working tree and every loaded module is under it
    adapter_spec = importlib.util.find_spec(ADAPTER_PACKAGE)
    adapter_dir = _norm(repo / "adapters" / "src" / ADAPTER_PACKAGE)
    if adapter_spec is None or adapter_spec.origin is None or _norm(adapter_spec.origin) != _norm(
            Path(adapter_dir) / "__init__.py"):
        raise ModuleProvenanceError("ADAPTERS_ORIGIN", "genesis_adapters does not resolve to adapters/src")
    adapter_modules = []
    for name in sorted(name for name in list(sys.modules)
                       if name == ADAPTER_PACKAGE or name.startswith(ADAPTER_PACKAGE + ".")):
        module = sys.modules[name]
        if module is None or getattr(module, "__file__", None) is None \
                or not _inside(_norm(module.__file__), adapter_dir):
            raise ModuleProvenanceError("ADAPTERS_ORIGIN", "adapter module outside adapters/src")
        if type(module.__spec__.loader) is not importlib.machinery.SourceFileLoader:
            raise ModuleProvenanceError("LOADER_TYPE", "adapter loader is not a plain SourceFileLoader")
        adapter_modules.append(name)

    return {
        "verdict": "PASS",
        "repo": str(repo),
        "python": sys.version.split()[0],
        "flags": flags,
        "genesis_origin": str(Path(genesis_dir) / "__init__.py"),
        "manifest_sha256": manifest_digest,
        "modules": modules,
        "adapter_modules": adapter_modules,
        "site_dirs": [str(item) for item in dirs],
        "sys_path": [str(item) for item in sys.path],
    }
