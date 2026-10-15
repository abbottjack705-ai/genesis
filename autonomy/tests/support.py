"""Harness for the workflow tests: a throwaway writer repository, scripted Codex, and a Lead driver.

Only the LLM roles (implementer, skeptic) and the Codex CLI are scripted. Git, the engine, the locks,
the evidence manifests and the validation subprocesses are real.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from genesis_autonomy import engine

AUTONOMY = Path(__file__).resolve().parents[1]
FAKE_CODEX = AUTONOMY / "tests" / "fakes" / "fake_codex.py"
PY = sys.executable
FRAMEWORK = ["genesis_workflow.py", "shard_tests.py", "review_schema.json"]
PACKAGE = "genesis_autonomy"

# Validation argv that proves a work file exists (the engine runs it in a detached checkout of the candidate).
def check_exists(path: str) -> list[str]:
    return [PY, "-B", "-c", f"import os,sys; sys.exit(0 if os.path.exists({path!r}) else 1)"]


def check_contains(path: str, needle: str) -> list[str]:
    return [PY, "-B", "-c", f"import sys; sys.exit(0 if {needle!r} in open({path!r}).read() else 1)"]


def dryrun_roadmap() -> dict:
    """DR0 is gated and nothing depends on it, so it must not stop DR1. DR2 depends on DR1."""
    return {
        "schema": "genesis-autonomy-roadmap/1",
        "milestones": [
            {"id": "DR0", "name": "gated paper item", "track": "X", "authority": "fixture", "depends_on": [],
             "human_gate": {"id": "HG-DR0", "trigger": "fixture gate", "checkpoint": "fixture"},
             "tasks": [{"id": "DR0.1", "title": "gated work", "acceptance": "never runs before approval"}],
             "validation": [{"id": "ok", "argv": [PY, "-B", "-c", "print(1)"]}]},
            {"id": "DR1", "name": "first paper item", "track": "X", "authority": "fixture", "depends_on": [],
             "human_gate": None,
             "tasks": [{"id": "DR1.1", "title": "write the work file", "acceptance": "work/DR1.1.txt exists"}],
             "validation": [{"id": "work-file", "argv": check_contains("work/DR1.1.txt", "GOOD")}]},
            {"id": "DR2", "name": "second paper item", "track": "X", "authority": "fixture", "depends_on": ["DR1"],
             "human_gate": None,
             "tasks": [{"id": "DR2.1", "title": "write the second file", "acceptance": "work/DR2.1.txt exists"}],
             "validation": [{"id": "work-file", "argv": check_exists("work/DR2.1.txt")}]},
        ],
    }


def git(cwd, *args, check=True) -> str:
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    if check and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr}")
    return proc.stdout.strip()


def make_repo(root: Path, roadmap: dict, *, wait_seconds: int = 0, envelope_patch: dict | None = None) -> Path:
    """A writer repository on branch dryrun-build with the real workflow code and a fixture roadmap."""
    repo = Path(root) / "writer"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "dryrun-build")
    git(repo, "config", "user.name", "Test Harness")
    git(repo, "config", "user.email", "harness@example.invalid")
    (repo / "autonomy").mkdir()
    shutil.copytree(AUTONOMY / PACKAGE, repo / "autonomy" / PACKAGE,
                    ignore=shutil.ignore_patterns("__pycache__"))
    for name in FRAMEWORK:
        shutil.copy2(AUTONOMY / name, repo / "autonomy" / name)
    envelope = json.loads((AUTONOMY / "ENVELOPE.json").read_text(encoding="utf-8"))
    envelope["writer_branch"] = "dryrun-build"
    envelope["heavy"]["wait_seconds"] = wait_seconds
    envelope["heavy"]["min_available_mib"] = 1
    for key, value in (envelope_patch or {}).items():
        envelope[key] = value
    (repo / "autonomy" / "ENVELOPE.json").write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
    (repo / "autonomy" / "ROADMAP.json").write_text(json.dumps(roadmap, indent=2) + "\n", encoding="utf-8")
    (repo / "autonomy" / "approvals").mkdir()
    (repo / "autonomy" / "approvals" / "README.md").write_text("fixture\n", encoding="utf-8")
    (repo / ".gitignore").write_text("__pycache__/\nautonomy/state/\n", encoding="utf-8")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    return repo


def make_context(repo: Path, scenario: list[dict] | None = None, *, extra_env: dict | None = None,
                 memory_mib: int = 4096) -> engine.Context:
    """Context whose Codex is the scripted double. Billing variables are removed so the guard is quiet."""
    scenario_dir = Path(repo).parent / "scenario"
    scenario_dir.mkdir(exist_ok=True)
    scenario_file = scenario_dir / "codex.json"
    scenario_file.write_text(json.dumps(scenario or [{"verdict": "PASS"}]), encoding="utf-8")
    cursor = Path(str(scenario_file) + ".cursor")
    if cursor.exists():
        cursor.unlink()
    env = {k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY", "CODEX_API_KEY")}
    env["FAKE_CODEX_SCENARIO"] = str(scenario_file)
    env["FAKE_CODEX_LOG"] = str(scenario_dir / "codex-invocations.jsonl")
    env.update(extra_env or {})
    return engine.Context(repo, codex_command=[PY, "-B", str(FAKE_CODEX)], env=env,
                          memory_reader=lambda: memory_mib)


def commit_work(repo: Path, relpath: str, text: str, message: str) -> str:
    target = Path(repo) / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode("utf-8"))            # explicit LF: text mode would write CRLF on Windows
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def drive(ctx: engine.Context, *, implementer, max_calls: int = 80, stop_when=None) -> list[dict]:
    """Play the Lead: call go, perform each ACTION with the scripted roles, stop at a STOP.

    ``implementer(ctx, action)`` writes and commits work; ``implementer`` must call task_done itself
    through this driver. ``stop_when(result)`` may end the drive early.
    """
    results = []
    for _ in range(max_calls):
        result = engine.go(ctx)
        results.append(result)
        if result["status"] == "STOP":
            return results
        if stop_when and stop_when(result):
            return results
        if result["action"] == "IMPLEMENT":
            implementer(ctx, result)
            for task in result["tasks"]:
                engine.task_done(ctx, task["id"])
        elif result["action"] == "SKEPTIC":
            reply = Path(ctx.repo) / result["reply_file"]
            reply.parent.mkdir(parents=True, exist_ok=True)
            reply.write_text(json.dumps({"verdict": "CLEAR", "reviewed_sha": result["candidate"],
                                         "summary": "scripted skeptic: clear", "findings": []}),
                             encoding="utf-8")
            engine.record_skeptic(ctx, reply)
    raise AssertionError("drive did not reach a stop within its call budget")


def write_approval(repo: Path, gate_id: str) -> None:
    approvals = Path(repo) / "autonomy" / "approvals"
    approvals.mkdir(exist_ok=True)
    (approvals / f"{gate_id}.json").write_bytes(json.dumps({
        "gate_id": gate_id, "approved_by": "human-operator",
        "approval_reference": "fixture approval for the dry run", "scope": "fixture"}).encode("utf-8"))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", f"fixture approval {gate_id}")


def ledger_events(repo: Path) -> list[str]:
    path = Path(repo) / "autonomy" / "state" / "ledger.jsonl"
    if not path.exists():
        return []
    return [json.loads(line)["event"] for line in path.read_text(encoding="utf-8").splitlines() if line]
