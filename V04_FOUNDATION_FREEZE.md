# V0.4 foundation freeze — canonical record

| Field | Value |
| --- | --- |
| Freeze verdict | **V0.4 FOUNDATION FREEZE SATISFIED** — no unresolved CRITICAL/HIGH |
| Freeze-gate audit commit (documentation/evidence-only) | `47986ab081dc41ada3a71c790f8d4cfa12367654` |
| Certified executable baseline (immutable) | `4f11606615c7650f3bd74c7ccf5d2fb7a5a753c5` |
| Relationship | `47986ab` is a pure fast-forward of two documentation/evidence-only commits over `4f11606` (`95f99e6`, then `47986ab`). `src`, `tests`, `config`, `tools`, `DECISIONS` and `v04_pack` are byte-identical between `4f11606` and `47986ab`. |
| Date recorded | 2026-09-28 |
| This document | Documentation/metadata-only. Adds no change to any audited source, test, configuration, or activation state. |

This is the single canonical stop for "what is frozen, what was proven, what
is left, and where new work goes." It does not itself change `4f11606`'s
meaning; it records the verdict reached about that commit and indexes the
evidence.

## What is immutable

`4f11606` is the certified V0.4 foundation baseline. Its executable trees —
`src`, `tests`, `config`, `tools`, `DECISIONS`, `v04_pack` — must never be
amended, rebased, or rewritten. Any future change to foundation behavior is a
new remediation tranche on top of this commit (or a documented, separately
reviewed exception), never an edit to this history. Verify before trusting any
claim about it:

```text
git rev-parse 4f11606
git rev-parse 4f11606:src 4f11606:tests 4f11606:config 4f11606:tools 4f11606:DECISIONS 4f11606:v04_pack
git merge-base --is-ancestor 4f11606 47986ab && echo ancestor-ok
git diff --name-status 4f11606 47986ab   # must show only remediation_evidence/T6/* additions
```

Recorded executable tree IDs at both `4f11606` and `47986ab` (identical):

| Path | Tree SHA |
| --- | --- |
| `src` | `51cb635bc42b993815b6c02a23c4c3ceb7d98476` |
| `tests` | `e90b298180068fec03ba7e2fa81957082e7fb3ce` |
| `config` | `abd22db01ff482a8da84634ee740ba382b68c804` |
| `tools` | `a0e3411edb4e068fd4708050516cb6870834e7ac` |
| `DECISIONS` | `cc97ec6f841f1e3fbe6dbb57c9cb6e1ac24fdb64` |
| `v04_pack` | `3c3c1c27d80ed6f10c32ac6605a5f438b2e7de12` |

## How T6 got here

T6 is the largest tranche in the repository. Before the chain below, it closed
four findings of the T5 independent verification report — F-2 (durable
approval causality: a qualification recorded before its human grant could
later become spendable through a composed store or raw append),
F-3a/F-3b (a `RiskAuditLog.append` public path bypassed the N3 replay check;
a filesystem alias/hardlink mirror could be accepted as an independent risk-log
authority), and F-4 (the audit package's `verify --repo` compared Git-blob
members but never raw-worktree member content, so a self-consistent rewrite of
raw evidence passed) — plus the separate E1–E10 series (exact-JSON append
verification, ordered critical-evidence invalidation, pinned-odds
recertification, N2 owner-identity witness comparison, durable dataset/
experiment/PIT preconditions, canonical-LF lock pinning, complete
`work/test_runtime` removal, and replace-ref/graft protection for audit
packages) and C-1 (`9b32c6f`, the single pinned composition root of the PAPER
authority graph). Their commits, memos and evidence (`T6_F2_AUTHORITY_MEMO.md`,
`T6_WIP_F2_CHECKPOINT.md`, `T6_WIP_F3_CHECKPOINT.md`, `T6_WIP_F4_CHECKPOINT.md`,
`F2_*`/`F3_*`/`F4_*` evidence files) are unchanged history beneath `4f11606`
and are not re-described here.

From composition root `9b32c6f`, T6 then closed the remaining hostile findings
against that state:

