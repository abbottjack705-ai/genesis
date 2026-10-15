"""Roadmap: milestones, tasks, validation commands, dependencies and human gates.

A human gate is cleared only by a file under ``autonomy/approvals/`` written by a human operator and
committed by them. The engine checks the file's shape; it cannot prove who wrote it, so agents must
never create approval files (see autonomy/README.md, residuals).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .state import WorkflowError

SCHEMA = "genesis-autonomy-roadmap/1"
APPROVED_BY = "human-operator"


def load(repo: Path) -> dict:
    path = Path(repo) / "autonomy" / "ROADMAP.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise WorkflowError("ROADMAP_MALFORMED", f"cannot read ROADMAP.json: {exc}") from exc
    validate(doc)
    return doc


def validate(doc: dict) -> None:
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise WorkflowError("ROADMAP_MALFORMED", "unknown or missing roadmap schema")
    milestones = doc.get("milestones")
    if not isinstance(milestones, list) or not milestones:
        raise WorkflowError("ROADMAP_MALFORMED", "no milestones")
    ids = [m.get("id") for m in milestones]
    if len(set(ids)) != len(ids) or not all(isinstance(i, str) and i for i in ids):
        raise WorkflowError("ROADMAP_MALFORMED", "milestone ids must be unique non-empty strings")
    for m in milestones:
        for key in ("name", "track", "authority", "tasks", "validation", "depends_on"):
            if key not in m:
                raise WorkflowError("ROADMAP_MALFORMED", f"{m['id']}: missing {key}")
        if not m["tasks"] or not m["validation"]:
            raise WorkflowError("ROADMAP_MALFORMED", f"{m['id']}: needs at least one task and one validation")
        for task in m["tasks"]:
            if not all(task.get(k) for k in ("id", "title", "acceptance")):
                raise WorkflowError("ROADMAP_MALFORMED", f"{m['id']}: task needs id, title and acceptance")
        for check in m["validation"]:
            argv = check.get("argv")
            if not check.get("id") or not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
                raise WorkflowError("ROADMAP_MALFORMED", f"{m['id']}: validation needs id and a string argv")
        for dep in m["depends_on"]:
            if dep not in ids:
                raise WorkflowError("ROADMAP_MALFORMED", f"{m['id']}: depends on unknown milestone {dep}")
        gate = m.get("human_gate")
        if gate is not None and not all(gate.get(k) for k in ("id", "trigger", "checkpoint")):
            raise WorkflowError("ROADMAP_MALFORMED", f"{m['id']}: human_gate needs id, trigger and checkpoint")


def gate_approved(repo: Path, gate_id: str) -> bool:
    """True only for an approval that is committed (HEAD holds exactly these bytes) and well formed.

    A present but uncommitted or edited file is refused, not accepted: an approval must be in history.
    """
    rel = f"autonomy/approvals/{gate_id}.json"
    path = Path(repo) / rel
    if not path.exists():
        return False
    # git's own comparison, so core.autocrlf and line endings are judged the way git judges them
    in_head = subprocess.run(["git", "cat-file", "-e", f"HEAD:{rel}"], cwd=str(repo), capture_output=True)
    same = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", rel], cwd=str(repo), capture_output=True)
    if in_head.returncode != 0 or same.returncode != 0:
        raise WorkflowError("APPROVAL_UNCOMMITTED", f"{rel} exists but HEAD does not hold this approval; "
                                                    f"commit the approval before the gate can clear")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise WorkflowError("APPROVAL_MALFORMED", f"{path.name} is not valid JSON") from exc
    ok = (doc.get("gate_id") == gate_id and doc.get("approved_by") == APPROVED_BY
          and isinstance(doc.get("approval_reference"), str) and doc["approval_reference"].strip() != "")
    if not ok:
        raise WorkflowError("APPROVAL_MALFORMED", f"{path.name} does not match gate {gate_id} "
                                                  f"(needs gate_id, approved_by={APPROVED_BY!r}, approval_reference)")
    return True


def select(doc: dict, statuses: dict, repo: Path):
    """Pick the next runnable milestone in roadmap order.

    Returns (milestone, None, None) when one is runnable, otherwise (None, reason, detail) where reason is
    COMPLETE, HUMAN_GATE (the only remaining work waits on a gate) or BLOCKED (waiting on dependencies).
    A gated milestone that nothing else depends on does not stop unrelated paper-only work.
    """
    pending = [m for m in doc["milestones"] if statuses.get(m["id"], {}).get("status") == "PENDING"]
    if not pending:
        return None, "COMPLETE", None
    waiting_gates = []
    for m in pending:
        if any(statuses.get(d, {}).get("status") != "PASSED" for d in m["depends_on"]):
            continue
        gate = m.get("human_gate")
        if gate and not gate_approved(repo, gate["id"]):
            waiting_gates.append({"milestone": m["id"], **gate})
            continue
        return m, None, None
    if waiting_gates:
        return None, "HUMAN_GATE", waiting_gates
    return None, "BLOCKED", "pending milestones wait on dependencies that never pass"


def pending_gates(doc: dict, statuses: dict, repo: Path) -> list[dict]:
    """Gates still waiting on a human. A broken approval is reported on its gate, never allowed to crash a stop."""
    out = []
    for m in doc["milestones"]:
        gate = m.get("human_gate")
        if not (gate and statuses.get(m["id"], {}).get("status") == "PENDING"):
            continue
        try:
            if gate_approved(repo, gate["id"]):
                continue
            out.append({"milestone": m["id"], **gate})
        except WorkflowError as exc:
            out.append({"milestone": m["id"], **gate, "approval_problem": exc.code, "message": exc.message})
    return out
