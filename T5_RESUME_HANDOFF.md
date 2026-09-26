# T5 resume handoff — Project Genesis V0.4

Written 2026-09-26 by Claude Code (Opus 4.8), for a fresh Opus 5.5 Ultracode
session. This document describes **in-progress, uncommitted T5 remediation
work**. T5 is **not complete, not green overall, not audited, and not
adapter/production/live ready.** The foundation disposition remains
**HOLD / ADAPTER NO-GO** from the independent hostile re-audit of T4.

Do not restart the analysis or re-plan from scratch. Resume from section
"Exact recommended next-action sequence".

---

## 1. Exact repository identity

- Repo: `C:\Users\abbot\Documents\Codex\2026-09-21\goal-complete-the-project-genesis-v0\work\genesis-remediation`
- Branch: `main`
- HEAD at time of writing: `ac6b66be9dc119a75a0dfb772890cfd2c3919c52` (**T4**, sealed)
- HEAD tree: `730b931ed8f6b5fa066a60e9de8467f5d6b6ebd7`
- Parent chain (immutable, do not rewrite): T4 `ac6b66b` → T3 `39a2132` → T2 `4214f38` → T1 `d130c21` → S5 `27dd525`.

A WIP resume checkpoint commit is created **after** this document (see §12). It
sits on `main` on top of T4. It is **not** the T5 candidate; it only preserves
the in-progress worktree so a fresh session can resume byte-for-byte.

## 2. Current git status (uncommitted T5 delta on top of T4)

Modified (production — scope is deliberately only the two protected-boundary files):
```
 M src/genesis/protected.py
 M src/genesis/protected_research_worker.py
```
Modified (retained tests, fixture relocation only — see §6):
```
 M tests/test_astra_s5_process.py
 M tests/test_remediation_r9_protected.py
```
New (untracked):
```
?? tests/protected_research_programs.py          # relocated retained research programs
?? tests/test_astra_t5_protected_closure.py      # N1 + PA-1 RED->GREEN suite
?? tests/test_astra_t5_owner_binding.py          # N2 RED (fix NOT yet implemented)
?? tests/test_astra_t5_risk_replay_integrity.py  # N3 RED (fix NOT yet implemented)
?? tests/test_astra_t5_approval_ordering.py      # O-5 RED (fix NOT yet implemented)
?? tests/test_astra_t5_package_evidence.py       # O-1/O-2/O-3 RED (tool flags NOT added)
?? T5_RESUME_HANDOFF.md                           # this file
```
Confirmed untouched vs HEAD: `DECISIONS/`, `v04_pack/`, `V04_MIGRATION_PLAN.md`,
and every other `src/genesis/*.py` including `risk.py`, `execution.py`,
`selection.py`, `decision_output.py`, `release_proof.py`. There is no
`work/test_runtime` scratch left in the tree.

SHA-256 of the working files (verify before resuming; if these differ, someone
edited the tree after this handoff):
```
bb48e55959bc3e7d410cdb6993c6efd51f213c7ef5198ea678a41bb4182311f0  src/genesis/protected.py
d324c464e2c8b63eb8d661ea5c31fb52613a391e73290ec232280cba23d2bd73  src/genesis/protected_research_worker.py
ad135a89e207912f23437333f29da9772eb3edd9f75f51f6b440e67236c3cd47  tests/test_astra_s5_process.py
60dcd502e2d5063ac33b7b0e4dc8e92521f41731b29a9274940be46bd0d2d9f4  tests/test_remediation_r9_protected.py
a8b33209b3f9a7a0ff35063b20e74806fc00f47dd2ca96ba862e63d64a0ec847  tests/protected_research_programs.py
60e16e6788eff4061b62704e7db09965f43de1ea60ecf6dee47f6d93c3e7a124  tests/test_astra_t5_approval_ordering.py
dbcc862c2cae8fc0a776b517fa6c653b18dd23dbe1445f895a9ba171145ad5a2  tests/test_astra_t5_owner_binding.py
52cdc3027c516c639e54e474508ee3e745cec6a6545b8970ebcf86f34ef9ac14  tests/test_astra_t5_package_evidence.py
78a63b586dcbd5e4efccc44e7bbd5740355dab4616fae3fec80f94c455b0dee7  tests/test_astra_t5_protected_closure.py
5dbd05e7b0d43135924106c2bcbb3e951335a5abb02203210103bf533bb9d9d2  tests/test_astra_t5_risk_replay_integrity.py
```

