# Project Genesis V0.4 remediation handoff

Date: 2026-09-21
Status: **R0–R10 locally green; ready for independent hostile re-audit; adapter NO-GO**

## Review decision requested

Run the frozen Astra hostile implementation audit against the exact final R10
snapshot. Determine whether any unresolved CRITICAL/HIGH enforcement weakness
remains relevant to the first read-only sport/source adapter gate. Do not approve
later strategy, provider, cloud, venue or live work through this review.

The task performing this remediation has not self-certified that independent
audit. Until the external review and explicit checkpoint approval are complete,
the adapter decision remains NO-GO.

## Authority and exact identity

- Authority ZIP SHA-256:
  `a3a8e191be2176551e6ae99367f601eddd08b93fd7434432c2e84ca4b4d448e0`.
- Inner foundation snapshot SHA-256:
  `1015cf7507f5aebce87f812367df3c77eebe58da15a0fa478acfb8d168201585`.
- Manifest: 156/156 entries verified.
- Audited baseline: `ae9cfa11128a476b2ec7f598df3d68e30b91f156`, tag
  `v0.4-audited-v2.1-baseline`.
- Last production remediation commit before R10: `128d392`.
- The final R10 commit, tree and bundle digests are in the generated external
  handoff manifest, created after the green commit to avoid a self-referential
  identity claim.

## Green batch chain

| Batch | Green commit | Closure |
|---|---|---|
| R0 | `8625e7b` | frozen baseline and separate F01–F15 RED evidence |
| R1 | `afc56b7` | serialized append-only persistence |
| R2 | `f8f91ff` | causal PIT/evidence/provenance identity |
| R3 | `f42bd8d` | authority-derived qualification and strict tiers |
| R4 | `169ef9d` | unbiased comparable-group ranking |
| R5 | `28d5013` | durable authority-derived exact risk |
| R6 | `8bb86f3` | candidate-unique orders and exact approval binding |
| R7 | `b1f22e5` | one-head settlement/correction lineage |
| R8 | `d486297` | approved A quota policy and atomic authority |
| R9 | `128d392` | separately spawned protected evaluator boundary |
| R10 | final manifest | integrated replay, stress, recovery, docs and re-audit bundle |

## Verification summary

```text
python -m unittest discover -s tests -t . -v
Ran 110 tests
OK

python -m compileall -q src tests
PASSED
```

Additional gates:

- F12: 20/20 runs, each 8 processes × 10 appends, zero forks/corruption.
- Cross-component concurrency/fault: 3/3 campaigns; 24/24 executions.
- Restart: 17/17 order states and 7/7 risk exposure states.
- Process death inside append transaction: prior head preserved; subsequent
  append and replay passed.
- Legacy unsafe-route source scan: no use outside defining modules; behavioral
  guards passed.
- Full details: `TEST_EVIDENCE.md` and `remediation_evidence/R10/`.

## Reviewer entrypoints

Read in this order:

1. the frozen V2.1 `00_START_HERE_CODEX.md` and `04_GO_NO_GO_TEST_GATE.md`;
2. `PROJECT_STATE.md`, `ARCHITECTURE.md`, `TEST_EVIDENCE.md` and this handoff;
3. `remediation_evidence/R10/FINDING_TRACEABILITY.md` and
   `HOSTILE_REAUDIT_HANDOFF.md`;
4. each R0–R9 checkpoint and RED/GREEN artifact;
5. production modules and primary remediation tests named by the traceability map;
6. the frozen `12_ASTRA_FINAL_AUDIT_PROMPT.md` included in the external bundle.

Re-run:

```text
python -m unittest discover -s tests -t . -v
python -m compileall -q src tests
git diff --check
git status --short --branch
```

## Migration/compatibility decisions

- JSONL is the business/audit authority; SQLite coordinates only serialization.
- Explicit legacy migrations never infer missing identity or intent.
- Pre-audit incomplete candidates/packs/approvals/orders are audit-only.
- Ambiguous duplicate settlement history fails closed.
- Legacy quota migration requires an explicitly named interpretation.
- Active quota policy is approved Interpretation A; B is test-only.
- Registered V2 protected campaigns cannot enter the unsafe in-process harness.
- Real protected activation remains disabled pending this independent review.

## Scope attestation

No source/sport adapter, acquisition path, model or strategy search, outcome
backtest, external provider call, credential, dashboard/PWA, cloud/VPS deploy,
exchange/venue integration, live execution, chaos-certification system or £100
canary was implemented or run. The objective and V0.4 risk laws were not changed.

## Residual external questions

These are deliberately unresolved external or later-phase facts, not hidden
implementation claims:

1. Does the independent hostile audit find a CRITICAL/HIGH adapter-gating gap?
2. Which real provider/source can prove entitlement, PIT availability, revisions
   and current quota terms? The 250 OddsPapi allowance is unverified.
3. What separately reviewed deployment boundary will host real protected labels?
4. Which first read-only adapter, sport semantics and market settlement rules will
   later receive separate authority?
5. What later prospective evidence establishes calibration/profitability and
   operating/cloud costs?

## Stop point

R0–R10 implementation and evidence preparation stop here. The only next action
authorized by this handoff is the independent hostile audit and checkpoint
decision. Do not begin the next Genesis phase from this task.
