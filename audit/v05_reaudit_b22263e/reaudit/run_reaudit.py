#!/usr/bin/env python3
"""Candidate-independent hostile re-audit driver for the V0.5 slice-1 remediation candidate.

Written by the re-auditor. It imports NOTHING from the candidate: every check uses git plumbing, the
architecture authority read from git, Python's ``ast`` over the candidate's source text, and the
candidate's own test commands run as subprocesses. Stdlib only.

    python run_reaudit.py --repo <clone holding the candidate> --candidate b22263e \
        [--predecessor cfcff3dbb285eaa48a6cfc1eceedb91e27662c81] --out <dir> \
        [--expect-frozen 493:1] [--expect-adapter 690:1] [--suites both|adapter|frozen|none] [--no-netblock]

Every check reports PASS, FAIL, REVIEW (a human must read the cited lines) or CANNOT_RUN. CANNOT_RUN is
never a pass. Exit status: 1 if any FAIL, else 2 if any CANNOT_RUN, else 0.

Authority: c8dfafd V05_ADAPTER_ARCHITECTURE.md r3 (blob 30c4ca7d43fe11504e873e25944f9bdd30079253).
"""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PINNED_TREES = {
    "src": "51cb635bc42b993815b6c02a23c4c3ceb7d98476",
    "tests": "e90b298180068fec03ba7e2fa81957082e7fb3ce",
    "config": "abd22db01ff482a8da84634ee740ba382b68c804",
    "tools": "a0e3411edb4e068fd4708050516cb6870834e7ac",
    "DECISIONS": "cc97ec6f841f1e3fbe6dbb57c9cb6e1ac24fdb64",
    "v04_pack": "3c3c1c27d80ed6f10c32ac6605a5f438b2e7de12",
}
FREEZE = "2278e2a68083f7ac58d796b1ed9c43d50020b6b0"
AUTHORITY = "c8dfafdff3be611fa6255a03ed361bc46d7ad8fe"
AUTHORITY_BLOB = "30c4ca7d43fe11504e873e25944f9bdd30079253"
NO_TOUCH = ("remediation_evidence/", ".gitignore", ".gitattributes", "pyproject.toml", "requirements.lock",
            "V05_ADAPTER_ARCHITECTURE.md")
SENTINEL = "GENESIS-SENTINEL-KEY-0123456789abcdef"
NETWORK_MODULES = {"socket", "ssl", "http", "urllib.request", "requests", "httpx", "aiohttp", "urllib3",
                   "ftplib", "smtplib", "telnetlib", "xmlrpc.client", "websocket", "websockets"}
PROCESS_CONTROL = {"BaseException", "KeyboardInterrupt", "SystemExit", "GeneratorExit"}
FORBIDDEN_ANYWHERE_FLAGS = {"--ca-file", "--cafile", "--ca", "--connect", "--connect-address", "--insecure",
                            "--no-verify", "--trust-ca", "--cert"}
TIME_FLAGS = {"--at", "--granted-at", "--recorded-at", "--now", "--time", "--as-of"}
APPROVAL_PARSER = re.compile(r"approv|ready|grant|reset|g[0-3]", re.I)

RESULTS: list[dict] = []


# --------------------------------------------------------------------------------------------- utils
def record(cid: str, title: str, status: str, **detail) -> None:
    assert status in {"PASS", "FAIL", "REVIEW", "CANNOT_RUN", "INFO"}
    RESULTS.append({"id": cid, "title": title, "status": status, **detail})
    print(f"[{status:10}] {cid} {title}")


def git(repo: Path, *args: str, binary: bool = False, check: bool = True):
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout if binary else proc.stdout.decode("utf-8", errors="replace")


def blob(repo: Path, rev: str, path: str) -> bytes | None:
    proc = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{path}"], capture_output=True)
    return proc.stdout if proc.returncode == 0 else None


def tree_files(repo: Path, rev: str, prefix: str) -> list[str]:
    out = git(repo, "ls-tree", "-r", "--name-only", rev, "--", prefix, check=False)
    return [p for p in out.splitlines() if p]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def entropy(token: str) -> float:
    counts = {ch: token.count(ch) for ch in set(token)}
    return -sum(n / len(token) * math.log2(n / len(token)) for n in counts.values())


