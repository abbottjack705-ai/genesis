# adapters/DECISIONS

Reserved for **human** approval records (for example `ADR-A001`, the acceptance record for
the slice-1 architecture at its commit SHA). The implementing model does not create, edit or
append any gate or approval record, and no ADR here is marked ACCEPTED.

Currently empty on purpose. Gate records G1/G2/G2R/G3 live in the runtime ledger
`authority.jsonl`, which is operator-owned (design section 16.6) and never committed.
