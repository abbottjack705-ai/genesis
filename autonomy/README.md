# Genesis autonomous construction workflow

Paper-only, offline construction of Project Genesis, driven from Claude Code. The operator says GO once; the
workflow selects the next authorised milestone, has agents build it, validates it, has it reviewed by an
independent cross-vendor reviewer (Codex), records the result, and moves on. It stops only at a real checkpoint.

Live, provider, credential and betting activation are **not authorised**. The envelope is paper-only and the
roadmap puts every activation behind a human gate.

## Operator entry points

| You type | What it does |
|---|---|
| `/genesis-go` | Runs the loop until a STOP: human gate, pause, fail-closed block, deferral, or completion |
| `/genesis-status` | Shows the resumable state and the milestone GO would start. Changes nothing |
| `/genesis-pause <reason>` | Stops at the next safe point. Changes no code or evidence |
| `/genesis-explain-current-gate` | Explains the current or next human gate and what a human must commit to clear it |

Start Claude Code in this repository's writer worktree (`C:\Users\abbot\fz\autonomous-build`, branch
`autonomous-build`) so the project commands and agents load. Plain CLI forms, for scripts and debugging:

    python -B autonomy/genesis_workflow.py status
    python -B autonomy/genesis_workflow.py go --select-only
    python -B autonomy/genesis_workflow.py go
    python -B autonomy/genesis_workflow.py explain-gate
    python -B autonomy/genesis_workflow.py pause --reason "..."
    python -B autonomy/genesis_workflow.py resume [--clear-block]
    python -B autonomy/genesis_workflow.py codex-preflight [--probe]
    python -B autonomy/genesis_workflow.py verify

Exit codes: 0 ok or ACTION, 2 refused (fail closed, nothing changed), 3 STOP.

## Roles

| Role | Who | Tools / rights |
|---|---|---|
| Genesis Lead | the Claude Code session running `/genesis-go` | drives the loop; spawns the agents below; never certifies |
| Implementation Agent | `genesis-implementer` subagent | the only writer of content; writes files for one task; **no shell** (it cannot commit, run git or call the engine) |
| Architecture and Research | `genesis-architect` subagent | read-only reasoning and source checks |
| Test and Evidence | `genesis-evidence` subagent | read-only provenance and manifest checks |
| Internal Skeptic | `genesis-skeptic` subagent | read-only adversarial review; replies with one JSON object |
| Integration and State | `autonomy/genesis_workflow.py` (the engine) | deterministic; owns state, ledger, records, commits |
| Independent Codex reviewer | `codex exec`, invoked by the engine | read-only sandbox, own detached checkout at the candidate SHA |

The engine, not an agent, decides transitions. An agent's report is an input the engine checks; it is never
the verdict.

## One milestone, end to end

    IDLE -> IMPLEMENTING (Implementation Agent, per task, task-done after each commit)
         -> FREEZING     candidate = writer HEAD; writer must be clean; no frozen or immutable path changed
         -> VALIDATING   fresh detached checkout of the candidate; checks run under the host heavy lock,
                         each in a kill-on-close Job Object; MANIFEST.json over every output
         -> SKEPTIC_PENDING   Internal Skeptic reply recorded; it must name the candidate SHA
         -> CODEX_REVIEWING   Codex on its own checkout at the candidate SHA; verdict must name that SHA
         -> ADVANCING    milestone record copied and committed under autonomy/records/<milestone>/
         -> IDLE         next milestone, with no operator round trip

A rejection at any review step (validation failure, skeptic findings, REMEDIATION_REQUIRED) does not overwrite
anything. The rejected candidate's evidence is copied to `autonomy/records/<milestone>/rejected-r<n>-<sha>/` and
committed, the writer moves on from that commit, and the remediation becomes a new child commit with a new SHA
that must pass every step again. The rejected candidate stays reachable in history.

## Where state lives

- `autonomy/state/` (git-ignored, per worktree): `state.json` (resumable; `state_digest` covers every other
  field), `ledger.jsonl` (hash-chained, append-only), `STATE.md` (human-readable view), `runs/` (validation,
  skeptic and review evidence), `packets/` (what each agent was handed), `engine.lock`.
