from __future__ import annotations

import unittest
from pathlib import Path

from genesis.canonical import CandidateBet, MarketSide
from genesis.coverage import ExclusionLedger
from genesis.registry import (
    DatasetManifest,
    DatasetRegistry,
    ExperimentRegistry,
    ExperimentSpec,
    RegistryConflict,
    StrategyArtifact,
    StrategyLifecycle,
    StrategyRegistry,
)
from genesis.selection import qualify
from genesis.reasons import ReasonCode
from ._support import scratch_directory


class RegistryAndSelectionTests(unittest.TestCase):
    def test_attempt_budget_is_consumed_and_strategy_is_pass_first(self):
        with scratch_directory() as tmp:
            registry = ExperimentRegistry(tmp / "experiments.jsonl")
            registry.register(ExperimentSpec("x1", "family", None, "h", "m", "d1", "all", (), "y", 1, "train", "valid", None, ("brier",)))
            registry.record_attempt("x1", note="synthetic")
            with self.assertRaises(RegistryConflict):
                registry.record_attempt("x1", note="over-budget")
            replayed = ExperimentRegistry(tmp / "experiments.jsonl")
            with self.assertRaises(RegistryConflict):
                replayed.register(ExperimentSpec("x1", "family", None, "h", "m", "d1", "all", (), "y", 1, "train", "valid", None, ("brier",)))

            datasets = DatasetRegistry(tmp / "datasets.jsonl")
            datasets.register(DatasetManifest("d", "v1", "schema-v1", "2026-01-01T00:00:00Z", ("a" * 64,), ("source-v1",), "ready_at<=decision_at", ("x",), ("y",)))
            self.assertEqual(len(DatasetRegistry(tmp / "datasets.jsonl")._latest), 1)

            strategies = StrategyRegistry(tmp / "strategies.jsonl")
            strategies.register(StrategyArtifact("s", "v1", StrategyLifecycle.IDEA, "a" * 64, "b" * 64, "c" * 64, "test", "2026-01-01T00:00:00Z"))
            strategies.transition(
                "s", "v1", StrategyLifecycle.EXPLORATION,
                occurred_at="2026-01-01T00:01:00Z",
            )
            self.assertEqual(
                StrategyRegistry(tmp / "strategies.jsonl").current_head(
                    "s", "v1"
                ).lifecycle,
                StrategyLifecycle.EXPLORATION,
            )

            exclusions = ExclusionLedger(tmp / "coverage.jsonl")
            exclusions.append_exclusion(
                entry_id="x-e1", entity_id="e1", source_contract_id="source-v1",
                recorded_at="2026-01-01T00:00:00Z", reason_codes=(ReasonCode.AMBIGUOUS_IDENTITY,),
            )
            self.assertEqual(exclusions.verify(), 1)

        candidate = CandidateBet(
            "c1", "s1", "v1", "football", "e1", "m1", "sel1", MarketSide.BACK,
            "1.50", "2.30", "2.00", "0.60", "0.55", "model-v1", "pack-1",
            "2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z", True,
        )
        decision = qualify(
            candidate,
            now="2026-01-01T00:10:00Z",
            market_supported=True,
            strategy_approved=False,
            model_supported=True,
            evidence_fresh=True,
            price_sane=True,
            execution_available=True,
            risk_approved=True,
        )
        self.assertEqual(decision.action, "PASS")
