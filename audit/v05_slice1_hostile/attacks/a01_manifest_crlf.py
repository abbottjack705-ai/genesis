"""Area 1 supplement: FRZ-09 manifest parity (oracle P-1 criterion, candidate key layout) and A-1 CRLF.

Oracle P-1 read ``modules`` / top-level keys and so could not see the candidate's ``entries`` object (keys
relative to ``src/``). This check applies the SAME criterion - every ``.py`` of frozen tree 51cb635 present,
nothing extra, blob SHA-1 and SHA-256 equal - to the actual layout, plus: ``src_tree`` names the frozen tree,
the file's SHA-256 equals the pin in ``verify.py``, and the file is canonical. It then runs the candidate's
own startup guard inside a CRLF (core.autocrlf=true) checkout and requires a fail-closed refusal.

    python -B attacks/a01_manifest_crlf.py --repo <LF checkout> [--crlf-repo <autocrlf=true checkout>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

FROZEN_SRC = "51cb635bc42b993815b6c02a23c4c3ceb7d98476"


def git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--crlf-repo", default="")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    repo = Path(args.repo).resolve()
    expected = {}
    for line in git(repo, "ls-tree", "-r", FROZEN_SRC).decode().splitlines():
        meta, path = line.split("\t", 1)
        _mode, kind, blob = meta.split()
        if kind == "blob" and path.endswith(".py"):
            data = git(repo, "cat-file", "blob", blob)
            assert hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest() == blob
            expected[path] = {"blob_sha1": blob, "sha256": hashlib.sha256(data).hexdigest()}
    raw = (repo / "adapters" / "config" / "frozen_genesis_modules.json").read_bytes()
    manifest = json.loads(raw)
    entries = manifest.get("entries", {})
    c.check("A1", "P-1 (candidate layout): manifest entries == every .py of frozen src tree, blob SHA-1 and SHA-256 "
                  "equal", entries == expected, expected=len(expected), got=len(entries),
            missing=sorted(set(expected) - set(entries))[:5], extra=sorted(set(entries) - set(expected))[:5])
    c.check("A1", "manifest names the frozen src tree and schema", manifest.get("src_tree") == FROZEN_SRC
            and manifest.get("schema") == "genesis.adapters.frozen-modules.v1", src_tree=manifest.get("src_tree"))
    pin_line = [line for line in (repo / "adapters/src/genesis_adapters/oddspapi/verify.py").read_text(
        encoding="utf-8").splitlines() if "FROZEN_MANIFEST_SHA256" in line and "=" in line]
    digest = hashlib.sha256(raw).hexdigest()
    c.check("A1", "manifest SHA-256 equals the pin in verify.py", any(digest in line for line in pin_line),
            manifest_sha256=digest)
    canonical = (json.dumps(manifest, ensure_ascii=False, allow_nan=False, sort_keys=True,
                            separators=(",", ":")) + "\n").encode()
    c.check("A1", "manifest bytes are canonical JSON with one trailing LF (no CRLF)", canonical == raw)

    if args.crlf_repo:
        crlf = Path(args.crlf_repo).resolve()
        sample = (crlf / "src" / "genesis" / "time.py").read_bytes()
        code = ("import sys; from pathlib import Path; r=Path(sys.argv[1]);"
                "sys.path[:0]=[str(r/'adapters'/'src'), str(r/'src')];"
                "import genesis.time, genesis.pit\n"
                "from genesis_adapters import provenance_guard as g; from genesis_adapters.oddspapi import verify as v\n"
                "try:\n g.verify_loaded_genesis_modules(r, manifest_path=r/'adapters'/'config'/'frozen_genesis_modules.json',"
                " expected_manifest_sha256=v.FROZEN_MANIFEST_SHA256); print('PASSED')\n"
                "except g.ModuleProvenanceError as e:\n print('REFUSED', e.code)")
        env = dict(os.environ, PYTHONPYCACHEPREFIX=tempfile.mkdtemp(prefix="pyc-crlf-"))
        proc = subprocess.run([sys.executable, "-B", "-c", code, str(crlf)], capture_output=True, text=True, env=env)
        verdict = (proc.stdout.strip().splitlines() or [proc.stderr.strip()[-200:]])[-1]
        c.check("A1", "A-1: in a core.autocrlf=true checkout the startup guard refuses (never normalizes CRLF)",
                b"\r\n" in sample and verdict.startswith("REFUSED"), checkout_has_crlf=b"\r\n" in sample,
                verdict=verdict)
        suite = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "adapters/adapter_tests",
                                "-t", "adapters"], cwd=crlf, capture_output=True, text=True, env=env, timeout=900)
        tail = (suite.stderr.strip().splitlines() or [""])[-1]
        c.check("A1", "A-1: the adapter suite in the CRLF checkout fails closed at the package guard",
                suite.returncode != 0 and ("ModuleProvenanceError" in suite.stderr or "MODULE_HASH" in suite.stderr),
                exit=suite.returncode, tail=tail)
    return c.finish(args.out)


if __name__ == "__main__":
    sys.exit(main())
