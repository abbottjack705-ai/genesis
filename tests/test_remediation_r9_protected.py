from __future__ import annotations

import json
import os
import threading
import unittest
from pathlib import Path

from genesis.evaluation import EvaluationRequest, ProtectedEvaluationError
from genesis.labels import DecisionFact, DecisionFrame, FutureOutcomeLabel
from genesis.protected import (
    FrozenPredictionArtifact,
    LegacyUnsafeProtectedEvaluationBoundary,
    ProtectedAttemptLedger,
    ProtectedCampaign,
    ProtectedCampaignRegistry,
    ResearchProgramRef,
    SealedFrameSet,
    launch_trusted_protected_evaluator,
)
from genesis.provenance import AvailabilityClass, ProvenanceRef
from genesis.registry import ExperimentRegistry, ExperimentSpec, RegistryConflict
from genesis.repro import canonical_json
from ._support import scratch_directory


def digest(character: str) -> str:
    return character * 64


def ref() -> ProvenanceRef:
    return ProvenanceRef(
        digest("a"),
        "synthetic-v1",
        "synthetic://protected",
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:01Z",
        AvailabilityClass.PROSPECTIVE_CAPTURED,
        "test-v1",
    )


def make_frames(count: int, *, changed: bool = False) -> tuple[DecisionFrame, ...]:
    return tuple(
        DecisionFrame(
            f"frame-{index}",
            f"entity-{index}",
            "2026-01-01T00:00:00Z",
            (
                DecisionFact(
                    "signal",
                    (index + 1 if changed else index) % 2,
                    "2025-12-31T23:00:00Z",
                    "2025-12-31T23:01:00Z",
                    ref(),
                ),
            ),
            "dataset-v1",
            digest("b"),
        )
        for index in range(count)
    )


def labels_for(
    frames: tuple[DecisionFrame, ...],
    outcomes: tuple[object, ...] | None = None,
) -> tuple[FutureOutcomeLabel, ...]:
    values = outcomes or tuple(index % 2 for index in range(len(frames)))
    return tuple(
        FutureOutcomeLabel(
            f"label-{index}",
            frame.entity_id,
            values[index],
            "2026-01-01T01:00:00Z",
            ref(),
            "label-v1",
        )
        for index, frame in enumerate(frames)
    )


def signal_program(frame: DecisionFrame) -> str:
    return "0.9" if frame.values()["signal"] else "0.1"


def half_program(_frame: DecisionFrame) -> str:
    return "0.5"


def failing_program(_frame: DecisionFrame) -> str:
    raise RuntimeError("secret detail")


def build_fixture(
    root: Path,
    *,
    count: int = 2,
    max_attempts: int = 3,
    minimum_cell_size: int = 1,
    campaign_id: str = "campaign-1",
):
    frames = make_frames(count)
    sealed = SealedFrameSet.create(
        campaign_id=campaign_id,
        dataset_version="dataset-v1",
        frames=frames,
    )
    experiments = ExperimentRegistry(root / "experiments.jsonl")
    experiments.register(
        ExperimentSpec(
            experiment_id="experiment-1",
            family="family-1",
            parent_id=None,
            hypothesis="protected synthetic",
            mechanism="calibration",
            dataset_version="dataset-v1",
            eligibility_definition="sealed frame set",
            features=("signal",),
            target="future label",
            search_budget=max_attempts,
            training_period="train",
            validation_period="validation",
            protected_period="protected",
            primary_metrics=("brier",),
        )
    )
    campaign = ProtectedCampaign.create_registered(
        campaign_id=campaign_id,
        family_id="family-1",
        max_attempts=max_attempts,
        evaluator_digest=digest("e"),
        minimum_cell_size=minimum_cell_size,
        experiment_id="experiment-1",
        sealed_frames=sealed,
        registered_at="2026-01-01T00:00:00Z",
    )
    campaigns = ProtectedCampaignRegistry(root / "campaigns.jsonl")
    campaigns.register(campaign, experiments)
    attempts = ProtectedAttemptLedger(root / "attempts.jsonl")
    return {
        "root": root,
        "frames": frames,
        "sealed": sealed,
        "experiments": experiments,
        "campaign": campaign,
        "campaigns": campaigns,
        "attempts": attempts,
    }