- **F-1/E3** — closed the worker's teardown re-entry gap (forbidden sinks now
  refused in every phase regardless of mode; native process modules fail
  closed with no audit event). Full discovery 437/437 (1 skip).
- **F-A** (found by the E11 hostile audit) — inverted the research-import
  policy from an incomplete denylist to a fail-closed positive allowlist.
  Full discovery 442/442 (1 skip).
- **F-B** (found by a further E11 re-audit; three findings, reconciled from
  two independent remediations) — closed attribute/object reachability
  beyond import statements, added always-on native-event denial, and added
  identity-based (`is`, not `id()`) trusted-definition integrity. Full
  discovery 480/480 (1 skip).
- **ADR-0004** — real Windows outer OS-level confinement (Job Object +
  capability-less AppContainer), opt-in and off by default; real protected
  activation stays disabled. Full discovery 493/493 (1 skip) at `4f11606`.

## E11 verdict (OS-level containment)

Independently assessed **SATISFIED at `4f11606`**
(`remediation_evidence/T6/FB_E11_OS_CONTAINMENT_VERDICT.md`) by static review
plus witnessed Windows 11 execution:

- Containment suite (`test_astra_t6_fb_os_containment` +
  `test_astra_t6_fb_os_confinement`, `-v`): **22 tests, 0 skipped, all OK.**
- Full discovery: **493 tests total, 1 skipped, 0 failures, 0 errors** (the
  one skip is the platform symlink case, unrelated to containment).
- Host/gates: Windows 11 build `10.0.26200`; Python 3.12; `IS_WINDOWS=True`;
  `APPCONTAINER=True`; `mpssvc` (Windows Defender Firewall) and `BFE` (Base
  Filtering Engine) both RUNNING.
- Evidence and integrity manifest:
  `remediation_evidence/T6/FB_E11_EVIDENCE_HASHES.sha256`,
  `FB_E11_windows_evidence_raw.zip`.

## Final freeze-gate audit (foundation-wide)

A final independent hostile audit re-attacked the E11-certified state per
`remediation_evidence/T6/FB_E11_FREEZE_GATE_HANDOFF.md` and returned
**V0.4 FOUNDATION FREEZE SATISFIED** at `47986ab`:

- Full discovery: **493 total / 492 pass / 1 skip / 0 fail / 0 err** in 671
  seconds.
- Containment suite: **22/22, 0 skipped.**
- F12 append-stress: **20/20.**
- Lifecycle: **5/5.**
- `python -m compileall -q src tests` and `git diff --check`: clean.
- No unresolved CRITICAL or HIGH finding.

## Non-blocking residuals (carried into v0.5; none blocked the freeze)

| ID | Finding | Location | Disposition |
| --- | --- | --- | --- |
| F-1 | `icacls` success check keys on the English string "Successfully processed"; a non-English Windows host fails **closed** (confinement unavailable, never unconfined) | `src/genesis/protected_confinement_win.py:365` | Portability/availability; fix before relying on confinement on a non-English host |
| F-2 | Attestation's `environment_keys` omits `LOCALAPPDATA`, which is actually injected into the confined worker | `src/genesis/protected.py:1124` vs `:1023-1030` | Cosmetic accuracy |
| F-7 | Confined std streams rely on GC on the direct `close()` path (`ResourceWarning` on the test path only; production `dispose_research` closes them first) | `ConfinedResearchProcess.close()` / `ConfinedWorkerProcess` | Resource hygiene |
| LAY price-sanity | `assess_price_sanity` defaults `side=BetSide.BACK`; the caller never passes `side=`, so a LAY candidate is scored against the BACK break-even sign | `src/genesis/selection.py:881`, `src/genesis/policy.py:255` | Non-blocking: no LAY-capable strategy is authorized yet. **Fix before any LAY-capable strategy approval.** |
| Declared-time quota | Quota/ingestion/lifecycle timestamps are writer-declared, not sourced from a trusted clock; a writer can future-date a quota window to borrow budget | quota/ingestion/lifecycle authorities | The adapter phase must stamp times from a trusted source before quota authority is extended to live provider calls |
| T6 evidence byte-stability | `remediation_evidence/T6/*.md` had no `-text` `.gitattributes` rule, so an `autocrlf=true` checkout could reconvert line endings and break the recorded SHA-256 hashes | `.gitattributes` | **Fixed in this freeze commit** (rule mirrors the existing `*.txt -text` T6 rule; all affected files were already LF) |
| State docs T5-era | `PROJECT_STATE.md`/`ARCHITECTURE.md`/`TEST_EVIDENCE.md`/`HANDOFF.md`/`ASSUMPTIONS.md` had not been updated past T5 | top-level docs | **Fixed in this freeze commit** |
| Single-host evidence | E11's Windows execution evidence comes from one Windows 11, English-locale host | `remediation_evidence/T6/FB_E11_*` | Re-run on an independent and, ideally, non-English-locale host before treating containment as broadly proven |

