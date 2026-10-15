"""Persistent workflow state: one digest-protected JSON document and a hash-chained ledger.

The engine is the only writer. Every change goes through ``save`` and ``append_event``, so the state
digest and the ledger head always describe the same history. A mismatch on load is refused.

Files (all under ``autonomy/state/``, git-ignored):
  state.json   the resumable state; ``state_digest`` covers every other field
  ledger.jsonl append-only events; each line hashes its predecessor
  STATE.md     a human-readable rendering of state.json (never read back)
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path

SCHEMA = "genesis-autonomy-state/1"
STATE_REL = Path("autonomy") / "state"
GENESIS_PREV = "0" * 64

# Legal phase moves. PAUSED and BLOCKED are entered through ``halt`` and left through ``unhalt``.
TRANSITIONS = {
    "IDLE": {"IMPLEMENTING", "HUMAN_GATE", "COMPLETE"},
    "IMPLEMENTING": {"FREEZING"},
    "FREEZING": {"VALIDATING", "IMPLEMENTING"},
    "VALIDATING": {"SKEPTIC_PENDING", "IMPLEMENTING"},
    "SKEPTIC_PENDING": {"CODEX_REVIEWING", "IMPLEMENTING"},
    "CODEX_REVIEWING": {"ADVANCING", "IMPLEMENTING"},
    "ADVANCING": {"IDLE", "COMPLETE"},
    "HUMAN_GATE": {"IDLE"},
    "PAUSED": set(),
    "BLOCKED": set(),
    "COMPLETE": set(),
}


class WorkflowError(RuntimeError):
    """A fail-closed refusal. ``code`` is stable and machine-readable; ``message`` is for the operator."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_of(obj) -> str:
    return sha256_bytes(canonical(obj))


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def state_dir(repo: Path) -> Path:
    return Path(repo) / STATE_REL


def new_state(*, product_sha: str, evidence_sha: str, branch: str, writer: str,
              envelope_digest: str, roadmap_digest: str, milestone_ids: list[str]) -> dict:
    return {
        "schema": SCHEMA,
        "baseline": {"product_sha": product_sha, "evidence_sha": evidence_sha,
                     "branch": branch, "writer_worktree": writer},
        "envelope_digest": envelope_digest,
        "roadmap_digest": roadmap_digest,
        "phase": "IDLE",
        "halt": None,
        "human_gate": None,
        "milestones": {mid: {"status": "PENDING"} for mid in milestone_ids},
        "active": None,
        "completed": [],
        "ledger_head": GENESIS_PREV,
        "ledger_length": 0,
        "recovered_torn_writes": 0,
        "next_action": "run go",
        "state_digest": "",
        "updated_utc": utc_now(),
    }


def _body(state: dict) -> dict:
    return {k: v for k, v in state.items() if k != "state_digest"}


def read_ledger(repo: Path) -> list[dict]:
    path = state_dir(repo) / "ledger.jsonl"
    if not path.exists():
        return []
    entries, prev = [], GENESIS_PREV
    for raw in path.read_bytes().splitlines():
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw.decode("ascii"))
        except ValueError as exc:
            raise WorkflowError("LEDGER_TAMPERED", f"ledger line is not valid JSON: {exc}") from exc
        if entry.get("prev") != prev:
            raise WorkflowError("LEDGER_TAMPERED", "ledger hash chain is broken")
        if digest_of({k: v for k, v in entry.items() if k != "hash"}) != entry.get("hash"):
            raise WorkflowError("LEDGER_TAMPERED", "ledger entry does not match its hash")
        prev = entry["hash"]
        entries.append(entry)
    return entries


