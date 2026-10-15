"""Independent cross-vendor review through the Codex CLI, with billing and verdict guards.

Codex runs non-interactively, with the user's existing ChatGPT subscription login, inside a read-only
sandbox, on a detached worktree pinned to the candidate SHA. Its structured output must name that exact
SHA and must be a verdict the engine can act on. Anything else is refused (fail closed).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .state import WorkflowError, sha256_bytes

PROBE_EXPECTED = "GENESIS_CODEX_PREFLIGHT_OK"
VERDICTS = ("PASS", "REMEDIATION_REQUIRED")
SEVERITIES = ("BLOCKER", "HIGH", "MEDIUM", "LOW")
FINDING_KEYS = {"severity", "file", "line", "summary", "required_fix"}
VERDICT_KEYS = {"review_complete", "verdict", "reviewed_sha", "summary", "findings"}
# Flags that keep the reviewer hermetic: no user hooks, MCP servers or rules, and no session files.
HERMETIC = ["--ephemeral", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check"]


def resolve_command(command: list[str]) -> list[str]:
    exe = shutil.which(command[0])
    if exe is None:
        raise WorkflowError("CODEX_MISSING", f"{command[0]!r} is not on PATH")
    return [exe, *command[1:]]


def _run(argv: list[str], *, env: dict, timeout: float, input_text: str | None = None):
    try:
        return subprocess.run(argv, env=env, input=input_text, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise WorkflowError("REVIEW_TIMEOUT", f"{argv[0]} did not finish within {timeout:.0f}s") from exc


def preflight(cfg: dict, command: list[str], env: dict) -> dict:
    """Refuse unless Codex is logged in with the subscription and no API-key variable would redirect billing."""
    forbidden = sorted(name for name in cfg["forbidden_env"] if env.get(name))
    if forbidden:
        raise WorkflowError("BILLING_GUARD", f"{', '.join(forbidden)} is set. The reviewer must use the existing "
                                             f"ChatGPT subscription login, so unset it before running")
    login = _run([*command, "login", "status"], env=env, timeout=120)
    text = login.stdout + login.stderr
    if cfg["required_login"] not in text:
        raise WorkflowError("CODEX_NOT_SUBSCRIPTION_AUTHENTICATED",
                            f"expected {cfg['required_login']!r} from `codex login status`")
    version = _run([*command, "--version"], env=env, timeout=120)
    return {"login": cfg["required_login"], "version": version.stdout.strip()}


def probe(cfg: dict, command: list[str], env: dict, scratch: Path) -> dict:
    """Harmless non-interactive call: one short reply, read-only sandbox, nothing written to the repo."""
    scratch.mkdir(parents=True, exist_ok=True)
    last = scratch / "probe_last_message.txt"
    argv = [*command, "exec", *HERMETIC, "--sandbox", "read-only", "-C", str(scratch),
            "--output-last-message", str(last), "-"]
    proc = _run(argv, env=env, timeout=cfg["timeout_seconds"],
                input_text=f"Reply with exactly this single line and nothing else: {PROBE_EXPECTED}")
    answer = last.read_text(encoding="utf-8").strip() if last.exists() else ""
    if proc.returncode != 0 or answer != PROBE_EXPECTED:
        raise WorkflowError("CODEX_PROBE_FAILED", f"exit {proc.returncode}, answer {answer[:80]!r}")
    return {"answer": answer, "exit": proc.returncode}


def parse_verdict(path: Path, candidate_sha: str) -> dict:
    if not path.exists():
        raise WorkflowError("REVIEW_INVALID", "the reviewer wrote no final message")
    raw = path.read_bytes()
    try:
        doc = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise WorkflowError("REVIEW_INVALID", f"final message is not JSON: {exc}") from exc
    if not isinstance(doc, dict) or set(doc) != VERDICT_KEYS:
        raise WorkflowError("REVIEW_INVALID", "final message does not have exactly the verdict fields")
    if doc["verdict"] not in VERDICTS:
        raise WorkflowError("REVIEW_INVALID", f"unknown verdict {doc['verdict']!r}")
    if doc["reviewed_sha"] != candidate_sha:
        raise WorkflowError("REVIEWED_WRONG_SHA", f"reviewed {doc['reviewed_sha']}, candidate is {candidate_sha}")
    if doc["review_complete"] is not True:
        # the reviewer could not judge the candidate (for example its sandbox refused the reads). That is an
        # environment outcome, never a code finding: it blocks the milestone instead of sending it for remediation.
        raise WorkflowError("REVIEW_INCOMPLETE", f"the reviewer did not complete the review: {doc['summary'][:300]}")
    findings = doc["findings"]
    if not isinstance(findings, list):
        raise WorkflowError("REVIEW_INVALID", "findings must be a list")
    for f in findings:
        if not isinstance(f, dict) or set(f) != FINDING_KEYS or f["severity"] not in SEVERITIES:
            raise WorkflowError("REVIEW_INVALID", "a finding is malformed")
    blocking = [f for f in findings if f["severity"] in ("BLOCKER", "HIGH")]
    if doc["verdict"] == "PASS" and blocking:
        raise WorkflowError("REVIEW_INVALID", "PASS with BLOCKER or HIGH findings is not a PASS")
    if doc["verdict"] == "REMEDIATION_REQUIRED" and not findings:
        raise WorkflowError("REVIEW_INVALID", "REMEDIATION_REQUIRED must list its findings")
    return {"verdict": doc["verdict"], "reviewed_sha": doc["reviewed_sha"], "summary": doc["summary"],
            "findings": findings, "sha256": sha256_bytes(raw)}


def review(cfg: dict, command: list[str], env: dict, *, candidate_sha: str, worktree: Path,
           packet_text: str, run_dir: Path, schema_path: Path) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "review_packet.md").write_bytes(packet_text.encode("utf-8"))
    last = run_dir / "review_last_message.json"
    argv = [*command, "exec", *HERMETIC, "--sandbox", "read-only", "-C", str(worktree),
            "--output-schema", str(schema_path), "--output-last-message", str(last), "-"]
    proc = _run(argv, env=env, timeout=cfg["timeout_seconds"], input_text=packet_text)
    (run_dir / "review_stdout.txt").write_bytes(proc.stdout.encode("utf-8", "replace"))
    (run_dir / "review_stderr.txt").write_bytes(proc.stderr.encode("utf-8", "replace"))
    if proc.returncode != 0:
        raise WorkflowError("REVIEW_INVALID", f"codex exited {proc.returncode}")
    return parse_verdict(last, candidate_sha)
