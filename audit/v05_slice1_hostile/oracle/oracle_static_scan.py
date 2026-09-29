#!/usr/bin/env python3
"""Oracle 13 - independent static scan of adapters/src (areas 1, 6, 7, 10, 15).

NOT the implementer's FRZ-05..11 scanners. Written from c8dfafd text alone.

  python oracle_static_scan.py --repo <checkout> [--json out.json]

X-01  handlers: bare except / except BaseException / KeyboardInterrupt / SystemExit /
      contextlib.suppress(...) anywhere except ONE `except BaseException` in
      oddspapi/transport_http.py::send  (7.7, FRZ-11)
X-02  return/break/continue inside `finally` (7.7)
X-03  network imports (socket, ssl, http.client, http, urllib.request, requests, httpx,
      aiohttp) outside oddspapi/transport_http.py (FRZ-06)
X-04  `reveal_for_transport` call sites outside transport_http.py (7.4)
X-05  private-member access on genesis.* names: attribute `_x` on an imported genesis
      object; `genesis.<mod>.<Name> = ...` assignments; subclassing frozen classes (2.1.3)
X-06  reserve authority tokens: QuotaReserveAuthorization / grant_authorization /
      revoke_authorization / BudgetClass.RESERVE (FRZ-07)
X-07  OperationalStatus.READY outside cli.py (FRZ-08)
X-08  numeric timeout/sleep literals: timeout=<num>, settimeout(<num>), setdefaulttimeout,
      sleep(<num>) (FRZ-10) - reported for review, not all are violations
X-09  destructive filesystem calls in runtime: os.remove/unlink/rmdir, shutil.rmtree/move,
      os.rename/replace, Path.unlink/rename/replace/write_bytes on evidence/quota/cache
      paths (immutability, 12.2 rule 10, F-42)
X-10  str(exc) / exc.args / traceback.format_exc / repr(exc) reaching persisted records in
      transport_http.py or acquisition.py (7.7 step 2)
X-11  text-mode file reads used for hashing in provenance_guard.py / verify.py (CRLF)
X-12  `logging.getLogger`/`print(` in transport_http.py (7.7 hygiene)
X-13  environment variables read: names containing KEY/TOKEN/SECRET/CRED must be path
      indirection only (7.5: no env var holds the key)
X-14  `float(` on odds/line paths in parser.py / normalize.py (23: never float)
X-15  `follow_redirects|allow_redirects|HTTPRedirectHandler|Location` in transport_http.py
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

NET = {"socket", "ssl", "http", "http.client", "urllib.request", "requests", "httpx", "aiohttp"}
RESERVE = {"QuotaReserveAuthorization", "grant_authorization", "revoke_authorization"}


class Scan(ast.NodeVisitor):
    def __init__(self, rel: str):
        self.rel = rel
        self.f: dict[str, list] = {k: [] for k in ("X-01", "X-02", "X-03", "X-04", "X-05", "X-06", "X-07",
                                                   "X-08", "X-09", "X-10", "X-14", "X-15")}
        self.genesis_names: set[str] = set()
        self.in_finally = 0

    def note(self, key, node, text=""):
        self.f[key].append(f"{self.rel}:{getattr(node, 'lineno', '?')} {text}")

    def visit_Import(self, n):
        for a in n.names:
            if a.name in NET or a.name.split(".")[0] in {"socket", "ssl", "requests", "httpx", "aiohttp"}:
                if not self.rel.endswith("transport_http.py"):
                    self.note("X-03", n, a.name)
        self.generic_visit(n)

    def visit_ImportFrom(self, n):
        mod = n.module or ""
        if (mod in NET or mod.split(".")[0] in {"socket", "ssl", "http", "requests", "httpx", "aiohttp"}) and not self.rel.endswith("transport_http.py"):
            self.note("X-03", n, mod)
        if mod == "genesis" or mod.startswith("genesis."):
            for a in n.names:
                self.genesis_names.add(a.asname or a.name)
                if a.name.startswith("_"):
                    self.note("X-05", n, f"private import {a.name}")
                if a.name in RESERVE:
                    self.note("X-06", n, a.name)
        self.generic_visit(n)

    def visit_ExceptHandler(self, n):
        t = n.type
        names = []
        if t is None:
            names = ["<bare>"]
        elif isinstance(t, ast.Name):
            names = [t.id]
        elif isinstance(t, ast.Tuple):
            names = [e.id for e in t.elts if isinstance(e, ast.Name)]
        elif isinstance(t, ast.Attribute):
            names = [t.attr]
        bad = [x for x in names if x in {"<bare>", "BaseException", "KeyboardInterrupt", "SystemExit", "GeneratorExit"}]
        if bad:
            self.note("X-01", n, f"except {names}")
        self.generic_visit(n)

    def visit_Try(self, n):
        for stmt in n.body + n.orelse + [h for h in n.handlers]:
            pass
        self.generic_visit_body(n.body); self.generic_visit_body(n.orelse)
        for h in n.handlers:
            self.visit(h)
        self.in_finally += 1
        self.generic_visit_body(n.finalbody)
        self.in_finally -= 1

    visit_TryStar = visit_Try

    def generic_visit_body(self, body):
        for s in body:
            self.visit(s)

    def _flow(self, n):
        if self.in_finally:
            self.note("X-02", n, type(n).__name__)
        self.generic_visit(n)

    visit_Return = _flow
    visit_Break = _flow
    visit_Continue = _flow

    def visit_FunctionDef(self, n):
        saved, self.in_finally = self.in_finally, 0
        self.generic_visit(n)
        self.in_finally = saved

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, n):
        for b in n.bases:
            name = b.id if isinstance(b, ast.Name) else (b.attr if isinstance(b, ast.Attribute) else "")
            if name in self.genesis_names:
                self.note("X-05", n, f"class {n.name} subclasses frozen {name}")
        self.generic_visit(n)

    def visit_Attribute(self, n):
        base = n.value
        if n.attr == "reveal_for_transport" and not self.rel.endswith("transport_http.py"):
            self.note("X-04", n)
        if n.attr == "READY" and isinstance(base, ast.Name) and base.id == "OperationalStatus" and not self.rel.endswith("cli.py"):
            self.note("X-07", n)
        if n.attr == "RESERVE" and isinstance(base, ast.Name) and base.id == "BudgetClass":
            self.note("X-06", n, "BudgetClass.RESERVE")
        if n.attr.startswith("_") and not n.attr.startswith("__") and isinstance(base, ast.Name) and base.id in self.genesis_names:
            self.note("X-05", n, f"{base.id}.{n.attr}")
        if n.attr in RESERVE:
            self.note("X-06", n, n.attr)
        if n.attr in {"remove", "unlink", "rmdir", "rmtree", "rename", "replace", "move"} and isinstance(base, ast.Name) and base.id in {"os", "shutil"}:
            self.note("X-09", n, f"{base.id}.{n.attr}")
        if n.attr in {"unlink", "rename", "replace", "write_bytes", "write_text"} and not isinstance(base, ast.Name):
            self.note("X-09", n, f"Path.{n.attr}?")
        if n.attr in {"args", "__traceback__", "__cause__", "__context__", "__notes__"} and self.rel.endswith(("transport_http.py", "acquisition.py")):
            self.note("X-10", n, n.attr)
        self.generic_visit(n)

    def visit_Assign(self, n):
        for t in n.targets:
            if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and (t.value.id == "genesis" or t.value.id in self.genesis_names):
                self.note("X-05", n, f"assignment to {ast.unparse(t)}")
        self.generic_visit(n)

    def visit_Call(self, n):
        fn = n.func
        fname = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
        for kw in n.keywords:
            if kw.arg == "timeout" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, (int, float)):
                self.note("X-08", n, f"timeout={kw.value.value}")
        if fname in {"settimeout", "setdefaulttimeout", "sleep"} and n.args and isinstance(n.args[0], ast.Constant):
            self.note("X-08", n, f"{fname}({n.args[0].value})")
        if fname in {"suppress"} and any(isinstance(a, ast.Name) and a.id in {"BaseException", "KeyboardInterrupt", "SystemExit"} for a in n.args):
            self.note("X-01", n, "contextlib.suppress(process-control)")
        if fname in {"str", "repr", "format_exc", "format_exception", "print_exc"} and self.rel.endswith(("transport_http.py", "acquisition.py")):
            self.note("X-10", n, f"{fname}(...)")
        if fname == "float" and self.rel.endswith(("parser.py", "normalize.py")):
            self.note("X-14", n, "float(")
        if fname in RESERVE:
            self.note("X-06", n, fname)
        self.generic_visit(n)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    root = Path(a.repo) / "adapters" / "src" / "genesis_adapters"
    if not root.exists():
        print("CANNOT RUN: adapters/src/genesis_adapters absent (candidate not present)")
        return 2
    agg: dict[str, list] = {}
    extra: dict[str, list] = {"X-11": [], "X-12": [], "X-13": [], "X-15": []}
    for f in sorted(root.rglob("*.py")):
        rel = str(f.relative_to(a.repo)).replace("\\", "/")
        src = f.read_text(encoding="utf-8", errors="replace")
        s = Scan(rel)
        s.visit(ast.parse(src))
        for k, v in s.f.items():
            agg.setdefault(k, []).extend(v)
        if rel.endswith(("provenance_guard.py", "verify.py")):
            for i, line in enumerate(src.splitlines(), 1):
                if re.search(r"open\([^)]*\)", line) and "b" not in re.search(r"open\(([^)]*)\)", line).group(1).split(",")[-1] and "read_bytes" not in line:
                    extra["X-11"].append(f"{rel}:{i} {line.strip()[:120]}")
                if re.search(r"read_text\(|\.splitlines\(\)|newline=|\\r\\n", line):
                    extra["X-11"].append(f"{rel}:{i} {line.strip()[:120]}")
        if rel.endswith("transport_http.py"):
            for i, line in enumerate(src.splitlines(), 1):
                if re.search(r"getLogger|print\(|logging\.", line):
                    extra["X-12"].append(f"{rel}:{i} {line.strip()[:120]}")
                if re.search(r"follow_redirects|allow_redirects|HTTPRedirectHandler|Location", line):
                    extra["X-15"].append(f"{rel}:{i} {line.strip()[:120]}")
        for i, line in enumerate(src.splitlines(), 1):
            m = re.search(r"environ(?:\.get)?\s*[\[\(]\s*['\"]([A-Z0-9_]+)", line)
            if m:
                extra["X-13"].append(f"{rel}:{i} {m.group(1)}")
    # X-01 allowance: exactly one except BaseException in transport_http.py
    be = [x for x in agg.get("X-01", []) if "transport_http.py" in x and "BaseException" in x]
    others = [x for x in agg.get("X-01", []) if x not in be]
    verdicts = {
        "X-01": {"pass": len(be) == 1 and not others, "transport_BaseException_count": len(be), "other": others},
        "X-02": {"pass": not agg.get("X-02"), "detail": agg.get("X-02", [])},
        "X-03": {"pass": not agg.get("X-03"), "detail": agg.get("X-03", [])},
        "X-04": {"pass": not agg.get("X-04"), "detail": agg.get("X-04", [])},
        "X-05": {"pass": not agg.get("X-05"), "detail": agg.get("X-05", [])},
        "X-06": {"pass": not agg.get("X-06"), "detail": agg.get("X-06", [])},
        "X-07": {"pass": not agg.get("X-07"), "detail": agg.get("X-07", [])},
        "X-08": {"pass": not agg.get("X-08"), "detail": agg.get("X-08", [])},
        "X-09": {"review": agg.get("X-09", [])},
        "X-10": {"review": agg.get("X-10", [])},
        "X-11": {"pass": not extra["X-11"], "detail": extra["X-11"]},
        "X-12": {"pass": not extra["X-12"], "detail": extra["X-12"]},
        "X-13": {"review": extra["X-13"]},
        "X-14": {"pass": not agg.get("X-14"), "detail": agg.get("X-14", [])},
        "X-15": {"review": extra["X-15"]},
    }
    print(json.dumps(verdicts, indent=2))
    if a.json:
        Path(a.json).write_text(json.dumps(verdicts, indent=2))
    return 0 if all(v.get("pass", True) for v in verdicts.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