# ------------------------------------------------------------------------------- R0 pin and lineage
def r0_pin(repo: Path, candidate: str, predecessor: str | None) -> str | None:
    try:
        full = git(repo, "rev-parse", "--verify", f"{candidate}^{{commit}}").strip()
    except RuntimeError as exc:
        record("R00", f"candidate {candidate} resolves to a commit in {repo}", "CANNOT_RUN", error=str(exc))
        return None
    record("R00", "candidate resolves to a commit", "PASS", candidate=full,
           subject=git(repo, "log", "-1", "--format=%s", full).strip())
    for name, rev in (("authority c8dfafd", AUTHORITY), ("freeze 2278e2a", FREEZE),
                      *((("predecessor", predecessor),) if predecessor else ())):
        ok = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", rev, full]).returncode == 0
        record("R00", f"{name} is an ancestor of the candidate", "PASS" if ok else "FAIL", rev=rev)
    authority_blob = git(repo, "rev-parse", f"{AUTHORITY}:V05_ADAPTER_ARCHITECTURE.md", check=False).strip()
    record("R00", "authority blob at c8dfafd is 30c4ca7", "PASS" if authority_blob == AUTHORITY_BLOB else "FAIL",
           blob=authority_blob)
    head_blob = git(repo, "rev-parse", f"{full}:V05_ADAPTER_ARCHITECTURE.md", check=False).strip()
    record("R00", "authority text unchanged at the candidate", "PASS" if head_blob == AUTHORITY_BLOB else "FAIL",
           blob=head_blob)
    fsck = subprocess.run(["git", "-C", str(repo), "fsck", "--no-dangling", "--connectivity-only"],
                          capture_output=True, text=True)
    record("R00", "git fsck --connectivity-only", "PASS" if fsck.returncode == 0 else "FAIL",
           stderr=fsck.stderr.strip()[-400:])
    chain = git(repo, "log", "--first-parent", "--reverse", "--format=%H %an <%ae> %s", f"{AUTHORITY}..{full}")
    record("R00", "first-parent chain authority..candidate (informational)", "INFO",
           commits=chain.strip().splitlines())
    if predecessor:
        sub = git(repo, "log", "--reverse", "--format=%H %s", f"{predecessor}..{full}").strip().splitlines()
        record("R00", "remediation commits predecessor..candidate (informational)", "INFO", commits=sub)
    return full


# ------------------------------------------------------------------------------- R1 frozen identity
def r1_frozen(repo: Path, full: str, predecessor: str | None) -> None:
    bad = {}
    for name, pinned in PINNED_TREES.items():
        got = git(repo, "rev-parse", "--verify", f"{full}:{name}", check=False).strip() or "(missing)"
        if got != pinned:
            bad[name] = got
    record("R01", "six frozen tree SHAs at the candidate", "FAIL" if bad else "PASS", mismatches=bad)
    commits = git(repo, "rev-list", f"{AUTHORITY}..{full}").split()
    every = []
    for commit in commits:
        for name, pinned in PINNED_TREES.items():
            got = git(repo, "rev-parse", "--verify", f"{commit}:{name}", check=False).strip()
            if got != pinned:
                every.append((commit[:12], name, got))
    record("R01", f"six tree SHAs at EVERY commit authority..candidate ({len(commits)} commits, §2.1.2)",
           "FAIL" if every else "PASS", mismatches=every[:20])
    diff = git(repo, "diff", "--name-status", FREEZE, full, "--", *PINNED_TREES).strip()
    record("R01", "git diff --name-status freeze..candidate -- <six trees> is empty",
           "FAIL" if diff else "PASS", diff=diff.splitlines()[:20])
    changed = git(repo, "diff", "--name-only", AUTHORITY, full).split("\n")
    changed = [p for p in changed if p]
    outside = [p for p in changed if not p.startswith("adapters/")]
    record("R01", f"every path changed authority..candidate is under adapters/ ({len(changed)} paths)",
           "FAIL" if outside else "PASS", outside=outside[:40])
    touched = [p for p in changed if any(p == n or p.startswith(n) for n in NO_TOUCH)]
    record("R01", "no-touch list untouched (§23)", "FAIL" if touched else "PASS", touched=touched)
    if predecessor:
        rem = [p for p in git(repo, "diff", "--name-only", predecessor, full).split("\n") if p]
        out2 = [p for p in rem if not p.startswith("adapters/")]
        record("R01", f"implementer claim: remediation changed only adapters/ ({len(rem)} paths)",
               "FAIL" if out2 else "PASS", outside=out2[:40])
    eol = git(repo, "ls-files", "--eol", "--with-tree", full, "--", *PINNED_TREES, check=False)
    crlf = [line for line in eol.splitlines() if "i/crlf" in line or "i/mixed" in line]
    record("R01", "no frozen blob is stored with CRLF/mixed endings", "FAIL" if crlf else "PASS", lines=crlf[:10])
    attrs = blob(repo, full, "adapters/.gitattributes")
    ok = attrs is not None and any("fixtures/**" in line and "-text" in line
                                   for line in attrs.decode(errors="replace").splitlines())
    record("R01", "adapters/.gitattributes protects fixtures with -text", "PASS" if ok else "FAIL",
           content=(attrs or b"").decode(errors="replace").splitlines())
    check = subprocess.run(["git", "-C", str(repo), "diff", "--check", AUTHORITY, full], capture_output=True, text=True)
    record("R01", "git diff --check authority..candidate", "PASS" if check.returncode == 0 else "FAIL",
           output=check.stdout.strip().splitlines()[:20])


