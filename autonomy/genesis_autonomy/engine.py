"""The workflow engine: a deterministic state machine that the Genesis Lead drives.

``go`` advances the milestone as far as it can without an LLM, then returns one of two things:

  ACTION  an LLM step the Lead must perform now (IMPLEMENT or SKEPTIC), with a packet to hand over;
  STOP    a human checkpoint, a pause, a fail-closed block, a deferral, or completion.

Deterministic steps (freeze, validate, Codex review, advance) run inside ``go``. Each one checks the
writer worktree, the exact candidate SHA and the evidence manifests before it trusts anything.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

from . import evidence, gitops, heavy, review, roadmap
from . import state as st
from .state import WorkflowError, digest_of, utc_now

COAUTHOR = "Co-Authored-By: Claude Haiku 5.5 <noreply@anthropic.com>"
MAX_STEPS = 500
# Workflow governance: changed between milestones by a human-governed commit, never by a candidate.
GOVERNANCE_PREFIXES = ["autonomy/approvals/", "autonomy/state/", "autonomy/genesis_autonomy/",
                       "autonomy/genesis_workflow.py", "autonomy/shard_tests.py", "autonomy/tests/",
                       "autonomy/ENVELOPE.json", "autonomy/ROADMAP.json", "autonomy/review_schema.json",
                       ".claude/"]
DEFERRABLE = {"HEAVY_BUSY", "MEMORY_GATE", "ENGINE_BUSY"}
SKEPTIC_KEYS = {"verdict", "reviewed_sha", "summary", "findings"}
SKEPTIC_VERDICTS = ("CLEAR", "FINDINGS")
REJECTION_KINDS = ("VALIDATION_FAILED", "SKEPTIC_FINDINGS", "CODEX_REMEDIATION_REQUIRED")


class Context:
    """Everything a command needs: the writer repository, its configuration and injectable host hooks."""

    def __init__(self, repo, *, codex_command=None, env=None, memory_reader=None):
        self.repo = Path(repo)
        self.envelope = _load_json(self.repo / "autonomy" / "ENVELOPE.json", "genesis-autonomy-envelope/1")
        self.roadmap_doc = roadmap.load(self.repo)
        self.codex_command = list(codex_command or self.envelope["codex"]["command"])
        self.env = dict(env) if env is not None else None
        self.memory_reader = memory_reader or heavy.available_memory_mib
        self.common = gitops.common_dir(self.repo)
        self.state_root = self.repo / st.STATE_REL
        self.wt_root = self.repo.parent / (self.repo.name + "-worktrees")
        self.schema_path = self.repo / self.envelope["codex"]["review_schema"]

    def child_env(self) -> dict:
        return dict(os.environ) if self.env is None else dict(self.env)

    def milestone(self, mid: str) -> dict:
        for m in self.roadmap_doc["milestones"]:
            if m["id"] == mid:
                return m
        raise WorkflowError("ROADMAP_MALFORMED", f"unknown milestone {mid}")

    def forbidden(self, path: str) -> bool:
        """True for any path a candidate may not change.

        Frozen and immutable history; human-only approvals; and the workflow's own governance (engine, CLI,
        envelope, roadmap, tests, Claude commands, agents and settings). Those change only between milestones,
        through a human-governed commit, so the engine that judges a candidate is never changed by that candidate.
        Comparison is case-folded because the host filesystem is case-insensitive.
        """
        prefixes = (self.envelope["frozen_prefixes"] + self.envelope["immutable_prefixes"]
                    + GOVERNANCE_PREFIXES)
        folded = path.casefold()
        return any(folded == p.rstrip("/").casefold() or folded.startswith(p.casefold()) for p in prefixes)


def _load_json(path: Path, schema: str) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise WorkflowError("ENVELOPE_MALFORMED", f"cannot read {path.name}: {exc}") from exc
    if doc.get("schema") != schema:
        raise WorkflowError("ENVELOPE_MALFORMED", f"{path.name} has an unknown schema")
    return doc


def _lock(ctx: Context):
    return heavy.ExclusiveFileLock(ctx.state_root / "engine.lock", "ENGINE_BUSY",
                                   "another engine command is running")


def _open(ctx: Context, *, mutate: bool) -> dict:
    state = st.load(ctx.repo)
    env_d, road_d = digest_of(ctx.envelope), digest_of(ctx.roadmap_doc)
    if (state["envelope_digest"], state["roadmap_digest"]) != (env_d, road_d):
        if state["phase"] != "IDLE":
            raise WorkflowError("CONFIG_CHANGED", "ENVELOPE.json or ROADMAP.json changed during a milestone; "
                                                  "re-baseline only while IDLE")
        if mutate:
            state["envelope_digest"], state["roadmap_digest"] = env_d, road_d
            st.append_event(ctx.repo, state, {"event": "CONFIG_RECORDED", "envelope": env_d, "roadmap": road_d})
    for m in ctx.roadmap_doc["milestones"]:
        state["milestones"].setdefault(m["id"], {"status": "PENDING"})
    return state


def _recover(ctx: Context, state: dict) -> None:
    """Called while the engine lock is held: any in-flight marker belongs to a process that has died."""
    active = state.get("active")
    if active and active.get("inflight"):
        st.append_event(ctx.repo, state, {"event": "INTERRUPTED", "milestone": active["milestone"],
                                          "round": active["round"], "inflight": active["inflight"]})
        active["interruptions"] = active.get("interruptions", 0) + 1
        active["inflight"] = None
    if ctx.wt_root.exists():
        for child in ctx.wt_root.iterdir():
            gitops.remove_worktree(ctx.repo, child)
    gitops.git(ctx.repo, "worktree", "prune", check=False)
    st.save(ctx.repo, state)   # recovery events and state land together; never a ledger-only entry


def _assert_writer(ctx: Context, state: dict) -> None:
    base = state["baseline"]
    if not gitops.same_path(gitops.toplevel(ctx.repo), base["writer_worktree"]):
        raise WorkflowError("WRITER_MISMATCH", f"engine is running in {ctx.repo}, not the writer {base['writer_worktree']}")
    if gitops.branch(ctx.repo) != ctx.envelope["writer_branch"]:
        raise WorkflowError("WRITER_MISMATCH", f"writer must be on {ctx.envelope['writer_branch']}")


def _assert_candidate_head(ctx: Context, state: dict) -> None:
    """Every review step judges the frozen candidate. If the writer HEAD has moved, the review is stale: refuse."""
    candidate = state["active"]["candidate"]
    if candidate is None or gitops.head(ctx.repo) != candidate:
        raise WorkflowError("CANDIDATE_MOVED", f"the writer HEAD is no longer the frozen candidate {candidate}; "
                                                f"a commit landed after freeze, so this review is stale")


def _stop(ctx: Context, state: dict, reason: str, detail=None) -> dict:
    st.save(ctx.repo, state)
    return {"status": "STOP", "reason": reason, "phase": state["phase"], "detail": detail,
            "milestone": (state.get("active") or {}).get("milestone"),
            "pending_gates": roadmap.pending_gates(ctx.roadmap_doc, state["milestones"], ctx.repo),
            "next_action": state.get("next_action")}


def _action(ctx: Context, state: dict, payload: dict) -> dict:
    st.save(ctx.repo, state)
    return {"status": "ACTION", "phase": state["phase"], "pending_gates": roadmap.pending_gates(
        ctx.roadmap_doc, state["milestones"], ctx.repo), **payload}


def _block(ctx: Context, state: dict, code: str, message: str, detail=None) -> dict:
    st.halt(ctx.repo, state, "BLOCKED", f"{code}: {message}", detail)
    state["next_action"] = f"blocked ({code}); fix the cause, then resume --clear-block"
    return _stop(ctx, state, "BLOCKED", {"code": code, "message": message, **({} if detail is None else {"detail": detail})})


def _write_text(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return str(path)


def _rel(ctx: Context, path) -> str:
    return Path(path).relative_to(ctx.repo).as_posix() if Path(path).is_relative_to(ctx.repo) else str(path)


# ----------------------------------------------------------------------------- commands

def init(ctx: Context, *, product_sha: str, evidence_sha: str) -> dict:
    with _lock(ctx):
        if (ctx.state_root / "state.json").exists():
            raise WorkflowError("ALREADY_INITIALISED", "workflow state exists; refusing to overwrite it")
        if not gitops.same_path(gitops.toplevel(ctx.repo), ctx.repo):
            raise WorkflowError("WRITER_MISMATCH", "init must run from the writer worktree root")
        if gitops.branch(ctx.repo) != ctx.envelope["writer_branch"]:
            raise WorkflowError("WRITER_MISMATCH", f"writer must be on {ctx.envelope['writer_branch']}")
        if not gitops.is_clean(ctx.repo):
            raise WorkflowError("WRITER_DIRTY", "the writer worktree must be clean before init")
        head = gitops.head(ctx.repo)
        if not gitops.is_ancestor(ctx.repo, product_sha, head):
            raise WorkflowError("BASELINE_MISMATCH", f"{product_sha} is not an ancestor of HEAD")
        state = st.new_state(product_sha=product_sha, evidence_sha=evidence_sha,
                             branch=ctx.envelope["writer_branch"], writer=str(ctx.repo),
                             envelope_digest=digest_of(ctx.envelope), roadmap_digest=digest_of(ctx.roadmap_doc),
                             milestone_ids=[m["id"] for m in ctx.roadmap_doc["milestones"]])
        for m in ctx.roadmap_doc["milestones"]:
            if m.get("baseline_status") == "PASSED":   # work certified before this workflow existed
                state["milestones"][m["id"]] = {"status": "PASSED", "candidate": m["baseline_evidence"],
                                                "record_commit": "baseline"}
        st.append_event(ctx.repo, state, {"event": "INIT", "head": head, "product": product_sha})
        st.save(ctx.repo, state)
        return {"status": "INITIALISED", "head": head, "milestones": list(state["milestones"])}


def status(ctx: Context) -> dict:
    state = _open(ctx, mutate=False)
    active = state.get("active") or {}
    remaining = [t for t in active.get("tasks", []) if t not in active.get("done", [])]
    return {"phase": state["phase"], "halt": state.get("halt"), "human_gate": state.get("human_gate"),
            "milestone": active.get("milestone"), "round": active.get("round"), "mode": active.get("mode"),
            "remaining_tasks": remaining, "candidate": active.get("candidate"),
            "validation": (active.get("validation") or {}).get("result"),
            "skeptic": (active.get("skeptic") or {}).get("verdict"),
            "codex": (active.get("review") or {}).get("verdict"),
            "rejected": [r["kind"] for r in active.get("rejected", [])],
            "completed": [c["milestone"] for c in state["completed"]],
            "pending_gates": roadmap.pending_gates(ctx.roadmap_doc, state["milestones"], ctx.repo),
            "ledger_length": state["ledger_length"], "recovered_torn_writes": state["recovered_torn_writes"],
            "next_action": state.get("next_action"), "state_digest": state["state_digest"]}


def select_only(ctx: Context) -> dict:
    """What ``go`` would start next. Before init it uses the roadmap's baseline statuses; it changes nothing."""
    try:
        statuses = _open(ctx, mutate=False)["milestones"]
    except WorkflowError as exc:
        if exc.code != "NOT_INITIALISED":
            raise
        statuses = {m["id"]: ({"status": "PASSED"} if m.get("baseline_status") == "PASSED"
                              else {"status": "PENDING"}) for m in ctx.roadmap_doc["milestones"]}
    m, reason, detail = roadmap.select(ctx.roadmap_doc, statuses, ctx.repo)
    if m is None:
        return {"status": "NO_RUNNABLE_MILESTONE", "reason": reason, "detail": detail}
    return {"status": "WOULD_START", "milestone": m["id"], "name": m["name"], "track": m["track"],
            "tasks": [t["id"] for t in m["tasks"]], "authority": m["authority"]}