## 3. What T5 is closing (from the independent hostile re-audit of T4)

Audit report: `outputs/GENESIS_V04_T1_T4_INDEPENDENT_HOSTILE_REAUDIT_REPORT.md`.
Findings to close in T5:
- **N1 (HIGH)** — B4/B5 protected-research boundary bypassable: function-local
  imports, `importlib`, stdlib/builtins indirection, and unhashed/cached helper
  code certified under a program digest. **Class**, not just the 6 probes.
- **N2 (MEDIUM)** — composed-owner identity not bound: split strategy registry
  (2-a), shadow release-proof owner (2-b), one approval sent from two order
  logs (2-c); generalize to every risk-composed owner.
- **N3 (LOW)** — a factual `record_exposure` whose id collides with an approval
  id permanently bricks risk replay (fail-closed DoS).
- **O-5 (LOW)** — a grant appended after (or backdated before) a qualification
  is still accepted; approval must exist before it is relied upon.
- **O-1/O-2/O-3 (LOW, evidence path)** — package `verify` has no expected-commit
  pin, tolerates duplicate JSON keys / omitted raw members; add
  `--expect-commit`, `--require-raw-root`, `--require-historical` pins.

## 4. Test status right now (measured 2026-09-26 on the current worktree)

| Suite | Meaning | Result NOW |
|---|---|---|
| `tests.test_astra_t5_protected_closure` | N1 (14) + PA-1 (1) | **15 OK (GREEN)** |
| `tests.test_astra_s5_process` + `test_remediation_r9_protected` + `test_astra_t3_protected_integrity` (+closure) | retained protected regression w/ new worker + nonce | **53 OK (GREEN)** — last recorded after the PA-1 parent change |
| `tests.test_astra_t5_owner_binding` | N2 | **RED** (fix not implemented) |
| `tests.test_astra_t5_risk_replay_integrity` | N3 | **RED** (fix not implemented) |
| `tests.test_astra_t5_approval_ordering` | O-5 | **RED** (fix not implemented) |
| combined N2+N3+O-5 run | — | 18 methods, **20 failures** |
| `tests.test_astra_t5_package_evidence` | O-1/O-2/O-3 | **4 failures (RED)** — tool flags not added |

The full repository suite (all ~297+ tests), compileall, concurrency/crash/
restart campaigns, static gates and deterministic package rebuild have **NOT**
been run since the T5 changes began. That is required before any T5 seal.

## 5. N1 fix — IMPLEMENTED and verified green (architecture)

All in `src/genesis/protected_research_worker.py`. The design intent: a
certificate is issued only for computation performed by the **hashed program
bytes plus trusted runtime** (stdlib + the Genesis package the worker itself
runs from), with **no raw `FutureOutcomeLabel` reachable**. Layers, in order:

1. **Static program audit** (`_audit_program_code`) over every code object of
   the hashed module (module top level, class bodies, nested functions):
   rejects a forbidden-name set (`_FORBIDDEN_PROGRAM_NAMES`: `eval`, `exec`,
   `compile`, `globals`, `getattr`, `__globals__`, `__code__`, `import_module`,
   frame/`gc`/`ctypes` reflection names, etc.) appearing as either `co_names`
   or string consts; and rejects any `IMPORT_NAME` that is not a top-level,
   level-0 import of an allowed module (control modules such as `importlib`,
   `sys`, `ctypes`, `gc`, `subprocess`, `threading`, `inspect`, `types`,
   `builtins`, `marshal`, `pickle` are denied — see `_CONTROL_MODULES`).
