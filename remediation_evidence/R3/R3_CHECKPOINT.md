# R3 — Authoritative qualification and strict tier contract

Status: **GREEN**

## Red-before basis

R0 recorded F01 and F09 before this batch: caller-created all-true facts qualified a candidate
with missing decision artifacts, and a missing tier both qualified and entered ranking.

## Closed invariants

- `QualificationAuthority.evaluate(candidate, now=...)` is the sole post-audit V0.4
  qualification boundary and requires every registry/store/read-view dependency.
- The caller-facts `qualify_v04` route is audit-only and always PASS; the legacy `qualify`
  function is not called by authoritative orchestration.
- Immutable `StrategyDecisionContract` identity binds config, exact canonical odds profile,
  explicit adapter version, exact market capability, PAPER lifecycle, support/comparability,
  model, calibration, feature, gate-policy, and approved-tier policy.
- Strategy lifecycle and market capability are resolved at `candidate.decision_at`. Later PAPER
  promotion or later capability registration cannot validate an earlier candidate.
- Candidate identity is recomputed with the strategy-decision-contract hash. Legacy/incomplete,
  copied, stale, or mismatched identity cannot qualify.
- Evidence pack, structured evidence, PIT source state, freshness, contradiction, uncertainty,
  odds-profile, and price checks resolve from their owners.
- Until R5/R6, production risk/execution read views explicitly return UNKNOWN; they never call
  the audited unsafe engines. Deterministic positive fixtures are isolated to tests.
- An authoritative QUALIFY atomically persists one immutable `QualificationRecord`; exact replay
  is idempotent. PASS persists no risk-authorising record.
- One shared exact tier parser admits only `1.0u`, `1.5u`, `2.0u`, `2.5u`, and `3.0u`, subject
  to both active policy and strategy-contract approval. Ranking rejects forged/invalid tiers.
- V0.4 policy construction now independently forbids a unit fraction other than 0.025 and any
  tier or maximum above 3u.

## Matrix evidence

- T-F01-001..020: all-true spoof, missing/corrupt evidence, artifact mismatch, capability and
  lifecycle PIT behavior, UNKNOWN stage views, deterministic gate order, dependency guards,
  immutable qualification handoff, exact identity recomputation, and comparability propagation
  are green.
- T-F09-001..006: missing, malformed, unsupported, above-maximum, contract-disallowed, every
  allowed tier, and rank-bypass defense are green.

## Verification

- Targeted R3 suite: **11/11 green** (`tests.test_remediation_r3_qualification`).
- Full suite: **52/52 green**.
- `python -m compileall -q src tests`: **green**.
- `git diff --check`: no whitespace errors (only platform line-ending notices).

## Scope check

No source adapter, acquisition, strategy/model discovery, provider API, UI, cloud, credential,
live-trading, chaos, or canary scope was added.
