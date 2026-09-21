# R2 — PIT, evidence, and provenance causal identity

Status: **GREEN**

## Red-before basis

R0 recorded the production failures before this batch:

- F06 — a decision read could return an unchecked PIT record.
- F10 — identical raw bytes with a second legitimate observation collided at the
  artifact-keyed metadata path.
- F11 — a material structured-claim change left evidence-pack identity unchanged.

## Closed invariants

- A `PITStore` cannot be constructed without its `SourceCapabilityRegistry` authority.
- Source capability state is append-only/versioned and is selected as of the requested
  `decision_at`; later READY state cannot validate an earlier read.
- PIT admissibility now includes `retrieved_at <= decision_at` in addition to available,
  ready, validity, and supersession time.
- Raw content identity is only SHA-256 plus byte length. Each complete observation has a
  separate deterministic ID, exact duplicate publication is idempotent, and multiple
  observations of the same bytes are retained.
- Observation publication resolves and validates an exact append-only `SourceContract`;
  unknown, availability-substituted, provider/source/parser/licence/URI-incompatible claims
  fail closed.
- `ProvenanceRef` carries the exact observation ID for V2 authority.
- Every material `ResearchEvidence` field is canonical and digest-bearing; its structured
  store verifies that provenance resolves to the exact immutable observation and raw object.
- Evidence-pack V2 identity includes structured evidence hashes and verifies their existence.
  Pre-audit packs remain replayable but are explicitly audit-only.
- A structured claim or exact observation change therefore changes the research digest,
  evidence-pack hash, and candidate-decision hash.

## Matrix evidence

- T-F06-001..009: mandatory authority, unknown/blocked handling, future-ready and
  future-retrieval rejection, feature-view enforcement, ingestion/read separation,
  versioned readiness, and existing supersession behavior are green.
- T-F10-001..010: multi-observation raw content, exact replay, parser/content-type variants,
  tamper/missing-artifact detection, deterministic legacy import, deterministic observation
  replay, availability substitution, and unknown-contract rejection are green.
- T-F11-001..009: claim/status/span/contradiction/observation mutation, deterministic digest,
  missing structured object, legacy pack, and complete identity propagation are green.

## Verification

- Targeted R2 suite: **9/9 green** (`tests.test_remediation_r2_causal_evidence`).
- Full suite: **41/41 green**.
- `python -m compileall -q src tests`: **green**.
- `git diff --check`: no whitespace errors (only platform line-ending notices).

## Scope check

No source adapter, data acquisition, strategy/model, provider API, UI, cloud, credential,
live-trading, chaos, or canary scope was added.