def launch(fixture, *, outcomes=None, allow_fault_injection: bool = False):
    trusted_labels = labels_for(fixture["frames"], outcomes)
    research_workdir = fixture["root"] / "research-worker"
    research_workdir.mkdir(exist_ok=True)
    client = launch_trusted_protected_evaluator(
        campaign=fixture["campaign"],
        sealed_frames=fixture["sealed"],
        labels=trusted_labels,
        campaigns=fixture["campaigns"],
        experiments=fixture["experiments"],
        attempts=fixture["attempts"],
        family_limit=fixture["campaign"].max_attempts,
        research_workdir=research_workdir,
        allowed_program_import_roots=(Path(__file__).resolve().parents[1],),
        allow_fault_injection=allow_fault_injection,
        local_checkpoint_test_only=True,
    )
    return client


def request(
    fixture,
    *,
    strategy: str = "strategy-1",
    program: ResearchProgramRef | None = None,
    rules_digest: str | None = None,
) -> EvaluationRequest:
    return EvaluationRequest(
        fixture["campaign"].campaign_id,
        strategy,
        program.program_digest if program is not None else digest("c"),
        "dataset-v1",
        rules_digest or fixture["campaign"].evaluator_digest,
    )


def contains_label_object(value, seen: set[int] | None = None, depth: int = 0) -> bool:
    if isinstance(value, FutureOutcomeLabel):
        return True
    if depth > 5 or isinstance(value, (str, bytes, int, float, bool, type(None))):
        return False
    seen = seen or set()
    if id(value) in seen:
        return False
    seen.add(id(value))
    if isinstance(value, dict):
        return any(contains_label_object(item, seen, depth + 1) for item in value.values())
    if isinstance(value, (tuple, list, set)):
        return any(contains_label_object(item, seen, depth + 1) for item in value)
    if value.__class__.__module__.startswith("multiprocessing"):
        return False
    return contains_label_object(getattr(value, "__dict__", {}), seen, depth + 1)


