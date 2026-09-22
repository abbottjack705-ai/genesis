# Data dictionary

All timestamps are explicit UTC ISO-8601 values. All durable records carry a
stable identifier, schema/version information, and provenance where they
represent external evidence.

| Record | Required semantics |
|---|---|
| `EvidenceMetadata` | Full artifact hash, source/provider/type, retrieval, first-seen, parse-ready, publisher/validity timestamps, parser/version, content type, byte length, licensing note, availability class. |
| `SourceContract` | Provider URI pattern, timestamp precision, availability rule, parser version, historical/prospective support, and licensing/access note. |
| `Participant` | Persistent sport identity, canonical name, source references, confidence, and validity interval. |
| `Event` | Sport, scheduled start as known then, distinct participant IDs, venue, version, meeting/competition identifiers, and source references. |
| `MarketSnapshot` | Event/market/selection IDs, market type, observed/received/ready/published/validity timestamps, side, decimal odds, size, status, source sequence, provenance, and supersession reference. |
| `ResearchEvidence` | Structured claim category/status, exact source reference, source/retrieval/ready times, evidence span, freshness expiry, extractor/prompt-schema version, and contradiction links. |
| `DecisionFact` | One named value with availability and ready timestamps and one provenance reference. Future fields are rejected. |
| `DecisionFrame` | Immutable decision ID, entity, decision time, facts, dataset version, config digest. It is the only model-input envelope. |
| `FutureOutcomeLabel` | Separate label ID/entity/value, observed time, source reference, and label schema. It is never a `DecisionFact`. |
| `CandidateBet` | Versioned strategy/model, event/market/selection, requested/observed odds, raw and conservative probabilities, evidence pack/cutoff, decision hash, status dimensions, dependency/correlation identifiers, expiry, uncertainty, and gate reasons. |
| `EvidencePack` | Frozen cutoff/pack times, source artifact hashes, extractor versions, prompt schema hash, contradictions, freshness state, feature manifest hash, and immutable pack hash. |
| `FeatureInputManifest-v1` | Closed content-addressed sorted exact feature/evidence input references, event/market, cutoff and structured-evidence hashes; each required reference pins source contract/capability row, raw bytes, observation, PIT row and field/transform. S3a provenance only; it does not approve a model or tier rule. |
| `SourceInputBinding-v1` | Durable one-to-one source-contract/PIT-source/provider mapping with an approval reference; test synthetic bindings are not operational strategy authority. |
| `MarketCapability` | Separate data/model/venue/settlement/liquidity/strategy/live capability facts; any required false or unknown fact blocks qualification. |
| `CandidateRunRecord` | Every candidate stage/status, decision hash, rank, PASS reason, near-miss flag, and dependency group in an append-only run log. |
| `RiskApproval` / `Exposure` | Single-use candidate-linked approval and matched/partial/unmatched/pending/UNKNOWN liability state. |
| `OrderRecord` | Paper-only idempotent intent, V0.4 order state, and state history. |
| `FillRecord` / `LedgerEvent` | Actual fill and settlement/correction events used as the P/L source of truth. |
| `CoverageEntry` | Entity/source status, record time, reason codes, optional artifact hash, and optional supersession link. |
| `DatasetManifest` | Dataset/version, schema, artifacts, source contracts, availability policy, decision fields, disjoint future-label fields, and split definition. |
| `ExperimentSpec` | Hypothesis, mechanism, universe, dataset, features, target, search budget, periods, metrics, and immutable attempt count. |
| `StrategyArtifact` | Strategy/version, lifecycle, code/config/model digests, support region, and controlled approval reference. |
