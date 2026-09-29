#!/usr/bin/env python3
"""Oracle 1 - frozen foundation identity (audit area 1).

Independent of the implementer's guard. Uses only git plumbing.

  python oracle_frozen_identity.py --repo <path> --commit <sha> [--json out.json]

Checks, all against V05_ADAPTER_ARCHITECTURE.md (c8dfafd) section 2.1/2.2/2.3 and
V04_FOUNDATION_FREEZE.md:
  I-1  six frozen tree object IDs at <commit> equal the pinned values
  I-2  git diff --name-status <freeze> <commit> -- <six trees> is empty
  I-3  every path changed between <authority> and <commit> lies under adapters/
       (the implementer's claim) - top-level additive doc updates are allowed by
       section 2.1.5 but are reported so the auditor sees them
  I-4  the no-touch list of section 23 is untouched: remediation_evidence/**,
       .gitignore, top-level .gitattributes, pyproject.toml, requirements.lock,
       V05_ADAPTER_ARCHITECTURE.md
  I-5  no frozen-tree blob is stored with CRLF or mixed endings at <commit>
       (git ls-files --eol) - the guard must see LF bytes
  I-6  adapters/.gitattributes exists at <commit> and protects fixtures with -text
  I-7  the S0..S7 commit list (if given) is exactly authority..commit, first-parent
Exit 0 = every check PASS, 1 = at least one FAIL, 2 = could not run.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

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
NO_TOUCH = (
    "remediation_evidence/", ".gitignore", ".gitattributes", "pyproject.toml",
    "requirements.lock", "V05_ADAPTER_ARCHITECTURE.md",
)


def git(repo: str, *args: str) -> str:
    proc = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--commit", required=True)
    ap.add_argument("--authority", default=AUTHORITY)
    ap.add_argument("--freeze", default=FREEZE)
    ap.add_argument("--stages", default="", help="comma list of S0..S7 SHAs (oldest first)")
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    results: dict[str, dict] = {}

    try:
        commit = git(args.repo, "rev-parse", "--verify", f"{args.commit}^{{commit}}").strip()
    except RuntimeError as exc:
        print(f"CANNOT RUN: candidate commit not present: {exc}")
        return 2

    # I-1
    trees = {}
    ok = True
    for name, pinned in PINNED_TREES.items():
        try:
            actual = git(args.repo, "rev-parse", "--verify", f"{commit}:{name}").strip()
        except RuntimeError:
            actual = "(missing)"
        trees[name] = {"pinned": pinned, "actual": actual, "equal": actual == pinned}
        ok &= actual == pinned
    results["I-1_tree_ids"] = {"pass": ok, "detail": trees}

    # I-2
    diff = git(args.repo, "diff", "--name-status", args.freeze, commit, "--", *PINNED_TREES).strip()
    results["I-2_frozen_diff_empty"] = {"pass": diff == "", "detail": diff.splitlines()}

    # I-3
    changed = git(args.repo, "diff", "--name-only", args.authority, commit).strip().splitlines()
    outside = [p for p in changed if not p.startswith("adapters/")]
    results["I-3_only_adapters"] = {"pass": not outside, "changed_count": len(changed),
                                    "outside_adapters": outside}

    # I-4
    touched = [p for p in changed if any(p == n or p.startswith(n) for n in NO_TOUCH)]
    results["I-4_no_touch_list"] = {"pass": not touched, "detail": touched}

    # I-5
    eol = git(args.repo, "ls-files", "--eol", "--with-tree", commit, "--", *PINNED_TREES)
    bad = [line for line in eol.splitlines() if "i/crlf" in line or "i/mixed" in line]
    results["I-5_frozen_blobs_lf"] = {"pass": not bad, "detail": bad[:50]}

    # I-6
    try:
        ga = git(args.repo, "show", f"{commit}:adapters/.gitattributes")
        has_rule = any("fixtures/**" in line and "-text" in line for line in ga.splitlines())
        results["I-6_nested_gitattributes"] = {"pass": has_rule, "detail": ga.strip().splitlines()}
    except RuntimeError:
        results["I-6_nested_gitattributes"] = {"pass": False, "detail": "adapters/.gitattributes absent"}

    # I-7
    if args.stages:
        claimed = [s.strip() for s in args.stages.split(",") if s.strip()]
        actual = git(args.repo, "log", "--first-parent", "--reverse", "--format=%H",
                     f"{args.authority}..{commit}").split()
        match = len(actual) == len(claimed) and all(a.startswith(c) for a, c in zip(actual, claimed))
        results["I-7_stage_commits"] = {"pass": match, "claimed": claimed, "actual": actual}

    all_pass = all(v["pass"] for v in results.values())
    print(json.dumps({"commit": commit, "all_pass": all_pass, "results": results}, indent=2))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"commit": commit, "all_pass": all_pass, "results": results}, fh, indent=2)
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
