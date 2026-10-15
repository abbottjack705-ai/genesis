#!/usr/bin/env python3
"""Genesis autonomous construction workflow: command-line entry point.

Run from the writer worktree root:   python -B autonomy/genesis_workflow.py <command>

Every command prints one JSON object. Exit codes:
  0  ok, or an ACTION the Lead must perform next
  2  refused (fail closed); "code" says why and nothing was changed
  3  STOP: human gate, pause, block, deferral or completion; "reason" says which

The Genesis Lead (the Claude Code session running /genesis-go) drives this; see autonomy/README.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from genesis_autonomy import engine  # noqa: E402
from genesis_autonomy.state import WorkflowError  # noqa: E402

DEFAULT_PRODUCT_SHA = "2e8290ea7a8a26d4796de893036c12a0d05b7b2b"
DEFAULT_EVIDENCE_SHA = "70aa74f0b2de354307d838580c2f13096e466fc0"


def _emit(doc: dict, code: int) -> int:
    print(json.dumps(doc, indent=2, sort_keys=True, default=str))
    return code


def _context(args) -> engine.Context:
    repo = Path(__file__).resolve().parent.parent
    return engine.Context(repo)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="genesis_workflow", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="create the workflow state (once)")
    init.add_argument("--product-sha", default=DEFAULT_PRODUCT_SHA)
    init.add_argument("--evidence-sha", default=DEFAULT_EVIDENCE_SHA)
    sub.add_parser("status", help="show the resumable state")
    go = sub.add_parser("go", help="advance until an ACTION or a STOP")
    go.add_argument("--select-only", action="store_true", help="show the milestone go would start, changing nothing")
    done = sub.add_parser("task-done", help="record that the Lead saw the implementer commit a task")
    done.add_argument("--task", required=True)
    skeptic = sub.add_parser("record-skeptic", help="record the internal skeptic's JSON reply")
    skeptic.add_argument("--file", required=True)
    pause = sub.add_parser("pause", help="stop at the next safe point")
    pause.add_argument("--reason", required=True)
    resume = sub.add_parser("resume", help="continue after a pause or a fixed block")
    resume.add_argument("--clear-block", action="store_true", help="required to resume a BLOCKED state")
    sub.add_parser("explain-gate", help="explain the current or next human gate")
    pre = sub.add_parser("codex-preflight", help="check Codex billing and login; --probe makes one harmless call")
    pre.add_argument("--probe", action="store_true")
    sub.add_parser("verify", help="read-only integrity check of state, ledger and evidence")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        ctx = _context(args)
        if args.command == "init":
            return _emit(engine.init(ctx, product_sha=args.product_sha, evidence_sha=args.evidence_sha), 0)
        if args.command == "status":
            return _emit(engine.status(ctx), 0)
        if args.command == "go":
            if args.select_only:
                return _emit(engine.select_only(ctx), 0)
            result = engine.go(ctx)
            return _emit(result, 0 if result["status"] == "ACTION" else 3)
        if args.command == "task-done":
            return _emit(engine.task_done(ctx, args.task), 0)
        if args.command == "record-skeptic":
            result = engine.record_skeptic(ctx, args.file)
            return _emit(result, 0)
        if args.command == "pause":
            return _emit(engine.pause(ctx, args.reason), 0)
        if args.command == "resume":
            return _emit(engine.resume(ctx, clear_block=args.clear_block), 0)
        if args.command == "explain-gate":
            return _emit(engine.explain_gate(ctx), 0)
        if args.command == "codex-preflight":
            return _emit(engine.codex_preflight(ctx, probe_call=args.probe), 0)
        if args.command == "verify":
            return _emit(engine.verify(ctx), 0)
    except WorkflowError as exc:
        return _emit({"status": "REFUSED", "code": exc.code, "message": exc.message}, 2)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