# ---------------------------------------------------------------------------------- R2 FRZ-09 parity
def expected_frozen_entries(repo: Path) -> dict[str, tuple[str, str]]:
    out = git(repo, "ls-tree", "-r", "--full-tree", PINNED_TREES["src"])
    entries = {}
    for line in out.splitlines():
        meta, path = line.split("\t", 1)
        _mode, _typ, sha = meta.split()
        if path.endswith(".py"):
            data = git(repo, "cat-file", "blob", sha, binary=True)
            entries["src/" + path] = (sha, sha256(data))
    return entries


def walk_json(value, sink: list) -> None:
    if isinstance(value, dict):
        strings = [v for v in value.values() if isinstance(v, str)]
        if any(re.fullmatch(r"[0-9a-f]{40}", s) for s in strings) and any(re.fullmatch(r"[0-9a-f]{64}", s)
                                                                          for s in strings):
            sink.append(value)
        for key, sub in value.items():
            if isinstance(sub, dict) and isinstance(key, str) and key.endswith(".py"):
                sub = dict(sub, __key__=key)
            walk_json(sub, sink)
    elif isinstance(value, list):
        for sub in value:
            walk_json(sub, sink)


def r2_frz09(repo: Path, full: str) -> None:
    expected = expected_frozen_entries(repo)
    record("R02", f"expected frozen module set from git tree 51cb635 ({len(expected)} modules)", "INFO",
           digest=sha256(json.dumps(expected, sort_keys=True).encode()))
    raw = blob(repo, full, "adapters/config/frozen_genesis_modules.json")
    if raw is None:
        record("R02", "candidate manifest adapters/config/frozen_genesis_modules.json present", "FAIL")
        return
    try:
        doc = json.loads(raw)
    except ValueError as exc:
        record("R02", "candidate manifest parses as JSON", "FAIL", error=str(exc))
        return
    record("R02", "candidate manifest bytes are LF-only", "PASS" if b"\r" not in raw else "FAIL",
           sha256=sha256(raw))
    rows: list[dict] = []
    walk_json(doc, rows)
    found: dict[str, tuple[str, str]] = {}
    for row in rows:
        sha1 = next(v for v in row.values() if isinstance(v, str) and re.fullmatch(r"[0-9a-f]{40}", v))
        s256 = next(v for v in row.values() if isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v))
        path = next((v for k, v in row.items() if isinstance(v, str) and v.endswith(".py")), row.get("__key__"))
        if path:
            path = path.replace("\\", "/")
            path = path if path.startswith("src/") else "src/" + path.lstrip("/")
            found[path] = (sha1, s256)
    missing = sorted(set(expected) - set(found))
    extra = sorted(set(found) - set(expected))
    wrong = sorted(p for p in set(expected) & set(found) if expected[p] != found[p])
    status = "PASS" if not (missing or extra or wrong) and found else ("CANNOT_RUN" if not found else "FAIL")
    record("R02", "FRZ-09 manifest equals git ls-tree 51cb635 (blob SHA-1 + SHA-256, no extra, no missing)", status,
           entries=len(found), missing=missing[:10], extra=extra[:10], wrong=wrong[:10])
    pinned = sha256(raw)
    hits = []
    for path in tree_files(repo, full, "adapters/src"):
        if path.endswith(".py"):
            text = blob(repo, full, path) or b""
            if pinned.encode() in text:
                hits.append(path)
    record("R02", "manifest SHA-256 is pinned as a literal in adapters/src (§2.4)", "PASS" if hits else "FAIL",
           manifest_sha256=pinned, pinned_in=hits)


# ------------------------------------------------------------------------------------ R3 CRLF attack
def clone(repo: Path, full: str, dest: Path, autocrlf: str) -> Path:
    subprocess.run(["git", "-c", f"core.autocrlf={autocrlf}", "clone", "-q", "--no-hardlinks", "--no-checkout",
                    str(repo), str(dest)], check=True)
    subprocess.run(["git", "-C", str(dest), "config", "core.autocrlf", autocrlf], check=True)
    subprocess.run(["git", "-C", str(dest), "checkout", "-q", "--detach", full], check=True)
    return dest


def import_suite_package(checkout: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPYCACHEPREFIX=tempfile.mkdtemp(prefix="reaudit-pyc-"))
    env.pop("PYTHONPATH", None)
    code = "import sys; sys.path.insert(0, 'adapters'); import adapter_tests"
    return subprocess.run([sys.executable, "-B", "-c", code], cwd=checkout, capture_output=True, text=True,
                          env=env, timeout=600)


def r3_crlf(repo: Path, full: str, work: Path) -> None:
    lf = clone(repo, full, work / "lf", "false")
    crlf = clone(repo, full, work / "crlf", "true")
    expected = expected_frozen_entries(repo)
    differ = sum(sha256((crlf / p).read_bytes()) != expected[p][1] for p in expected)
    same_lf = sum(sha256((lf / p).read_bytes()) == expected[p][1] for p in expected)
    record("R03", "precondition: LF clone holds frozen bytes; autocrlf=true clone changes them",
           "PASS" if same_lf == len(expected) and differ == len(expected) else "CANNOT_RUN",
           lf_equal=same_lf, crlf_different=differ, modules=len(expected))
    control = import_suite_package(lf)
    record("R03", "control: adapter_tests imports cleanly (guard passes) in the LF clone",
           "PASS" if control.returncode == 0 else "CANNOT_RUN", exit=control.returncode,
           stderr=control.stderr.strip()[-600:])
    attack = import_suite_package(crlf)
    refused = attack.returncode != 0 and re.search(r"Provenance|MODULE_|provenance", attack.stderr or "")
    record("R03", "A-1: adapter_tests REFUSES to start in the autocrlf=true clone (FRZ-09 fail-closed)",
           "PASS" if refused else ("CANNOT_RUN" if control.returncode != 0 else "FAIL"), exit=attack.returncode,
           stderr_tail=(attack.stderr or "").strip()[-600:])


