# R8 — Explicit and atomic quota semantics

Status: **GREEN**

## Red-before basis

A baseline-compatible hostile probe ran in a detached worktree at `b1f22e5`. It
reproduced double-subtraction (normal call 191 blocked at monthly use 190), accepted an
evidence-free `cached=True`, and admitted all eight concurrent workers through a 7-unit
daily ceiling. See `RED_BEFORE.md` and the retained R0 F14 result.

## Closed invariants

- The digest-pinned active config is approved Interpretation A under `D-REM-001`:
  provider assumption 250, normal budget 220, protected reserve 30, daily billable 7.
- Interpretation B is parameterized only as an explicitly gated test fixture. Missing,
  corrupt, revoked, or test-only active policy state fails closed; no arithmetic-value
  guess chooses an interpretation.
- Provider allowance, Genesis normal budget, protected reserve, daily budget, active
  approval, test-only state, and provider-terms re-verification are distinct fields.
- Normal calls may use units 1..220 and never auto-upgrade. Unit 221 requires an explicit
  reserve request; unit 250 is final under A and unit 251 is blocked. Under B, normal 191
  requires reserve authority and Genesis stops at 220 despite provider headroom.
- `QuotaReserveAuthorization` is content-addressed and binds provider, exact policy
  version/digest, YYYY-MM period, grant <=30, reason, approval reference, grant time,
  validity window, and deterministic ID. Exact grant replay is idempotent.
- Grant, irreversible revocation, allowed reserve consumption, and blocked requests are
  authoritative append-only events. Wrong provider/policy/period, missing, expired,
  revoked, or exhausted authority fails closed.
- Reserve authority extends monthly reserve only; it cannot bypass the seventh/eighth
  daily boundary.
- Request check and append share the R1 inter-process transaction. Daily races admit
  exactly 7; normal-month races stop exactly at 220; restarted/concurrent reserve use
  cannot exceed the remaining per-authorization grant or provider ceiling.
- Request IDs are payload-bound and restart-idempotent. Event time cannot regress to
  manufacture additional daily capacity.
- Cache hits cost zero only for a verified, fresh object bound to the exact provider and
  active quota-policy digest. Stale or wrong-bound objects do not bypass billing.
- Replay re-derives active-policy daily/monthly/normal/reserve counters and every reserve
  binding. A hash-valid forged allowed event still fails closed.
- One legitimate allowance is a hard policy law; there is no account/key selector and a
  mismatched provider cannot bypass the ledger.
- Legacy billable events remain usage evidence. Legacy policy fields migrate only through
  an API that requires an explicitly named interpretation and provider ceiling.

## Matrix evidence

- T-F14-001..007: original 190 block reproduced; A boundaries 190/191/220/221/250/251
  and explicit reserve use are green.
- T-F14-008..012: B normal 190, reserve through 220, and 221/250 prohibition are green.
- T-F14-013: active config resolves only to approved A.
- T-F14-014..017: verified-fresh cache and daily 7/8 boundaries are green for the
  parameterized model.
- T-F14-018..019: daily, normal-monthly, and reserve boundary races cannot oversubscribe.
- T-F14-020..021: missing/corrupt/revoked config fails closed; A stops at 250.
- T-F14-022..027: no auto-escalation; provider/policy/period/expiry/revocation/grant
  bindings; restart/concurrency; and daily guard over reserve authority are green.

## Verification

- Targeted R8 suite: **14/14 green**.
- Full suite: **96/96 green**.
- Compileall: **green**.
- Diff check: **green**.

## Scope check

The 250 provider allowance remains an unverified planning assumption. No provider lookup,
network use, credential, account, adapter, cloud, strategy, sport, or live path was added.
