# Assumptions and unresolved questions

## Foundation assumptions

- Python 3.11+ and the standard library are sufficient for this milestone.
- File-backed content addressing and JSONL hash chains are adequate before a
  concurrency requirement justifies SQLite/PostgreSQL/object storage.
- Decimal arithmetic is preferred for money and odds-facing calculations;
  model probability storage is serialized as a decimal string.
- The V0.4 near-fair price-sanity tolerance is a versioned starting policy,
  approximately -2 percentage points, not an empirically validated law.
- Daily ranges are search/output aims only; they are never qualification
  quotas or caps.
- The generic accounting module implements exchange-style back and lay
  primitives. Venue-specific commission, dead-heat, void, non-runner, and
  market rules must be supplied by an approved venue contract.
- The protected evaluator is an interface skeleton, not a security boundary;
  a real campaign must run with process/service isolation and a one-way result
  channel.

## Unresolved evidence

- Hoofs probability/rank/confidence/minimum-back semantics are not present in
  supplied code and must not be guessed.
- No Race Shape report parser or availability history was supplied.
- Betfair API credentials, supported market inventory, delay/live-key terms,
  and exact settlement rules have not been verified or activated.
- No current-information capture source is admitted.
- The V0.4 quota and <=£10/month runtime values are planning constraints until
  official provider/cloud terms are reverified.
- Legacy sports-engine data contains MLB-specific assumptions and must not be
  treated as a Genesis multi-sport dataset.

## Frozen V0.4 foundation residuals (non-blocking; carried into v0.5)

Recorded at the V0.4 foundation freeze (`47986ab`, exec tree `4f11606`; see
`V04_FOUNDATION_FREEZE.md`). None blocked the freeze; each is a concrete
assumption or gap the next phase must close, not a hidden defect.

- LAY price-sanity: `assess_price_sanity` (`policy.py`) defaults
  `side=BetSide.BACK`, and its caller in `selection.py` never passes `side=`.
  A LAY candidate is therefore scored against the BACK break-even sign.
  Non-blocking only because no LAY-capable strategy is authorized; must be
  fixed and independently re-tested before one is.
- Trusted clock: quota, ingestion and lifecycle timestamps are writer-declared,
  not sourced from a trusted clock, so a writer can currently future-date a
  quota window to borrow budget. The adapter phase must stamp these times from
  a source the adapter cannot control before quota authority is extended to
  live provider calls.
- E11 Windows containment evidence (`remediation_evidence/T6/FB_E11_*`) was
  witnessed on one Windows 11, English-locale host. Linux skips 13 containment
  tests; a non-English-locale host is unverified because `icacls`'s success
  check keys on the English string "Successfully processed" (fails closed, not
  silently unconfined, but untested there).
- ADR-0004's OS-level confinement (Job Object + AppContainer) is real and
  independently verified but opt-in and off by default; real protected
  activation stays disabled pending separate operator approval of ADR-0004 and
  its once-provisioned (not per-launch) container-identity deployment model.
- Top-level state docs (`PROJECT_STATE.md`, `ARCHITECTURE.md`,
  `TEST_EVIDENCE.md`, `HANDOFF.md`, this file) were T5-era until the freeze
  commit refreshed them; keep them current with future tranches rather than
  letting them drift again.