# ----------------------------------------------------------------------------------- R4 static scans
def is_network_module(name: str) -> bool:
    top = name.split(".")[0]
    return name in NETWORK_MODULES or top in {"socket", "ssl", "http", "requests", "httpx", "aiohttp", "urllib3",
                                               "websocket", "websockets"} or name.startswith("urllib.request")


class Scan(ast.NodeVisitor):
    def __init__(self, path: str):
        self.path = path
        self.findings: list[tuple[str, int, str]] = []
        self.genesis_aliases: set[str] = set()
        self.exc_names: list[set[str]] = []
        self.parsers: dict[str, str] = {}

    def add(self, kind: str, node: ast.AST, text: str = "") -> None:
        self.findings.append((kind, getattr(node, "lineno", 0), text))

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if is_network_module(alias.name):
                self.add("NET_IMPORT", node, alias.name)
            if alias.name == "genesis" or alias.name.startswith("genesis."):
                self.genesis_aliases.add(alias.asname or alias.name.split(".")[0])
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = node.module or ""
        if is_network_module(mod):
            self.add("NET_IMPORT", node, mod)
        if mod == "urllib" and any(a.name == "request" for a in node.names):
            self.add("NET_IMPORT", node, "urllib.request")
        if mod == "genesis" or mod.startswith("genesis."):
            for alias in node.names:
                if alias.name.startswith("_"):
                    self.add("PRIVATE_GENESIS", node, f"{mod}.{alias.name}")
                self.genesis_aliases.add(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("_") and not node.attr.startswith("__") and isinstance(node.value, ast.Name) \
                and node.value.id in self.genesis_aliases:
            self.add("PRIVATE_GENESIS", node, f"{node.value.id}.{node.attr}")
        if node.attr == "READY" and isinstance(node.value, ast.Name) and node.value.id == "OperationalStatus":
            self.add("READY_REF", node)
        if node.attr == "RESERVE" and isinstance(node.value, ast.Name) and node.value.id == "BudgetClass":
            self.add("RESERVE", node)
        if node.attr in {"grant_authorization", "revoke_authorization"}:
            self.add("RESERVE", node, node.attr)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id == "QuotaReserveAuthorization":
            self.add("RESERVE", node, node.id)
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:
        for handler in node.handlers:
            names = set()
            if handler.type is None:
                self.add("BARE_EXCEPT", handler)
            else:
                elts = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
                for elt in elts:
                    name = elt.id if isinstance(elt, ast.Name) else getattr(elt, "attr", "")
                    if name in PROCESS_CONTROL:
                        self.add("PROCESS_CONTROL_HANDLER", handler, name)
            if handler.name:
                names.add(handler.name)
            self.exc_names.append(names)
            for stmt in handler.body:
                self.visit(stmt)
            self.exc_names.pop()
        for stmt in node.body + node.orelse:
            self.visit(stmt)
        for stmt in node.finalbody:
            self._finally(stmt, in_loop=False)
            self.visit(stmt)

    visit_TryStar = visit_Try

    def _finally(self, node: ast.AST, in_loop: bool) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            return
        if isinstance(node, ast.Return):
            self.add("FLOW_IN_FINALLY", node, "return")
        if isinstance(node, (ast.Break, ast.Continue)) and not in_loop:
            self.add("FLOW_IN_FINALLY", node, type(node).__name__.lower())
        loop = in_loop or isinstance(node, (ast.For, ast.While, ast.AsyncFor))
        for child in ast.iter_child_nodes(node):
            self._finally(child, loop)

    def visit_Assign(self, node: ast.Assign) -> None:
        call = node.value
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "add_parser" \
                and call.args and isinstance(call.args[0], ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.parsers[target.id] = str(call.args[0].value)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else (func.id if isinstance(func, ast.Name) else "")
        if name == "reveal_for_transport":
            self.add("REVEAL", node)
        if name == "suppress":
            for arg in node.args:
                if isinstance(arg, ast.Name) and arg.id in PROCESS_CONTROL:
                    self.add("PROCESS_CONTROL_SUPPRESS", node, arg.id)
        for kw in node.keywords:
            if kw.arg == "timeout" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, (int, float)) \
                    and not isinstance(kw.value.value, bool):
                self.add("LITERAL_TIMEOUT", node, f"timeout={kw.value.value}")
        if name in {"settimeout", "setdefaulttimeout", "sleep"} and node.args \
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, (int, float)):
            self.add("LITERAL_TIMEOUT", node, f"{name}({node.args[0].value})")
        if name == "sleep":
            self.add("SLEEP_CALL", node)
        if name in {"format_exc", "print_exc", "format_exception", "print_exception", "format_tb", "extract_tb"}:
            self.add("TRACEBACK_TEXT", node, name)
        if name in {"str", "repr", "format"} and node.args and isinstance(node.args[0], ast.Name) \
                and any(node.args[0].id in names for names in self.exc_names):
            self.add("EXCEPTION_TEXT", node, f"{name}({node.args[0].id})")
        if name == "add_argument":
            flags = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            owner = func.value.id if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) else "?"
            parser = self.parsers.get(owner, owner)
            for flag in flags:
                if flag in FORBIDDEN_ANYWHERE_FLAGS:
                    self.add("CLI_TRUST_SEAM", node, f"{parser}:{flag}")
                elif flag in TIME_FLAGS:
                    self.add("CLI_TIME_FLAG", node, f"{parser}:{flag}")
        self.generic_visit(node)

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        for value in node.values:
            if isinstance(value, ast.FormattedValue) and isinstance(value.value, ast.Name) \
                    and any(value.value.id in names for names in self.exc_names):
                self.add("EXCEPTION_TEXT", node, f"f-string {{{value.value.id}}}")
        self.generic_visit(node)


