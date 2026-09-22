# ADR-0002 v1: exact S3 input manifest and candidate-v3 decision identity

Date drafted: 2026-09-22

Status: **PROPOSED — NOT APPROVED; no S3 implementation authority**

Scope: Astra A5 then A4, offline/PAPER foundation only. This record is the
exact contract proposed for the explicit human decision required by Project
Genesis §38. Approval to *draft* it is not approval to implement it.

## Decision and authority boundary

1. Preserve every existing `candidate-v1` and `candidate-v2` record, the
   current `candidate_decision_hash()`/`DECISION_HASH_FIELDS` algorithm, and
   their persisted hash values and historical replay **unchanged**. The S3
   plan's phrase “next candidate-v2” conflicts with the repository: R3 already
   makes `candidate-v2` eligible. The new schema is `candidate-v3`, with a
   distinct `candidate-decision-v3` hash domain. No old record is relabelled,
   rehashed, or silently upgraded.
2. `FeatureInputManifest-v1` is the immutable exact set of inputs required by
   a frozen evidence pack at its `evidence_cutoff_ts`. `DecisionOutput-v1` is
   an immutable output from a trusted, pinned deterministic resolver, not a
   caller-supplied `CandidateBet` assertion. The v3 candidate hash binds both
   artifact identities. A merely self-hashed object is not trusted authority.
3. This ADR approves **no** model, calibration, strategy-specific tier formula,
   tier cutoffs, expiry duration/TTL, or expiry derivation. Runtime may create
   a risk-authorising v3 qualification only when separately approved, active,
   exact strategy-specific resolver/rule bindings exist and reproduce every
   material output. Until then, operational qualification is `PASS`/blocked.
   Deterministic synthetic, test-scoped rules may prove plumbing but cannot
   become operational authority.

## Canonical encoding and artifact IDs

All three new contracts below use closed schemas: unknown keys, omitted required
keys, duplicate keys, implicit defaults and unsupported versions fail closed.
Hash IDs are lowercase 64-character SHA-256 hex of the unsigned contract's
`canonical_json` bytes (UTF-8, sorted keys, compact separators, terminal LF).
The ID itself is not part of those bytes. Domain/schema strings are included
in each unsigned body; IDs from another domain cannot substitute. JSON numbers
are forbidden for decision-material numeric values. Decimal values are finite,
nonnegative where appropriate, and encoded as canonical plain strings with no
exponent, leading `+`, negative zero or redundant trailing zeros (`0`, not
`0.0`); probability values are in `[0,1]`, and odds must exceed 1. Timestamps
are explicit UTC strings normalized to `YYYY-MM-DDTHH:MM:SS.ffffffZ` before
hashing; naive/non-UTC inputs are rejected. Ordered lists retain declared
order; set-like lists are unique and sorted lexically before hashing. Empty
strings and placeholder/digest-shaped-but-unresolved IDs are not proof.

## A5: `FeatureInputManifest-v1`

The unsigned manifest has exactly these top-level fields:

```text
domain = "genesis.feature-input-manifest.v1"
schema_version = "feature-input-manifest-v1"
event_id, market_id, evidence_cutoff_ts
required_inputs: nonempty sorted array of InputRef-v1
structured_evidence_hashes: nonempty sorted array of verified digests
```

Each `InputRef-v1` has exactly: `role` (`feature` or `evidence`), `input_key`,
`entity_id`, `event_id`, `market_id`, `source_id`, `source_contract_id`,
`source_capability_version`, `source_capability_record_hash`,
`raw_artifact_hash`, `observation_id`, `pit_record_id`, `pit_record_hash`,
`field_id`, and `transform_artifact_hash`. For `feature`, the last two fields
must identify the exact required field and approved deterministic transform;
for `evidence`, they are explicit `null`. Each pair (`role`, `input_key`) is
unique. Sorting is by the canonical tuple (`role`, `input_key`, `entity_id`,
`source_id`, `observation_id`, `pit_record_id`); conflicting duplicate keys or
records are invalid. A genuinely direct/identity transform still requires a
pinned approved transform identity; `null` is not a permissive feature default.

`manifest_hash = SHA256(canonical_json(unsigned manifest))`. The existing
`EvidencePack.feature_manifest_hash` must equal this hash. The manifest **does
not** contain `pack_hash`, avoiding a circular hash. The pack's
`evidence_cutoff_ts` must equal the manifest cutoff. Its distinct
`source_artifact_hashes` must equal the distinct raw hashes represented in
`required_inputs`, and its `structured_evidence_hashes` must equal the
manifest's verified structured-evidence hashes. Every structured evidence
source observation must resolve to a matching exact `InputRef`; no unrelated
same-event PIT row can satisfy a required input. Additional unrelated PIT rows
are ignored, not substituted.