- `autonomy/records/` (committed): milestone records and preserved rejected candidates, each with a SHA-256
  manifest. These are the durable evidence.
- `autonomy/ENVELOPE.json` (policy), `autonomy/ROADMAP.json` (milestones, tasks, gates, validation),
  `autonomy/approvals/` (human gate approvals; see its README).

If state, ledger, evidence or config changes outside the engine, the next command refuses: `STATE_DIGEST_MISMATCH`,
`LEDGER_TAMPERED`, `EVIDENCE_MISMATCH`, `CONFIG_CHANGED`. Interruption is safe: a crashed run is recorded as
`INTERRUPTED` and its step runs again from a fresh checkout. A single unrecorded ledger entry (a crash between
the append and the save) is adopted once and counted; two or more are refused.

## Fail-closed rules (enforced in code, tested)

- Writer must be the writer worktree on the writer branch; the engine refuses from anywhere else.
- Candidate must be clean and committed; a dirty writer becomes a FIX task, never a silent freeze.
- Any change under `src/ tests/ config/ tools/ DECISIONS/ v04_pack/` (frozen, `PROJECT_STATE.md`) or
  `independent_certifications/ remediation_evidence/ adapters/evidence/` (immutable) blocks the milestone.
- Validation, skeptic and review must all name the exact candidate SHA. Any other SHA is refused.
- Codex verdict: `PASS` only with no BLOCKER or HIGH finding; malformed output is refused, never guessed.
- Codex runs only under the existing ChatGPT subscription login. `OPENAI_API_KEY` or `CODEX_API_KEY` in the
  environment is a refusal (`BILLING_GUARD`). The reviewer runs with `--ignore-user-config --ignore-rules
  --ephemeral --sandbox read-only`.
- The reviewer's packet carries the full diff inline, so its judgement does not depend on shell reads. A diff over
  400 KB fails closed (`REVIEW_PACKET_TOO_LARGE`) rather than being cut short.
- A review that is not complete (`review_complete: false`, for example when the sandbox refuses reads) blocks the
  milestone (`REVIEW_INCOMPLETE`). It is never recorded as a code finding and never sent back for remediation.
- `init` stores exact commits: a moving reference such as `HEAD~1` is resolved before it is recorded.
- Heavy validation: one per host at a time (OS byte-range lock in the shared git directory). Below
  `min_available_mib` free memory it defers; after `max_deferrals` deferrals it blocks. A crashed run's
  checks are killed by their Job Object, so nothing keeps running after its engine is gone.
- A gated milestone does not stop unrelated paper-only work; it stops the loop only when nothing else can run.
- Attempt limit: `max_remediation_rounds`. Beyond it the milestone blocks for operator review.

- Governance is not a candidate's to change: the engine, CLI, envelope, roadmap, tests, approvals, Claude commands,
  agents and settings (`GOVERNANCE_PREFIXES` in `engine.py`). A candidate that touches them is blocked. Changing
  them is a human-governed commit made between milestones, while the state is IDLE.
- Frozen-tree checks use `git diff --no-renames`, so moving a frozen file out of its tree cannot hide behind its
  new name. Path matching is case-folded, because the host filesystem is case-insensitive.
- Every review step checks that the writer HEAD still equals the frozen candidate. A commit that lands after freeze
  makes the review stale and blocks the milestone (`CANDIDATE_MOVED`).

## Human gates

Gates are listed in `ENVELOPE.json` (`human_gate_triggers`) and attached to roadmap milestones (`human_gate`).
A gate is cleared only by a human committing `autonomy/approvals/<gate_id>.json` with `approved_by:
"human-operator"` and an `approval_reference`. Agents must never write that file. The engine accepts an approval
only when HEAD holds it (`git diff --quiet HEAD`, so line endings are judged as git judges them); a present but
uncommitted approval is refused (`APPROVAL_UNCOMMITTED`). Shape is checked; authorship is not (see residuals).

## Permissions (headless and interactive)

- Only the Lead (the session running `/genesis-go`) has a shell that can reach the engine or git commits. The
  implementer, skeptic, architect and evidence agents have no Bash, so they cannot record their own reviews or
  commit as the engine. That is the role separation the permission layer enforces.