def r4_static(repo: Path, full: str) -> None:
    files = [p for p in tree_files(repo, full, "adapters/src") if p.endswith(".py")]
    if not files:
        record("R04", "adapters/src holds Python sources", "CANNOT_RUN")
        return
    findings: list[tuple[str, str, int, str]] = []
    exc_args: list[tuple[str, int]] = []
    for path in files:
        text = (blob(repo, full, path) or b"").decode("utf-8", errors="replace")
        try:
            tree = ast.parse(text, filename=path)
        except SyntaxError as exc:
            findings.append(("SYNTAX", path, exc.lineno or 0, str(exc)))
            continue
        scan = Scan(path)
        scan.visit(tree)
        findings += [(k, path, line, t) for k, line, t in scan.findings]
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in {"args", "__notes__", "__cause__", "__context__"} \
                    and isinstance(node.value, ast.Name) and node.value.id in {"exc", "err", "error", "e"}:
                exc_args.append((path, node.lineno))
    by = lambda k: [(p, l, t) for kk, p, l, t in findings if kk == k]                         # noqa: E731
    transport = [p for p in files if p.endswith("transport_http.py")]
    net = [f for f in by("NET_IMPORT") if f[0] not in transport]
    record("R04", "FRZ-06: network modules imported only by transport_http.py", "FAIL" if net else "PASS",
           offenders=net, transport_files=transport)
    reveal = [f for f in by("REVEAL") if f[0] not in transport]
    record("R04", "FRZ-06: Secret.reveal_for_transport called only in transport_http.py",
           "FAIL" if reveal else "PASS", offenders=reveal, all_calls=by("REVEAL"))
    record("R04", "FRZ-07: no reserve authority / BudgetClass.RESERVE", "FAIL" if by("RESERVE") else "PASS",
           offenders=by("RESERVE"))
    ready = [f for f in by("READY_REF") if not f[0].endswith("cli.py")]
    record("R04", "FRZ-08: OperationalStatus.READY referenced only by cli.py", "FAIL" if ready else "PASS",
           offenders=ready, cli=[f for f in by("READY_REF") if f[0].endswith("cli.py")])
    pc = by("PROCESS_CONTROL_HANDLER")
    allowed = [f for f in pc if f[0] in transport and f[2] == "BaseException"]
    others = [f for f in pc if f not in allowed[:1]]
    record("R04", "FRZ-11: exactly one BaseException handler (transport_http.send); no other process-control handler",
           "PASS" if len(allowed) == 1 and not others else "FAIL", handlers=pc)
    record("R04", "FRZ-11: no bare except, no suppress(BaseException/KI/SE), no return/break/continue in finally",
           "FAIL" if by("BARE_EXCEPT") or by("PROCESS_CONTROL_SUPPRESS") or by("FLOW_IN_FINALLY") else "PASS",
           bare=by("BARE_EXCEPT"), suppress=by("PROCESS_CONTROL_SUPPRESS"), finally_flow=by("FLOW_IN_FINALLY"))
    record("R04", "FRZ-10: no literal timeout/settimeout/setdefaulttimeout/sleep",
           "FAIL" if by("LITERAL_TIMEOUT") else "PASS", offenders=by("LITERAL_TIMEOUT"))
    record("R04", "production sleep() calls (timing-dependent code; read each)", "REVIEW" if by("SLEEP_CALL") else "PASS",
           calls=by("SLEEP_CALL"))
    record("R04", "FRZ-05: no private genesis.* member used", "FAIL" if by("PRIVATE_GENESIS") else "PASS",
           offenders=by("PRIVATE_GENESIS"))
    text_uses = by("EXCEPTION_TEXT") + by("TRACEBACK_TEXT") + [(p, l, "exc.args/notes/cause") for p, l in exc_args]
    record("R04", "§7.6/§7.7: exception text extraction sites (each must be secret-scanned or never persisted)",
           "REVIEW" if text_uses else "PASS", sites=text_uses)
    seam = by("CLI_TRUST_SEAM")
    record("R04", "HA-006: no CA/connect/insecure option in any production parser (§7.6 system trust store)",
           "FAIL" if seam else "PASS", offenders=seam)
    times = by("CLI_TIME_FLAG")
    approval = [f for f in times if APPROVAL_PARSER.search(f[2].split(":")[0])]
    record("R04", "HA-013: no operator-supplied time option on approve/ready/grant/reset parsers (§16.2/§16.5)",
           "FAIL" if approval else ("REVIEW" if times else "PASS"), approval=approval, other_time_flags=times)