def go(ctx: Context) -> dict:
    with _lock(ctx):
        state = _open(ctx, mutate=True)
        _recover(ctx, state)
        st.save(ctx.repo, state)
        return _drive(ctx, state)


def _drive(ctx: Context, state: dict) -> dict:
    for _ in range(MAX_STEPS):
        if (ctx.state_root / "PAUSE_REQUESTED").exists() and state["phase"] not in ("PAUSED", "BLOCKED", "COMPLETE"):
            st.halt(ctx.repo, state, "PAUSED", "operator pause requested")
        if state["phase"] in ("PAUSED", "BLOCKED", "COMPLETE"):
            return _stop(ctx, state, state["phase"] if state["phase"] != "COMPLETE" else "COMPLETE",
                         state.get("halt"))
        try:
            result = _step(ctx, state)
        except WorkflowError as exc:
            if exc.code in DEFERRABLE:
                active = state.get("active")
                if active is not None:
                    active["deferrals"] = active.get("deferrals", 0) + 1
                    if active["deferrals"] > ctx.envelope["heavy"]["max_deferrals"]:
                        return _block(ctx, state, "DEFERRAL_LIMIT",
                                      f"{exc.code} persisted across {active['deferrals']} runs; "
                                      f"free the host, then resume --clear-block")
                state["next_action"] = f"deferred ({exc.code}); run go again when the host is free"
                return _stop(ctx, state, "DEFERRED", {"code": exc.code, "message": exc.message})
            return _block(ctx, state, exc.code, exc.message)
        st.save(ctx.repo, state)
        if result is not None:
            return result
    raise WorkflowError("STEP_LIMIT", "the engine made no stop decision within its step budget")


