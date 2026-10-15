#!/usr/bin/env python3
"""Test double for the Codex CLI. It honours the argv contract the engine uses for `codex exec`.

Scripted behaviour comes from FAKE_CODEX_SCENARIO (a JSON list; each real review consumes one entry).
Every invocation is appended to FAKE_CODEX_LOG so tests can assert the sandbox, the working directory
and the hermetic flags. The fake never touches the network or a subscription.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def _arg(name, argv):
    return argv[argv.index(name) + 1] if name in argv else None


def main() -> int:
    argv = sys.argv[1:]
    if argv[:2] == ["login", "status"]:
        print("Logged in using ChatGPT")
        return 0
    if argv[:1] == ["--version"]:
        print("codex-cli fake")
        return 0
    if argv[:1] != ["exec"]:
        print(f"fake codex: unsupported invocation {argv}", file=sys.stderr)
        return 2
    stdin = sys.stdin.read()
    cwd = _arg("-C", argv)
    last = Path(_arg("--output-last-message", argv))
    log = os.environ.get("FAKE_CODEX_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "cwd": cwd, "sandbox": _arg("--sandbox", argv), "stdin_bytes": len(stdin.encode("utf-8")),
                "stdin_has_diff": "BEGIN DIFF" in stdin,
                "hermetic": all(flag in argv for flag in ("--ignore-user-config", "--ignore-rules", "--ephemeral")),
                "argv": argv}) + "\n")
    if "Reply with exactly this single line" in stdin:
        last.write_text("GENESIS_CODEX_PREFLIGHT_OK", encoding="utf-8")
        return 0
    scenario = Path(os.environ["FAKE_CODEX_SCENARIO"])
    entries = json.loads(scenario.read_text(encoding="utf-8"))
    cursor = Path(str(scenario) + ".cursor")
    n = int(cursor.read_text(encoding="utf-8")) if cursor.exists() else 0
    cursor.write_text(str(n + 1), encoding="utf-8")
    entry = entries[min(n, len(entries) - 1)]
    if "raw" in entry:
        text = entry["raw"]
    else:
        sha = entry.get("reviewed_sha", "HEAD")
        if sha == "HEAD":
            sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True,
                                 text=True).stdout.strip()
        text = json.dumps({"review_complete": entry.get("review_complete", True), "verdict": entry["verdict"],
                           "reviewed_sha": sha, "summary": entry.get("summary", "fake review"),
                           "findings": entry.get("findings", [])})
    last.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