# ----------------------------------------------------------------------------- R5 secrets and export
SECRET_PATTERNS = {
    "PEM_PRIVATE_KEY": re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----"),
    "GITHUB_TOKEN": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})"),
    "AWS_ACCESS_KEY": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    "SLACK_TOKEN": re.compile(rb"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "SK_TOKEN": re.compile(rb"\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}"),
    "GOOGLE_API_KEY": re.compile(rb"\bAIza[0-9A-Za-z_-]{35}\b"),
    "ASSIGNED_SECRET": re.compile(rb"(?i)(?:api[_-]?key|apikey|secret|token|passw(?:or)?d)[\"']?\s*[:=]\s*[\"']"
                                  rb"([A-Za-z0-9_\-+/=]{20,})[\"']"),
}


def r5_secrets(repo: Path, full: str, work: Path) -> None:
    objects = git(repo, "rev-list", "--objects", f"{AUTHORITY}..{full}").splitlines()
    seen: dict[str, str] = {}
    for line in objects:
        parts = line.split(" ", 1)
        if len(parts) == 2 and parts[0] not in seen:
            seen[parts[0]] = parts[1]
    hits, sentinel_paths, scanned = [], set(), 0
    for sha, path in seen.items():
        if git(repo, "cat-file", "-t", sha).strip() != "blob":
            continue
        data = git(repo, "cat-file", "blob", sha, binary=True)
        scanned += 1
        if SENTINEL.encode() in data:
            sentinel_paths.add(path)
        for cls, pattern in SECRET_PATTERNS.items():
            for match in pattern.finditer(data):
                token = match.group(1) if match.groups() else match.group(0)
                text = token.decode("ascii", errors="replace")
                if cls == "ASSIGNED_SECRET" and (SENTINEL in text or re.fullmatch(r"[0-9a-f]{40,64}", text)
                                                 or entropy(text) < 3.5 or "SENTINEL" in text.upper()):
                    continue
                hits.append({"class": cls, "path": path, "blob": sha[:12], "token_sha256": sha256(token)[:16]})
    pem = [h for h in hits if h["class"] == "PEM_PRIVATE_KEY"]
    other = [h for h in hits if h["class"] != "PEM_PRIVATE_KEY"]
    record("R05", f"history secret sweep authority..candidate ({scanned} blobs): no credential-shaped token",
           "REVIEW" if other else "PASS", hits=other[:40])
    bad_sentinel = sorted(p for p in sentinel_paths if not p.startswith(("adapters/adapter_tests/", "adapters/evidence/")))
    record("R05", "sentinel key appears only under adapter_tests/ or evidence/", "FAIL" if bad_sentinel else "PASS",
           outside=bad_sentinel, count=len(sentinel_paths))
    head_pem = sorted({h["path"] for h in pem if blob(repo, full, h["path"]) is not None
                       and SECRET_PATTERNS["PEM_PRIVATE_KEY"].search(blob(repo, full, h["path"]) or b"")})
    history_only = sorted({h["path"] for h in pem} - set(head_pem))
    record("R05", "private keys anywhere in authority..candidate history (HA-006)",
           "REVIEW" if pem else "PASS", at_candidate=head_pem, removed_but_in_history=history_only)
    for path in head_pem:
        attr = git(repo, "check-attr", "--source", full, "export-ignore", "--", path, check=False).strip() \
            if _has_attr_source(repo) else _check_attr_at(repo, full, path)
        record("R05", f"export-ignore set for committed private key {path}",
               "PASS" if attr.endswith(": set") else "FAIL", attr=attr)
    archive = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", full], capture_output=True)
    tar_path = work / "candidate.tar"
    tar_path.write_bytes(archive.stdout)
    import tarfile
    shipped = []
    with tarfile.open(tar_path) as tar:
        for member in tar.getmembers():
            if member.isfile():
                data = tar.extractfile(member).read()
                if SECRET_PATTERNS["PEM_PRIVATE_KEY"].search(data):
                    shipped.append(member.name)
    record("R05", "git archive <candidate> ships no private key", "FAIL" if shipped else "PASS", shipped=shipped)
    hosts = _pinned_hosts(repo, full)
    certs = []
    for path in tree_files(repo, full, "adapters"):
        data = blob(repo, full, path) or b""
        for body in re.findall(rb"-----BEGIN CERTIFICATE-----(.+?)-----END CERTIFICATE-----", data, re.S):
            try:
                der = base64.b64decode(b"".join(body.split()))
            except ValueError:
                continue
            named = [h for h in hosts if h.encode() in der]
            if named:
                certs.append({"path": path, "names_provider_host": named})
    record("R05", "no committed certificate names a pinned provider host (HA-006)", "FAIL" if certs else "PASS",
           certs=certs, pinned_hosts=sorted(hosts))


