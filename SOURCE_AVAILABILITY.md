# Source availability contract

## Rules

1. A source value is decision-usable only when both `available_at` and
   `ready_at` are no later than the decision timestamp.
2. Naive timestamps, non-UTC timestamps, and unknown availability classes fail
   closed.
3. Retrieval time, publisher/source time, parse-ready time, and decision time
   are separate fields. A retrospective timestamp is not evidence of a
   historical capture.
4. Raw bytes are evidence; parsed projections are derived artifacts and carry
   the raw artifact hash and parser version.
5. Corrections add a new artifact/manifest record. They cannot replace a
   previous source record.
6. Decision/model code must use the controlled `PITStore.as_of_query` or
   `feature_view` interface; unrestricted historical-table access is not an
   admissible foundation contract.
7. Source capability status, point-in-time reliability, revision behaviour,
   coverage, quota, schema, and entitlement must be explicitly READY before a
   source can support a decision. Unknown is fail-closed.

## Availability classes

- `historical_reconstructed`: use only with a documented, conservative
  historical availability rule; it is not automatically equivalent to a live
  capture.
- `prospective_captured`: captured and made parse-ready before decision time.
- `live_received`: a future execution-stage class, not enabled here.
- `derived`: computed only from admissible earlier records.
- `assumed`: explicit assumption, never silently promoted to evidence.
- `future_label`: outcomes/settlement data; forbidden in decision frames.
- `unknown`: quarantined and unusable.

No external source is currently active. The synthetic source capability and
bitemporal PIT interfaces are tested foundation contracts only. Betfair,
Hoofs, Race Shape, football, and tennis sources need separate contracts before
ingestion. The legacy MLB chronology is evidence for design lessons only, not
an active Genesis source.