def append_event(repo: Path, state: dict, event: dict) -> dict:
    """Append one hash-chained ledger entry and advance the head held in ``state``."""
    entry = {"utc": utc_now(), "prev": state["ledger_head"], **event}
    entry["hash"] = digest_of({k: v for k, v in entry.items() if k != "hash"})
    path = state_dir(repo) / "ledger.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "ab") as fh:
        fh.write((json.dumps(entry, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii"))
        fh.flush()
        os.fsync(fh.fileno())
    state["ledger_head"] = entry["hash"]
    state["ledger_length"] += 1
    return entry


def _verify_ledger(repo: Path, state: dict) -> None:
    entries = read_ledger(repo)
    head = entries[-1]["hash"] if entries else GENESIS_PREV
    recorded_len, recorded_head = state["ledger_length"], state["ledger_head"]
    if len(entries) == recorded_len and head == recorded_head:
        return
    # A crash between the ledger append and the state save leaves exactly one unrecorded entry.
    # Adopt it (it is hash-chained onto the recorded head) and count the recovery; anything else is refused.
    if len(entries) == recorded_len + 1 and entries[-1]["prev"] == recorded_head:
        state["ledger_head"] = head
        state["ledger_length"] = len(entries)
        state["recovered_torn_writes"] += 1
        return
    raise WorkflowError("LEDGER_MISMATCH",
                        f"ledger has {len(entries)} entries but state records {recorded_len}")


def load(repo: Path) -> dict:
    path = state_dir(repo) / "state.json"
    if not path.exists():
        raise WorkflowError("NOT_INITIALISED", "no workflow state; run init first")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise WorkflowError("STATE_MALFORMED", f"state.json is not valid JSON: {exc}") from exc
    if not isinstance(state, dict) or state.get("schema") != SCHEMA:
        raise WorkflowError("STATE_MALFORMED", "state.json has an unknown schema")
    if state.get("state_digest") != digest_of(_body(state)):
        raise WorkflowError("STATE_DIGEST_MISMATCH", "state.json was changed outside the engine")
    if state.get("phase") not in TRANSITIONS and state.get("phase") not in ("PAUSED", "BLOCKED"):
        raise WorkflowError("STATE_MALFORMED", f"unknown phase {state.get('phase')!r}")
    _verify_ledger(Path(repo), state)
    return state


def save(repo: Path, state: dict) -> None:
    state["updated_utc"] = utc_now()
    state["state_digest"] = digest_of(_body(state))
    base = state_dir(repo)
    write_atomic(base / "state.json", (json.dumps(state, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    write_atomic(base / "STATE.md", render(state).encode("utf-8"))


def set_phase(state: dict, new: str) -> None:
    old = state["phase"]
    if new not in TRANSITIONS.get(old, set()):
        raise WorkflowError("MALFORMED_TRANSITION", f"{old} -> {new} is not a legal move")
    state["phase"] = new


def halt(repo: Path, state: dict, kind: str, reason: str, detail=None) -> None:
    """Stop at a safe point. ``kind`` is PAUSED (operator) or BLOCKED (fail-closed refusal)."""
    if kind not in ("PAUSED", "BLOCKED"):
        raise WorkflowError("MALFORMED_TRANSITION", f"cannot halt as {kind}")
    if state["phase"] in ("PAUSED", "BLOCKED", "COMPLETE"):
        return
    state["halt"] = {"kind": kind, "reason": reason, "detail": detail,
                     "from_phase": state["phase"], "utc": utc_now()}
    state["phase"] = kind
    append_event(repo, state, {"event": kind, "reason": reason, "phase": state["halt"]["from_phase"]})


def unhalt(repo: Path, state: dict, *, clear_block: bool) -> str:
    if state["phase"] not in ("PAUSED", "BLOCKED"):
        raise WorkflowError("NOT_HALTED", f"phase is {state['phase']}; nothing to resume")
    if state["phase"] == "BLOCKED" and not clear_block:
        raise WorkflowError("BLOCK_NOT_CLEARED", "a fail-closed block needs an explicit --clear-block after the cause is fixed")
    resumed = state["halt"]["from_phase"]
    append_event(repo, state, {"event": "RESUMED", "from": state["phase"], "to": resumed,
                               "reason": state["halt"]["reason"]})
    state["phase"] = resumed
    state["halt"] = None
    return resumed


def render(state: dict) -> str:
    active = state.get("active") or {}
    lines = [
        "# Genesis autonomous construction: current state",
        "",
        "Generated from state.json by the engine. Do not edit; the digest will refuse a changed state.json.",
        "",
        f"- Phase: **{state['phase']}**",
        f"- Branch: `{state['baseline']['branch']}` in `{state['baseline']['writer_worktree']}`",
        f"- Baseline product SHA: `{state['baseline']['product_sha']}`",
        f"- Evidence SHA: `{state['baseline']['evidence_sha']}`",
        f"- Ledger entries: {state['ledger_length']} (head `{state['ledger_head'][:16]}`)",
        f"- Next action: {state.get('next_action')}",
    ]
    if state.get("halt"):
        lines.append(f"- Halted: {state['halt']['kind']} - {state['halt']['reason']}")
    if state.get("human_gate"):
        lines.append(f"- Human gate: {state['human_gate'].get('id')} - {state['human_gate'].get('trigger')}")
    if active:
        lines += [
            "",
            "## Active milestone",
            f"- Milestone: {active.get('milestone')} (round {active.get('round')}, mode {active.get('mode')})",
            f"- Tasks done: {', '.join(active.get('done', [])) or 'none'}",
            f"- Candidate: `{active.get('candidate') or 'not frozen'}`",
            f"- Candidate parent: `{active.get('candidate_parent') or 'n/a'}`",
            f"- Validation: {(active.get('validation') or {}).get('result', 'not run')}",
            f"- Skeptic: {(active.get('skeptic') or {}).get('verdict', 'not run')}",
            f"- Codex review: {(active.get('review') or {}).get('verdict', 'not run')}",
            f"- Rejected candidates: {len(active.get('rejected', []))}",
        ]
    lines += ["", "## Milestones"]
    for mid, rec in state["milestones"].items():
        lines.append(f"- {mid}: {rec['status']}")
    return "\n".join(lines) + "\n"
