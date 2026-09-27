"""E8: a write's preconditions are decided on durable history, in its transaction.

Invariant: the dataset, experiment and PIT stores check uniqueness and budget
against the verified log inside the append's own critical section, never
against a cache an instance built earlier. Two instances opened over one log
therefore cannot both succeed where one history allows only one write, what
any live instance reports equals what a fresh instance replays, and a durable
history that already breaks those rules (as a pre-E8 race could leave) fails
closed on replay instead of silently picking one row.
"""

from __future__ import annotations

import threading
import unittest

from genesis.pit import (
    BitemporalRecord, OperationalStatus, PITStore, SourceCapability, SourceCapabilityRegistry,
)
from genesis.registry import (
    AppendOnlyJsonl, DatasetManifest, DatasetRegistry, ExperimentRegistry, ExperimentSpec,
    RegistryConflict,
)

from ._support import scratch_directory


def spec(budget: int = 1) -> ExperimentSpec:
    return ExperimentSpec(
        experiment_id="exp", family="fam", parent_id=None, hypothesis="h", mechanism="m",
        dataset_version="d1", eligibility_definition="e", features=("f",), target="t",
        search_budget=budget, training_period="tr", validation_period="va",
        protected_period=None, primary_metrics=("m",),
    )


def manifest(policy: str) -> DatasetManifest:
    return DatasetManifest(
        dataset_id="ds", version="v1", schema_version="1", created_at="2026-01-01T00:00:00Z",
        artifact_hashes=("a" * 64,), source_contract_ids=("c",), availability_policy=policy,
        decision_time_fields=("x",), future_label_fields=("y",),
    )


def capabilities(root) -> SourceCapabilityRegistry:
    registry = SourceCapabilityRegistry(root / "sources.jsonl")
    registry.register(SourceCapability(
        source_id="src", provider="p", access_method="m", cost_tier="t",
        entitlement_class="e", historical_availability_class="h",
        point_in_time_reliability="verified", revision_behaviour="r", coverage="c",
        rate_quota_limits="q", schema_version="1", operational_status=OperationalStatus.READY,
        recorded_at="2025-12-31T00:00:00Z", version="v1",
    ))
    return registry


def pit_record(payload: str) -> BitemporalRecord:
    return BitemporalRecord(
        record_id="r1", entity_id="e1", source_id="src", payload_hash=payload * 64,
        available_at="2026-01-01T00:00:00Z", published_at=None,
        retrieved_at="2026-01-01T00:00:00Z", ready_at="2026-01-01T00:00:00Z",
        valid_from="2026-01-01T00:00:00Z",
    )


class T6E8DurablePreconditionTests(unittest.TestCase):
    def test_e8_experiment_budget_holds_across_instances(self):
        with scratch_directory() as root:
            path = root / "experiments.jsonl"
            ExperimentRegistry(path).register(spec(budget=1))
            first, second = ExperimentRegistry(path), ExperimentRegistry(path)
            self.assertEqual(first.record_attempt("exp", note="a").attempts_used, 1)
            with self.assertRaises(RegistryConflict):
                second.record_attempt("exp", note="b")
            attempts = [row for row in AppendOnlyJsonl(path).records()
                        if row["record_type"] == "experiment_attempt"]
            self.assertEqual(len(attempts), 1)
            for view in (first, second, ExperimentRegistry(path)):
                self.assertEqual(view.get("exp").attempts_used, 1)

    def test_e8_concurrent_attempts_never_exceed_the_budget(self):
        with scratch_directory() as root:
            path = root / "experiments.jsonl"
            ExperimentRegistry(path).register(spec(budget=2))
            instances = [ExperimentRegistry(path) for _ in range(6)]
            barrier = threading.Barrier(len(instances))
            outcomes: list[str] = []

            def attempt(registry: ExperimentRegistry) -> None:
                barrier.wait(30)
                try:
                    registry.record_attempt("exp", note="c")
                    outcomes.append("ok")
                except RegistryConflict:
                    outcomes.append("refused")

            threads = [threading.Thread(target=attempt, args=(item,)) for item in instances]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(60)
            self.assertEqual(sorted(outcomes), ["ok", "ok"] + ["refused"] * 4)
            replayed = ExperimentRegistry(path)
            self.assertEqual(replayed.get("exp").attempts_used, 2)
            self.assertEqual(
                [row["attempt_number"] for row in AppendOnlyJsonl(path).records()
                 if row["record_type"] == "experiment_attempt"],
                [1, 2],
            )

    def test_e8_experiment_registration_is_unique_across_instances(self):
        with scratch_directory() as root:
            path = root / "experiments.jsonl"
            first, second = ExperimentRegistry(path), ExperimentRegistry(path)
            first.register(spec(budget=1))
            with self.assertRaises(RegistryConflict):
                second.register(spec(budget=5))
            self.assertEqual(ExperimentRegistry(path).get("exp").search_budget, 1)
            self.assertEqual(second.get("exp").search_budget, 1)

    def test_e8_dataset_version_is_unique_across_instances(self):
        with scratch_directory() as root:
            path = root / "datasets.jsonl"
            first, second = DatasetRegistry(path), DatasetRegistry(path)
            first.register(manifest("first"))
            with self.assertRaises(RegistryConflict):
                second.register(manifest("second"))
            self.assertEqual(len(AppendOnlyJsonl(path).records()), 1)
            for view in (first, second, DatasetRegistry(path)):
                self.assertEqual(view._latest[("ds", "v1")].availability_policy, "first")

    def test_e8_one_pit_record_id_has_one_payload_across_instances(self):
        with scratch_directory() as root:
            registry = capabilities(root)
            first = PITStore(root / "pit.jsonl", capabilities=registry)
            second = PITStore(root / "pit.jsonl", capabilities=registry)
            first.append(pit_record("a"))
            with self.assertRaises(RegistryConflict):
                second.append(pit_record("b"))
            second.append(pit_record("a"))  # the same record again is idempotent
            self.assertEqual(len(AppendOnlyJsonl(root / "pit.jsonl").records()), 1)
            for view in (first, second, PITStore(root / "pit.jsonl", capabilities=registry)):
                [found] = view.as_of_query("e1", "2026-01-01T00:01:00Z")
                self.assertEqual(found.payload_hash, "a" * 64)

    def test_e8_a_history_a_pre_e8_race_could_leave_fails_closed(self):
        with scratch_directory() as root:
            experiments = root / "experiments.jsonl"
            ExperimentRegistry(experiments).register(spec(budget=1))
            for _ in range(2):
                AppendOnlyJsonl(experiments).append({
                    "record_type": "experiment_attempt", "experiment_id": "exp",
                    "attempt_number": 1, "note": "raced",
                })
            with self.assertRaises(RegistryConflict):
                ExperimentRegistry(experiments).get("exp")

            datasets = root / "datasets.jsonl"
            for policy in ("first", "second"):
                AppendOnlyJsonl(datasets).append(
                    {"record_type": "dataset_registered", **manifest(policy).to_dict()}
                )
            with self.assertRaises(RegistryConflict):
                DatasetRegistry(datasets)

            registry = capabilities(root)
            for payload in ("a", "b"):
                AppendOnlyJsonl(root / "pit.jsonl").append(
                    {"record_type": "pit_record", **pit_record(payload).to_dict()}
                )
            with self.assertRaises(RegistryConflict):
                PITStore(root / "pit.jsonl", capabilities=registry)


if __name__ == "__main__":
    unittest.main()