2. **Restricted builtins** (`_InterpreterBaseline.research_builtins`): the
   program executes with `__import__` wrapped by `_guarded_import` and with
   `eval/exec/compile/getattr/globals/locals/setattr/delattr/vars/...` removed.
3. **Import origin guard** (`_ResearchOriginGuard`, a `MetaPathFinder` inserted
   at `sys.meta_path[0]`): raises `ImportError` for any module whose spec origin
   resolves under a research root. Trusted runtime (stdlib + Genesis package
   dir, `TRUSTED_RUNTIME_ROOT`) is exempt via `_inside()`.
4. **Post-exec clean-process check** (`_InterpreterBaseline.require_clean`):
   after executing the module and after producing predictions, scans
   `gc.get_objects()` for any live `FutureOutcomeLabel` (→
   `ResearchProcessContaminated`) and for live research-root code objects other
   than the current program; and compares module-binding identities, builtins,
   env, decimal context, `sys.path`/`meta_path`/`path_hooks`, recursion limit
   against the captured baseline.
5. **Per-request scope restore + poisoning latch**: `restore_request_scope`
   forgets request-loaded modules and submodule bindings; any contamination sets
   `poisoned=True` so all later requests on that worker fail closed.

Roots are used only to **locate** the one hashed program file; they are no
longer placed on `sys.path` (the T4 line `for root ... sys.path.insert` was
removed).

### IMPORTANT known limitation of the in-process approach (see §8/§10)
`require_clean` is an **in-process state comparison**. The PEP 578 audit-event
map I collected (`~/t5/diag/audit_events.py` output) proves that plain module/
class attribute assignment and `func.__globals__` reads are **not** auditable
events, so an in-process snapshot can never be provably complete. The intended
**stronger** architecture (NOT yet implemented) is in §8.

## 6. Retained-fixture relocation — IMPLEMENTED, behaviour-preserving

To make legitimate retained programs self-contained (they previously imported
other test modules, which the new closure would reject as unhashed code):
- New `tests/protected_research_programs.py` holds the retained programs
  (`signal_program`, `half_program`, `exception_program`, `failing_program`,
  `crash_program`, `slow_program`, `hostile_parent_probe`) copied **verbatim**.
- `tests/test_astra_s5_process.py` and `tests/test_remediation_r9_protected.py`
  now import them; parent-sentinel globals moved onto the programs module.
- Verified on **sealed T4 source** these relocations are behaviour-neutral:
  `~/t5/evidence/T5_FIXTURE_RELOCATION_NEUTRAL_ON_T4.txt` (40 tests OK with
  `src/` unchanged).

## 7. PA-1 — hostile-pre-audit discovery (IPC response integrity)

**Discovered during hostile self-audit of the N1 fix, beyond the auditor's
inventory.** The research worker shares its stdout pipe with the parent as the
IPC channel. A hostile research callback can `os.write()` to the inherited
stdout file descriptor a fully-formed, self-consistent `{"status":"artifact",
...}` line (correct campaign/dataset/frame ids, valid artifact hash) so the
parent reads the **forged** artifact instead of the worker's real one — the
parent then certifies attacker-chosen predictions (e.g. Brier `0`).

- **RED reproduction:** `tests/test_astra_t5_protected_closure.py::
  test_research_cannot_forge_a_worker_response_on_the_ipc_channel`. Confirmed
  RED on both sealed T4 and the pre-fix current tree (`('certified','0')`).
- **Fix (IMPLEMENTED, and the closure suite is GREEN with it):**
  per-request **nonce authentication**.
  - Parent (`src/genesis/protected.py`, `ProtectedEvaluationClient.run`):
    generates `nonce = secrets.token_hex(32)`, sends it in the `predict`
    message, and requires the reply to carry back the exact nonce; a
    non-error reply without the matching nonce triggers
    `_terminate_research_after_protocol_violation()` (kills the worker — the
    stream is no longer trustworthy) and fails closed.
  - Worker (`src/genesis/protected_research_worker.py`): accepts `nonce` in the
    `predict` message (validated 64-hex), keeps it only in a local, and echoes
    it in the `artifact` reply. Error replies keep the generic
    `{"status":"error","message":"protected evaluation failed"}` form (no nonce).
  - The callback never receives the nonce, so a forged line cannot include it.

