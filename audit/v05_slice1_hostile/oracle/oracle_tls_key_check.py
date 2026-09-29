#!/usr/bin/env python3
"""Oracle 12 - committed test TLS private key (audit area 12).

  python oracle_tls_key_check.py --repo <checkout> --commit <sha>

K-1  enumerate tracked blobs containing a PEM private-key block (any type) at <commit>
K-2  for each: path under adapters/adapter_tests/fixtures/?  size?  key type?  encrypted?
K-3  consumption: grep adapters/src (runtime package) for references to the fixtures
     path, 'server.key', 'server.crt', 'cafile', 'load_verify_locations', 'SSLContext',
     'check_hostname', 'CERT_NONE', 'create_default_context' - the CA-injection hook must
     be unreachable from runtime paths (cli.py, transport_http.py in live mode)
K-4  shipping: pyproject has no build backend / package-data config -> no wheel; but
     `git archive` and any tarball of the repo ship it. .gitattributes export-ignore?
K-5  scanner classification: gitleaks rule `private-key`, trufflehog `PrivateKey`,
     detect-secrets `PrivateKeyDetector`, GitHub secret scanning (generic private key
     when push protection is on) all key on '-----BEGIN ... PRIVATE KEY-----'
K-6  does the matching cert bind a real host name? (SAN/CN) - a cert for 'localhost'/
     127.0.0.1 only is harmless; one naming the pinned provider host is not.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

PEM = re.compile(rb"-----BEGIN ([A-Z ]*PRIVATE KEY)-----")


def git(repo, *args, binary=False):
    p = subprocess.run(["git", "-C", repo, *args], capture_output=True)
    if p.returncode:
        raise RuntimeError(p.stderr.decode(errors="replace"))
    return p.stdout if binary else p.stdout.decode(errors="replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--commit", default="HEAD")
    a = ap.parse_args()
    out = {}
    keys = []
    for line in git(a.repo, "ls-tree", "-r", "-l", a.commit).splitlines():
        meta, path = line.split("\t", 1)
        _m, kind, blob, size = meta.split()
        if kind != "blob" or int(size) > 200_000:
            continue
        if any(path.endswith(x) for x in (".key", ".pem", ".crt", ".p12", ".pfx", ".der")) or "tls" in path.lower():
            data = git(a.repo, "cat-file", "blob", blob, binary=True)
            m = PEM.search(data)
            if m:
                keys.append({"path": path, "size": int(size), "type": m.group(1).decode(),
                             "encrypted": b"ENCRYPTED" in data or b"Proc-Type: 4,ENCRYPTED" in data,
                             "under_test_fixtures": path.startswith("adapters/adapter_tests/fixtures/")})
    out["K-1_2_private_keys"] = keys
    runtime = []
    try:
        files = git(a.repo, "ls-tree", "-r", "--name-only", a.commit, "--", "adapters/src").splitlines()
    except RuntimeError:
        files = []
    pat = re.compile(r"fixtures/tls|server\.key|server\.crt|cafile|load_verify_locations|CERT_NONE|check_hostname|SSLContext\(|create_default_context|GENESIS_[A-Z_]*(CA|TLS|CERT)[A-Z_]*")
    for f in files:
        src = git(a.repo, "show", f"{a.commit}:{f}")
        for i, line in enumerate(src.splitlines(), 1):
            if pat.search(line):
                runtime.append(f"{f}:{i}: {line.strip()[:140]}")
    out["K-3_runtime_tls_references"] = runtime
    try:
        ga = git(a.repo, "show", f"{a.commit}:.gitattributes") + git(a.repo, "show", f"{a.commit}:adapters/.gitattributes")
    except RuntimeError:
        ga = ""
    out["K-4_export_ignore_present"] = "export-ignore" in ga
    try:
        py = git(a.repo, "show", f"{a.commit}:pyproject.toml")
        out["K-4_build_system"] = "[build-system]" in py
    except RuntimeError:
        out["K-4_build_system"] = None
    out["K-5_scanner_classification"] = ("Any PEM private-key block is flagged by gitleaks (private-key), trufflehog "
                                         "(PrivateKey), detect-secrets (PrivateKeyDetector); GitHub push protection flags "
                                         "generic private keys when enabled.") if keys else "no key blocks found"
    certs = []
    for line in git(a.repo, "ls-tree", "-r", "--name-only", a.commit).splitlines():
        if line.endswith((".crt", ".pem")):
            data = git(a.repo, "cat-file", "blob", git(a.repo, "rev-parse", f"{a.commit}:{line}").strip(), binary=True)
            if b"BEGIN CERTIFICATE" in data:
                try:
                    txt = subprocess.run(["openssl", "x509", "-noout", "-subject", "-ext", "subjectAltName", "-enddate"],
                                         input=data, capture_output=True).stdout.decode(errors="replace")
                except FileNotFoundError:
                    txt = "openssl unavailable"
                certs.append({"path": line, "x509": txt.strip()})
    out["K-6_certificates"] = certs
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
