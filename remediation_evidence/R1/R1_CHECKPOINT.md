# R1 — Persistence authority and cross-process serialization

Status: **GREEN**

## Red-before basis

R0 reproduced the persistence split-brain and race failures before this batch:

- F01 — concurrent append could fork an append-only JSONL chain.
- F02 — two concurrent admissions could both observe an absent intent and append duplicates.
- F12 — a restart/retry race could fork the attempt chain.

The production implementation was unchanged when those observations were recorded in
`remediation_evidence/R0/red_before_result.json`.

## Smallest production change

- JSONL remains the sole domain authority.
- Each append log now has a sibling SQLite file used only as a transaction and serialization
  coordinator.
- A writer enters `BEGIN IMMEDIATE`, verifies the complete JSONL chain from disk, evaluates an
  optional conditional builder against that verified state, appends one canonical line, flushes
  and fsyncs it, and only then commits the coordination transaction.
- New rows carry a monotonic sequence number; verified legacy rows without a sequence remain
  readable and the next append receives the correct sequence.
- Evidence and evidence-pack manifests use the same append primitive rather than maintaining
  separate unsafe implementations.
- Coordinator sidecars are excluded from Git because they are runtime synchronization state,
  never audit authority.

## Verification

- Targeted R1 suite: **4/4 green** (`tests.test_remediation_r1_persistence`).
- Hostile cross-process append: **8 processes × 10 writes = 80 rows**, one verified chain with
  sequences 1–80.
- Conditional-append race: exactly one child appended and one failed closed with
  `RegistryConflict`.
- Torn/truncated JSONL: rejected before any write.
- Legacy-chain migration: verified and extended without rewriting history.
- Full suite: **32/32 green**.
- `python -m compileall -q src tests`: **green**.

## Scope check

No adapter, acquisition, strategy, model, provider, UI, cloud, credential, live-trading, chaos,
or canary scope was added.
