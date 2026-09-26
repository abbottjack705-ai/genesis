"""Build and verify byte-explicit Genesis hostile re-audit packages."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA = "genesis-audit-evidence-package-v2"
MANIFEST_NAME = "GENESIS_AUDIT_PACKAGE_MANIFEST.json"
REPRESENTATIONS = {
    "git_blob_bytes": "exact bytes returned by Git object plumbing at target commit",
    "raw_worktree_bytes": "exact bytes read from the named checkout path; no normalization",
    "historical_raw_artifact_bytes": "exact pre-existing external artifact bytes; no normalization",
}
TOP_LEVEL_FIELDS = {
    "schema_version",
    "target",
    "repository_status",
    "representation_contract",
    "source_snapshot",
    "raw_worktree_roots",
    "authorities",
    "members",
    "non_authorizations",
    "self_reference_note",
}
NON_AUTHORIZATIONS = ["adapter", "shadow-research", "protected-campaign", "live-money"]
SELF_REFERENCE_NOTE = (
    "The manifest hashes every package member except itself; the adjacent "
    "SHA-256 sidecar authenticates the finished ZIP and embedded manifest."
)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: str, name: str) -> str:
    if len(value) != 64 or value.lower() != value:
        raise ValueError(f"{name} must be lowercase SHA-256 hex")
    int(value, 16)
    return value


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args], stderr=subprocess.STDOUT,
    )


def _safe_member(name: str) -> str:
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
        raise ValueError("archive member path is invalid")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("archive member path is unsafe")
    if path.as_posix() != name:
        raise ValueError("archive member path is not canonical")
    return name


def _git_sha1(value: object, name: str) -> str:
    if not isinstance(value, str) or len(value) != 40 or value.lower() != value:
        raise ValueError(f"{name} is not lowercase Git SHA-1")
    int(value, 16)
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"package manifest has a duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"package manifest has a non-finite JSON number: {value}")


def _manifest_bytes(manifest: dict[str, Any]) -> bytes:
    return (
        json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _load_manifest(raw: bytes) -> dict[str, Any]:
    """Parse exactly one canonical manifest representation (O-2).

    Duplicate keys, non-finite numbers and any encoding other than the
    builder's canonical bytes are rejected, so no conflicting value can hide
    behind an alternative JSON representation.
    """

    manifest = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
    )
    if not isinstance(manifest, dict) or _manifest_bytes(manifest) != raw:
        raise ValueError("package manifest bytes are not the canonical encoding")
    return manifest


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


def _parse_pair(value: str, name: str) -> tuple[str, str]:
    if "=" not in value:
        raise ValueError(f"{name} must be LABEL=VALUE")
    left, right = value.split("=", 1)
    if not left or not right:
        raise ValueError(f"{name} must have nonempty sides")
    return left, right


def _tree(repo: Path, revision: str) -> tuple[str, str, list[dict[str, Any]]]:
    commit = _git(repo, "rev-parse", "--verify", f"{revision}^{{commit}}").decode().strip()
    tree = _git(repo, "rev-parse", f"{commit}^{{tree}}").decode().strip()
    rows: list[dict[str, Any]] = []
    output = _git(repo, "ls-tree", "-rz", "--full-tree", commit)
    for record in output.split(b"\x00"):
        if not record:
            continue
        header, raw_path = record.split(b"\t", 1)
        mode, kind, object_id = header.decode("ascii").split(" ")
        if kind != "blob":
            raise ValueError(f"unsupported non-blob Git member: {raw_path!r}")
        repository_path = raw_path.decode("utf-8")
        _safe_member(repository_path)
        raw = _git(repo, "cat-file", "blob", object_id)
        rows.append({
            "archive_path": f"git-blobs/{repository_path}",
            "representation": "git_blob_bytes",
            "source_path": repository_path,
            "repository_path": repository_path,
            "git_mode": mode,
            "git_blob_oid": object_id,
            "bytes": len(raw),
            "sha256": sha256(raw),
            "_raw": raw,
        })
    rows.sort(key=lambda row: row["repository_path"])
    return commit, tree, rows


def _worktree_files(repo: Path, relative: str) -> tuple[str, list[tuple[str, Path]]]:
    requested = Path(relative)
    if requested.is_absolute():
        raise ValueError("raw worktree root must be repository-relative")
    root = repo.resolve()
    target = (root / requested).resolve(strict=True)
    if not target.is_relative_to(root):
        raise ValueError("raw worktree root escapes repository")
    canonical = _safe_member(target.relative_to(root).as_posix())
    # Only Git-tracked paths: ignored caches are neither evidence nor clean-checked.
    listed = _git(root, "ls-files", "-z", "--", canonical)
    paths = sorted(name.decode("utf-8") for name in listed.split(b"\x00") if name)
    if not paths:
        raise ValueError("raw worktree root contains no tracked files")
    return canonical, [(_safe_member(path), root / path) for path in paths]


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key != "_raw"}


def _add(rows: dict[str, dict[str, Any]], row: dict[str, Any]) -> None:
    path = _safe_member(row["archive_path"])
    if path == MANIFEST_NAME or path in rows:
        raise ValueError(f"duplicate archive member: {path}")
    rows[path] = row


def _zip_write(archive: zipfile.ZipFile, name: str, raw: bytes) -> None:
    info = zipfile.ZipInfo(_safe_member(name), date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    archive.writestr(info, raw, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def build_package(
    *,
    repo: Path,
    revision: str,
    output: Path,
    raw_worktree_roots: list[str],
    historical: list[str],
    authorities: list[str],
) -> dict[str, Any]:
    repo = repo.resolve(strict=True)
    output = output.resolve()
    if output.exists() or Path(str(output) + ".sha256").exists():
        raise ValueError("package output or sidecar already exists")
    status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise ValueError("repository must be clean before packaging")
    commit, tree, source = _tree(repo, revision)
    head = _git(repo, "rev-parse", "HEAD").decode().strip()
    if head != commit:
        raise ValueError("target commit must be the clean checkout HEAD")

    rows: dict[str, dict[str, Any]] = {}
    for row in source:
        _add(rows, row)
    declared_roots: list[str] = []
    for relative_root in raw_worktree_roots:
        canonical_root, files = _worktree_files(repo, relative_root)
        if any(_under(canonical_root, other) or _under(other, canonical_root)
               for other in declared_roots):
            raise ValueError(f"raw worktree roots overlap: {canonical_root}")
        declared_roots.append(canonical_root)
        for relative, path in files:
            raw = path.read_bytes()
            _add(rows, {
                "archive_path": f"raw-worktree/{relative}",
                "representation": "raw_worktree_bytes",
                "source_path": relative,
                "bytes": len(raw),
                "sha256": sha256(raw),
                "_raw": raw,
            })
    for specification in historical:
        label, source_path = _parse_pair(specification, "historical artifact")
        label = _safe_member(label)
        raw = Path(source_path).resolve(strict=True).read_bytes()
        _add(rows, {
            "archive_path": f"historical/{label}",
            "representation": "historical_raw_artifact_bytes",
            "source_path": label,
            "bytes": len(raw),
            "sha256": sha256(raw),
            "_raw": raw,
        })

    source_by_path = {row["repository_path"]: row for row in source}
    authority_rows: list[dict[str, str]] = []
    for specification in authorities:
        repository_path, approved_hash = _parse_pair(specification, "authority")
        repository_path = _safe_member(repository_path)
        approved_hash = _digest(approved_hash, "approved authority hash")
        if repository_path not in source_by_path:
            raise ValueError(f"authority is absent from target commit: {repository_path}")
        actual = source_by_path[repository_path]["sha256"]
        if actual != approved_hash:
            raise ValueError(f"authority Git-blob bytes do not match approval: {repository_path}")
        authority_rows.append({
            "repository_path": repository_path,
            "approved_sha256": approved_hash,
            "git_blob_sha256": actual,
            "archive_path": source_by_path[repository_path]["archive_path"],
            "representation": "git_blob_bytes",
        })
    authority_rows.sort(key=lambda row: row["repository_path"])

    public_members = [_public(rows[path]) for path in sorted(rows)]
    manifest = {
        "schema_version": SCHEMA,
        "target": {"commit": commit, "tree": tree},
        "repository_status": "clean",
        "representation_contract": REPRESENTATIONS,
        "source_snapshot": [_public(row) for row in source],
        "raw_worktree_roots": sorted(declared_roots),
        "authorities": authority_rows,
        "members": public_members,
        "non_authorizations": NON_AUTHORIZATIONS,
        "self_reference_note": SELF_REFERENCE_NOTE,
    }
    manifest_raw = _manifest_bytes(manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x") as archive:
        _zip_write(archive, MANIFEST_NAME, manifest_raw)
        for name in sorted(rows):
            _zip_write(archive, name, rows[name]["_raw"])
    archive_hash = sha256(output.read_bytes())
    sidecar = Path(str(output) + ".sha256")
    sidecar.write_bytes(f"{archive_hash}  {output.name}\n".encode("ascii"))
    verify_package(
        archive_path=output, repo=repo, extract_to=None, authorities=authorities,
        expect_commit=commit, required_raw_roots=declared_roots,
        required_historical=[
            f"{row['source_path']}={row['sha256']}"
            for row in public_members
            if row["representation"] == "historical_raw_artifact_bytes"
        ],
    )
    return {
        "archive": str(output),
        "sha256": archive_hash,
        "bytes": output.stat().st_size,
        "sidecar": str(sidecar),
        "manifest_sha256": sha256(manifest_raw),
        "members": len(rows),
        "source_files": len(source),
        "target_commit": commit,
        "target_tree": tree,
    }


def _validate_manifest(manifest: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(manifest, dict) or set(manifest) != TOP_LEVEL_FIELDS:
        raise ValueError("package manifest has unknown or missing top-level fields")
    if manifest["schema_version"] != SCHEMA:
        raise ValueError("unsupported package manifest schema")
    if manifest["repository_status"] != "clean":
        raise ValueError("package repository status is not clean")
    if manifest["non_authorizations"] != NON_AUTHORIZATIONS:
        raise ValueError("package non-authorizations are not exact")
    if manifest["self_reference_note"] != SELF_REFERENCE_NOTE:
        raise ValueError("package self-reference note is not exact")
    if manifest["representation_contract"] != REPRESENTATIONS:
        raise ValueError("package representation contract is not exact")
    target = manifest["target"]
    if not isinstance(target, dict) or set(target) != {"commit", "tree"}:
        raise ValueError("package target is malformed")
    for key in ("commit", "tree"):
        value = target[key]
        if not isinstance(value, str) or len(value) != 40 or value.lower() != value:
            raise ValueError(f"target {key} is not lowercase Git SHA-1")
        int(value, 16)
    members = manifest["members"]
    source = manifest["source_snapshot"]
    if not isinstance(members, list) or not isinstance(source, list):
        raise ValueError("package member inventories are malformed")
    member_by_path: dict[str, dict[str, Any]] = {}
    for row in members:
        required = {"archive_path", "representation", "source_path", "bytes", "sha256"}
        if not isinstance(row, dict) or not required.issubset(row):
            raise ValueError("package member row is malformed")
        if row["representation"] != "git_blob_bytes" and set(row) != required:
            raise ValueError("package member row has undeclared fields")
        path = _safe_member(row["archive_path"])
        if path == MANIFEST_NAME or path in member_by_path:
            raise ValueError("package member inventory contains a duplicate")
        representation = row["representation"]
        if representation not in REPRESENTATIONS:
            raise ValueError("package member representation is unsupported")
        prefix = {
            "git_blob_bytes": "git-blobs/",
            "raw_worktree_bytes": "raw-worktree/",
            "historical_raw_artifact_bytes": "historical/",
        }[representation]
        if not path.startswith(prefix):
            raise ValueError("package member path disagrees with representation")
        if not isinstance(row["bytes"], int) or row["bytes"] < 0:
            raise ValueError("package member byte length is invalid")
        _digest(row["sha256"], "package member hash")
        member_by_path[path] = row
    if sorted(member_by_path) != [row["archive_path"] for row in members]:
        raise ValueError("package members are not in canonical order")
    if source != [row for row in members if row["representation"] == "git_blob_bytes"]:
        raise ValueError("source snapshot is not the exact Git-blob member subset")
    for row in source:
        expected = {
            "archive_path", "representation", "source_path", "repository_path",
            "git_mode", "git_blob_oid", "bytes", "sha256",
        }
        if set(row) != expected or row["source_path"] != row["repository_path"]:
            raise ValueError("Git source member row is malformed")
        if row["archive_path"] != f"git-blobs/{row['repository_path']}":
            raise ValueError("Git source archive path is inconsistent")
    for row in members:
        prefix = {
            "raw_worktree_bytes": "raw-worktree/",
            "historical_raw_artifact_bytes": "historical/",
        }.get(row["representation"])
        if prefix is not None and row["archive_path"] != prefix + _safe_member(row["source_path"]):
            raise ValueError("package member source path disagrees with its archive path")
    _validate_raw_roots(manifest["raw_worktree_roots"], members, source)
    authorities = manifest["authorities"]
    if not isinstance(authorities, list):
        raise ValueError("authority inventory is malformed")
    for row in authorities:
        if not isinstance(row, dict) or set(row) != {
            "repository_path", "approved_sha256", "git_blob_sha256",
            "archive_path", "representation",
        }:
            raise ValueError("authority row is malformed")
        if row["representation"] != "git_blob_bytes":
            raise ValueError("authority is not labeled as Git-blob bytes")
        approved = _digest(row["approved_sha256"], "approved authority hash")
        actual = _digest(row["git_blob_sha256"], "authority Git-blob hash")
        if approved != actual:
            raise ValueError("authority bytes differ from approved hash")
        member = member_by_path.get(row["archive_path"])
        if member is None or member.get("repository_path") != row["repository_path"]:
            raise ValueError("authority does not resolve to its Git source member")
        if member["sha256"] != approved:
            raise ValueError("authority member bytes differ from approved hash")
    return members, target


def _validate_raw_roots(
    roots: Any, members: list[dict[str, Any]], source: list[dict[str, Any]],
) -> None:
    """Every declared raw root carries exactly its tracked files (O-3).

    The raw set under a root must equal the target commit's tracked files under
    it, which the source snapshot lists, so an omitted raw member is detected
    without Git. Omitting a whole root is visible only against a caller pin.
    """

    if not isinstance(roots, list) or roots != sorted(set(roots)):
        raise ValueError("package raw worktree roots are not a sorted unique list")
    for root in roots:
        _safe_member(root)
        if any(other != root and (_under(root, other) or _under(other, root))
               for other in roots):
            raise ValueError("package raw worktree roots overlap")
    raw_paths = sorted(
        row["source_path"] for row in members if row["representation"] == "raw_worktree_bytes"
    )
    tracked = [row["repository_path"] for row in source]
    for root in roots:
        expected = sorted(path for path in tracked if _under(path, root))
        if not expected:
            raise ValueError(f"package raw worktree root has no tracked files: {root}")
        if [path for path in raw_paths if _under(path, root)] != expected:
            raise ValueError(f"package raw worktree root is incomplete or altered: {root}")
    if any(not any(_under(path, root) for root in roots) for path in raw_paths):
        raise ValueError("package raw worktree member lies outside every declared root")


def _require_commit(target: dict[str, Any], expected: str) -> None:
    if target["commit"] != _git_sha1(expected, "expected commit pin"):
        raise ValueError("package target commit differs from the caller-pinned commit")


def _require_raw_roots(manifest: dict[str, Any], pins: list[str]) -> None:
    expected = [_safe_member(pin) for pin in pins]
    if len(expected) != len(set(expected)):
        raise ValueError("duplicate raw worktree root pin")
    if sorted(expected) != manifest["raw_worktree_roots"]:
        raise ValueError("package raw worktree roots differ from caller-pinned roots")


def _require_historical(members: list[dict[str, Any]], pins: list[str]) -> None:
    expected: dict[str, str] = {}
    for specification in pins:
        label, digest = _parse_pair(specification, "historical pin")
        label = _safe_member(label)
        if label in expected:
            raise ValueError(f"duplicate historical pin: {label}")
        expected[label] = _digest(digest, "pinned historical hash")
    actual = {
        row["source_path"]: row["sha256"]
        for row in members if row["representation"] == "historical_raw_artifact_bytes"
    }
    if actual != expected:
        raise ValueError("package historical artifacts differ from caller-pinned hashes")


def _require_authorities(manifest: dict[str, Any], pins: list[str]) -> None:
    expected: dict[str, str] = {}
    for specification in pins:
        repository_path, approved_hash = _parse_pair(specification, "authority")
        repository_path = _safe_member(repository_path)
        if repository_path in expected:
            raise ValueError(f"duplicate authority pin: {repository_path}")
        expected[repository_path] = _digest(approved_hash, "approved authority hash")
    actual = {
        row["repository_path"]: row["approved_sha256"]
        for row in manifest["authorities"]
    }
    if len(actual) != len(manifest["authorities"]) or actual != expected:
        raise ValueError("package authority rows differ from caller-pinned approvals")


def verify_package(
    *,
    archive_path: Path,
    repo: Path | None,
    extract_to: Path | None,
    authorities: list[str] | None = None,
    expect_commit: str | None = None,
    required_raw_roots: list[str] | None = None,
    required_historical: list[str] | None = None,
) -> dict[str, Any]:
    """Verify one package; caller pins bind it to facts from outside it (O-1/O-3).

    Without an out-of-band package hash, a self-consistent forgery can still
    pass: pins and ``--repo`` narrow what a forger can change, never more.
    """

    archive_path = archive_path.resolve(strict=True)
    archive_hash = sha256(archive_path.read_bytes())
    sidecar = Path(str(archive_path) + ".sha256")
    if not sidecar.is_file():
        raise ValueError("package SHA-256 sidecar is missing")
    parts = sidecar.read_text(encoding="ascii").strip().split("  ", 1)
    if parts != [archive_hash, archive_path.name]:
        raise ValueError("package sidecar does not identify the exact ZIP")
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise ValueError("package ZIP contains duplicate member names")
        for name in names:
            _safe_member(name)
        if archive.testzip() is not None:
            raise ValueError("package ZIP CRC verification failed")
        if MANIFEST_NAME not in names:
            raise ValueError("package manifest is missing")
        manifest_raw = archive.read(MANIFEST_NAME)
        manifest = _load_manifest(manifest_raw)
        members, target = _validate_manifest(manifest)
        if expect_commit is not None:
            _require_commit(target, expect_commit)
        if authorities is not None:
            _require_authorities(manifest, authorities)
        if required_raw_roots is not None:
            _require_raw_roots(manifest, required_raw_roots)
        if required_historical is not None:
            _require_historical(members, required_historical)
        expected_names = {MANIFEST_NAME, *(row["archive_path"] for row in members)}
        if set(names) != expected_names:
            raise ValueError("package ZIP membership differs from manifest")
        for row in members:
            raw = archive.read(row["archive_path"])
            if len(raw) != row["bytes"] or sha256(raw) != row["sha256"]:
                raise ValueError(f"package member bytes fail manifest: {row['archive_path']}")

        git_cross_check = False
        if repo is not None:
            repo = repo.resolve(strict=True)
            commit, tree, source = _tree(repo, target["commit"])
            if commit != target["commit"] or tree != target["tree"]:
                raise ValueError("package target commit/tree differs from Git")
            expected = [_public(row) for row in source]
            if manifest["source_snapshot"] != expected:
                raise ValueError("package source inventory differs from Git tree")
            for row in source:
                if archive.read(row["archive_path"]) != row["_raw"]:
                    raise ValueError("package Git member differs from object database")
            git_cross_check = True

        fresh_verified = False
        if extract_to is not None:
            destination = extract_to.resolve()
            if destination.exists() and any(destination.iterdir()):
                raise ValueError("fresh extraction destination is not empty")
            destination.mkdir(parents=True, exist_ok=True)
            for name in names:
                target_path = (destination / Path(*PurePosixPath(name).parts)).resolve()
                if not target_path.is_relative_to(destination):
                    raise ValueError("package extraction path escapes destination")
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(archive.read(name))
            for row in members:
                raw = (destination / Path(*PurePosixPath(row["archive_path"]).parts)).read_bytes()
                if len(raw) != row["bytes"] or sha256(raw) != row["sha256"]:
                    raise ValueError("freshly extracted member fails manifest")
            if (destination / MANIFEST_NAME).read_bytes() != manifest_raw:
                raise ValueError("freshly extracted manifest bytes changed")
            fresh_verified = True
    return {
        "archive": str(archive_path),
        "sha256": archive_hash,
        "bytes": archive_path.stat().st_size,
        "manifest_sha256": sha256(manifest_raw),
        "members": len(members),
        "source_files": len(manifest["source_snapshot"]),
        "target_commit": target["commit"],
        "target_tree": target["tree"],
        "sidecar_verified": True,
        "authorities_pinned": authorities is not None,
        "commit_pinned": expect_commit is not None,
        "raw_roots_pinned": required_raw_roots is not None,
        "historical_pinned": required_historical is not None,
        "raw_worktree_roots": manifest["raw_worktree_roots"],
        "git_cross_check": git_cross_check,
        "fresh_extraction_verified": fresh_verified,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--repo", required=True, type=Path)
    build.add_argument("--commit", required=True)
    build.add_argument("--output", required=True, type=Path)
    build.add_argument("--raw-worktree-root", action="append", default=[])
    build.add_argument("--historical", action="append", default=[])
    build.add_argument("--authority", action="append", default=[])
    verify = commands.add_parser("verify")
    verify.add_argument("--archive", required=True, type=Path)
    verify.add_argument("--repo", type=Path)
    verify.add_argument("--extract-to", type=Path)
    verify.add_argument("--authority", action="append")
    verify.add_argument("--expect-commit")
    verify.add_argument("--require-raw-root", action="append")
    verify.add_argument("--require-historical", action="append")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "build":
            report = build_package(
                repo=args.repo,
                revision=args.commit,
                output=args.output,
                raw_worktree_roots=args.raw_worktree_root,
                historical=args.historical,
                authorities=args.authority,
            )
        else:
            report = verify_package(
                archive_path=args.archive,
                repo=args.repo,
                extract_to=args.extract_to,
                authorities=args.authority,
                expect_commit=args.expect_commit,
                required_raw_roots=args.require_raw_root,
                required_historical=args.require_historical,
            )
    except (
        OSError,
        ValueError,
        UnicodeError,
        json.JSONDecodeError,
        zipfile.BadZipFile,
        subprocess.CalledProcessError,
    ) as exc:
        print(f"audit package rejected: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
