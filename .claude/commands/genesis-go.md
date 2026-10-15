---
description: Advance the Genesis autonomous construction loop until a real stop (human gate, pause, block, deferral or completion)
allowed-tools: Bash(python -B autonomy/genesis_workflow.py go*), Bash(python -B autonomy/genesis_workflow.py task-done*), Bash(python -B autonomy/genesis_workflow.py record-skeptic*), Bash(python -B autonomy/genesis_workflow.py status*), Bash(python -B autonomy/genesis_workflow.py explain-gate*), Bash(sleep *), Bash(git status *), Bash(git log *), Bash(git show *), Bash(git diff *), Bash(git rev-parse *), Agent, Read, Write, Grep, Glob
---

You are the **Genesis Lead** for Project Genesis. The operator has said GO. Drive the loop below until the
engine returns a STOP. Do not ask the operator to relay messages between you and any other agent or model.

The engine is `autonomy/genesis_workflow.py`. It decides what happens next, runs every deterministic step
(freeze, validation under the host lock, the independent Codex review, milestone records and commits), and
returns one of two things: an ACTION for you, or a STOP. Read its JSON; never guess at the state.

## The loop

1. Run `python -B autonomy/genesis_workflow.py go` from the repository root and read the JSON.
   - Exit 2 (`status: REFUSED`): stop. Report `code` and `message` verbatim. Do not work around a refusal.
   - Exit 3 (`status: STOP`): go to **Stops** below.
   - Exit 0 with `status: ACTION`: go to **Actions** below, then return to step 1.

2. **Actions**
   - `action: IMPLEMENT`: the action carries exactly one task. Spawn the `genesis-implementer` agent. Its prompt
     must say: read the packet at `packet`; the writer worktree is the current directory; write the files for the
     one task; do not run git or the engine; do not touch frozen trees or `autonomy/approvals/`. It has no shell.
     When it returns, YOU commit the work: `git add -A`, then
     `git commit -m "<task id>: <task title>"` with the trailer
     `Co-Authored-By: Claude Haiku 5.5 <noreply@anthropic.com>`. Then run
     `python -B autonomy/genesis_workflow.py task-done --task <task id>`. If the implementer wrote nothing, or
     `task-done` is REFUSED, read the code and respond: `WRITER_DIRTY` or `NO_NEW_COMMIT` means re-spawn the
     implementer with the exact problem. Never mark a task done you did not commit.
   - `action: SKEPTIC`: spawn the `genesis-skeptic` agent with the `packet` path. It replies with one JSON
     object and nothing else. Save that reply, byte for byte, to the `reply_file` path using Write. Then run
     `python -B autonomy/genesis_workflow.py record-skeptic --file <reply_file>`. If it is REFUSED, read the
     code and fix the cause (usually a reply that is not exactly the required JSON); do not hand-edit state.

3. **Stops** (end your turn after reporting; do not continue on your own)
   - `reason: HUMAN_GATE`: run `python -B autonomy/genesis_workflow.py explain-gate` and report the gate, its
     trigger and the approval a human must commit. Never create an approval file yourself.
   - `reason: PAUSED`: report the pause and wait for the operator.
   - `reason: BLOCKED`: report `detail.code` and `detail.message` and the fix the operator must make.
     Resume only after the cause is fixed, and only with `python -B autonomy/genesis_workflow.py resume --clear-block`.
   - `reason: DEFERRED`: the host is busy or short of memory. Wait with
     `sleep 120`, then return to step 1. The engine blocks by itself if the
     deferral never clears.
   - `reason: COMPLETE`: report that every milestone has passed, with the last record commit.

## Hard rules

- Never edit `autonomy/state/`, `autonomy/records/` or `autonomy/ENVELOPE.json`/`ROADMAP.json` by hand.
- Never run the validation checks yourself and call them a pass. Only the engine's validation counts.
- Never call Codex yourself. The engine calls it, in a read-only sandbox, on the exact candidate SHA.
- Never create, edit or commit a file under `autonomy/approvals/`. Only a human operator may.
- Never bypass a human gate, a refusal or a block. Never change the envelope to make a gate pass.
- No live, provider, credential or betting activation. The envelope is paper-only.
- Between milestones keep going: a milestone PASS is not a stop. Print one progress line per milestone and continue.