### PA-1 hardening NOT yet finished (REQUIRED before PA-1 is "closed")
The user explicitly required attacking the new auth design before closing it.
**Not yet done.** Must test and, where needed, harden against:
1. **Nonce disclosure** — prove the callback cannot read the nonce via any
   frame/parent-object/`gc`/globals path (should already be blocked by N1
   layers 1–4, but must be demonstrated, not assumed).
2. **Replay / cross-request reuse** — the worker must not accept or echo a
   stale nonce; a forged line replaying a *previous* request's nonce must be
   rejected (parent uses a fresh nonce each call and checks equality, so a
   replayed old nonce ≠ current nonce → should fail; add an explicit test).
3. **Substitution / interleaving** — concurrent requests are serialized by
   `_research_lock`; confirm no window where a forged reply with a
   valid-but-other-request nonce is accepted.
4. **FD injection variants** — the RED test writes to fds 3..63; also test the
   worker's real stdout fd number explicitly, and partial/split-line writes
   that could interleave with the genuine reply mid-line.
5. **Worker restart / stale state** — after a poisoning kill or crash, a new
   worker must not accept a nonce minted for the dead worker.
6. **Request/program-identity mismatch** — a reply whose nonce matches but whose
   artifact identity (campaign/dataset/frame/digest) does not must still be
   rejected (parent already checks these AFTER the nonce; keep and test).
7. Consider whether the genuine reply and a forged reply can both arrive (reader
   thread queues both lines) and the parent picks the wrong one — the parent
   reads exactly one message per request under the lock; test that a forged
   pre-write followed by the genuine write does not cause the genuine reply of a
   *later* request to be consumed early (queue desync). If a desync is possible,
   move research IPC off the shared stdout to a dedicated pipe/fd.

## 8. Architectural decision made, and the REJECTED approach

**Decision (recommended, NOT yet implemented): one worker process per program
identity.** A research worker should execute code of at most one program digest
for its whole lifetime; a different digest gets the generic failure and a fresh
worker is spawned. Combined with a **permanent PEP 578 audit hook** (armed at
first research execution, closure-captured so research cannot rebind it) that
allows only the one bound program code object plus byte-identical trusted-runtime
files and denies code/function creation, frame access, `gc` introspection,
`ctypes`, threads, processes, sockets, pickle — this removes every cross-program
state channel that an in-process snapshot cannot see, and lets the fragile
`require_clean`/`restore_request_scope` state-diff machinery be **deleted**.

**REJECTED as insufficient on its own: the static deny-list + in-process
state-snapshot approach that is currently implemented.** Reason, proven
empirically (`~/t5/diag/audit_events.py`): attribute assignment on modules/
classes and `func.__globals__` reads raise **no** audit event, so an in-process
"baseline vs current" comparison can never be complete; a sufficiently creative
program could mutate reachable state in a way the snapshot does not enumerate.
The current implementation passes all 15 closure tests, but its guarantee rests
on enumerated names/state rather than an interpreter-level invariant. Treat the
current N1 code as a **strong first layer to be superseded / backed by** the
per-process-identity + audit-hook design, not as the final closure.

Note: moving to per-identity workers will change the retained T3 test
`test_changed_module_executes_new_verified_bytes_not_cached_callable`, which
today expects a second, different program to certify in the *same* worker. Under
the stronger design the second digest fails closed in that worker and certifies
in a fresh one. That is **stricter**, not weaker (it asserts both B4 outcomes).
Any such change must be recorded in the T5 authority memo, and the immutable
RED evidence must be preserved.

