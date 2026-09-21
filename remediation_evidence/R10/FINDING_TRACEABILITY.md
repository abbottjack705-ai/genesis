# F01–F15 implementation traceability

This map names the production modules/functions changed by remediation, their
green batch commit and the primary regression evidence. Closely related matrix
rows are intentionally grouped into behavior-focused test methods.

| Finding | Exact remediated production locations | Green commit | Primary tests/evidence |
|---|---|---|---|
| F01 authoritative qualification | `registry.py::StrategyDecisionContract`, `StrategyRegistry.lifecycle_at`; `decision.py::decision_hash_for_candidate`; `capabilities.py::MarketCapabilityRegistry.require_ready_at`; `selection.py::QualificationAuthority.evaluate`, `QualificationRecordStore.append`, audit-only `qualify_v04` | `f42bd8d` | `R3QualificationAuthorityTests`; R3 checkpoint |
| F02 candidate order uniqueness | `execution.py::PaperExecutionAdapter._replay`, `create_intent`; `registry.py::AppendOnlyJsonl.transaction` | `8bb86f3` (`afc56b7` primitive) | `R6OrderUniquenessTests`; R6 checkpoint |
| F03 exact genuine risk binding | `risk.py::RiskEngine.get_approval`, `consume_for_order`; `execution.py::OrderIntent`, `PaperExecutionAdapter.bind_risk`, `transition`, `recertify` | `8bb86f3` | `R6RiskBindingTests`, `R6RestartAndRecertificationTests` |
| F04 settlement lineage | `ledger.py::FillRecord.fragment`, `SettlementLedger._event_from_row`, `_replay`, `_settle`, `settle`, `record_cancellation`, `head`, `total_pnl` | `b1f22e5` | `R7SettlementLineageTests`; R7 RED/GREEN |
| F05 3u/exact risk derivation | `policy.py::RiskPolicy`, `parse_tier`; `risk.py::BankrollSnapshotStore.current`, `SafetyStateStore.current`, `RiskApproval`, `RiskEngine.approve`, `stake_for_units`, `reserved_exposures`, `transition_reservation` | `28d5013` | `R5RiskAuthorityTests`; R5 checkpoint |
| F06 mandatory PIT capability | `pit.py::SourceCapabilityRegistry.require_ready_at`, `BitemporalRecord.admissible_at`, `PITStore.__init__`, `as_of_query`, `feature_view` | `f8f91ff` | `R2PITAuthorityTests`; R2 checkpoint |
| F07 no short-price rank bias | `selection.py::rank_qualified`; retained `policy.py::assess_price_sanity` eligibility gate | `169ef9d` | `R4RankingTests`; R4 checkpoint |
| F08 no label/market lexical rank bias | `selection.py::rank_qualified` deterministic group queues and round-robin | `169ef9d` | `R4RankingTests`; R4 checkpoint |
| F09 fail-closed tier | `policy.py::RiskPolicy`, `parse_tier`; `selection.py::QualificationAuthority.evaluate`, `rank_qualified`; `risk.py::RiskEngine.approve` | `f42bd8d`, `28d5013` | `R3StrictTierTests`, R5 tier tests |
| F10 content vs observation identity | `provenance.py::SourceContractRegistry`, `ProvenanceRef`; `evidence.py::EvidenceContent`, `EvidenceObservation`, `EvidenceStore.publish`, `import_legacy_metadata` | `f8f91ff` | `R2ObservationIdentityTests`; R2 checkpoint |
| F11 structured evidence freeze | `canonical.py::ResearchEvidence`; `evidence.py::StructuredEvidenceStore.publish`; `evidence_pack.py::EvidencePack.freeze`, `EvidencePackStore.freeze`, `use_authoritatively`; `decision.py::decision_hash_for_candidate` | `f8f91ff` | `R2StructuredEvidenceTests`; R2 checkpoint |
| F12 append concurrency | `registry.py::AppendOnlyJsonl._verified_records`, `transaction`, `append`; `evidence.py` and `evidence_pack.py` manifest writers routed through the same primitive | `afc56b7` | `R1PersistenceTests`; R10 20-run stress and process-death test |
| F13 protected isolation | `evaluation.py::LegacyInProcessEvaluationHarness` explicit unsafe name; `protected.py::SealedFrameSet`, `FrozenPredictionArtifact`, `ProtectedCampaignRegistry.register`, `ProtectedAttemptLedger.reserve_trusted`, `_trusted_evaluator_worker`, `ProtectedEvaluationClient.submit/run`, `launch_trusted_protected_evaluator` | `128d392` | `R9ProtectedIsolationTests`; R9 RED/GREEN |
| F14 quota semantics | `quota.py::QuotaPolicy`, `load_quota_policy`, `QuotaReserveAuthorization`, `QuotaLedger._replay`, `grant_authorization`, `revoke_authorization`, `request`, `allow_cached_or_block`; `config/oddspapi_quota_policy_v2.json` | `d486297` | `R8QuotaPolicyTests`; R8 RED/GREEN |
| F15 restart durability | `risk.py::RiskEngine._exposures`, `get_approval`, `reserved_exposures`, `transition_reservation`; `execution.py::PaperExecutionAdapter.__init__`, `_replay`, `_current_records`, `get`, `bind_risk`; durable mode/safety stores | `28d5013`, `8bb86f3` | R5 restart test; R6 fault/restart tests; R10 17-order/7-risk matrix |

## Batch file provenance

- R1 `afc56b7`: `registry.py`, `evidence.py`, `evidence_pack.py`.
- R2 `f8f91ff`: `canonical.py`, `evidence.py`, `evidence_pack.py`, `pit.py`,
  `provenance.py`.
- R3 `f42bd8d`: `canonical.py`, `capabilities.py`, `decision.py`, `policy.py`,
  `registry.py`, `selection.py`.
- R4 `169ef9d`: `selection.py`.
- R5 `28d5013`: `policy.py`, `risk.py`.
- R6 `8bb86f3`: `execution.py`, `risk.py`.
- R7 `b1f22e5`: `ledger.py`.
- R8 `d486297`: `quota.py`, active quota config.
- R9 `128d392`: `evaluation.py`, `protected.py`, `registry.py`.
- R10: no production module changed; integrated test/document/evidence only.

The exact per-commit file lists are reproducible with
`git show --name-only <commit>`.