class R9ProtectedIsolationTests(unittest.TestCase):
    def test_research_client_has_no_labels_and_strategy_runs_outside_evaluator(self):
        with scratch_directory() as root:
            fixture = build_fixture(root)
            client = launch(fixture)
            try:
                self.assertNotEqual(client.evaluator_pid, os.getpid())
                self.assertNotEqual(client.research_pid, os.getpid())
                self.assertNotEqual(client.research_pid, client.evaluator_pid)
                self.assertFalse(contains_label_object(client))
                self.assertNotIn("label", " ".join(client.__dict__).lower())
                program = ResearchProgramRef.from_callable(signal_program)
                certificate = client.run(request(fixture, program=program), program)
                self.assertEqual(client.last_research_pid, client.research_pid)
                self.assertEqual(certificate.metrics["brier"], "0.01")
                self.assertFalse(certificate.raw_labels_exposed)
                self.assertEqual(certificate.frame_manifest_hash, client.frame_manifest_hash)
            finally:
                client.close()

    def test_raw_ipc_has_no_label_query_and_returns_only_generic_error(self):
        with scratch_directory() as root:
            fixture = build_fixture(root)
            client = launch(fixture)
            try:
                client._connection.send_bytes(canonical_json({"op": "steal_labels"}))
                self.assertTrue(client._connection.poll(10))
                response = json.loads(client._connection.recv_bytes())
                self.assertEqual(response, {"status": "error", "message": "protected evaluation failed"})
                self.assertNotIn("label-", json.dumps(response))
            finally:
                client.close()

    def test_small_cell_is_suppressed_and_attempt_is_durable(self):
        with scratch_directory() as root:
            fixture = build_fixture(root, count=1, minimum_cell_size=2)
            program = ResearchProgramRef.from_callable(half_program)
            with launch(fixture) as client:
                certificate = client.run(request(fixture, program=program), program)
            self.assertEqual(certificate.metrics, {"suppressed": "true"})
            self.assertEqual(certificate.n_observations, 0)
            restarted = ProtectedAttemptLedger(root / "attempts.jsonl")
            self.assertEqual(restarted.counts(fixture["campaign"]), (1, 1))

    def test_research_failure_is_generic_non_refundable_and_survives_restart(self):
        with scratch_directory() as root:
            fixture = build_fixture(root, max_attempts=1)
            failing = ResearchProgramRef.from_callable(failing_program)
            with launch(fixture) as client:
                with self.assertRaises(ProtectedEvaluationError) as caught:
                    client.run(request(fixture, program=failing), failing)
                self.assertEqual(str(caught.exception), "protected evaluation failed")
                self.assertIsNone(caught.exception.__cause__)
            self.assertEqual(
                ProtectedAttemptLedger(root / "attempts.jsonl").counts(fixture["campaign"]),
                (1, 1),
            )
            valid = ResearchProgramRef.from_callable(half_program)
            with launch(fixture) as restarted:
                with self.assertRaises(ProtectedEvaluationError):
                    restarted.run(request(fixture, program=valid), valid)

    def test_evaluator_crash_after_reservation_consumes_attempt(self):
        with scratch_directory() as root:
            fixture = build_fixture(root, max_attempts=1)
            client = launch(fixture, allow_fault_injection=True)
            with self.assertRaises(ProtectedEvaluationError) as caught:
                client.crash_after_reservation_for_test(request(fixture))
            self.assertEqual(str(caught.exception), "protected evaluator unavailable")
            self.assertEqual(
                ProtectedAttemptLedger(root / "attempts.jsonl").counts(fixture["campaign"]),
                (1, 1),
            )
            program = ResearchProgramRef.from_callable(half_program)
            with launch(fixture) as restarted:
                with self.assertRaises(ProtectedEvaluationError):
                    restarted.run(request(fixture, program=program), program)

    def test_unregistered_campaign_and_wrong_evaluator_digest_reject_pre_label(self):
        with scratch_directory() as root:
            fixture = build_fixture(root)
            unregistered = ProtectedCampaign.create_registered(
                campaign_id="not-registered",
                family_id="family-1",
                max_attempts=1,
                evaluator_digest=digest("e"),
                minimum_cell_size=1,
                experiment_id="experiment-1",
                sealed_frames=SealedFrameSet.create(
                    campaign_id="not-registered",
                    dataset_version="dataset-v1",
                    frames=fixture["frames"],
                ),
                registered_at="2026-01-01T00:00:00Z",
            )
            with self.assertRaises(RegistryConflict):
                launch_trusted_protected_evaluator(
                    campaign=unregistered,
                    sealed_frames=fixture["sealed"],
                    labels=labels_for(fixture["frames"]),
                    campaigns=fixture["campaigns"],
                    experiments=fixture["experiments"],
                    attempts=fixture["attempts"],
                    family_limit=1,
                    local_checkpoint_test_only=True,
                )
            with launch(fixture) as client:
                program = ResearchProgramRef.from_callable(half_program)
                with self.assertRaises(ProtectedEvaluationError):
                    client.run(
                        request(fixture, program=program, rules_digest=digest("f")),
                        program,
                    )
            self.assertEqual(fixture["attempts"].counts(fixture["campaign"]), (0, 0))

    def test_missing_extra_and_substituted_frame_artifacts_reject_and_consume(self):
        with scratch_directory() as root:
            fixture = build_fixture(root, max_attempts=3)
            req = request(fixture)
            alternate = SealedFrameSet.create(
                campaign_id=fixture["campaign"].campaign_id,
                dataset_version="dataset-v1",
                frames=make_frames(2, changed=True),
            )
            artifacts = (
                FrozenPredictionArtifact.create(
                    req,
                    fixture["sealed"].frame_manifest_hash,
                    {fixture["frames"][0].decision_id: "0.5"},
                ),
                FrozenPredictionArtifact.create(
                    req,
                    fixture["sealed"].frame_manifest_hash,
                    {
                        fixture["frames"][0].decision_id: "0.5",
                        fixture["frames"][1].decision_id: "0.5",
                        "extra-frame": "0.5",
                    },
                ),
                FrozenPredictionArtifact.create(
                    req,
                    alternate.frame_manifest_hash,
                    {frame.decision_id: "0.5" for frame in fixture["frames"]},
                ),
            )
            with launch(fixture) as client:
                for artifact in artifacts:
                    with self.assertRaises(ProtectedEvaluationError) as caught:
                        client.submit(req, artifact)
                    self.assertEqual(str(caught.exception), "protected evaluation failed")
                    self.assertIsNone(caught.exception.__cause__)
            self.assertEqual(fixture["attempts"].counts(fixture["campaign"]), (3, 3))

    def test_label_dependent_internal_failure_has_no_side_channel(self):
        with scratch_directory() as root:
            fixture = build_fixture(root, count=1, max_attempts=1)
            program = ResearchProgramRef.from_callable(half_program)
            with launch(fixture, outcomes=("TOP-SECRET-OUTCOME",)) as client:
                with self.assertRaises(ProtectedEvaluationError) as caught:
                    client.run(request(fixture, program=program), program)
                self.assertEqual(str(caught.exception), "protected evaluation failed")
                self.assertNotIn("TOP-SECRET", str(caught.exception))
                self.assertIsNone(caught.exception.__cause__)
                self.assertIsNone(caught.exception.__context__)

    def test_two_evaluator_processes_cannot_both_take_final_attempt(self):
        with scratch_directory() as root:
            fixture = build_fixture(root, max_attempts=1)
            first = launch(fixture)
            second = launch(fixture)
            program = ResearchProgramRef.from_callable(half_program)
            barrier = threading.Barrier(3)
            outcomes: list[str] = []

            def run_client(client, strategy_id: str) -> None:
                barrier.wait()
                try:
                    client.run(
                        request(fixture, strategy=strategy_id, program=program),
                        program,
                    )
                    outcomes.append("certificate")
                except ProtectedEvaluationError:
                    outcomes.append("rejected")

            threads = [
                threading.Thread(target=run_client, args=(first, "strategy-a")),
                threading.Thread(target=run_client, args=(second, "strategy-b")),
            ]
            try:
                for thread in threads:
                    thread.start()
                barrier.wait()
                for thread in threads:
                    thread.join(20)
                self.assertEqual(sorted(outcomes), ["certificate", "rejected"])
                self.assertEqual(
                    ProtectedAttemptLedger(root / "attempts.jsonl").counts(fixture["campaign"]),
                    (1, 1),
                )
            finally:
                first.close()
                second.close()

    def test_registered_v2_campaign_cannot_select_legacy_harness(self):
        with scratch_directory() as root:
            fixture = build_fixture(root)
            with self.assertRaises(RegistryConflict):
                LegacyUnsafeProtectedEvaluationBoundary(
                    fixture["campaign"],
                    fixture["frames"],
                    labels_for(fixture["frames"]),
                    ProtectedAttemptLedger(),
                    legacy_test_only=True,
                )
            legacy = ProtectedCampaign("legacy", "family", 1, digest("e"))
            with self.assertRaises(RegistryConflict):
                LegacyUnsafeProtectedEvaluationBoundary(
                    legacy,
                    fixture["frames"],
                    labels_for(fixture["frames"]),
                    ProtectedAttemptLedger(),
                )

    def test_real_protected_activation_remains_disabled_pending_review(self):
        with scratch_directory() as root:
            fixture = build_fixture(root)
            with self.assertRaisesRegex(RegistryConflict, "independent boundary review"):
                launch_trusted_protected_evaluator(
                    campaign=fixture["campaign"],
                    sealed_frames=fixture["sealed"],
                    labels=labels_for(fixture["frames"]),
                    campaigns=fixture["campaigns"],
                    experiments=fixture["experiments"],
                    attempts=fixture["attempts"],
                    family_limit=fixture["campaign"].max_attempts,
                )


if __name__ == "__main__":
    unittest.main()
