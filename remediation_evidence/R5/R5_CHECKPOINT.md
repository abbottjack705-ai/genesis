# R5 — Risk authority, 3u hard boundary, and durable reservations

Status: **GREEN**

## Red-before basis

R0 recorded F05/F15 risk behavior before this batch: a caller could request arbitrary £50
liability against £100 bankroll, and restart lost every approval/reservation.

## Closed invariants

- `RiskEngine` requires durable bankroll, qualification, safety, and audit authorities plus the
  exact active `PolicySet`; there is no raw bankroll/liability approval API.
- The current bankroll head is risk-owned. A request may repeat only its snapshot ID for stale
  detection; bankroll value is never accepted from the caller.
- Risk loads the immutable qualification record, verifies its candidate/policy/expiry/integrity,
  and takes the tier only from that record.
- The V0.4 policy itself enforces `1u = 0.025`, declared tiers only, and a hard 3u maximum.
- Stake is derived from the current bankroll and approved tier. BACK liability equals stake;
  LAY liability is independently derived from stake and odds with Decimal accounting.
- Caller expected tier/stake/liability fields are mismatch detectors only.
- Open, correlated, pending, and UNKNOWN exposure checks operate over replayable durable state.
- Durable safety state owns the kill switch; no caller boolean can clear it.
- Each approval binds bankroll snapshot/value, qualification and strategy-contract identity,
  tier, stake, liability, side/odds, policy version/digest, safety state, issue time, and exact
  candidate expiry. Approval/reservation replay survives restart.
- Consumption is single-use across different orders and idempotent only for exact same-order
  recovery; R6 will bind this operation to execution state.

## Matrix evidence

T-F05-001..018 are green: raw arbitrary liability removal; exact 3u BACK and 2u LAY arithmetic;
malformed/unsupported/>3u rejection; expected-value mismatch detection; 60% and correlation
limits; UNKNOWN blocking; no daily turnover cap; durable kill state; stale/current bankroll;
restart; hard-policy guards; qualification-owned tier; and missing, expired, mismatched, or
tampered qualification rejection.

## Verification

- Targeted R5 suite: **8/8 green** (`tests.test_remediation_r5_risk`).
- Full suite: **66/66 green**.
- `python -m compileall -q src tests`: **green**.
- `git diff --check`: no whitespace errors (only platform line-ending notices).

## Scope check

No source adapter, acquisition, strategy/model, provider API, UI, cloud, credential,
live-trading, chaos, or canary scope was added.