For **every** required input, the resolver must load the actual immutable raw
bytes, observation, source contract, selected source-capability row and PIT
record by these exact IDs/hashes. It verifies all cross-links (including the
approved source-contract-to-source mapping, provider, event/market/entity,
payload/raw hash, field and transform) and checks publication/availability,
retrieval, parse/PIT readiness, validity and supersession at the manifest's
**evidence cutoff**. A hash-shaped reference without the corresponding object,
an unknown capability, a later observation/retrieval, an unready source, or an
ambiguous PIT head is a `PASS`/block. A later revision cannot retroactively
replace the selected as-of-cutoff input. Strategy lifecycle and market
capability remain checked at the prescribed decision time; S1 current market
and safety recertification remains an action-time check. The frozen pack must
have existed by decision time (`frozen_at <= decision_at`).

## A4: trusted `DecisionOutput-v1`

The unsigned output has exactly these fields (all required; only explicitly
named nullable values may be `null`):

```text
domain = "genesis.decision-output.v1"
schema_version = "decision-output-v1"
feature_manifest_hash, evidence_pack_hash
strategy_decision_contract_hash, strategy_config_hash
odds_profile_hash, sport_adapter_version, market_capability_id
model_artifact_hash, calibration_artifact_hash, gate_policy_hash
model_runner_hash, calibration_runner_hash
tier_rule_hash, expiry_rule_hash, resolver_binding_hash
strategy_id, strategy_version, model_version
sport, market_family, event_id, market_id, selection_id, side
evidence_cutoff_ts, decision_at
model_probability, calibrated_probability, conservative_probability
model_support_status, calibration_status, uncertainty_status
critical_uncertainty_flags, support_region_id
observed_odds, requested_odds_min, requested_odds_max
approved_tier, expires_at
comparability_group_id, selection_dependency_group
correlation_cluster_ids, meeting_id, competition_id
participant_ids, shared_evidence_ids
```

`meeting_id`, `competition_id` and `selection_dependency_group` are explicitly
nullable; all other scalar identities are nonempty. The three ID arrays and
uncertainty-flags array are unique sorted strings (possibly empty). `side` is
the canonical BACK/LAY value. Price bounds are ordered and the observed odds
are evaluated against the approved odds profile and existing price policy;
this record does not change either. `approved_tier` must be one of the existing
five approved tiers **and must be reproduced by the exact approved strategy
tier rule**; membership alone never authorises it. `expires_at` must be later
than `decision_at` and reproduced by the exact approved strategy expiry rule;
this ADR defines no duration. `comparability_group_id` is the approved
ranking-support group; correlation/dependency identifiers remain distinct.
Evidence completeness, contradiction/freshness, model/support/calibration and
uncertainty gate facts must be recomputed from the verified inputs/approved
artifacts; a copied status flag cannot bypass a gate.

`decision_output_hash = SHA256(canonical_json(unsigned output))`. The
strategy's exact active `StrategyDecisionContract` and a separately approved
`StrategyOutputRuleBinding-v1` must pin the resolver/model/calibration runners
and the exact strategy-specific tier and expiry rules. Its closed unsigned
schema is: domain `genesis.strategy-output-rule-binding.v1`, schema version,
`strategy_decision_contract_hash`, `active_policy_digest`,
`approved_tier_policy_id`, `model_artifact_hash`,
`calibration_artifact_hash`, `feature_manifest_hash`, `gate_policy_hash`,
`model_runner_hash`, `calibration_runner_hash`, `tier_rule_hash`,
`expiry_rule_hash`, `resolver_artifact_hash`, `scope=PAPER`, `valid_from`,
`valid_through` (explicitly nullable), and `human_approval_reference`.
`resolver_binding_hash` is the canonical hash of that unsigned body. Every
overlapping field must match the active strategy contract/policy/output
exactly. The binding cannot be created or activated by a candidate/research
caller, cannot apply before its approved validity window, and a revoked or
ambiguous binding is unavailable. No operational binding or strategy-specific
rule is approved by this ADR. The trusted resolver must execute
or independently verify those pinned deterministic rules over the exact A5
manifest/pack and persist the output atomically or content-address it before
qualification. It must re-read and verify the object on restart. A caller may
present an output hash, but cannot assert `verified=True` or supply its own
economic values as authority.