def _human_gate(ctx: Context, state: dict):
    gate = state["human_gate"]
    if roadmap.gate_approved(ctx.repo, gate["id"]):
        state["human_gate"] = None
        st.append_event(ctx.repo, state, {"event": "GATE_CLEARED", "gate": gate["id"]})
        st.set_phase(state, "IDLE")
        state["next_action"] = f"gate {gate['id']} approved; selecting the next milestone"
        return None
    state["next_action"] = f"human gate {gate['id']}: see explain-gate"
    return _stop(ctx, state, "HUMAN_GATE", gate)


def _step(ctx: Context, state: dict):
    phase = state["phase"]
    if phase == "IDLE":
        return _idle(ctx, state)
    if phase == "HUMAN_GATE":
        return _human_gate(ctx, state)
    if phase == "IMPLEMENTING":
        return _implementing(ctx, state)
    if phase == "FREEZING":
        return _freeze(ctx, state)
    if phase == "VALIDATING":
        return _validate(ctx, state)
    if phase == "SKEPTIC_PENDING":
        return _skeptic_action(ctx, state)
    if phase == "CODEX_REVIEWING":
        return _codex(ctx, state)
    if phase == "ADVANCING":
        return _advance(ctx, state)
    raise WorkflowError("MALFORMED_TRANSITION", f"no step for phase {phase}")


def _idle(ctx: Context, state: dict):
    if state.get("active"):
        raise WorkflowError("STATE_MALFORMED", "IDLE with an active milestone")
    m, reason, detail = roadmap.select(ctx.roadmap_doc, state["milestones"], ctx.repo)
    if m is None:
        if reason == "COMPLETE":
            st.set_phase(state, "COMPLETE")
            state["next_action"] = "none: every milestone has passed"
            st.append_event(ctx.repo, state, {"event": "COMPLETE"})
            return _stop(ctx, state, "COMPLETE")
        if reason == "HUMAN_GATE":
            st.set_phase(state, "HUMAN_GATE")
            state["human_gate"] = detail[0]
            state["next_action"] = f"human gate {detail[0]['id']}: see explain-gate"
            st.append_event(ctx.repo, state, {"event": "HUMAN_GATE", "gate": detail[0]["id"]})
            return _stop(ctx, state, "HUMAN_GATE", detail)
        return _block(ctx, state, "DEPENDENCY_DEADLOCK", str(detail))
    _start(ctx, state, m)
    return None


def _start(ctx: Context, state: dict, m: dict) -> None:
    _assert_writer(ctx, state)
    if not gitops.is_clean(ctx.repo):
        raise WorkflowError("WRITER_DIRTY", "the writer must be clean before a milestone starts")
    head = gitops.head(ctx.repo)
    state["active"] = {
        "milestone": m["id"], "name": m["name"], "round": 1, "mode": "INITIAL",
        "tasks": [t["id"] for t in m["tasks"]],
        "task_titles": {t["id"]: {"title": t["title"], "acceptance": t["acceptance"]} for t in m["tasks"]},
        "done": [], "milestone_base": head, "round_base": head, "last_head": head,
        "candidate": None, "candidate_parent": None, "changed": [], "diff_stat": "",
        "validation": None, "skeptic": None, "review": None, "rejected": [], "runs": [],
        "findings": [], "reason": None, "writer_retries": 0, "attempts": 0,
        "inflight": None, "interruptions": 0,
    }
    state["milestones"][m["id"]] = {"status": "ACTIVE"}
    st.append_event(ctx.repo, state, {"event": "MILESTONE_STARTED", "milestone": m["id"], "base": head})
    st.set_phase(state, "IMPLEMENTING")
    state["next_action"] = f"implement {m['id']}"