def _has_attr_source(repo: Path) -> bool:
    out = subprocess.run(["git", "check-attr", "-h"], capture_output=True, text=True)
    return "--source" in (out.stdout + out.stderr)


def _check_attr_at(repo: Path, full: str, path: str) -> str:
    tmp = Path(tempfile.mkdtemp(prefix="reaudit-attr-"))
    try:
        clone(repo, full, tmp / "c", "false")
        return git(tmp / "c", "check-attr", "export-ignore", "--", path, check=False).strip()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _pinned_hosts(repo: Path, full: str) -> set[str]:
    hosts = set()
    raw = blob(repo, full, "adapters/config/oddspapi_v4_endpoints.json")
    if raw:
        for match in re.finditer(rb'"host"\s*:\s*"([^"]+)"', raw):
            hosts.add(match.group(1).decode())
    return hosts or {"api.oddspapi.io"}


# ----------------------------------------------------------------------------------- R6 test-ID claim
def architecture_test_ids(repo: Path) -> list[str]:
    text = git(repo, "show", f"{AUTHORITY}:V05_ADAPTER_ARCHITECTURE.md")
    section = text[text.index("## 18. Test matrix"):text.index("## 19. Staged")]
    ids = []
    for line in section.splitlines():
        match = re.match(r"\|\s*([A-Z]+-[0-9]+[a-z]?)(?:\s*…\s*([0-9]+))?\s*\|", line)
        if not match:
            continue
        first, last = match.groups()
        if last:
            prefix, num = first.rsplit("-", 1)
            ids += [f"{prefix}-{i:0{len(num)}d}" for i in range(int(num), int(last) + 1)]
        else:
            ids.append(first)
    if "including F-11b" in section:
        ids.append("FM-11b")
    return ids


def r6_test_ids(repo: Path, full: str) -> None:
    ids = architecture_test_ids(repo)
    corpus = b""
    for path in tree_files(repo, full, "adapters/adapter_tests"):
        if path.endswith(".py"):
            corpus += (blob(repo, full, path) or b"") + b"\n"
    text = corpus.decode("utf-8", errors="replace")
    absent = []
    for test_id in ids:
        variants = {test_id, test_id.replace("-", "_"), test_id.replace("-", "").lower(),
                    test_id.lower().replace("-", "_")}
        if not any(re.search(r"(?<![A-Za-z0-9])" + re.escape(v) + r"(?![0-9])", text, re.I) for v in variants):
            absent.append(test_id)
    record("R06", f"every §18 test ID ({len(ids)}; 166 tabled + FM-11b) is named in adapter_tests",
           "FAIL" if absent else "PASS", count=len(ids), absent=absent,
           note="name presence only; behaviour is judged by the probes and mutation run")


# ---------------------------------------------------------------------------------------- R7 suites
def run_suite(cmd: list[str], cwd: Path, log: Path, netblock: bool, netlog: Path) -> tuple[int, str]:
    env = dict(os.environ, PYTHONPYCACHEPREFIX=tempfile.mkdtemp(prefix="reaudit-pyc-"))
    env.pop("PYTHONPATH", None)
    if netblock:
        env["REAUDIT_NETLOG"] = str(netlog)
        env["PYTHONPATH"] = str(HERE / "netblock_site")
        flags = ["-B"] if "-B" in cmd else []
        cmd = [cmd[0], *flags, str(HERE / "netblock.py"), *[a for a in cmd[1:] if a != "-B"]]
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)
    log.write_text(f"$ {' '.join(cmd)}\n(cwd={cwd})\n{proc.stdout}\n--- stderr ---\n{proc.stderr}\nexit={proc.returncode}\n",
                   encoding="utf-8")
    return proc.returncode, proc.stderr + proc.stdout


def parse_counts(output: str) -> tuple[int | None, int, bool]:
    ran = re.findall(r"^Ran (\d+) tests?", output, re.M)
    ok = re.search(r"^OK(?: \((.*)\))?$", output, re.M)
    skipped = 0
    if ok and ok.group(1):
        found = re.search(r"skipped=(\d+)", ok.group(1))
        skipped = int(found.group(1)) if found else 0
    return (int(ran[-1]) if ran else None), skipped, bool(ok)


