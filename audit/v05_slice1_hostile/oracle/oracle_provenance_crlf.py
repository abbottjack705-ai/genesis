#!/usr/bin/env python3
"""Oracle 2 - FRZ-09 module provenance and the CRLF fail-closed rule (audit area 1).

  python oracle_provenance_crlf.py --repo <candidate checkout> [--json out.json]

P-1  Regenerate the expected frozen-module manifest from the frozen src tree object
     51cb635... with git plumbing (path, blob SHA-1, SHA-256 of blob bytes) and compare
     with adapters/config/frozen_genesis_modules.json (entries, blob ids, sha256).
     The manifest's own SHA-256 is printed so it can be compared with the pin in
     adapters/src/genesis_adapters/oddspapi/verify.py.
P-2  Hash the *working tree* copies of every src/genesis/**/*.py in the checkout.
     A Windows checkout with core.autocrlf=true would hold CRLF bytes whose blob id
     differs from the manifest. The architecture (2.4 check 2) requires the guard to
     compare bytes, so such a checkout must be refused, not normalized.
P-3  CRLF attack in a subprocess: copy the checkout to a temp dir, rewrite one frozen
     module with CRLF endings (same text), import genesis from that copy and call the
     candidate's provenance_guard.verify_loaded_genesis_modules(repo, manifest_path=...).
     Expected: ModuleProvenanceError (fail closed). A guard that opens files in text
     mode, strips \r, or hashes normalized text passes the CRLF copy -> DEFECT.
P-4  Same as P-3 with a one-byte semantic edit (a comment character changed), to show
     the subprocess harness itself detects a genuine change (control).
P-5  Static: provenance_guard.py must read files in binary mode and must not contain
     newline normalization ("\\r\\n", "newline=", "universal", ".replace(b'\\r'").
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FROZEN_SRC_TREE = "51cb635bc42b993815b6c02a23c4c3ceb7d98476"


def git(repo: str, *args: str, binary: bool = False):
    proc = subprocess.run(["git", "-C", repo, *args], capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout if binary else proc.stdout.decode()


def expected_manifest(repo: str) -> dict[str, dict]:
    out = {}
    for line in git(repo, "ls-tree", "-r", FROZEN_SRC_TREE).splitlines():
        meta, path = line.split("\t", 1)
        _mode, kind, blob = meta.split()
        if kind != "blob" or not path.startswith("genesis/") or not path.endswith(".py"):
            continue
        data = git(repo, "cat-file", "blob", blob, binary=True)
        header = f"blob {len(data)}\0".encode()
        assert hashlib.sha1(header + data).hexdigest() == blob
        out["src/" + path] = {"blob_sha1": blob, "sha256": hashlib.sha256(data).hexdigest(),
                              "size": len(data), "has_crlf": b"\r\n" in data}
    return out


def hash_working(path: Path) -> dict:
    data = path.read_bytes()
    return {"blob_sha1": hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest(),
            "sha256": hashlib.sha256(data).hexdigest(), "has_crlf": b"\r\n" in data}


SUBPROCESS = r'''
import sys, json, importlib
repo = sys.argv[1]; manifest = sys.argv[2]
sys.path.insert(0, repo + "/src"); sys.path.insert(0, repo + "/adapters/src")
import genesis, genesis.pit, genesis.quota, genesis.evidence, genesis.feature_manifest
from pathlib import Path
try:
    from genesis_adapters import provenance_guard
except Exception as exc:
    print(json.dumps({"outcome": "IMPORT_FAILED", "class": type(exc).__name__})); sys.exit(3)
result = None
try:
    verdict = provenance_guard.verify_loaded_genesis_modules(Path(repo), manifest_path=Path(manifest))
    result = {"outcome": "PASSED", "verdict_keys": sorted(verdict)[:20] if isinstance(verdict, dict) else str(type(verdict))}
except BaseException as exc:
    result = {"outcome": "REFUSED", "class": type(exc).__name__}
print(json.dumps(result))
sys.exit(0 if result["outcome"] == "PASSED" else 1)
'''


def run_guard(copy: Path) -> dict:
    manifest = copy / "adapters" / "config" / "frozen_genesis_modules.json"
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
               PYTHONPYCACHEPREFIX=tempfile.mkdtemp(prefix="pyc-"))
    proc = subprocess.run([sys.executable, "-B", "-c", SUBPROCESS, str(copy), str(manifest)],
                          capture_output=True, text=True, env=env)
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        return {"outcome": "HARNESS_ERROR", "stdout": proc.stdout[-500:], "stderr": proc.stderr[-800:]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    repo = Path(args.repo).resolve()
    res: dict[str, dict] = {}

    exp = expected_manifest(str(repo))
    manifest_path = repo / "adapters" / "config" / "frozen_genesis_modules.json"
    if manifest_path.exists():
        raw = manifest_path.read_bytes()
        cand = json.loads(raw)
        # tolerate either {"modules": {path: {...}}} or {path: {...}} or a list
        entries = cand.get("modules", cand) if isinstance(cand, dict) else {e.get("path"): e for e in cand}
        if isinstance(entries, list):
            entries = {e.get("path"): e for e in entries}
        missing = sorted(set(exp) - set(entries))
        extra = sorted(set(entries) - set(exp))
        mism = []
        for p, e in exp.items():
            c = entries.get(p) or {}
            cb = c.get("blob_sha1") or c.get("blob") or c.get("git_blob_sha1")
            cs = c.get("sha256") or c.get("blob_sha256")
            if cb != e["blob_sha1"] or cs != e["sha256"]:
                mism.append({"path": p, "expected": e, "candidate": c})
        res["P-1_manifest_parity"] = {"pass": not (missing or extra or mism), "expected_entries": len(exp),
                                      "missing": missing, "extra": extra, "mismatch": mism[:20],
                                      "manifest_sha256": hashlib.sha256(raw).hexdigest()}
    else:
        res["P-1_manifest_parity"] = {"pass": False, "detail": "manifest absent (candidate not present?)",
                                      "expected_entries": len(exp)}

    wt = {}
    ok = True
    for p, e in exp.items():
        f = repo / p
        if not f.exists():
            wt[p] = "MISSING"; ok = False; continue
        h = hash_working(f)
        if h["blob_sha1"] != e["blob_sha1"]:
            wt[p] = h; ok = False
    res["P-2_working_tree_bytes"] = {"pass": ok, "deviating": wt}

    guard_present = (repo / "adapters" / "src" / "genesis_adapters" / "provenance_guard.py").exists()
    if guard_present:
        target = "src/genesis/time.py"
        with tempfile.TemporaryDirectory(prefix="crlf-") as td:
            copy = Path(td) / "repo"
            shutil.copytree(repo, copy, ignore=shutil.ignore_patterns(".git", "__pycache__", "runtime"))
            clean = run_guard(copy)
            data = (copy / target).read_bytes()
            (copy / target).write_bytes(data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
            crlf = run_guard(copy)
            (copy / target).write_bytes(data.replace(b'"""', b'""" ', 1))
            edit = run_guard(copy)
        res["P-3_clean_copy_control"] = {"pass": clean.get("outcome") == "PASSED", "detail": clean}
        res["P-3_crlf_refused"] = {"pass": crlf.get("outcome") == "REFUSED", "detail": crlf,
                                   "note": "PASSED here means CRLF was normalized away -> DEFECT (fail-open)"}
        res["P-4_edit_refused_control"] = {"pass": edit.get("outcome") == "REFUSED", "detail": edit}
        src = (repo / "adapters/src/genesis_adapters/provenance_guard.py").read_text(encoding="utf-8", errors="replace")
        text_opens = [m.group(0) for m in re.finditer(r"open\([^)]*\)", src)
                      if "'rb'" not in m.group(0) and '"rb"' not in m.group(0) and "read_bytes" not in m.group(0)]
        norm = [k for k in ("\\r\\n", "newline=", "universal", "replace(b'\\r'", 'replace(b"\\r"', "splitlines") if k in src]
        res["P-5_static_binary_read"] = {"pass": not text_opens and not norm,
                                         "text_mode_opens": text_opens, "normalization_tokens": norm}
    else:
        res["P-3_crlf_refused"] = {"pass": False, "detail": "candidate provenance_guard.py absent - not run"}

    all_pass = all(v["pass"] for v in res.values())
    print(json.dumps({"all_pass": all_pass, "results": res}, indent=2))
    if args.json:
        Path(args.json).write_text(json.dumps({"all_pass": all_pass, "results": res}, indent=2))
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
