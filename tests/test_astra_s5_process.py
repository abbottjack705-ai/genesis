from __future__ import annotations

import inspect
import json
import os
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path

import genesis.protected as protected
from genesis.evaluation import EvaluationRequest, ProtectedEvaluationError
from genesis.labels import DecisionFact, DecisionFrame, FutureOutcomeLabel
from genesis.protected import (
    ProtectedAttemptLedger,
    ProtectedCampaign,
    ProtectedCampaignRegistry,
    SealedFrameSet,
)
from genesis.provenance import AvailabilityClass, ProvenanceRef
from genesis.registry import ExperimentRegistry, ExperimentSpec, RegistryConflict
from . import protected_research_programs as programs
from ._support import attach_to_scratch, remove_tree, scratch_directory
from .protected_research_programs import (
    FORBIDDEN_LABEL_ENV,
    crash_program,
    exception_program,
    half_program,
    hostile_parent_probe,
    signal_program,
    slow_program,
)


PARENT_CALLBACK_EXECUTED = False
S5_LABEL_ROOTS: list[Path] = []


def digest(character: str) -> str:
    return character * 64


def ref() -> ProvenanceRef:
    return ProvenanceRef(
        digest("a"),
        "synthetic-v1",
        "synthetic://astra-s5",
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:01Z",
        AvailabilityClass.PROSPECTIVE_CAPTURED,
        "test-v1",
    )


