# R10 — Integrated adversarial replay and re-audit handoff

Status: **GREEN LOCALLY / READY FOR INDEPENDENT HOSTILE AUDIT**

The independent audit is not self-certified here. The first read-only
sport/source adapter remains **NO-GO** until that audit finds no unresolved
CRITICAL/HIGH adapter-gating weakness and the checkpoint is explicitly approved.

## Authority and lineage

- V2.1 authority ZIP SHA-256:
  `a3a8e191be2176551e6ae99367f601eddd08b93fd7434432c2e84ca4b4d448e0`.
- Inner foundation snapshot SHA-256:
  `1015cf7507f5aebce87f812367df3c77eebe58da15a0fa478acfb8d168201585`.
- Authority manifest: 156/156 entries verified.
- Audited baseline: `ae9cfa11128a476b2ec7f598df3d68e30b91f156`, tag
  `v0.4-audited-v2.1-baseline`.
- Last R9 checkpoint: `128d392`.
- Exact final R10 commit/tree and bundle hashes are generated in the external
  re-audit manifest after the green commit. This avoids recording a false
  self-referential commit identity inside that commit.

## Integrated deterministic gate

```text
python -m unittest discover -s tests -t . -v
Ran 110 tests in 26.759s
OK

python -m compileall -q src tests
exit 0
```

All original and remediation tests ran; none was skipped. `git diff --check`
was also clean before final commit.

After the evidence-backed documentation update, the complete suite was rerun:
**110/110 passed in 25.851 seconds**.

## Repeated concurrency/fault gate

- F12: 20/20 independent runs passed.
- Each F12 run: 8 spawned processes, 10 appends/process, a shared start barrier,
  30-second join bound, 80 unique rows, sequence 1–80, one valid JSONL chain.
- Aggregate F12: 1,600 expected rows, zero fork/corruption, 66.398 seconds.
- Cross-component: 3/3 campaigns passed, each containing 8 concurrency/fault
  tests; 24/24 executions in 17.363 seconds.
- Components: conditional append, candidate uniqueness, settlement head,
  daily quota, monthly normal quota, restarted reserve authority, protected
  attempt reservation, and append-transaction process death.

## Restart/recovery gate

`tests/test_remediation_r10_integration.py` proves:

- every one of the 17 `OrderState` values reaches an explicit durable restart
  disposition;
- `SUBMISSION_PENDING`, `SUBMISSION_SENT`, `UNKNOWN`, and
  `RECONCILIATION_REQUIRED` restart reconciliation-blocking;
- all other order states replay exactly;
- all 7 `ExposureState` values replay exactly, with the five open states still
  reserved and SETTLED/VOID still terminal;
- a spawned process exiting inside `AppendOnlyJsonl.transaction()` after the
  verified read but before append leaves the prior head valid, releases the
  coordinator lock, and permits a later valid append.

R5/R6 tests separately cover bankroll/safety/approval/reservation/order replay,
single-use consumption, kill state, corrupt schema, duplicate prevention,
terminal release, and the crash between approval consumption and order binding.

## Legacy unsafe-route gate

The source scan for `qualify_v04`, `LegacyUnsafeProtectedEvaluationBoundary`,
and `LegacyInProcessEvaluationHarness` found them only in the modules that define
the explicit legacy/audit harnesses. No other production module imports or calls
them. Behavioral tests additionally prove:

- `QualificationAuthority` does not route through the legacy qualifier;
- registered V2 protected campaigns cannot select the unsafe harness;
- real protected activation remains disabled unless the explicit local
  checkpoint test switch is supplied.

## Documentation gate

Only after the integrated suite, compile, 20-run F12 stress, cross-component
stress and restart matrix were green, R10 updated:

- `PROJECT_STATE.md`;
- `ARCHITECTURE.md`;
- `TEST_EVIDENCE.md`;
- `HANDOFF.md`;
- `V04_MIGRATION_PLAN.md`;
- `AUDIT_LOG.md`.

## R10 change scope

Production code changed: **none**. R10 adds one integration/fault test and
truthful documentation/evidence. It does not fabricate a new RED-before result;
the batch validates already-remediated invariants. All finding-specific RED and
GREEN evidence is indexed in `RED_GREEN_INDEX.md`.

No sport/source adapter, acquisition, model or strategy research, external API,
credential, dashboard, cloud deployment, venue/exchange integration, live path,
chaos-certification system, or £100 canary was added or run.

## Required next action

Run the frozen Astra prompt against the final snapshot and actively attack all
GO/NO-GO questions. The smallest unresolved question is: **does the final R10
snapshot still contain any CRITICAL/HIGH enforcement weakness relevant to the
first read-only adapter gate?**

Until answered independently with no such open finding: **NO-GO**.