def _implementing(ctx: Context, state: dict):
    a = state["active"]
    remaining = [t for t in a["tasks"] if t not in a["done"]]
    if not remaining:
        st.set_phase(state, "FREEZING")
        return None
    packet = _write_implement_packet(ctx, state, remaining)
    state["next_action"] = f"implementer: {', '.join(remaining)} (round {a['round']})"
    tasks = [{"id": t, **a["task_titles"][t]} for t in remaining]
    return _action(ctx, state, {"action": "IMPLEMENT", "milestone": a["milestone"], "round": a["round"],
                                "mode": a["mode"], "tasks": tasks, "writer": str(ctx.repo),
                                "branch": ctx.envelope["writer_branch"], "packet": _rel(ctx, packet),
                                "reason": a.get("reason")})


def _freeze(ctx: Context, state: dict):
    a = state["active"]
    _assert_writer(ctx, state)
    if not gitops.is_clean(ctx.repo):
        return _writer_retry(ctx, state, "the writer has uncommitted changes: commit or revert them")
    head = gitops.head(ctx.repo)
    if head == a["round_base"] or not gitops.is_ancestor(ctx.repo, a["round_base"], head):
        return _writer_retry(ctx, state, "no commit has been made since this round started")
    changed = gitops.changed_paths(ctx.repo, a["milestone_base"], head)
    forbidden = [p for p in changed if ctx.forbidden(p)]
    if forbidden:
        return _block(ctx, state, "FROZEN_TREE_TOUCHED",
                      "the candidate changes frozen or immutable paths; that needs a new remediation tranche",
                      forbidden)
    a["candidate"] = head
    a["candidate_parent"] = a["round_base"]
    a["changed"] = changed
    a["diff_stat"] = gitops.diff_stat(ctx.repo, a["milestone_base"], head)
    a["reason"] = None
    st.append_event(ctx.repo, state, {"event": "CANDIDATE_FROZEN", "milestone": a["milestone"],
                                      "round": a["round"], "candidate": head, "parent": a["round_base"]})
    st.set_phase(state, "VALIDATING")
    state["next_action"] = f"validate candidate {head[:12]}"
    return None


def _writer_retry(ctx: Context, state: dict, reason: str):
    a = state["active"]
    a["writer_retries"] += 1
    if a["writer_retries"] > ctx.envelope["max_writer_retries"]:
        return _block(ctx, state, "WRITER_NOT_READY", reason)
    fix = f"FIX-{a['writer_retries']}"
    a["tasks"].append(fix)
    a["task_titles"][fix] = {"title": "Make the writer clean and committed", "acceptance": reason}
    a["reason"] = reason
    st.set_phase(state, "IMPLEMENTING")
    st.append_event(ctx.repo, state, {"event": "WRITER_NOT_READY", "reason": reason, "task": fix})
    state["next_action"] = f"implementer: {fix}"
    return None


def _validate(ctx: Context, state: dict):
    a = state["active"]
    _assert_candidate_head(ctx, state)
    candidate = a["candidate"]
    a["attempts"] += 1
    run_id = f"{a['milestone']}-r{a['round']}-validate-{a['attempts']}"
    run_dir = ctx.state_root / "runs" / run_id
    wt = ctx.wt_root / run_id
    a["inflight"] = {"step": "VALIDATING", "run": run_id, "utc": utc_now()}
    a["runs"].append({"kind": "validation", "run": run_id, "round": a["round"]})
    st.save(ctx.repo, state)
    try:
        gitops.add_worktree_detached(ctx.repo, wt, candidate)
        if gitops.head(wt) != candidate or not gitops.is_clean(wt):
            raise WorkflowError("SHA_MISMATCH", "fresh validation checkout is not the clean candidate")
        m = ctx.milestone(a["milestone"])
        heavy_cfg = ctx.envelope["heavy"]
        results = heavy.run_heavy(
            ctx.common, purpose=f"validate {a['milestone']} r{a['round']} {candidate[:12]}",
            min_available_mib=heavy_cfg["min_available_mib"], wait_seconds=heavy_cfg["wait_seconds"],
            memory_reader=ctx.memory_reader,
            action=lambda: _run_checks(ctx, m, wt, run_dir, candidate))
        if gitops.head(wt) != candidate or not gitops.is_clean(wt):
            raise WorkflowError("SHA_MISMATCH", "the validation checkout changed while the checks ran")
    except WorkflowError:
        a["inflight"] = None   # a refusal is not a crash: nothing is left in flight
        raise
    finally:
        gitops.remove_worktree(ctx.repo, wt)
    manifest_sha = evidence.write_manifest(run_dir, run_id, {"candidate": candidate, "checks": results})
    a["inflight"] = None
    a["deferrals"] = 0
    failing = [r for r in results if r["returncode"] != 0]
    a["validation"] = {"run": run_id, "result": "FAIL" if failing else "PASS", "candidate": candidate,
                       "manifest_sha256": manifest_sha, "checks": [r["id"] for r in results]}
    if failing:
        findings = [{"severity": "BLOCKER", "file": "", "line": None,
                     "summary": f"validation check {r['id']} exited {r['returncode']}",
                     "required_fix": f"make {r['id']} pass on the candidate"} for r in failing]
        return _reject(ctx, state, "VALIDATION_FAILED", findings)
    st.append_event(ctx.repo, state, {"event": "VALIDATION_PASSED", "candidate": candidate, "run": run_id,
                                      "manifest_sha256": manifest_sha})
    _write_skeptic_packet(ctx, state)
    st.set_phase(state, "SKEPTIC_PENDING")
    state["next_action"] = f"skeptic review of {candidate[:12]}"
    return None


