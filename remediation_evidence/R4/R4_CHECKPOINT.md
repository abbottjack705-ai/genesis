# R4 — Ranking semantics

Status: **GREEN**

## Red-before basis

R0 recorded F07/F08 before this batch: the exceptional-short odds region received an ordinal
bonus, and a weaker `alpha` market family outranked a stronger `zulu` family lexically.

## Closed invariants

- Ranking accepts only authoritative QUALIFY decisions with a qualification-record reference,
  a strict valid tier, and an approved comparability group.
- Valid tier descending is the only global quality precedence.
- Within an explicit comparability group, conservative probability orders candidates, followed
  only by stable decision/candidate identity.
- Across equal-tier incomparable groups, deterministic round-robin provides diversification.
  Group queues are ordered by their minimum stable candidate identity, never by group name,
  market family, market ID, odds region, raw probability, EV, or implied probability.
- Exceptional-short eligibility retains the existing stricter non-negative-margin rule in
  qualification but receives no ranking bonus.

## Matrix evidence

- T-F07-001..007: stronger comparable normal-price candidate, 1.49/1.50 boundary invariance,
  incomparable-group isolation, explicit within-group quality, policy guard retention,
  permutation invariance, and group-label-independent round-robin are green.
- T-F08-001..005: market-family and market-ID labels have no quality role, stable identity is
  the final tie-break, and group-label renaming preserves order.

## Verification

- Targeted R4 suite: **6/6 green** (`tests.test_remediation_r4_ranking`).
- Existing tier/ranking regression remains green.
- Full suite: **58/58 green**.
- `python -m compileall -q src tests`: **green**.
- `git diff --check`: no whitespace errors (only platform line-ending notices).

## Scope check

No source adapter, acquisition, strategy/model, provider API, UI, cloud, credential,
live-trading, chaos, or canary scope was added.