- `.claude/settings.json` allows the Lead's engine commands (`go`, `task-done`, `record-skeptic`), read-only
  status commands, `git add` and `git commit`, and listing. It denies `resume` and `init` (run `resume
  --clear-block` yourself, in a terminal), push, reset, clean, checkout, stash, worktree, branch, tag and config
  operations, and removal.
- Permissions granted by a command's `allowed-tools` were observed to lapse after a subagent returns in headless
  runs. The project allowlist therefore carries the Lead's commands, and the subagents' missing shell is what
  keeps them away from those commands.
- Claude Code permission rules match command text. The engine's checks (candidate HEAD, frozen and governance
  paths, committed approvals, independent review on the exact SHA) hold regardless of the permission layer.
- Writing files needs an edit mode. Run unattended with `claude --permission-mode acceptEdits`; in the default
  mode edits from subagents are refused in headless runs.

## Resource policy

- One heavy validation per host at a time, across worktrees and Claude sessions.
- Validation runs each shard in a fresh process. The adapter monolithic full-suite run is not used as evidence,
  because it exceeds this host's memory. `shard_tests.py` gives deterministic shards with exact coverage
  reconciliation (every inventoried test runs exactly once, only expected skips are allowed) and labels every
  result `SHARDED`, never `MONOLITHIC`.
- Claude Code's own settings are not modified. This version (2.1.301) exposes no memory-pressure setting in
  `claude --help`, so none is claimed. The workflow adds its own gate on top.

## Verified in the setup dry run

See `autonomy/records/SETUP/` for the transcript and its manifest. Scenarios (`autonomy/tests/test_dryrun.py`,
`test_units.py`) run real git, the real engine, the real host locks and Job Objects, with scripted roles and a
Codex double that honours the real `codex exec` argv contract. The live Codex CLI was exercised separately with
one harmless call (`codex-preflight --probe`).

## Residuals (recorded, not hidden)

1. **Human-gate authorship is procedural.** The engine checks the approval file's shape, not who committed it.
   Enforcement is the operator's rule that agents never write approvals. Git signing would close this; not done.
2. **Monolithic adapter run is not observed.** Accepted residual: `MONOLITHIC RUN NOT OBSERVED - HOST MEMORY
   LIMITATION`. Adapter coverage uses `shard_tests.py`, and every result says SHARDED.
3. **Host memory is currently tight.** At setup time free memory was about 1.0 GiB of 7.86 GiB at 87% load, below
   the 1536 MiB gate. Heavy validation defers until memory is freed; the workflow does not close applications.
4. **Process containment is Windows-specific.** Validation children are placed in kill-on-close Job Objects on
   Windows. On other platforms only the direct child is killed on timeout.
5. **Pre-existing source not found.** The setup brief refers to a "monolithic adapter-run memory limitation" residual.
   It was not found by wording in any ref, memory note or adapter record. This workflow records the limitation as
   stated in the brief; the source reference should be supplied by the operator.
6. **Engine commits carry a co-author trailer** (`Co-Authored-By: Claude Haiku 5.5`) on record and rejection commits.
7. **Push is manual.** The workflow commits to `autonomous-build` locally and never pushes.
8. **Codex sandbox on this host (operator decision).** In the end-to-end run the read-only Codex sandbox refused
   file reads ("execution policy blocked read-only access"). Windows reports the PowerShell execution policy as
   `Undefined` in every scope (effectively Restricted). The workflow now judges from the inline diff and blocks,
   rather than guessing, when a review cannot complete. Changing the execution policy is a host security setting;
   it is the operator's call, not the workflow's. Until it is decided, reviews that need file reads will block.
9. **Skeptic and review findings have no residual route.** A finding is fixed or the milestone blocks. A route to
   accept a documented residual needs a human-governed approval design; it does not exist yet.
10. **Roadmap validations must be exact.** A substring check (for example `'GOOD' in text`) accepts `NOTGOOD`.
    The roadmap's own checks are authored by humans between milestones; the skeptic flags weak ones.
