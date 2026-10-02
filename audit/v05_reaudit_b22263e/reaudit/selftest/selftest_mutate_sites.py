#!/usr/bin/env python3
"""Self-test of mutate_sites.py on a toy repository shaped like the remediation's risk areas.

base: one function. head (the "remediation") adds a deadline check, a reset-authority check, a polling loop
on a clock that can stick exactly at the deadline, and a genuinely equivalent site. Expectations:
  * deadline ``t0 < deadline`` -> ``<=`` is KILLED (a test asserts equality is refused);
  * every reset-authority mutant is KILLED (tests cover each branch);
  * the poll loop ``t >= deadline`` -> ``>`` hangs on a clock stuck at the deadline -> TIMEOUT, not KILLED;
  * ``n >= 0`` -> ``n > 0`` inside ``max(0, n) if ... else 0`` is equivalent -> SURVIVED;
  * lines not changed by head are never mutated; the checkout is restored byte-for-byte.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent / "mutate_sites.py"

BASE = '''def untouched(a, b):
    return a < b
'''

HEAD = BASE + '''

def permitted(t0, deadline):
    return t0 < deadline


def reset_allowed(halt_reason, g1_after_halt, fp_halted, fp_new):
    if halt_reason in ("SECRET_ECHO", "AUTH_REJECTED"):
        if not g1_after_halt or fp_new == fp_halted:
            raise PermissionError("re-G1 with a new credential required")
    return True


def wait_until(clock, deadline):
    while True:
        t = clock()
        if t >= deadline:
            return t


def floor_zero(n):
    return max(0, n) if n >= 0 else 0
'''

TESTS = '''import unittest

from mod import floor_zero, permitted, reset_allowed, untouched, wait_until


class T(unittest.TestCase):
    def test_deadline(self):
        self.assertTrue(permitted(9, 10))
        self.assertFalse(permitted(10, 10))

    def test_reset(self):
        self.assertTrue(reset_allowed("OTHER", False, "a", "a"))
        for args in (("SECRET_ECHO", False, "a", "b"), ("SECRET_ECHO", True, "a", "a"),
                     ("AUTH_REJECTED", False, "a", "b")):
            with self.assertRaises(PermissionError):
                reset_allowed(*args)
        self.assertTrue(reset_allowed("SECRET_ECHO", True, "a", "b"))

    def test_wait(self):
        values = iter([0, 5, 10, 10])

        def clock():
            return next(values, 10)

        self.assertEqual(wait_until(clock, 10), 10)

    def test_floor(self):
        self.assertEqual([floor_zero(n) for n in (-2, 0, 3)], [0, 0, 3])

    def test_untouched(self):
        self.assertTrue(untouched(1, 2))
'''


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def main() -> int:
    repo = Path(tempfile.mkdtemp(prefix="mutself-"))
    git(repo, "init", "-q")
    (repo / "mod.py").write_text(BASE)
    (repo / "test_mod.py").write_text("import unittest\n")
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=s", "-c", "user.email=s@invalid", "commit", "-q", "-m", "base")
    base = git(repo, "rev-parse", "HEAD").strip()
    (repo / "mod.py").write_text(HEAD)
    (repo / "test_mod.py").write_text(TESTS)
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=s", "-c", "user.email=s@invalid", "commit", "-q", "-m", "head")
    head = git(repo, "rev-parse", "HEAD").strip()
    before = (repo / "mod.py").read_bytes()
    out = repo / "mutants.json"
    proc = subprocess.run([sys.executable, str(TOOL), "--repo", str(repo), "--base", base, "--head", head,
                           "--paths", "mod.py", "--test-cmd", f"{sys.executable} -B -m unittest -q test_mod",
                           "--timeout", "10", "--out", str(out)], capture_output=True, text=True)
    print(proc.stdout[-3000:].rstrip())
    if proc.stderr.strip():
        print(proc.stderr[-2000:].rstrip())
    doc = json.loads(out.read_text())
    by = {(m["line"], m["operator"]): m["status"] for m in doc["mutants"]}
    checks = []

    def expect(label, ok, **detail):
        checks.append(ok)
        print(f"[{'OK ' if ok else 'BAD'}] {label}" + (f" {detail}" if detail else ""))

    deadline_line = HEAD.splitlines().index("    return t0 < deadline") + 1
    poll_line = HEAD.splitlines().index("        if t >= deadline:") + 1
    floor_line = HEAD.splitlines().index("    return max(0, n) if n >= 0 else 0") + 1
    reset_lines = range(HEAD.splitlines().index("def reset_allowed(halt_reason, g1_after_halt, fp_halted, fp_new):") + 1,
                        HEAD.splitlines().index("    return True") + 2)
    expect("deadline < -> <= KILLED", by.get((deadline_line, "CMP < -> <=")) == "KILLED")
    expect("poll >= -> > on a stuck clock is TIMEOUT (never counted as killed)",
           by.get((poll_line, "CMP >= -> >")) == "TIMEOUT")
    expect("equivalent n >= 0 -> n > 0 SURVIVED", by.get((floor_line, "CMP >= -> >")) == "SURVIVED")
    reset = {k: v for k, v in by.items() if k[0] in reset_lines}
    expect("every reset-authority mutant KILLED", reset and all(v == "KILLED" for v in reset.values()),
           reset=reset)
    expect("the unchanged base line is never mutated", not any(k[0] == 2 for k in by))
    expect("checkout restored byte-for-byte", (repo / "mod.py").read_bytes() == before and doc["checkout_clean_after"])
    expect("no INVALID mutant", "INVALID" not in doc["counts"], counts=doc["counts"])
    print(json.dumps(doc["counts"]))
    return 0 if all(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