## 9. N2 / N3 / O-5 / package pins — NOT yet implemented (design intent)

- **N2** (`risk.py`/`execution.py`/`release_proof.py`): bind every
  risk-composed owner (strategy registry, safety, bankroll, mode, qualification,
  order log/execution, ledger, market, refresh, release-proof) to one
  authoritative identity — reuse the existing **mode precedent**
  (`_coherent_paper_mode` / `mode_authority_mismatch` compares
  `coordinator_path.resolve()`). Fail closed on mismatch at admission,
  consumption, submission, proof issuance, attach and release. RED suite:
  `test_astra_t5_owner_binding.py`. **Must not** forbid legitimate restarts,
  reopened stores, or relocated deployments (positive tests are included in the
  suite and must stay green).
- **N3** (`risk.py::record_exposure` and the `_exposures` replay): validate
  every append against the replay of the log *including* the new row, so a
  colliding id (exposure vs approval) is refused instead of bricking replay.
  RED suite: `test_astra_t5_risk_replay_integrity.py`.
- **O-5** (`selection.py` qualification append path / `decision_output.py`
  approval store): require the exact unrevoked human grant to exist (checked
  under the approval-ledger lock) at qualification-record time; a grant appended
  after, or backdated before, must never admit that qualification. RED suite:
  `test_astra_t5_approval_ordering.py`. Uses the **production** validator (not
  the `SyntheticQualificationRecordStore` fixture override).
- **Package pins** (`tools/genesis_audit_package.py`): add `--expect-commit`,
  `--require-raw-root`, `--require-historical` verify-side pins; reject
  duplicate JSON keys and omitted raw members. RED suite:
  `test_astra_t5_package_evidence.py`.

## 10. Invariants and project laws the next model MUST preserve

From `outputs/.../GENESIS_CLAUDE_CODE_HANDOFF.md` §9, the T4 handoff, and
`DO_NOT_BREAK.md`:
- Objective: sustainable long-run ROI via diversified good bets; not forced
  volume / favourite-chasing / pure-EV / trading / arbitrage.
- Tiers 1u/1.5u/2u/2.5u/3u; 1u = 2.5% bankroll; 3u = 7.5% hard single-bet max;
  ~60% open-liability ceiling; tighter correlated limits; no daily turnover cap.
- Hold-to-settlement; UNKNOWN/reconciliation ambiguity blocks and never
  auto-retries; one candidate hash / one order-intent lineage; exact replay
  idempotent; append-only JSONL is the business/audit authority, SQLite only
  coordinates serialization.
- All historical v1/v2/v3 candidate/output/binding/qualification/approval/order/
  settlement meanings unchanged; OddsPapi Interpretation A (220 / +30 reserve /
  251 blocked / 7 daily); PAPER/offline; real protected activation disabled.
- **Do not** normalize LF/CRLF and call B8 fixed; **do not** rewrite approved
  ADR hashes; **do not** edit ADR/approval bytes; **do not** manufacture a human
  approval, strategy authority, model, tier or TTL; **do not** weaken/skip a
  hostile/retained assertion to go green; **do not** amend/squash/reset/rebase
  S5–T4 history; **do not** discard the uncommitted T5 files.
- Approved ADR hashes to keep pinned: ADR-0002
  `7e851df9898f3a257a87b602bc1a7f6011ebae1397d42c17b8727c84e554ae00`,
  ADR-0003 `0fd4c63deb7a8431c41d7869163ccf79ce0295b63b585c8e4c3a0695f1dafaad`.
- Never manufacture human/strategy approval. Never declare the foundation
  cleared yourself. Stop for the independent hostile re-audit at the end.
- Env: Python 3.12.10, Windows 11, git `core.autocrlf=true`. Run protected/
  process tests from a **short path** (e.g. `C:\Users\abbot\t5\t4`) — MAX_PATH
  breaks `CreateProcess` under the long scratchpad path (this is an environment
  error, not a product failure).

## 11. Immutable evidence that must stay byte-identical