def _run_checks(ctx: Context, milestone: dict, wt: Path, run_dir: Path, candidate: str) -> list[dict]:
    run_dir.mkdir(parents=True, exist_ok=True)
    env = ctx.child_env()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPYCACHEPREFIX"] = str(run_dir / "pycache")
    results = []
    for check in milestone["validation"]:
        argv = [sys.executable if part == "python" else part for part in check["argv"]]
        started = time.monotonic()
        code, out, err = heavy.run_in_job(argv, cwd=str(wt), env=env,
                                          timeout=ctx.envelope["heavy"]["timeout_seconds"])
        (run_dir / f"{check['id']}.stdout.txt").write_bytes(out or b"")
        (run_dir / f"{check['id']}.stderr.txt").write_bytes(err or b"")
        results.append({"id": check["id"], "argv": argv, "returncode": code,
                        "seconds": round(time.monotonic() - started, 2), "candidate": candidate})
    return results


def _write_packet(ctx: Context, name: str, text: str) -> Path:
    return Path(_write_text(ctx.state_root / "packets" / name, text))


def _write_implement_packet(ctx: Context, state: dict, remaining: list[str]) -> Path:
    a = state["active"]
    lines = [
        f"# Implementation packet: {a['milestone']} {a['name']} (round {a['round']}, {a['mode']})",
        "",
        f"Writer worktree: {ctx.repo} (branch {ctx.envelope['writer_branch']}). You are the only writer.",
        f"Envelope: {ctx.envelope['envelope_id']}; operating mode {ctx.envelope['operating_mode']}; live_enabled=false.",
        "",
        "Rules (fail-closed; the engine checks them):",
        "- Commit each task in the writer worktree before it is reported done. The Lead then runs task-done.",
        "- Do not touch these trees: " + ", ".join(ctx.envelope["frozen_prefixes"] + ctx.envelope["immutable_prefixes"]) + ".",
        "- Do not create anything under autonomy/approvals/ and do not edit autonomy/state/.",
        "- Do not run heavy validation yourself; the engine runs it under the host lock.",
        "- No credentials, network calls to providers, live order or betting code.",
        "- Make no unrelated changes. Tests you write must be deterministic.",
        "",
        "Tasks to do now, in order:",
    ]
    for t in remaining:
        info = a["task_titles"][t]
        lines += [f"- {t}: {info['title']}", f"  Acceptance: {info['acceptance']}"]
    if a.get("mode") == "REMEDIATION" and a.get("findings_packet"):
        lines += ["", f"Findings to remediate on this child (preserved rejected candidate is in history): "
                      f"{a['findings_packet']}"]
    m = ctx.milestone(a["milestone"])
    lines += ["", "Milestone authority: " + m["authority"]]
    return _write_packet(ctx, f"{a['milestone']}-r{a['round']}-implement.md", "\n".join(lines) + "\n")


def _write_skeptic_packet(ctx: Context, state: dict) -> Path:
    a = state["active"]
    diff = gitops.diff_text(ctx.repo, a["milestone_base"], a["candidate"])
    diff_path = _write_packet(ctx, f"{a['milestone']}-r{a['round']}-candidate.diff", diff)
    lines = [
        f"# Internal skeptic packet: {a['milestone']} round {a['round']}",
        "",
        f"Candidate: {a['candidate']}",
        f"Milestone base: {a['milestone_base']}",
        f"Validation: {a['validation']['result']} (manifest {a['validation']['manifest_sha256'][:16]})",
        f"Full diff (read it with the Read tool): {_rel(ctx, diff_path)}",
        "",
        "Changed files:",
        *[f"- {p}" for p in a["changed"]],
        "",
        "Reply with a single JSON object and nothing else:",
        '{"verdict": "CLEAR" or "FINDINGS", "reviewed_sha": "<candidate>", "summary": "...", '
        '"findings": [{"severity": "BLOCKER|HIGH|MEDIUM|LOW", "file": "...", "line": null, '
        '"summary": "...", "required_fix": "..."}]}',
        "CLEAR means no findings. Use FINDINGS for anything that would have to change.",
    ]
    return _write_packet(ctx, f"{a['milestone']}-r{a['round']}-skeptic.md", "\n".join(lines) + "\n")


def _skeptic_action(ctx: Context, state: dict):
    _assert_candidate_head(ctx, state)
    a = state["active"]
    packet = ctx.state_root / "packets" / f"{a['milestone']}-r{a['round']}-skeptic.md"
    state["next_action"] = f"skeptic: record its JSON with record-skeptic ({a['candidate'][:12]})"
    return _action(ctx, state, {"action": "SKEPTIC", "milestone": a["milestone"], "round": a["round"],
                                "candidate": a["candidate"], "packet": _rel(ctx, packet),
                                "reply_file": _rel(ctx, ctx.state_root / "packets" /
                                                   f"{a['milestone']}-r{a['round']}-skeptic-reply.json")})


