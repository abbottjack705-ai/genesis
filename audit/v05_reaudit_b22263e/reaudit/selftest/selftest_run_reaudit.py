#!/usr/bin/env python3
"""Self-test of run_reaudit.py: proves each check family can FAIL, using synthetic candidates.

Builds, in a throw-away clone of a repository that holds the authority commit c8dfafd, one GOOD synthetic
"candidate" (a minimal adapters/ tree that satisfies every candidate-independent check) and eight BAD
variants, each breaking exactly one property. The driver must PASS the GOOD candidate and FAIL each BAD one
on the targeted check. Nothing here is the real candidate; this only measures the driver's power.

    python selftest_run_reaudit.py --source <repo containing c8dfafd> --out <dir>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DRIVER = HERE.parent / "run_reaudit.py"
AUTHORITY = "c8dfafdff3be611fa6255a03ed361bc46d7ad8fe"
SRC_TREE = "51cb635bc42b993815b6c02a23c4c3ceb7d98476"


def sh(cwd: Path, *cmd: str, check: bool = True) -> str:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"{cmd}: {proc.stderr}")
    return proc.stdout


def architecture_ids(repo: Path) -> list[str]:
    sys.path.insert(0, str(DRIVER.parent))
    import run_reaudit

    return run_reaudit.architecture_test_ids(repo)


def manifest(repo: Path) -> bytes:
    entries = {}
    for line in sh(repo, "git", "ls-tree", "-r", "--full-tree", SRC_TREE).splitlines():
        meta, path = line.split("\t", 1)
        sha = meta.split()[2]
        if path.endswith(".py"):
            data = subprocess.run(["git", "cat-file", "blob", sha], cwd=repo, capture_output=True, check=True).stdout
            entries[path] = {"blob_sha1": sha, "sha256": hashlib.sha256(data).hexdigest()}
    return (json.dumps({"src_tree": SRC_TREE, "entries": entries}, indent=1, sort_keys=True) + "\n").encode()


GUARD = '''import hashlib
import json
from pathlib import Path


class ModuleProvenanceError(RuntimeError):
    pass


def verify(repo: Path) -> None:
    doc = json.loads((repo / "adapters" / "config" / "frozen_genesis_modules.json").read_bytes())
    for rel, entry in doc["entries"].items():
        data = (repo / "src" / rel).read_bytes(){normalize}
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ModuleProvenanceError("MODULE_HASH_MISMATCH " + rel)
'''

TRANSPORT = '''import socket


def send(request, *, clock, deadline_at):
    code = None
    try:
        return socket.getaddrinfo
    except Exception as exc:
        return {"class": type(exc).__name__}
    except BaseException as exc:
        code = exc.code if isinstance(exc, SystemExit) and type(exc.code) is int else 1
        del exc
    raise SystemExit(code) from None
'''

CLI = '''import argparse


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser()
    sub = top.add_subparsers(dest="cmd")
    run = sub.add_parser("run")
    run.add_argument("--root")
    approve = sub.add_parser("approve-ready")
    approve.add_argument("--root"){extra}
    return top
'''

RUNNER = '''def acquire(item):
    for attempt in range(1):
        try:
            return item
        finally:
            pass
'''

ADAPTER_INIT = '''import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for entry in (ROOT / "adapters" / "src", ROOT / "src"):
    sys.path.insert(0, str(entry))
from genesis_adapters import provenance_guard  # noqa: E402

provenance_guard.verify(ROOT)
'''

TESTS = '''"""Synthetic self-test suite naming every architecture test ID:
{ids}
"""
import socket
import unittest


class SelfTest(unittest.TestCase):
    def test_passes(self):
        self.assertTrue(True)

    @unittest.skip("no symlink privilege (synthetic)")
    def test_real_symlink(self):
        pass

    def test_loopback_only(self):
        try:
            socket.create_connection(("127.0.0.1", 9), timeout=1).close()
        except OSError:
            pass{external}
'''

EXTERNAL = '''
        try:
            socket.create_connection(("192.0.2.1", 443), timeout=1).close()
        except OSError:
            pass'''


def write(root: Path, rel: str, data) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode() if isinstance(data, str) else data)


def tls_pair(work: Path, cn: str) -> tuple[bytes, bytes]:
    key, crt = work / f"{cn}.key", work / f"{cn}.crt"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(crt),
                    "-subj", f"/CN={cn}", "-addext", f"subjectAltName=DNS:{cn}", "-days", "1"],
                   check=True, capture_output=True)
    return key.read_bytes(), crt.read_bytes()


def build_good(repo: Path, work: Path, ids: list[str]) -> None:
    sh(repo, "git", "checkout", "-q", "--detach", AUTHORITY)
    man = manifest(repo)
    key, crt = tls_pair(work, "localhost")
    write(repo, "adapters/.gitattributes", "adapter_tests/fixtures/** -text\nadapter_tests/fixtures/tls/** export-ignore\n")
    write(repo, "adapters/config/frozen_genesis_modules.json", man)
    write(repo, "adapters/config/oddspapi_v4_endpoints.json", json.dumps({"endpoints": [{"role": "ODDS",
                                                                                        "host": "api.oddspapi.io"}]}))
    write(repo, "adapters/src/genesis_adapters/__init__.py", "")
    write(repo, "adapters/src/genesis_adapters/provenance_guard.py", GUARD.format(normalize=""))
    write(repo, "adapters/src/genesis_adapters/oddspapi/__init__.py", "")
    write(repo, "adapters/src/genesis_adapters/oddspapi/verify.py",
          f'FROZEN_MANIFEST_SHA256 = "{hashlib.sha256(man).hexdigest()}"\n')
    write(repo, "adapters/src/genesis_adapters/oddspapi/transport_http.py", TRANSPORT)
    write(repo, "adapters/src/genesis_adapters/oddspapi/acquisition.py", RUNNER)
    write(repo, "adapters/src/genesis_adapters/cli.py", CLI.format(extra=""))
    write(repo, "adapters/adapter_tests/__init__.py", ADAPTER_INIT)
    write(repo, "adapters/adapter_tests/test_selftest.py", TESTS.format(ids=" ".join(ids), external=""))
    write(repo, "adapters/adapter_tests/fixtures/tls/server.key", key)
    write(repo, "adapters/adapter_tests/fixtures/tls/server.crt", crt)
    sh(repo, "git", "add", "-A", "adapters")
    sh(repo, "git", "-c", "user.name=selftest", "-c", "user.email=selftest@invalid", "commit", "-q", "-m",
       "synthetic GOOD candidate")


def variant(repo: Path, good: str, name: str, mutate) -> str:
    sh(repo, "git", "checkout", "-q", "--detach", good)
    mutate(repo)
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "-c", "user.name=selftest", "-c", "user.email=selftest@invalid", "commit", "-q", "-m",
       f"synthetic BAD {name}")
    return sh(repo, "git", "rev-parse", "HEAD").strip()


def run_driver(repo: Path, candidate: str, out: Path, suites: str, expect_adapter: str = "3:1",
               expect_frozen: str = "493:19") -> dict:
    subprocess.run([sys.executable, str(DRIVER), "--repo", str(repo), "--candidate", candidate,
                    "--predecessor", AUTHORITY, "--out", str(out), "--suites", suites,
                    "--expect-adapter", expect_adapter, "--expect-frozen", expect_frozen],
                   capture_output=True, text=True)
    return json.loads((out / "reaudit_results.json").read_text())


def status_of(results: dict, needle: str) -> list[str]:
    return [r["status"] for r in results["results"] if needle in r["title"]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--good-suites", default="both")
    args = ap.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="selftest-"))
    repo = work / "repo"
    subprocess.run(["git", "clone", "-q", "--no-hardlinks", "--no-checkout", args.source, str(repo)], check=True)
    ids = architecture_ids(repo)
    build_good(repo, work, ids)
    good = sh(repo, "git", "rev-parse", "HEAD").strip()
    rows = []

    def expect(label: str, results: dict, needle: str, wanted: str) -> None:
        got = status_of(results, needle)
        ok = bool(got) and all(s == wanted for s in got)
        rows.append({"variant": label, "check": needle, "expected": wanted, "got": got, "pass": ok})
        print(f"[{'OK ' if ok else 'BAD'}] {label:5} {needle[:70]:70} expected {wanted} got {got}")

    res = run_driver(repo, good, out / "GOOD", args.good_suites)
    non_pass = [(r["id"], r["title"], r["status"]) for r in res["results"]
                if r["status"] not in ("PASS", "INFO", "REVIEW")]
    rows.append({"variant": "GOOD", "check": "no FAIL/CANNOT_RUN", "expected": "none", "got": non_pass,
                 "pass": not non_pass})
    print(f"[{'OK ' if not non_pass else 'BAD'}] GOOD  no FAIL or CANNOT_RUN anywhere: {non_pass}")
    expect("GOOD", res, "every §18 test ID", "PASS")
    expect("GOOD", res, "A-1: adapter_tests REFUSES", "PASS")
    expect("GOOD", res, "export-ignore set for committed private key", "PASS")
    if args.good_suites in ("both", "adapter"):
        expect("GOOD", res, "no-network", "PASS")
        expect("GOOD", res, "every adapter-suite skip", "REVIEW")

    cases = []

    def b1(r):
        write(r, "src/genesis/x_selftest.py", "X = 1\n")
    cases.append(("B1", b1, [("six frozen tree SHAs at the candidate", "FAIL"),
                             ("every path changed authority..candidate is under adapters/", "FAIL")], "none"))

    def b2(r):
        path = r / "adapters/config/frozen_genesis_modules.json"
        doc = json.loads(path.read_text())
        first = sorted(doc["entries"])[0]
        doc["entries"][first]["sha256"] = "0" * 64
        data = (json.dumps(doc, indent=1, sort_keys=True) + "\n").encode()
        path.write_bytes(data)
        write(r, "adapters/src/genesis_adapters/oddspapi/verify.py",
              f'FROZEN_MANIFEST_SHA256 = "{hashlib.sha256(data).hexdigest()}"\n')
    cases.append(("B2", b2, [("FRZ-09 manifest equals git ls-tree", "FAIL")], "none"))

    def b3(r):
        write(r, "adapters/src/genesis_adapters/provenance_guard.py",
              GUARD.format(normalize='.replace(b"\\r\\n", b"\\n")'))
    cases.append(("B3", b3, [("A-1: adapter_tests REFUSES", "FAIL")], "none"))

    def b4(r):
        write(r, "adapters/src/genesis_adapters/cli.py",
              CLI.format(extra='\n    approve.add_argument("--at")\n    run.add_argument("--ca-file")'))
    cases.append(("B4", b4, [("no CA/connect/insecure option", "FAIL"),
                             ("no operator-supplied time option", "FAIL")], "none"))

    def b5(r):
        write(r, "adapters/src/genesis_adapters/oddspapi/acquisition.py",
              "import socket\nimport time\n\n\ndef acquire(item):\n    try:\n        time.sleep(1)\n"
              "        return socket.create_connection(('h', 1), timeout=60)\n    except KeyboardInterrupt:\n"
              "        return None\n    finally:\n        return item\n")
    cases.append(("B5", b5, [("FRZ-06: network modules imported only", "FAIL"),
                             ("FRZ-11: exactly one BaseException handler", "FAIL"),
                             ("no bare except, no suppress", "FAIL"),
                             ("FRZ-10: no literal timeout", "FAIL"),
                             ("production sleep() calls", "REVIEW")], "none"))

    def b6(r):
        key, crt = tls_pair(work, "api.oddspapi.io")
        write(r, "adapters/adapter_tests/fixtures/tls/server.key", key)
        write(r, "adapters/adapter_tests/fixtures/tls/server.crt", crt)
        write(r, "adapters/.gitattributes", "adapter_tests/fixtures/** -text\n")
    cases.append(("B6", b6, [("export-ignore set for committed private key", "FAIL"),
                             ("git archive <candidate> ships no private key", "FAIL"),
                             ("no committed certificate names a pinned provider host", "FAIL")], "none"))

    def b7(r):
        trimmed = [i for i in ids if i != "BND-04"]
        write(r, "adapters/adapter_tests/test_selftest.py", TESTS.format(ids=" ".join(trimmed), external=""))
    cases.append(("B7", b7, [("every §18 test ID", "FAIL")], "none"))

    def b8(r):
        write(r, "adapters/adapter_tests/test_selftest.py", TESTS.format(ids=" ".join(ids), external=EXTERNAL))
    cases.append(("B8", b8, [("no-network", "FAIL")], "adapter"))

    for label, mutate, checks, suites in cases:
        commit = variant(repo, good, label, mutate)
        res = run_driver(repo, commit, out / label, suites)
        for needle, wanted in checks:
            expect(label, res, needle, wanted)
    (out / "selftest_results.json").write_text(json.dumps(rows, indent=1) + "\n")
    shutil.rmtree(work, ignore_errors=True)
    bad = [r for r in rows if not r["pass"]]
    print(f"== {len(rows)} expectations, {len(bad)} not met")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