def r7_suites(repo: Path, full: str, work: Path, out: Path, expect_frozen: str, expect_adapter: str,
              netblock: bool, which: str = "both") -> None:
    checkout = work / "lf" if (work / "lf").exists() else clone(repo, full, work / "lf", "false")
    netlog = out / "netblock_attempts.jsonl"
    if netlog.exists():
        netlog.unlink()
    if which in ("both", "frozen"):
        frozen_rc, frozen_out = run_suite([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                                          checkout, out / "frozen_suite.log", netblock, netlog)
        ran, skipped, ok = parse_counts(frozen_out)
        exp_ran, exp_skip = (int(x) for x in expect_frozen.split(":"))
        record("R07", f"frozen suite at the candidate: {ran} run / skipped={skipped} (expected {expect_frozen})",
               "PASS" if ok and frozen_rc == 0 and (ran, skipped) == (exp_ran, exp_skip) else "FAIL",
               exit=frozen_rc, ran=ran, skipped=skipped)
    if which in ("both", "adapter"):
        adapter_rc, adapter_out = run_suite([sys.executable, "-B", "-m", "unittest", "discover", "-s",
                                             "adapters/adapter_tests", "-t", "adapters", "-v"], checkout,
                                            out / "adapter_suite.log", netblock, netlog)
        ran, skipped, ok = parse_counts(adapter_out)
        exp_ran, exp_skip = (int(x) for x in expect_adapter.split(":"))
        record("R07", f"adapter suite (-B, fresh pycache prefix): {ran} run / skipped={skipped} "
                      f"(claim {expect_adapter})",
               "PASS" if ok and adapter_rc == 0 and (ran, skipped) == (exp_ran, exp_skip) else "FAIL",
               exit=adapter_rc, ran=ran, skipped=skipped)
        skips = re.findall(r"^(test\S+ \([^)]+\)).*?\.\.\. skipped (.*)$", adapter_out, re.M)
        record("R07", "every adapter-suite skip, named (a skip is never a PASS for its property)",
               "REVIEW" if skips else "PASS", skips=skips)
    if netblock:
        attempts = [json.loads(line) for line in netlog.read_text(encoding="utf-8").splitlines()] \
            if netlog.exists() else []
        external = [a for a in attempts if not a.get("loopback")]
        record("R07", "no-network: zero non-loopback connect/resolve attempts during both suites (audit hook, "
                      "inherited by Python subprocesses via sitecustomize)", "FAIL" if external else "PASS",
               external=external[:20], loopback_attempts=len(attempts) - len(external))
    porcelain = git(checkout, "status", "--porcelain", "--", *PINNED_TREES).strip()
    record("R07", "FRZ-03: frozen trees clean after both suites", "FAIL" if porcelain else "PASS",
           porcelain=porcelain.splitlines()[:20])
    env = dict(os.environ, PYTHONPYCACHEPREFIX=tempfile.mkdtemp(prefix="reaudit-pyc-"))
    comp = subprocess.run([sys.executable, "-m", "compileall", "-q", "src", "tests", "adapters/src",
                           "adapters/adapter_tests"], cwd=checkout, capture_output=True, text=True, env=env)
    record("R07", "compileall -q src tests adapters/src adapters/adapter_tests", "PASS" if comp.returncode == 0 else "FAIL",
           output=(comp.stdout + comp.stderr).strip()[-600:])


# --------------------------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--predecessor", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--expect-frozen", default="493:1", help="ran:skipped (Windows 493:1, Linux 493:19)")
    ap.add_argument("--expect-adapter", default="690:1")
    ap.add_argument("--suites", choices=("both", "adapter", "frozen", "none"), default="both")
    ap.add_argument("--no-netblock", action="store_true")
    ap.add_argument("--keep-work", action="store_true")
    args = ap.parse_args()
    repo = Path(args.repo).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="reaudit-work-"))
    try:
        full = r0_pin(repo, args.candidate, args.predecessor or None)
        if full:
            r1_frozen(repo, full, args.predecessor or None)
            r2_frz09(repo, full)
            r3_crlf(repo, full, work)
            r4_static(repo, full)
            r5_secrets(repo, full, work)
            r6_test_ids(repo, full)
            if args.suites != "none":
                r7_suites(repo, full, work, out, args.expect_frozen, args.expect_adapter, not args.no_netblock,
                          args.suites)
            else:
                record("R07", "suites", "CANNOT_RUN", reason="--suites none")
    except Exception as exc:  # a harness failure is reported, never hidden
        record("RXX", "driver completed", "CANNOT_RUN", error=f"{type(exc).__name__}: {exc}")
    finally:
        if not args.keep_work:
            shutil.rmtree(work, ignore_errors=True)
    statuses = [r["status"] for r in RESULTS]
    summary = {"candidate": args.candidate, "counts": {s: statuses.count(s) for s in sorted(set(statuses))},
               "results": RESULTS}
    (out / "reaudit_results.json").write_bytes((json.dumps(summary, indent=1, default=str) + "\n").encode())
    print("== " + json.dumps(summary["counts"]))
    if "FAIL" in statuses:
        return 1
    return 2 if "CANNOT_RUN" in statuses else 0


if __name__ == "__main__":
    sys.exit(main())
