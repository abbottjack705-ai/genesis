from __future__ import annotations

import unittest
from pathlib import Path

from genesis.evaluation import ProtectedEvaluationError
from genesis.protected import ResearchProgramRef, launch_trusted_protected_evaluator
from genesis.repro import canonical_json, sha256_bytes, sha256_file

from ._support import scratch_directory
from .test_astra_s5_process import (
    build_fixture,
    half_program,
    program_ref,
    request_for,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def pin(module: str, path: Path) -> ResearchProgramRef:
    unsigned = {
        "domain": "genesis.protected-research-program.v1",
        "schema_version": "research-program-ref-v1",
        "module": module,
        "qualname": "predict",
        "module_artifact_hash": sha256_file(path),
    }
    return ResearchProgramRef.from_dict(
        unsigned | {"program_digest": sha256_bytes(canonical_json(unsigned))}
    )


def launch(fixture, *roots: Path):
    return launch_trusted_protected_evaluator(
        campaign=fixture["campaign"],
        sealed_frames=fixture["sealed"],
        labels=fixture["labels"],
        campaigns=fixture["campaigns"],
        experiments=fixture["experiments"],
        attempts=fixture["attempts"],
        family_limit=fixture["campaign"].max_attempts,
        research_workdir=fixture["research_root"],
        allowed_program_import_roots=(*roots, REPOSITORY_ROOT),
        trusted_label_roots=(fixture["label_root"],),
        local_checkpoint_test_only=True,
    )


class AstraT3VerifiedByteTests(unittest.TestCase):
    def test_changed_module_executes_new_verified_bytes_not_cached_callable(self):
        with scratch_directory() as root:
            fixture = build_fixture(root / "campaign")
            code = root / "code"
            code.mkdir()
            source = code / "t3_mutable_program.py"
            source.write_text(
                'def predict(frame):\n    return "0.9" if frame.values()["signal"] else "0.1"\n',
                encoding="utf-8",
            )
            first = pin(source.stem, source)
            with launch(fixture, code) as client:
                before = client.run(
                    request_for(fixture, first, strategy_id="t3-before"), first,
                )
                source.write_text(
                    'def predict(frame):\n    return "0.5"\n', encoding="utf-8",
                )
                second = pin(source.stem, source)
                after = client.run(
                    request_for(fixture, second, strategy_id="t3-after"), second,
                )
                self.assertEqual(before.metrics["brier"], "0.01")
                self.assertEqual(
                    after.metrics["brier"],
                    "0.25",
                    "B4 RED: new bytes were certified while cached old code executed",
                )

    def test_import_time_path_mutation_cannot_change_bytes_already_verified_for_execution(self):
        with scratch_directory() as root:
            fixture = build_fixture(root / "campaign")
            code = root / "code"
            code.mkdir()
            source = code / "t3_self_mutating_program.py"
            source.write_text(
                "from pathlib import Path\n"
                "Path(__file__).write_text('def predict(frame):\\n    return \\\"0.5\\\"\\n', encoding='utf-8')\n"
                "def predict(frame):\n"
                "    return \"0.9\" if frame.values()[\"signal\"] else \"0.1\"\n",
                encoding="utf-8",
            )
            program = pin(source.stem, source)
            with launch(fixture, code) as client:
                try:
                    certificate = client.run(request_for(fixture, program), program)
                except ProtectedEvaluationError:
                    self.fail(
                        "B4 RED: post-verify path mutation displaced the verified bytes"
                    )
                self.assertEqual(certificate.metrics["brier"], "0.01")
            self.assertNotEqual(sha256_file(source), program.module_artifact_hash)

    def test_ambiguous_module_origin_fails_closed_before_execution(self):
        with scratch_directory() as root:
            fixture = build_fixture(root / "campaign", max_attempts=1)
            first_root = root / "first"
            second_root = root / "second"
            first_root.mkdir()
            second_root.mkdir()
            body = 'def predict(frame):\n    return "0.5"\n'
            first = first_root / "t3_ambiguous_program.py"
            second = second_root / first.name
            first.write_text(body, encoding="utf-8")
            second.write_text(body, encoding="utf-8")
            program = pin(first.stem, first)
            with launch(fixture, first_root, second_root) as client:
                with self.assertRaises(
                    ProtectedEvaluationError,
                    msg="B4 RED: ambiguous module origins were silently ordered",
                ):
                    client.run(request_for(fixture, program), program)

    def test_reference_to_module_outside_declared_roots_fails_closed(self):
        with scratch_directory() as root:
            fixture = build_fixture(root / "campaign", max_attempts=1)
            allowed = root / "allowed"
            outside = root / "outside"
            allowed.mkdir()
            outside.mkdir()
            source = outside / "t3_outside_program.py"
            source.write_text('def predict(frame):\n    return "0.5"\n', encoding="utf-8")
            program = pin(source.stem, source)
            with launch(fixture, allowed) as client:
                with self.assertRaises(ProtectedEvaluationError):
                    client.run(request_for(fixture, program), program)

    def test_identical_repeat_works_and_stale_reference_after_change_rejects(self):
        with scratch_directory() as root:
            fixture = build_fixture(root / "campaign")
            code = root / "code"
            code.mkdir()
            source = code / "t3_repeat_program.py"
            source.write_text('def predict(frame):\n    return "0.5"\n', encoding="utf-8")
            program = pin(source.stem, source)
            with launch(fixture, code) as client:
                first = client.run(
                    request_for(fixture, program, strategy_id="repeat-1"), program,
                )
                second = client.run(
                    request_for(fixture, program, strategy_id="repeat-2"), program,
                )
                self.assertEqual(first.metrics["brier"], "0.25")
                self.assertEqual(second.metrics["brier"], "0.25")
                source.write_text('def predict(frame):\n    return "0.9"\n', encoding="utf-8")
                with self.assertRaises(ProtectedEvaluationError):
                    client.run(
                        request_for(fixture, program, strategy_id="stale-ref"), program,
                    )


class AstraT3ReachableStateTests(unittest.TestCase):
    @staticmethod
    def write_program(code: Path, name: str, body: str) -> tuple[Path, ResearchProgramRef]:
        source = code / f"{name}.py"
        source.write_text(body, encoding="utf-8")
        return source, pin(name, source)

    def assert_program_blocked(self, body: str, *, name: str) -> None:
        with scratch_directory() as root:
            fixture = build_fixture(root / "campaign", max_attempts=1)
            code = root / "code"
            code.mkdir()
            _source, program = self.write_program(code, name, body)
            with launch(fixture, code) as client:
                try:
                    client.run(request_for(fixture, program), program)
                except ProtectedEvaluationError as exc:
                    self.assertEqual(str(exc), "protected evaluation failed")
                else:
                    self.fail(f"B5 RED: {name} reached protected evaluation")
            self.assertEqual(fixture["attempts"].counts(fixture["campaign"]), (1, 1))

    def test_object_dictionary_holder_with_raw_labels_is_rejected(self):
        self.assert_program_blocked(
            "from types import SimpleNamespace\n"
            "from tests.test_astra_s5_process import make_frames, labels_for\n"
            "HOLDER = SimpleNamespace(labels=labels_for(make_frames()))\n"
            "def predict(frame):\n"
            "    label = next(x for x in HOLDER.labels if x.entity_id == frame.entity_id)\n"
            "    return str(label.outcome_value)\n",
            name="t3_object_holder",
        )

    def test_class_state_reachable_through_instance_is_rejected(self):
        self.assert_program_blocked(
            "from tests.test_astra_s5_process import make_frames, labels_for\n"
            "class Holder:\n"
            "    labels = labels_for(make_frames())\n"
            "HOLDER = Holder()\n"
            "def predict(frame):\n"
            "    label = next(x for x in HOLDER.labels if x.entity_id == frame.entity_id)\n"
            "    return str(label.outcome_value)\n",
            name="t3_class_state_holder",
        )

    def test_slot_holder_with_raw_labels_is_rejected(self):
        self.assert_program_blocked(
            "from tests.test_astra_s5_process import make_frames, labels_for\n"
            "class Holder:\n"
            "    __slots__ = ('labels',)\n"
            "HOLDER = Holder()\n"
            "HOLDER.labels = labels_for(make_frames())\n"
            "def predict(frame):\n"
            "    label = next(x for x in HOLDER.labels if x.entity_id == frame.entity_id)\n"
            "    return str(label.outcome_value)\n",
            name="t3_slot_holder",
        )

    def test_function_attribute_with_raw_labels_is_rejected(self):
        self.assert_program_blocked(
            "from tests.test_astra_s5_process import make_frames, labels_for\n"
            "def predict(frame):\n"
            "    return '0.5'\n"
            "predict.hidden_labels = labels_for(make_frames())\n"
            "del make_frames, labels_for\n",
            name="t3_function_attribute",
        )

    def test_custom_imported_holder_with_raw_labels_is_rejected(self):
        with scratch_directory() as root:
            fixture = build_fixture(root / "campaign", max_attempts=1)
            code = root / "code"
            code.mkdir()
            (code / "t3_imported_state.py").write_text(
                "from types import SimpleNamespace\n"
                "from tests.test_astra_s5_process import make_frames, labels_for\n"
                "HOLDER = SimpleNamespace(labels=labels_for(make_frames()))\n",
                encoding="utf-8",
            )
            _source, program = self.write_program(
                code,
                "t3_imported_holder",
                "import t3_imported_state\n"
                "def predict(frame):\n"
                "    label = next(x for x in t3_imported_state.HOLDER.labels "
                "if x.entity_id == frame.entity_id)\n"
                "    return str(label.outcome_value)\n",
            )
            with launch(fixture, code) as client:
                with self.assertRaises(
                    ProtectedEvaluationError,
                    msg="B5 RED: imported holder was assumed label-free",
                ):
                    client.run(request_for(fixture, program), program)

    def test_from_imported_holder_class_is_rejected(self):
        with scratch_directory() as root:
            fixture = build_fixture(root / "campaign", max_attempts=1)
            code = root / "code"
            code.mkdir()
            (code / "t3_imported_class_state.py").write_text(
                "from tests.test_astra_s5_process import make_frames, labels_for\n"
                "class Holder:\n"
                "    labels = labels_for(make_frames())\n",
                encoding="utf-8",
            )
            _source, program = self.write_program(
                code,
                "t3_from_imported_holder",
                "from t3_imported_class_state import Holder\n"
                "HOLDER = Holder()\n"
                "def predict(frame):\n"
                "    label = next(x for x in HOLDER.labels "
                "if x.entity_id == frame.entity_id)\n"
                "    return str(label.outcome_value)\n",
            )
            with launch(fixture, code) as client:
                with self.assertRaises(
                    ProtectedEvaluationError,
                    msg="B5 RED: from-imported class state was assumed label-free",
                ):
                    client.run(request_for(fixture, program), program)

    def test_deep_cyclic_collection_with_raw_labels_is_rejected(self):
        self.assert_program_blocked(
            "from tests.test_astra_s5_process import make_frames, labels_for\n"
            "DEEP = list(labels_for(make_frames()))\n"
            "for _index in range(9):\n"
            "    DEEP = [DEEP]\n"
            "CYCLE = []\n"
            "CYCLE.append(CYCLE)\n"
            "CYCLE.append(DEEP)\n"
            "def predict(frame):\n"
            "    value = CYCLE[1]\n"
            "    for _index in range(9):\n"
            "        value = value[0]\n"
            "    label = next(x for x in value if x.entity_id == frame.entity_id)\n"
            "    return str(label.outcome_value)\n",
            name="t3_deep_cycle_label",
        )

    def test_opaque_reachable_global_fails_closed(self):
        self.assert_program_blocked(
            "class Opaque:\n"
            "    __slots__ = ()\n"
            "OPAQUE = Opaque()\n"
            "def predict(frame):\n"
            "    return '0.5' if OPAQUE else '0.1'\n",
            name="t3_opaque_global",
        )

    def test_label_free_deep_cycle_and_retained_simple_program_still_work(self):
        with scratch_directory() as root:
            fixture = build_fixture(root / "campaign")
            code = root / "code"
            code.mkdir()
            _source, cycle_program = self.write_program(
                code,
                "t3_safe_cycle",
                "SAFE = []\n"
                "SAFE.append(SAFE)\n"
                "NESTED = {'items': [[[[[[['safe']]]]]]]}\n"
                "def predict(frame):\n"
                "    return '0.5' if SAFE[0] is SAFE and NESTED else '0.1'\n",
            )
            with launch(fixture, code) as client:
                certificate = client.run(
                    request_for(fixture, cycle_program, strategy_id="safe-cycle"),
                    cycle_program,
                )
                self.assertEqual(certificate.metrics["brier"], "0.25")
            retained = program_ref(half_program)
            with launch(fixture, REPOSITORY_ROOT) as client:
                certificate = client.run(
                    request_for(fixture, retained, strategy_id="retained-half"),
                    retained,
                )
                self.assertEqual(certificate.metrics["brier"], "0.25")

    def test_rejected_hidden_label_consumes_attempt_across_restart(self):
        with scratch_directory() as root:
            fixture = build_fixture(root / "campaign", max_attempts=1)
            code = root / "code"
            code.mkdir()
            _source, hidden = self.write_program(
                code,
                "t3_nonrefundable_hidden_label",
                "from types import SimpleNamespace\n"
                "from tests.test_astra_s5_process import make_frames, labels_for\n"
                "HOLDER = SimpleNamespace(labels=labels_for(make_frames()))\n"
                "def predict(frame):\n"
                "    return '0.5' if HOLDER.labels else '0.1'\n",
            )
            with launch(fixture, code) as client:
                with self.assertRaises(ProtectedEvaluationError):
                    client.run(request_for(fixture, hidden), hidden)
            self.assertEqual(fixture["attempts"].counts(fixture["campaign"]), (1, 1))
            valid = program_ref(half_program)
            with launch(fixture, REPOSITORY_ROOT) as restarted:
                with self.assertRaises(ProtectedEvaluationError):
                    restarted.run(request_for(fixture, valid), valid)


if __name__ == "__main__":
    unittest.main()
