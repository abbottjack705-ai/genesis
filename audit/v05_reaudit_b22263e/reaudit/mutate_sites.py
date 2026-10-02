#!/usr/bin/env python3
"""Diff-site mutation run: mutate every predicate/guard on the lines a remediation changed.

Independent of the implementer's mutation campaign. It computes the lines changed between ``--base`` and
``--head`` under ``--paths``, generates first-order mutants on those lines only, applies each in place in a
CLEAN checkout of ``--head`` (restored byte-for-byte after every run), runs ``--test-cmd`` and classifies:

  KILLED     the command exited non-zero and at least one named test FAILED/ERRORED
  KILLED_IMPORT  non-zero exit with no named failing test (import/collection error: a weak kill)
  SURVIVED   exit 0 - the suite does not notice the change (a gap, or an equivalent mutant to be PROVEN)
  TIMEOUT    no result within --timeout. Reported separately and NEVER counted as killed: for a deadline or
             clock comparison a hang can hide a send-at-deadline behaviour that a test should assert.
  INVALID    the mutant does not compile (should not happen; reported)

Operators: comparison swaps (< <= > >= == != in/not in is/is not), and<->or, removal of ``not``, negation
of an ``if``/``while`` test, True<->False in ``return``, deletion of a ``raise`` (refusal removal) and of a
single-line call statement whose name looks like a guard (check/verify/require/guard/scan/refuse/assert/
validate/halt/reconcile).

    python mutate_sites.py --repo <clean checkout at head> --base <sha> --head <sha> \
        --paths adapters/src --test-cmd "python -B -m unittest discover -s adapters/adapter_tests -t adapters" \
        --timeout 1800 --out mutants.json [--focus <regex on file:line:text>] [--list-only]
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CMP_SWAP = {ast.Lt: ["<="], ast.LtE: ["<"], ast.Gt: [">="], ast.GtE: [">"], ast.Eq: ["!="], ast.NotEq: ["=="],
            ast.In: ["not in"], ast.NotIn: ["in"], ast.Is: ["is not"], ast.IsNot: ["is"]}
CMP_TEXT = {ast.Lt: r"<(?!=)", ast.LtE: r"<=", ast.Gt: r">(?!=)", ast.GtE: r">=", ast.Eq: r"==", ast.NotEq: r"!=",
            ast.In: r"\bin\b", ast.NotIn: r"\bnot\s+in\b", ast.Is: r"\bis\b(?!\s+not)", ast.IsNot: r"\bis\s+not\b"}
GUARD_CALL = re.compile(r"(check|verify|require|guard|scan|refuse|assert|validate|halt|reconcile)", re.I)


def changed_lines(repo: Path, base: str, head: str, paths: list[str]) -> dict[str, set[int]]:
    diff = subprocess.run(["git", "-C", str(repo), "diff", "-U0", "--no-color", base, head, "--", *paths],
                          capture_output=True, text=True, check=True).stdout
    out: dict[str, set[int]] = {}
    current = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@") and current and current.endswith(".py"):
            match = re.search(r"\+(\d+)(?:,(\d+))?", line)
            start, count = int(match.group(1)), int(match.group(2) or "1")
            out.setdefault(current, set()).update(range(start, start + count))
    return out


def offset(lines: list[str], lineno: int, col: int) -> int:
    return sum(len(x) for x in lines[:lineno - 1]) + len(lines[lineno - 1].encode()[:col].decode(errors="ignore"))


def mutants_for(path: str, text: str, lines_changed: set[int]) -> list[dict]:
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    found: list[dict] = []

    def span(node) -> tuple[int, int]:
        return offset(lines, node.lineno, node.col_offset), offset(lines, node.end_lineno, node.end_col_offset)

    def add(node, start: int, end: int, replacement: str, op: str) -> None:
        if node.lineno not in lines_changed:
            return
        found.append({"file": path, "line": node.lineno, "start": start, "end": end, "original": text[start:end],
                      "replacement": replacement, "operator": op, "context": lines[node.lineno - 1].strip()[:160]})

    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            left = node.left
            for op, right in zip(node.ops, node.comparators):
                _, gap_start = span(left)
                gap_end, _ = span(right)
                segment = text[gap_start:gap_end]
                match = re.search(CMP_TEXT[type(op)], segment)
                if match:
                    for repl in CMP_SWAP[type(op)]:
                        add(node, gap_start + match.start(), gap_start + match.end(), repl,
                            f"CMP {match.group(0)} -> {repl}")
                left = right
        elif isinstance(node, ast.BoolOp):
            word, other = ("and", "or") if isinstance(node.op, ast.And) else ("or", "and")
            for a, b in zip(node.values, node.values[1:]):
                _, gap_start = span(a)
                gap_end, _ = span(b)
                match = re.search(rf"\b{word}\b", text[gap_start:gap_end])
                if match:
                    add(node, gap_start + match.start(), gap_start + match.end(), other, f"BOOL {word} -> {other}")
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            start, _ = span(node)
            keyword = re.match(r"not\b\s*", text[start:])
            if keyword:
                add(node, start, start + keyword.end(), "", "NOT removed")
        elif isinstance(node, (ast.If, ast.While)):
            start, end = span(node.test)
            add(node.test, start, end, f"not ({text[start:end]})", f"{type(node).__name__.upper()} test negated")
        elif isinstance(node, ast.Return) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, bool):
            start, end = span(node.value)
            add(node, start, end, str(not node.value.value), f"RETURN {node.value.value} -> {not node.value.value}")
        elif isinstance(node, ast.Raise) and node.lineno == node.end_lineno:
            start, end = span(node)
            add(node, start, end, "pass", "RAISE deleted")
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and node.lineno == node.end_lineno:
            func = node.value.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if GUARD_CALL.search(name or ""):
                start, end = span(node)
                add(node, start, end, "pass", f"GUARD CALL {name}() deleted")
    found.sort(key=lambda m: (m["file"], m["line"], m["start"], m["operator"]))
    return found


def failing_tests(output: str) -> list[str]:
    return sorted(set(re.findall(r"^(?:FAIL|ERROR): (\S+ \([^)]+\))", output, re.M)))


def run(repo: Path, mutant: dict, cmd: str, timeout: int) -> dict:
    target = repo / mutant["file"]
    original = target.read_bytes()
    text = original.decode()
    mutated = text[:mutant["start"]] + mutant["replacement"] + text[mutant["end"]:]
    try:
        compile(mutated, mutant["file"], "exec")
    except SyntaxError as exc:
        return {"status": "INVALID", "error": str(exc)}
    env = dict(os.environ, PYTHONPYCACHEPREFIX=tempfile.mkdtemp(prefix="mut-pyc-"))
    started = time.monotonic()
    try:
        target.write_bytes(mutated.encode())
        proc = subprocess.run(shlex.split(cmd), cwd=repo, capture_output=True, text=True, env=env, timeout=timeout)
        output = proc.stdout + proc.stderr
        fails = failing_tests(output)
        status = "SURVIVED" if proc.returncode == 0 else ("KILLED" if fails else "KILLED_IMPORT")
        result = {"status": status, "exit": proc.returncode, "failing_tests": fails[:30],
                  "tail": output.strip().splitlines()[-3:]}
    except subprocess.TimeoutExpired:
        result = {"status": "TIMEOUT"}
    finally:
        target.write_bytes(original)
    result["seconds"] = round(time.monotonic() - started, 1)
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--paths", nargs="+", default=["adapters/src"])
    ap.add_argument("--test-cmd", default=f"{sys.executable} -B -m unittest discover -s adapters/adapter_tests -t adapters")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--focus", default="")
    ap.add_argument("--max", type=int, default=0)
    ap.add_argument("--list-only", action="store_true")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    repo = Path(args.repo).resolve()
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    want = subprocess.run(["git", "-C", str(repo), "rev-parse", args.head], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=no"],
                           capture_output=True, text=True).stdout.strip()
    if head != want or dirty:
        raise SystemExit(f"refusing: checkout must be a clean {args.head} (HEAD={head}, dirty={bool(dirty)})")
    sites = changed_lines(repo, args.base, args.head, args.paths)
    mutants: list[dict] = []
    for path, lines in sorted(sites.items()):
        mutants += mutants_for(path, (repo / path).read_text(encoding="utf-8"), lines)
    if args.focus:
        focus = re.compile(args.focus)
        mutants = [m for m in mutants if focus.search(f"{m['file']}:{m['line']}:{m['context']}")]
    if args.max:
        mutants = mutants[:args.max]
    print(f"{sum(len(v) for v in sites.values())} changed lines in {len(sites)} files -> {len(mutants)} mutants")
    for index, mutant in enumerate(mutants):
        mutant["id"] = f"D{index:03d}"
        if not args.list_only:
            mutant.update(run(repo, mutant, args.test_cmd, args.timeout))
            print(f"{mutant['id']} {mutant['status']:13} {mutant['file']}:{mutant['line']} {mutant['operator']}")
    clean = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=no"],
                           capture_output=True, text=True).stdout.strip()
    statuses = [m.get("status", "LISTED") for m in mutants]
    summary = {"base": args.base, "head": want, "paths": args.paths, "test_cmd": args.test_cmd,
               "changed_lines": {k: sorted(v) for k, v in sites.items()},
               "counts": {s: statuses.count(s) for s in sorted(set(statuses))},
               "checkout_clean_after": not clean, "mutants": mutants}
    Path(args.out).write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print("== " + json.dumps(summary["counts"]) + f" checkout_clean_after={not clean}")
    return 0 if not clean else 3


if __name__ == "__main__":
    sys.exit(main())
