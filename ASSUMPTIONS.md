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