def make_frames(count: int = 2) -> tuple[DecisionFrame, ...]:
    return tuple(
        DecisionFrame(
            f"frame-{index}",
            f"entity-{index}",
            "2026-01-01T00:00:00Z",
            (
                DecisionFact(
                    "signal",
                    index % 2,
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


def labels_for(frames: tuple[DecisionFrame, ...]) -> tuple[FutureOutcomeLabel, ...]:
    return tuple(
        FutureOutcomeLabel(
            f"label-{index}",
            frame.entity_id,
            index % 2,
            "2026-01-01T01:00:00Z",
            ref(),
            "label-v1",
        )
        for index, frame in enumerate(frames)
    )


def parent_only_callable(_frame: DecisionFrame) -> str:
    global PARENT_CALLBACK_EXECUTED
    PARENT_CALLBACK_EXECUTED = True
    return "0.5"


def build_fixture(root: Path, *, max_attempts: int = 3):
    frames = make_frames()
    sealed = SealedFrameSet.create(
        campaign_id="campaign-s5",
        dataset_version="dataset-v1",
        frames=frames,
    )
    experiments = ExperimentRegistry(root / "experiments.jsonl")
    experiments.register(
        ExperimentSpec(
            experiment_id="experiment-s5",
            family="family-s5",
            parent_id=None,
            hypothesis="synthetic A8 process boundary",
            mechanism="calibration",
            dataset_version="dataset-v1",
            eligibility_definition="sealed frames",
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
        campaign_id="campaign-s5",
        family_id="family-s5",
        max_attempts=max_attempts,
        evaluator_digest=digest("e"),
        minimum_cell_size=1,
        experiment_id="experiment-s5",
        sealed_frames=sealed,
        registered_at="2026-01-01T00:00:00Z",
    )
    campaigns = ProtectedCampaignRegistry(root / "campaigns.jsonl")
    campaigns.register(campaign, experiments)
    attempts = ProtectedAttemptLedger(root / "attempts.jsonl")
    label_root = Path(tempfile.mkdtemp(prefix="genesis-s5-labels-")).resolve()
    S5_LABEL_ROOTS.append(label_root)
    # Outside the repository by design; removed with this test's scratch (E10).
    attach_to_scratch(root, label_root)
    research_root = root / "research"
    research_root.mkdir()
    label_path = label_root / "raw-label.secret"
    label_path.write_text("TOP-SECRET-LABEL", encoding="utf-8")
    return {
        "frames": frames,
        "labels": labels_for(frames),
        "sealed": sealed,
        "experiments": experiments,
        "campaign": campaign,
        "campaigns": campaigns,
        "attempts": attempts,
        "label_root": label_root,
        "label_path": label_path,
        "research_root": research_root,
    }


def program_ref(callback):
    contract = getattr(protected, "ResearchProgramRef", None)
    if contract is None:
        return callback
    return contract.from_callable(callback)


def request_for(fixture, program, *, strategy_id: str = "strategy-s5") -> EvaluationRequest:
    strategy_digest = getattr(program, "program_digest", digest("c"))
    return EvaluationRequest(
        fixture["campaign"].campaign_id,
        strategy_id,
        strategy_digest,
        "dataset-v1",
        fixture["campaign"].evaluator_digest,
    )


def launch(fixture, *, allow_fault_injection: bool = False):
    kwargs = {
        "campaign": fixture["campaign"],
        "sealed_frames": fixture["sealed"],
        "labels": fixture["labels"],
        "campaigns": fixture["campaigns"],
        "experiments": fixture["experiments"],
        "attempts": fixture["attempts"],
        "family_limit": fixture["campaign"].max_attempts,
        "allow_fault_injection": allow_fault_injection,
        "local_checkpoint_test_only": True,
    }
    parameters = inspect.signature(protected.launch_trusted_protected_evaluator).parameters
    if "research_workdir" in parameters:
        kwargs["research_workdir"] = fixture["research_root"]
    if "allowed_program_import_roots" in parameters:
        kwargs["allowed_program_import_roots"] = (Path(__file__).resolve().parents[1],)
    if "trusted_label_roots" in parameters:
        kwargs["trusted_label_roots"] = (fixture["label_root"],)
    return protected.launch_trusted_protected_evaluator(**kwargs)


class AstraS5ProcessIsolationTests(unittest.TestCase):
    def tearDown(self) -> None:
        global PARENT_CALLBACK_EXECUTED
        programs.PARENT_LABEL_SENTINEL = None
        programs.PARENT_PROBE_PATH = None
        PARENT_CALLBACK_EXECUTED = False
        os.environ.pop(FORBIDDEN_LABEL_ENV, None)
        while S5_LABEL_ROOTS:
            remove_tree(S5_LABEL_ROOTS.pop())

    def test_retained_parent_label_environment_and_path_do_not_reach_research(self):
        with scratch_directory() as root:
            fixture = build_fixture(root)
            trace = root / "parent-callback-trace.json"
            programs.PARENT_LABEL_SENTINEL = fixture["labels"]
            programs.PARENT_PROBE_PATH = str(trace)
            os.environ[FORBIDDEN_LABEL_ENV] = str(fixture["label_path"])
            program = program_ref(hostile_parent_probe)
            with launch(fixture) as client:
                certificate = client.run(request_for(fixture, program), program)
                self.assertEqual(
                    certificate.metrics["brier"],
                    "0.01",
                    "A8: callback observed a parent-retained label or label path",
                )
                self.assertFalse(
                    trace.exists(),
                    "A8: research callback executed in the label-owning parent address space",
                )
                self.assertNotEqual(getattr(client, "last_research_pid", None), os.getpid())

    def test_successful_program_is_proven_to_run_in_a_third_pid(self):
        with scratch_directory() as root:
            fixture = build_fixture(root)
            program = program_ref(signal_program)
            with launch(fixture) as client:
                certificate = client.run(request_for(fixture, program), program)
                research_pid = getattr(client, "research_pid", None)
                self.assertIsNotNone(research_pid, "A8: no separate research process exists")
                self.assertNotEqual(research_pid, os.getpid())
                self.assertNotEqual(research_pid, client.evaluator_pid)
                self.assertEqual(getattr(client, "last_research_pid", None), research_pid)
                self.assertEqual(certificate.metrics["brier"], "0.01")

    def test_boundary_attestation_has_only_label_free_capabilities(self):
        with scratch_directory() as root:
            fixture = build_fixture(root)
            with launch(fixture) as client:
                boundary = getattr(client, "research_boundary", None)
                self.assertIsInstance(boundary, dict, "A8: no process-boundary evidence exists")
                self.assertTrue(boundary["research_ready_before_evaluator"])
                self.assertEqual(boundary["research_pid"], client.research_pid)
                capabilities = set(boundary["received_capabilities"])
                self.assertEqual(
                    capabilities,
                    {"sealed_frames", "research_ipc", "program_import_roots", "research_workdir"},
                )
                self.assertNotIn("label", " ".join(capabilities).lower())
                self.assertNotIn("evaluator", " ".join(capabilities).lower())
                self.assertNotIn(FORBIDDEN_LABEL_ENV, boundary["environment_keys"])
                self.assertNotEqual(Path(boundary["working_directory"]), fixture["label_root"])

    def test_direct_callable_is_rejected_before_attempt_or_parent_execution(self):
        global PARENT_CALLBACK_EXECUTED
        with scratch_directory() as root:
            fixture = build_fixture(root)
            direct_request = EvaluationRequest(
                fixture["campaign"].campaign_id,
                "direct-callable",
                digest("c"),
                "dataset-v1",
                fixture["campaign"].evaluator_digest,
            )
            with launch(fixture) as client:
                with self.assertRaises(ProtectedEvaluationError):
                    client.run(direct_request, parent_only_callable)
            self.assertFalse(PARENT_CALLBACK_EXECUTED)
            self.assertEqual(fixture["attempts"].counts(fixture["campaign"]), (0, 0))

    def test_program_reference_binds_exact_module_bytes_and_request_digest(self):
        contract = getattr(protected, "ResearchProgramRef", None)
        self.assertIsNotNone(contract, "A8: research still accepts an unversioned callback")
        program = contract.from_callable(signal_program)
        self.assertEqual(program_ref(signal_program).program_digest, program.program_digest)
        with self.assertRaises(ValueError):
            replace(program, module_artifact_hash=digest("f"))
        payload = program.to_dict()
        payload["program_digest"] = digest("f")
        with self.assertRaises(ValueError):
            contract.from_dict(payload)

    def test_research_process_crash_consumes_attempt_and_restart_cannot_refund(self):
        contract = getattr(protected, "ResearchProgramRef", None)
        self.assertIsNotNone(contract, "A8: no separately crashable research process exists")
        with scratch_directory() as root:
            fixture = build_fixture(root, max_attempts=1)
            crashing = contract.from_callable(crash_program)
            client = launch(fixture)
            try:
                with self.assertRaises(ProtectedEvaluationError) as caught:
                    client.run(request_for(fixture, crashing), crashing)
                self.assertEqual(str(caught.exception), "protected evaluation failed")
            finally:
                client.close()
            self.assertEqual(
                ProtectedAttemptLedger(root / "attempts.jsonl").counts(fixture["campaign"]),
                (1, 1),
            )
            valid = contract.from_callable(half_program)
            with launch(fixture) as restarted:
                with self.assertRaises(ProtectedEvaluationError):
                    restarted.run(request_for(fixture, valid), valid)

    def test_research_exception_is_generic_and_nonrefundable(self):
        contract = getattr(protected, "ResearchProgramRef", None)
        self.assertIsNotNone(contract, "A8: no isolated research error boundary exists")
        with scratch_directory() as root:
            fixture = build_fixture(root, max_attempts=1)
            failing = contract.from_callable(exception_program)
            with launch(fixture) as client:
                with self.assertRaises(ProtectedEvaluationError) as caught:
                    client.run(request_for(fixture, failing), failing)
                self.assertEqual(str(caught.exception), "protected evaluation failed")
                self.assertNotIn("TOP-SECRET", str(caught.exception))
                self.assertIsNone(caught.exception.__cause__)
            self.assertEqual(fixture["attempts"].counts(fixture["campaign"]), (1, 1))

    def test_malformed_research_ipc_is_generic_and_evaluator_remains_separate(self):
        with scratch_directory() as root:
            fixture = build_fixture(root)
            program = program_ref(half_program)
            with launch(fixture) as client:
                if not hasattr(client, "_research_roundtrip"):
                    self.fail("A8: research shares the evaluator IPC endpoint")
                response = client._research_roundtrip({"op": "steal_labels"})
                self.assertEqual(
                    response,
                    {"status": "error", "message": "protected evaluation failed"},
                )
                certificate = client.run(request_for(fixture, program), program)
                self.assertEqual(certificate.metrics["brier"], "0.25")
            self.assertEqual(fixture["attempts"].counts(fixture["campaign"]), (1, 1))

    def test_research_timeout_is_generic_nonrefundable_and_bounded(self):
        contract = getattr(protected, "ResearchProgramRef", None)
        self.assertIsNotNone(contract, "A8: no bounded research-process timeout exists")
        with scratch_directory() as root:
            fixture = build_fixture(root, max_attempts=1)
            slow = contract.from_callable(slow_program)
            with launch(fixture) as client:
                with self.assertRaises(ProtectedEvaluationError) as caught:
                    client.run(request_for(fixture, slow), slow)
                self.assertEqual(str(caught.exception), "protected evaluation failed")
            self.assertEqual(fixture["attempts"].counts(fixture["campaign"]), (1, 1))

    def test_module_global_raw_label_is_rejected_inside_worker(self):
        contract = getattr(protected, "ResearchProgramRef", None)
        self.assertIsNotNone(contract, "A8: worker does not inspect program label state")
        from .protected_label_bearing_program import label_bearing_program

        with scratch_directory() as root:
            fixture = build_fixture(root, max_attempts=1)
            program = contract.from_callable(label_bearing_program)
            with launch(fixture) as client:
                with self.assertRaises(ProtectedEvaluationError) as caught:
                    client.run(request_for(fixture, program), program)
                self.assertEqual(str(caught.exception), "protected evaluation failed")
                self.assertNotIn("TOP-SECRET", str(caught.exception))
            self.assertEqual(fixture["attempts"].counts(fixture["campaign"]), (1, 1))

    def test_two_research_workers_cannot_exceed_the_final_attempt(self):
        contract = getattr(protected, "ResearchProgramRef", None)
        self.assertIsNotNone(contract, "A8: no independent research workers exist")
        with scratch_directory() as root:
            fixture = build_fixture(root, max_attempts=1)
            program = contract.from_callable(half_program)
            first = launch(fixture)
            second = launch(fixture)
            self.assertNotEqual(first.research_pid, second.research_pid)
            barrier = threading.Barrier(3)
            outcomes: list[str] = []

            def execute(client, strategy_id: str) -> None:
                barrier.wait()
                try:
                    client.run(request_for(fixture, program, strategy_id=strategy_id), program)
                    outcomes.append("certificate")
                except ProtectedEvaluationError:
                    outcomes.append("rejected")

            workers = (
                threading.Thread(target=execute, args=(first, "strategy-a")),
                threading.Thread(target=execute, args=(second, "strategy-b")),
            )
            try:
                for worker in workers:
                    worker.start()
                barrier.wait()
                for worker in workers:
                    worker.join(20)
                self.assertEqual(sorted(outcomes), ["certificate", "rejected"])
                self.assertEqual(
                    ProtectedAttemptLedger(root / "attempts.jsonl").counts(fixture["campaign"]),
                    (1, 1),
                )
            finally:
                first.close()
                second.close()

    def test_label_root_overlap_is_rejected_and_real_campaign_guard_remains(self):
        parameters = inspect.signature(protected.launch_trusted_protected_evaluator).parameters
        self.assertIn("trusted_label_roots", parameters, "A8: label paths are not fenced")
        with scratch_directory() as root:
            fixture = build_fixture(root)
            common = {
                "campaign": fixture["campaign"],
                "sealed_frames": fixture["sealed"],
                "labels": fixture["labels"],
                "campaigns": fixture["campaigns"],
                "experiments": fixture["experiments"],
                "attempts": fixture["attempts"],
                "family_limit": fixture["campaign"].max_attempts,
                "research_workdir": fixture["label_root"],
                "allowed_program_import_roots": (Path(__file__).resolve().parents[1],),
                "trusted_label_roots": (fixture["label_root"],),
            }
            with self.assertRaises(RegistryConflict):
                protected.launch_trusted_protected_evaluator(
                    **common,
                    local_checkpoint_test_only=True,
                )
            common["research_workdir"] = fixture["research_root"]
            with self.assertRaisesRegex(RegistryConflict, "independent boundary review"):
                protected.launch_trusted_protected_evaluator(**common)


if __name__ == "__main__":
    unittest.main()