def record_skeptic(ctx: Context, reply_path) -> dict:
    with _lock(ctx):
        state = _open(ctx, mutate=True)
        _recover(ctx, state)
        if state["phase"] != "SKEPTIC_PENDING":
            raise WorkflowError("NOT_SKEPTIC_STEP", f"phase is {state['phase']}")
        a = state["active"]
        _assert_writer(ctx, state)
        _assert_candidate_head(ctx, state)
        raw = Path(reply_path).read_bytes()
        try:
            doc = json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise WorkflowError("SKEPTIC_MALFORMED", f"reply is not JSON: {exc}") from exc
        if not isinstance(doc, dict) or set(doc) != SKEPTIC_KEYS:
            raise WorkflowError("SKEPTIC_MALFORMED", "reply must have exactly verdict, reviewed_sha, summary, findings")
        if doc["verdict"] not in SKEPTIC_VERDICTS:
            raise WorkflowError("SKEPTIC_MALFORMED", f"unknown verdict {doc['verdict']!r}")
        if doc["reviewed_sha"] != a["candidate"]:
            raise WorkflowError("SKEPTIC_WRONG_SHA", f"reviewed {doc['reviewed_sha']}, candidate is {a['candidate']}")
        findings = doc["findings"]
        if not isinstance(findings, list) or any(not isinstance(f, dict) or set(f) != review.FINDING_KEYS
                                                 for f in findings):
            raise WorkflowError("SKEPTIC_MALFORMED", "findings are malformed")
        if doc["verdict"] == "CLEAR" and findings:
            raise WorkflowError("SKEPTIC_MALFORMED", "CLEAR cannot carry findings")
        if doc["verdict"] == "FINDINGS" and not findings:
            raise WorkflowError("SKEPTIC_MALFORMED", "FINDINGS must list them")
        run_id = f"{a['milestone']}-r{a['round']}-skeptic-{a['attempts'] + 1}"
        a["attempts"] += 1
        run_dir = ctx.state_root / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "skeptic.json").write_bytes(raw)
        a["runs"].append({"kind": "skeptic", "run": run_id, "round": a["round"]})
        a["skeptic"] = {"run": run_id, "verdict": doc["verdict"], "reviewed_sha": a["candidate"],
                        "sha256": st.sha256_bytes(raw)}
        st.append_event(ctx.repo, state, {"event": "SKEPTIC_RECORDED", "verdict": doc["verdict"],
                                          "candidate": a["candidate"]})
        if doc["verdict"] == "CLEAR":
            st.set_phase(state, "CODEX_REVIEWING")
            state["next_action"] = f"independent review of {a['candidate'][:12]}"
            st.save(ctx.repo, state)
            return {"status": "RECORDED", "skeptic": "CLEAR", "candidate": a["candidate"]}
        _reject(ctx, state, "SKEPTIC_FINDINGS", findings)
        st.save(ctx.repo, state)
        return {"status": "RECORDED", "skeptic": "FINDINGS", "candidate": a["candidate"],
                "phase": state["phase"]}