- Sealed checkpoints S5/T1/T2/T3/T4 commits and trees (see §1).
- `outputs/GENESIS_V04_T4_INTEGRATED_REAUDIT_ac6b66b.zip` (+ `.sha256`,
  `_BUILD_REPORT.json`, `_VERIFICATION_REPORT.json`) and
  `GENESIS_V04_T4_REAUDIT_DELIVERABLES.sha256` — verified OK on 2026-09-26.
- `outputs/GENESIS_V04_T1_T4_INDEPENDENT_HOSTILE_REAUDIT_REPORT.md`,
  `..._EVIDENCE.zip` (+ `.sha256`), `..._EVIDENCE_MANIFEST.json` — verified OK.
- All `remediation_evidence/T1..T4/` RED/GREEN evidence and the six original S5
  producer/audit artifacts.
- Auditor probe copies and this session's RED/neutrality evidence under
  `C:\Users\abbot\t5\evidence\` and `C:\Users\abbot\t5\diag\` (scratch, outside
  the repo). `~/t5/t4` is a short-path LF clone at T4 used for RED-on-T4 runs.

## 12. The WIP resume checkpoint (see also §1)

A single commit is made on `main` on top of T4 containing exactly the §2 files
plus this handoff, with a message beginning `WIP(T5 resume): ...` and stating it
is **NOT** the T5 candidate. It does not touch T4 or any prior commit; T4 stays
reachable and immutable at `ac6b66b`. The commit id is reported to the user in
chat (the next session should `git rev-parse HEAD` and diff against T4).

## 13. Exact recommended next-action sequence

1. Verify worktree matches §2 hashes; read the audit report §6/§7 of the
   integrated hostile re-audit; read this file fully.
2. **Finish PA-1 hostile hardening (§7)** — write deterministic tests for
   disclosure/replay/substitution/fd-injection/restart/identity-mismatch/queue-
   desync; if a queue desync is possible, move research IPC to a dedicated fd.
   Keep the generic-error contract. Re-run the protected regression.
3. **Implement the stronger N1 architecture (§8)** — per-program-identity
   worker + permanent closure-captured audit hook; delete the in-process
   state-diff crutch once the audit hook subsumes it; update the T3 retained
   test as noted and preserve its RED evidence; re-run all protected suites.
4. **Implement N2, N3, O-5, and the package pins (§9)** — RED→GREEN each, and
   keep the legitimate-composition positive tests green (do not pass by
   forbidding permitted configurations).
5. Full verification: entire suite + compileall + `git diff --check` +
   concurrency/crash/restart campaign + deterministic package rebuild +
   authority-integrity checks, from a short path.
6. **Hostile pre-audit** (adversary mindset): attack every repaired boundary for
   alternate representations/aliases/indirections, same-authority/different-
   object and same-object/different-authority, stale/copied/reopened stores,
   TOCTOU, mutation races, duplicate/replay/substitution, namespace collisions,
   malformed-but-parseable records, cross-boundary composition. For each new
   defect: retain immutable RED, classify, regress, repair, re-run, restart the
   hostile phase.
7. **Evidence audit (§ Phase 5 of the user brief):** fresh-checkout rebuild;
   verify commit/tree/parent, clean worktree, test counts and identities,
   package hashes, representation assumptions, pins/sidecars; attempt
   self-consistent tampering against the new evidence path.
8. Only after that gate: write the T5 authority memo + `GREEN_FINAL`, create the
   **T5 candidate** commit (separate from the WIP checkpoint), build+verify the
   integrated re-audit package from the clean T5 commit, and produce the T1–T5
   hostile re-audit handoff. **STOP** for the independent audit. Do not declare
   GO.

---
**Status line:** N1+PA-1 implemented and green (15 tests); PA-1 hardening,
stronger N1 architecture, and N2/N3/O-5/package pins NOT implemented; full
regression/stress/hostile-pre-audit/evidence-audit NOT done. T5 is IN PROGRESS.