## `candidate-v3` / `candidate-decision-v3` identity

The v3 hash preimage is exactly this closed object, after resolving and
verifying the two artifact IDs:

```json
{
  "domain": "genesis.candidate-decision.v3",
  "schema_version": "candidate-decision-v3",
  "strategy_decision_contract_hash": "<64-hex>",
  "feature_manifest_hash": "<64-hex>",
  "evidence_pack_hash": "<64-hex>",
  "decision_output_hash": "<64-hex>"
}
```

`candidate_decision_hash = SHA256(canonical_json(that preimage))`. The output
and manifest carry the exact event/market/selection/side, cutoff/time, model,
calibration, price, probability, uncertainty, tier, expiry, comparability and
dependence facts; all repeated hashes/fields in candidate, pack, contract,
manifest and output must match exactly. A copied v3 hash with any altered
material field is rejected, not repaired or interpreted as a different valid
decision. A genuinely different verified output or input produces a different
v3 hash. `candidate_id` remains a non-authoritative run/display reference; it
cannot alter the hash or permit a second order for the same hash.

`CandidateBet` and research/selection callbacks may carry copies for display
and mismatch detection only. Qualification and ranking must resolve their
authoritative immutable v3 values from the verified output, not from those
copies. Risk continues to take the tier from the durable QualificationRecord
(D-REM-007), after checking its exact output/candidate lineage; it must not
take units from the caller. The new `qualification-record-v3` must include the exact
`decision_output_hash`, `feature_manifest_hash`, v3 candidate hash, derived
tier and expiry; risk and order bind that same qualification/candidate lineage.
The existing one-candidate-hash/one-intent rule and single-use approval remain.

## Legacy, failure and activation rules

- v1/v2 candidate hashes and their historical qualification/risk/order events
  remain readable with their original meaning. Existing sent/matched orders
  may reconcile and settle under R7/S1; no old record is rewritten. An old
  unbound candidate or qualification is **audit-only for new qualification,
  risk approval, pending or sent submission** after S3b activation. S3a is an
  independently reviewed partial A5 checkpoint, not an A4 closure.
- Missing or incompatible manifest, pack, observation, capability, trusted
  output, resolver, rule binding or approval causes `PASS`/block with an
  explicit reason. It never falls back to a same-event row, a caller field,
  an arbitrary TTL, a default tier, or a legacy hash. All candidates and PASS
  reasons remain retained in the run log.
- An approved S3 schema alone does not create an operational strategy. With
  no independently approved strategy-specific tier/expiry/model resolver,
  operational `QUALIFY` remains disabled. Synthetic deterministic fixtures
  are test-only and cannot be promoted by a configuration switch or copied
  into the operational authority store without a later human decision.
- No odds range, price tolerance, staking unit, risk percentage, quota
  Interpretation A, hold-to-settlement rule, PAPER-only state, protected
  attempt/label boundary, or GO status changes here. S3 does not create a
  real adapter, model, protected campaign or live path.

## Required implementation gate after explicit approval

S3a (A5) precedes S3b (A4). Each gets new independent RED assertions on the
isolated clean `166f923` and immediately preceding green commit, then the
smallest fix, targeted and original Astra probes, restart/parallel/crash
checks, all retained R0–R10/S1/S2 tests, full `unittest discover` and
`compileall`, exact evidence/hashes, diff review and one green commit. S3a
cannot claim A4 closed. S3b must test individual swaps of probability,
uncertainty, observed price/band, permitted-tier substitution, expiry,
dependence and artifact/rule identities; forged/self-hashed or unsupported
output; valid deterministic replay; conflicting same-hash two-process
publication; crash between output and qualification; and legacy audit replay.
Neither stage grants adapter, shadow-research or live-money GO. A fresh
independent hostile re-audit remains mandatory.

## Approval requested

The operator must explicitly approve **this exact ADR version** before S3
production code or authoritative data migration is changed. Approval must be
recorded in a separate versioned `DECISIONS/` approval note citing this draft's
SHA-256, approver, UTC date and any amendments, avoiding a self-referential
hash inside the draft. The approved content must remain immutable. If any
field, canonicalization rule, legacy treatment or protected PIT/identity
behavior changes materially, publish a new proposed version and seek approval
again. This proposed record is not itself an approval.