## Evidence index

- `remediation_evidence/T6/T6_F2_AUTHORITY_MEMO.md`,
  `T6_WIP_F2_CHECKPOINT.md`, `T6_WIP_F3_CHECKPOINT.md`,
  `T6_WIP_F4_CHECKPOINT.md` — the T5-independent-review F-2/F-3/F-4 closures
  folded into composition root `9b32c6f`.
- `remediation_evidence/T6/T6_F1_AUTHORITY_MEMO.md` — F-1/E3 classification and construction.
- `remediation_evidence/T6/T6_FA_AUTHORITY_MEMO.md` — F-A classification and construction.
- `remediation_evidence/T6/T6_FB_AUTHORITY_MEMO.md` — F-B classification, construction,
  and the reconciliation of the two independent F-B remediations (this memo
  records that reconciliation; no separate `FB_RECONCILIATION.md` is committed
  to this repository).
- `remediation_evidence/T6/FB_E11_OS_CONTAINMENT_VERDICT.md` — E11 verdict and Windows evidence detail.
- `remediation_evidence/T6/FB_E11_FREEZE_GATE_HANDOFF.md` — final freeze-gate audit assignment, mandatory attacks and verdict framing.
- `remediation_evidence/T6/FB_E11_EVIDENCE_HASHES.sha256` — SHA-256 manifest for all E11/freeze evidence artifacts (in-repo and provenance).
- `remediation_evidence/T6/FB_E11_windows_evidence_raw.zip` — byte-exact original Windows evidence bundle.
- `DECISIONS/ADR-0004-s5-os-confinement-boundary.md` — the OS-confinement ADR (PROPOSED; real activation not approved).
- `PROJECT_STATE.md`, `ARCHITECTURE.md`, `TEST_EVIDENCE.md`, `HANDOFF.md`, `ASSUMPTIONS.md` — refreshed in this same freeze commit to reflect T6 and this verdict.

## Permitted next phase

Read-only adapter **development** may begin on a new branch cut from the
frozen commit `4f11606` (conventionally `v0.5-adapters`). That branch may add
the first sport/source adapter under separate authority, implementation, and
review. It must not:

- amend, rebase, or rewrite any commit at or before `4f11606`;
- enable real protected activation (`ACTIVATION_ENABLED` stays a guard, not a
  switch — the unconditional raises are the real gate);
- treat E11/freeze SATISFIED as authorization for a strategy, shadow research,
  protected campaign, external API/credential, cloud deployment, live order
  path, chaos-certification system, or £100 canary — none of that is granted
  here.

Any change proposed to the frozen foundation itself (not the new adapter
branch) is a new remediation tranche requiring its own RED/GREEN evidence and
a fresh independent hostile audit, exactly like T1–T6 before it.

## Note for future models/auditors

If you are asked to change `src/genesis`, `tests`, `config`, `tools`,
`DECISIONS`, or `v04_pack` as they exist at `4f11606`: stop and confirm you are
starting a new tranche on a new branch, not editing history. If you are asked
to build the first adapter, quota-clock trust, or the LAY price-sanity fix:
that work belongs on `v0.5-adapters` (or its successor), starts from `4f11606`,
and still needs its own tests, evidence and audit — the freeze does not
pre-approve it.
