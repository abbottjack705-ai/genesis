# Operations runbook

Current allowed mode: `OFFLINE_RESEARCH`.

The intended future modes are `SHADOW`, `PAPER`, `MICRO_LIVE`, and `LIVE`,
but no transition or broker adapter is implemented. Mode changes must be
audited and cannot be initiated by a research agent. Any future execution
service must be the only component holding order credentials and must stop new
placement on stale feeds, unknown account state, duplicate-order risk,
strategy quarantine, or accounting-integrity failure.

For now, run only the synthetic test suite and inspect append-only artifacts.
Do not add credentials to this repository.