def _codex(ctx: Context, state: dict):
    a = state["active"]
    cand = a["candidate"]
    _assert_writer(ctx, state)
    _assert_candidate_head(ctx, state)
    if not gitops.is_clean(ctx.repo):
        raise WorkflowError("WRITER_DIRTY", "the writer changed after validation")
    verify_validation(ctx, a)
    if not a["skeptic"] or a["skeptic"]["verdict"] != "CLEAR" or a["skeptic"]["reviewed_sha"] != cand:
        raise WorkflowError("SKEPTIC_MISSING", "no CLEAR skeptic record for this candidate")
    cfg = ctx.envelope["codex"]
    command = review.resolve_command(ctx.codex_command)
    env = ctx.child_env()
    review.preflight(cfg, command, env)
    a["attempts"] += 1
    run_id = f"{a['milestone']}-r{a['round']}-codex-{a['attempts']}"
    run_dir = ctx.state_root / "runs" / run_id
    wt = ctx.wt_root / run_id
    a["inflight"] = {"step": "CODEX_REVIEWING", "run": run_id, "utc": utc_now()}
    a["runs"].append({"kind": "codex", "run": run_id, "round": a["round"]})
    st.save(ctx.repo, state)
    try:
        gitops.add_worktree_detached(ctx.repo, wt, cand)
        if gitops.head(wt) != cand:
            raise WorkflowError("SHA_MISMATCH", "reviewer checkout is not at the candidate")
        packet = _review_packet(ctx, state)
        verdict, last_error = None, None
        for n in range(1 + cfg["retries"]):
            try:
                verdict = review.review(cfg, command, env, candidate_sha=cand, worktree=wt, packet_text=packet,
                                        run_dir=run_dir / f"try-{n + 1}", schema_path=ctx.schema_path)
                break
            except WorkflowError as exc:
                if exc.code not in ("REVIEW_INVALID", "REVIEW_TIMEOUT"):
                    raise
                last_error = exc
        if verdict is None:
            raise last_error
        if gitops.head(wt) != cand:
            raise WorkflowError("SHA_MISMATCH", "the reviewer changed its checkout")
    except WorkflowError:
        a["inflight"] = None
        raise
    finally:
        gitops.remove_worktree(ctx.repo, wt)
    a["inflight"] = None
    (run_dir / "verdict.json").write_bytes((json.dumps(verdict, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    a["review"] = {"run": run_id, "verdict": verdict["verdict"], "reviewed_sha": cand, "sha256": verdict["sha256"]}
    st.append_event(ctx.repo, state, {"event": "CODEX_VERDICT", "verdict": verdict["verdict"], "candidate": cand})
    if verdict["verdict"] == "PASS":
        st.set_phase(state, "ADVANCING")
        state["next_action"] = f"record milestone {a['milestone']}"
        return None
    return _reject(ctx, state, "CODEX_REMEDIATION_REQUIRED", verdict["findings"])


def _review_packet(ctx: Context, state: dict) -> str:
    a = state["active"]
    diff_stat = a["diff_stat"]
    tasks = "\n".join(f"- {t}: {info['title']} | acceptance: {info['acceptance']}"
                      for t, info in a["task_titles"].items() if t in a["done"] or t in a["tasks"])
    return "\n".join([
        f"# Independent cross-vendor review: {a['milestone']} {a['name']} (round {a['round']})",
        "",
        "You are the independent reviewer for Project Genesis. You run read-only; do not modify any file.",
        f"Candidate commit (review exactly this): {a['candidate']}",
        f"Candidate parent: {a['candidate_parent']}",
        f"Milestone base: {a['milestone_base']}",
        f"Inspect with git: git show --stat {a['candidate'][:12]}; git diff {a['milestone_base'][:12]} {a['candidate'][:12]}",
        "",
        "Read first: v04_pack/Genesis_v0.4_Implementation_Pack/03_PROJECT_LAWS_v0.4.md, autonomy/ENVELOPE.json,",
        "PROJECT_STATE.md (safe next step). Judge: correctness, fail-closed behaviour, PIT causality, immutable",
        "evidence, frozen-tree rules, the paper-only envelope (no live, provider, credential or betting activation),",
        "and whether the tests prove the claims. Do not re-open findings already closed with evidence.",
        "",
        "Tasks and acceptance:",
        tasks,
        "",
        f"Validation: {a['validation']['result']} for this candidate, manifest {a['validation']['manifest_sha256']}",
        f"Skeptic (internal, Claude): {a['skeptic']['verdict']} for this candidate",
        "",
        "Diff stat:",
        diff_stat,
        "",
        "Output: the JSON object required by the output schema only. verdict PASS only if there are no BLOCKER",
        "or HIGH findings; otherwise REMEDIATION_REQUIRED with every finding giving file, line, summary and",
        f"required_fix. reviewed_sha must be exactly {a['candidate']}.",
    ]) + "\n"


def verify_validation(ctx: Context, a: dict) -> None:
    v = a.get("validation")
    if not v or v["result"] != "PASS" or v["candidate"] != a["candidate"]:
        raise WorkflowError("VALIDATION_MISSING", "no PASS validation recorded for this candidate")
    run_dir = ctx.state_root / "runs" / v["run"]
    evidence.verify_manifest(run_dir, v["manifest_sha256"])


def _reject(ctx: Context, state: dict, kind: str, findings: list) -> dict | None:
    """Preserve the rejected candidate in history, then start a remediation child from the preserved head."""
    if kind not in REJECTION_KINDS:
        raise WorkflowError("MALFORMED_TRANSITION", f"unknown rejection kind {kind}")
    a = state["active"]
    mid, rnd, cand = a["milestone"], a["round"], a["candidate"]
    rel = f"autonomy/records/{mid}/rejected-r{rnd}-{cand[:12]}"
    dest = ctx.repo / rel
    dest.mkdir(parents=True, exist_ok=True)
    for run in a["runs"]:
        if run["round"] == rnd:
            src = ctx.state_root / "runs" / run["run"]
            if src.exists():
                shutil.copytree(src, dest / "evidence" / run["run"], ignore=shutil.ignore_patterns("pycache"))
    record = {"milestone": mid, "round": rnd, "candidate": cand, "candidate_parent": a["candidate_parent"],
              "kind": kind, "findings": findings, "utc": utc_now()}
    (dest / "REJECTION.json").write_bytes((json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    evidence.write_manifest(dest, f"rejected r{rnd} {cand}")
    record_commit = gitops.commit_paths(ctx.repo, [rel], f"autonomy({mid}): preserve rejected candidate {cand} "
                                                         f"(round {rnd}, {kind})\n\n{COAUTHOR}")
    a["rejected"].append({"round": rnd, "candidate": cand, "kind": kind, "record_commit": record_commit,
                          "record": rel})
    st.append_event(ctx.repo, state, {"event": "REJECTED", "milestone": mid, "round": rnd, "candidate": cand,
                                      "kind": kind, "record_commit": record_commit})
    if rnd >= 1 + ctx.envelope["max_remediation_rounds"]:
        return _block(ctx, state, "ATTEMPT_LIMIT", f"{mid} was rejected {rnd} times; operator review needed",
                      {"rejected": [r["candidate"] for r in a["rejected"]]})
    head = gitops.head(ctx.repo)
    findings_path = _write_packet(ctx, f"{mid}-r{rnd + 1}-findings.md", _findings_text(kind, findings))
    a.update({"round": rnd + 1, "mode": "REMEDIATION", "tasks": [f"R{rnd + 1}"], "done": [],
              "round_base": head, "last_head": head, "candidate": None, "candidate_parent": None,
              "changed": [], "diff_stat": "", "validation": None, "skeptic": None, "review": None,
              "findings": findings, "findings_packet": _rel(ctx, findings_path), "reason": None,
              "writer_retries": 0})
    a["task_titles"] = {f"R{rnd + 1}": {"title": f"Remediate round {rnd} findings",
                                       "acceptance": f"every finding in {_rel(ctx, findings_path)} is fixed and the "
                                                     f"validation and reviews pass again"}}
    st.set_phase(state, "IMPLEMENTING")
    state["next_action"] = f"implementer: remediation R{rnd + 1} of {mid}"
    return None


def _findings_text(kind: str, findings: list) -> str:
    lines = [f"# Findings that rejected the previous candidate ({kind})", ""]
    for f in findings:
        lines.append(f"- [{f.get('severity', 'BLOCKER')}] {f.get('file', '')}:{f.get('line', '')} "
                     f"{f.get('summary', '')}\n  required fix: {f.get('required_fix', '')}")
    return "\n".join(lines) + "\n"


def _advance(ctx: Context, state: dict):
    a = state["active"]
    mid, cand = a["milestone"], a["candidate"]
    _assert_writer(ctx, state)
    _assert_candidate_head(ctx, state)
    verify_validation(ctx, a)
    rel = f"autonomy/records/{mid}"
    dest = ctx.repo / rel
    dest.mkdir(parents=True, exist_ok=True)
    for run in a["runs"]:
        src = ctx.state_root / "runs" / run["run"]
        if src.exists():
            shutil.copytree(src, dest / "evidence" / run["run"], ignore=shutil.ignore_patterns("pycache"))
    record = {"milestone": mid, "name": a["name"], "result": "PASS", "candidate": cand,
              "candidate_parent": a["candidate_parent"], "milestone_base": a["milestone_base"],
              "rounds": a["round"], "rejected": a["rejected"], "changed": a["changed"],
              "diff_stat": a["diff_stat"], "validation": a["validation"], "skeptic": a["skeptic"],
              "review": a["review"], "utc": utc_now()}
    (dest / "MILESTONE.json").write_bytes((json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    evidence.write_manifest(dest, f"milestone {mid} PASS")
    record_commit = gitops.commit_paths(ctx.repo, [rel], f"autonomy({mid}): record PASS for candidate {cand}\n\n"
                                                         f"{COAUTHOR}")
    state["milestones"][mid] = {"status": "PASSED", "candidate": cand, "record_commit": record_commit}
    state["completed"].append({"milestone": mid, "candidate": cand, "record_commit": record_commit,
                               "rounds": a["round"]})
    state["active"] = None
    st.append_event(ctx.repo, state, {"event": "MILESTONE_PASSED", "milestone": mid, "candidate": cand,
                                      "record_commit": record_commit})
    st.set_phase(state, "IDLE")
    state["next_action"] = "select next milestone"
    return None


def task_done(ctx: Context, task_id: str) -> dict:
    with _lock(ctx):
        state = _open(ctx, mutate=True)
        _recover(ctx, state)
        if state["phase"] != "IMPLEMENTING":
            raise WorkflowError("NOT_IMPLEMENTING", f"phase is {state['phase']}")
        a = state["active"]
        remaining = [t for t in a["tasks"] if t not in a["done"]]
        if not remaining or remaining[0] != task_id:
            raise WorkflowError("TASK_ORDER", f"the next task is {remaining[0] if remaining else 'none'}")
        _assert_writer(ctx, state)
        if not gitops.is_clean(ctx.repo):
            raise WorkflowError("WRITER_DIRTY", "commit or revert the working tree before reporting a task done")
        head = gitops.head(ctx.repo)
        if head == a["last_head"]:
            if not task_id.startswith("FIX-"):
                raise WorkflowError("NO_NEW_COMMIT", f"{task_id} needs a new commit in the writer")
        elif not gitops.is_ancestor(ctx.repo, a["last_head"], head):
            raise WorkflowError("HEAD_REWOUND", "the writer HEAD does not descend from the last recorded task")
        a["done"].append(task_id)
        a["last_head"] = head
        st.append_event(ctx.repo, state, {"event": "TASK_DONE", "milestone": a["milestone"], "task": task_id,
                                          "head": head})
        st.save(ctx.repo, state)
        return {"status": "RECORDED", "task": task_id, "head": head,
                "remaining": [t for t in a["tasks"] if t not in a["done"]]}


def pause(ctx: Context, reason: str) -> dict:
    flag = ctx.state_root / "PAUSE_REQUESTED"
    ctx.state_root.mkdir(parents=True, exist_ok=True)
    flag.write_text(reason + "\n", encoding="utf-8")
    try:
        with _lock(ctx):
            state = _open(ctx, mutate=True)
            _recover(ctx, state)
            st.halt(ctx.repo, state, "PAUSED", f"operator pause: {reason}")
            st.save(ctx.repo, state)
            return {"status": "PAUSED", "phase": state["phase"]}
    except WorkflowError as exc:
        if exc.code != "ENGINE_BUSY":
            raise
        return {"status": "PAUSE_REQUESTED", "detail": "a go is running; it will stop at its next safe point"}


def resume(ctx: Context, *, clear_block: bool) -> dict:
    with _lock(ctx):
        state = _open(ctx, mutate=True)
        _recover(ctx, state)
        resumed = st.unhalt(ctx.repo, state, clear_block=clear_block)
        flag = ctx.state_root / "PAUSE_REQUESTED"
        if flag.exists():
            flag.unlink()
        st.save(ctx.repo, state)
        return {"status": "RESUMED", "phase": resumed}


def explain_gate(ctx: Context) -> dict:
    state = _open(ctx, mutate=False)
    gates = roadmap.pending_gates(ctx.roadmap_doc, state["milestones"], ctx.repo)
    current = state.get("human_gate") if state["phase"] == "HUMAN_GATE" else None
    return {"phase": state["phase"], "current_gate": current, "pending_gates": gates,
            "how_to_clear": "A human operator writes autonomy/approvals/<gate_id>.json with gate_id, "
                            "approved_by='human-operator' and an approval_reference (ADR, PR or message link), "
                            "commits it, then runs go. Agents must never create this file."}


def codex_preflight(ctx: Context, *, probe_call: bool) -> dict:
    cfg = ctx.envelope["codex"]
    command = review.resolve_command(ctx.codex_command)
    env = ctx.child_env()
    result = {"preflight": review.preflight(cfg, command, env)}
    if probe_call:
        result["probe"] = review.probe(cfg, command, env, ctx.state_root / "probe")
    return result


def verify(ctx: Context) -> dict:
    """Read-only integrity check: state digest, ledger chain, active evidence and every committed record."""
    state = _open(ctx, mutate=False)
    checked = []
    active = state.get("active") or {}
    if active.get("validation"):
        verify_validation(ctx, active)
        checked.append(active["validation"]["run"])
    records_root = ctx.repo / "autonomy" / "records"
    if records_root.exists():
        for rec in sorted(records_root.iterdir()):
            if rec.is_dir() and (rec / evidence.MANIFEST).exists():
                evidence.verify_manifest(rec)
                checked.append(rec.relative_to(ctx.repo).as_posix())
    return {"status": "VERIFIED", "ledger_length": state["ledger_length"], "checked": checked,
            "state_digest": state["state_digest"], "recovered_torn_writes": state["recovered_torn_writes"]}
