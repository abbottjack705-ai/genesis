"""T5 / N1: the protected research boundary binds all executed research code.

Invariants (ADR-0003 v1, T3 memo):

* I1 code identity: a certificate is issued only for computation performed by
  the hashed program bytes plus trusted runtime (standard library, Genesis).
  Unhashed code under the import roots, dynamically loaded code and state left
  behind by a different program identity cannot influence it.
* I2 label absence: no raw ``FutureOutcomeLabel`` instance exists in the
  research process when predictions are made or released, wherever it is
  hidden.

Every hostile program here builds its own synthetic labels through Genesis
types. A rejection therefore demonstrates the code/label control, not only
that test-helper modules are unavailable.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from genesis.evaluation import ProtectedEvaluationError

from ._support import scratch_directory
from .test_astra_s5_process import build_fixture, request_for
from .test_astra_t3_protected_integrity import launch, pin


LABELS = (
    "from genesis.labels import FutureOutcomeLabel\n"
    "from genesis.provenance import AvailabilityClass, ProvenanceRef\n"
    "def build_labels():\n"
    "    ref = ProvenanceRef('a' * 64, 'synthetic-v1', 'synthetic://t5', "
    "'2026-01-01T00:00:00Z', '2026-01-01T00:00:01Z', "
    "AvailabilityClass.PROSPECTIVE_CAPTURED, 'test-v1')\n"
    "    return tuple(FutureOutcomeLabel(f'label-{index}', f'entity-{index}', "
    "index % 2, '2026-01-01T01:00:00Z', ref, 'label-v1') for index in range(2))\n"
)
READ_LABEL = (
    "    label = next(x for x in {holder} if x.entity_id == frame.entity_id)\n"
    "    return str(label.outcome_value)\n"
)
SIGNAL_HELPER = 'def p(frame):\n    return "0.9" if frame.values()["signal"] else "0.1"\n'
HALF_HELPER = 'def p(frame):\n    return "0.5"\n'


def outcome(client, fixture, program, strategy_id):
    try:
        certificate = client.run(request_for(fixture, program, strategy_id=strategy_id), program)
    except ProtectedEvaluationError as exc:
        return ("blocked", str(exc))
    return ("certified", certificate.metrics["brier"])


class T5ProtectedBoundaryTests(unittest.TestCase):
    def workspace(self, root: Path, *, max_attempts: int = 3):
        fixture = build_fixture(root / "campaign", max_attempts=max_attempts)
        code = root / "code"
        code.mkdir()
        return fixture, code

    def write(self, code: Path, name: str, body: str):
        source = code / f"{name}.py"
        source.write_text(body, encoding="utf-8")
        return pin(name, source)

    def assert_blocked(self, result, message: str) -> None:
        self.assertEqual(result, ("blocked", "protected evaluation failed"), message)

    def run_single(self, name: str, body: str, *, helpers: dict[str, str] | None = None):
        with scratch_directory() as root:
            fixture, code = self.workspace(root)
            for helper, text in (helpers or {}).items():
                (code / f"{helper}.py").write_text(text, encoding="utf-8")
            program = self.write(code, name, body)
            with launch(fixture, code) as client:
                return outcome(client, fixture, program, name)

    # --- auditor N1 inventory -------------------------------------------------

    def test_function_local_import_of_label_holder_is_rejected(self):
        result = self.run_single(
            "t5_local_import",
            "def predict(frame):\n"
            "    import t5_holder_local\n"
            + READ_LABEL.format(holder="t5_holder_local.HOLDER"),
            helpers={"t5_holder_local": LABELS + "HOLDER = build_labels()\n"},
        )
        self.assert_blocked(result, "N1: function-local import reached raw labels")

    def test_importlib_import_module_of_label_holder_is_rejected(self):
        result = self.run_single(
            "t5_importlib",
            "import importlib\n"
            "def predict(frame):\n"
            "    holder = importlib.import_module('t5_holder_importlib')\n"
            + READ_LABEL.format(holder="holder.HOLDER"),
            helpers={"t5_holder_importlib": LABELS + "HOLDER = build_labels()\n"},
        )
        self.assert_blocked(result, "N1: importlib reached raw labels")

    def test_builtins_injected_labels_are_rejected(self):
        result = self.run_single(
            "t5_builtins",
            LABELS
            + "import builtins\n"
            "builtins.T5_HIDDEN_LABELS = build_labels()\n"
            "del builtins, build_labels, FutureOutcomeLabel\n"
            "def predict(frame):\n"
            + READ_LABEL.format(holder="T5_HIDDEN_LABELS"),
        )
        self.assert_blocked(result, "N1: labels injected into builtins were reachable")

    def test_stdlib_stash_reached_by_function_local_import_is_rejected(self):
        result = self.run_single(
            "t5_stdlib_local",
            LABELS
            + "import json\n"
            "json.t5_hidden = build_labels()\n"
            "del json, build_labels\n"
            "def predict(frame):\n"
            "    import json\n"
            + READ_LABEL.format(holder="json.t5_hidden"),
        )
        self.assert_blocked(result, "N1: stdlib-module stash was reachable")

    def test_new_digest_in_same_worker_never_certifies_stale_helper_code(self):
        with scratch_directory() as root:
            fixture, code = self.workspace(root)
            helper = code / "t5_mutable_helper.py"
            helper.write_text(SIGNAL_HELPER, encoding="utf-8")
            body = "def predict(frame):\n    import t5_mutable_helper\n    return t5_mutable_helper.p(frame)\n"
            first = self.write(code, "t5_cached_helper", body)
            with launch(fixture, code) as client:
                before = outcome(client, fixture, first, "before")
                helper.write_text(HALF_HELPER, encoding="utf-8")
                second = self.write(code, "t5_cached_helper", "# revision 2\n" + body)
                after = outcome(client, fixture, second, "after")
            self.assertNotEqual(first.program_digest, second.program_digest)
            self.assertIn(before, (("blocked", "protected evaluation failed"), ("certified", "0.01")))
            self.assertIn(
                after, (("blocked", "protected evaluation failed"), ("certified", "0.25")),
                "N1/B4: a new program digest certified the old cached helper code",
            )

    def test_same_digest_never_certifies_two_helper_computations(self):
        with scratch_directory() as root:
            fixture, code = self.workspace(root)
            helper = code / "t5_edited_helper.py"
            program = self.write(
                code, "t5_same_digest",
                "def predict(frame):\n    import t5_edited_helper\n    return t5_edited_helper.p(frame)\n",
            )
            helper.write_text(SIGNAL_HELPER, encoding="utf-8")
            with launch(fixture, code) as client:
                one = outcome(client, fixture, program, "one")
            helper.write_text(HALF_HELPER, encoding="utf-8")
            with launch(fixture, code) as client:
                two = outcome(client, fixture, program, "two")
            self.assertFalse(
                one[0] == two[0] == "certified" and one != two,
                f"N1/B4: one program digest certified two computations: {one} {two}",
            )

    # --- class variants beyond the auditor inventory --------------------------

    def test_top_level_helper_data_cannot_change_a_certified_computation(self):
        with scratch_directory() as root:
            fixture, code = self.workspace(root)
            helper = code / "t5_scale_helper.py"
            program = self.write(
                code, "t5_helper_data",
                "from t5_scale_helper import HIGH\n"
                "def predict(frame):\n"
                "    return HIGH if frame.values()['signal'] else '0.1'\n",
            )
            helper.write_text("HIGH = '0.9'\n", encoding="utf-8")
            with launch(fixture, code) as client:
                one = outcome(client, fixture, program, "one")
            # A different byte length defeats CPython's mtime+size .pyc reuse,
            # which could otherwise mask the unbound-code change within 1s.
            helper.write_text("HIGH = '0.45'\n", encoding="utf-8")
            with launch(fixture, code) as client:
                two = outcome(client, fixture, program, "two")
            self.assertFalse(
                one[0] == two[0] == "certified" and one != two,
                f"N1/B4: unhashed helper data changed a certified computation: {one} {two}",
            )

    def test_exec_of_unhashed_source_cannot_change_a_certified_computation(self):
        with scratch_directory() as root:
            fixture, code = self.workspace(root)
            helper = code / "t5_exec_source.txt"
            program = self.write(
                code, "t5_exec_program",
                "from pathlib import Path\n"
                f"exec(Path({str(helper)!r}).read_text(encoding='utf-8'))\n"
                "def predict(frame):\n"
                "    return p(frame)\n",
            )
            helper.write_text(SIGNAL_HELPER, encoding="utf-8")
            with launch(fixture, code) as client:
                one = outcome(client, fixture, program, "one")
            helper.write_text(HALF_HELPER, encoding="utf-8")
            with launch(fixture, code) as client:
                two = outcome(client, fixture, program, "two")
            self.assertFalse(
                one[0] == two[0] == "certified" and one != two,
                f"N1/B4: exec'd unhashed source changed a certified computation: {one} {two}",
            )
            self.assertEqual(two, ("blocked", "protected evaluation failed"))

    def test_unreferenced_module_global_labels_are_rejected(self):
        result = self.run_single(
            "t5_unreferenced_global",
            LABELS
            + "UNUSED_BUT_REACHABLE = build_labels()\n"
            "def predict(frame):\n"
            "    return '0.5'\n",
        )
        self.assert_blocked(result, "N1/B5: module-global labels were present in research")

    def test_labels_parked_in_an_unreferenced_stdlib_module_are_rejected(self):
        result = self.run_single(
            "t5_parked_labels",
            LABELS
            + "import json\n"
            "json.t5_parked = build_labels()\n"
            "del json, build_labels\n"
            "def predict(frame):\n"
            "    return '0.5'\n",
        )
        self.assert_blocked(result, "N1/B5: labels parked in stdlib state were present")

    def test_prior_program_cannot_leave_state_for_a_later_program(self):
        with scratch_directory() as root:
            fixture, code = self.workspace(root)
            writer = self.write(
                code, "t5_state_writer",
                "import json\njson.t5_shared_answer = '0.9'\n"
                "def predict(frame):\n    return '0.5'\n",
            )
            reader = self.write(
                code, "t5_state_reader",
                "import json\n"
                "def predict(frame):\n"
                "    return json.t5_shared_answer if frame.values()['signal'] else '0.1'\n",
            )
            with launch(fixture, code) as client:
                outcome(client, fixture, writer, "writer")
                later = outcome(client, fixture, reader, "reader")
            self.assert_blocked(
                later, "N1/B4: a later digest certified state left by another program",
            )

    def test_decimal_context_left_by_a_prior_program_cannot_change_a_later_one(self):
        with scratch_directory() as root:
            fixture, code = self.workspace(root, max_attempts=4)
            writer = self.write(
                code, "t5_context_writer",
                "import decimal\ndecimal.getcontext().prec = 1\n"
                "def predict(frame):\n    return '0.5'\n",
            )
            reader = self.write(
                code, "t5_context_reader",
                "from decimal import Decimal\n"
                "def predict(frame):\n    return str(Decimal(2) / Decimal(8))\n",
            )
            with launch(fixture, code) as client:
                baseline = outcome(client, fixture, reader, "reader-fresh")
            with launch(fixture, code) as client:
                outcome(client, fixture, writer, "writer")
                later = outcome(client, fixture, reader, "reader-after-writer")
            self.assertEqual(baseline, ("certified", "0.3125"))
            self.assertIn(
                later, (baseline, ("blocked", "protected evaluation failed")),
                "N1/B4: runtime context left by another program changed a certificate",
            )

    # --- hostile pre-audit finding PA-1: research writes into the IPC channel --

    def test_research_cannot_forge_a_worker_response_on_the_ipc_channel(self):
        with scratch_directory() as root:
            fixture, code = self.workspace(root)
            name = "t5_ipc_forger"
            body = (
                "import hashlib, json, os\n"
                "from pathlib import Path\n"
                "def _canonical(value):\n"
                "    return (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,\n"
                "                       separators=(',', ':')) + '\\n').encode('utf-8')\n"
                "_REF = {'domain': 'genesis.protected-research-program.v1',\n"
                "        'schema_version': 'research-program-ref-v1', 'module': "
                f"{name!r}, 'qualname': 'predict',\n"
                "        'module_artifact_hash': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}\n"
                "_UNSIGNED = {'schema_version': 'frozen-predictions-v1', 'campaign_id': 'campaign-s5',\n"
                f"             'dataset_version': 'dataset-v1', 'strategy_id': {name!r},\n"
                "             'strategy_digest': hashlib.sha256(_canonical(_REF)).hexdigest(),\n"
                f"             'frame_manifest_hash': {fixture['sealed'].frame_manifest_hash!r},\n"
                "             'predictions': [{'frame_id': 'frame-0', 'probability': '0'},\n"
                "                             {'frame_id': 'frame-1', 'probability': '1'}]}\n"
                "_ARTIFACT = dict(_UNSIGNED, artifact_hash=hashlib.sha256(_canonical(_UNSIGNED)).hexdigest())\n"
                "_TEMPLATE = _canonical({'status': 'artifact', 'artifact': _ARTIFACT, 'research_pid': 0})\n"
                "_SENT = []\n"
                "def predict(frame):\n"
                "    if not _SENT:\n"
                "        line = _TEMPLATE.replace(b'\"research_pid\":0', b'\"research_pid\":' + str(os.getpid()).encode())\n"
                "        for descriptor in range(3, 64):\n"
                "            try:\n"
                "                os.write(descriptor, line)\n"
                "            except OSError:\n"
                "                pass\n"
                "        _SENT.append(1)\n"
                "    return '0.5'\n"
            )
            program = self.write(code, name, body)
            with launch(fixture, code) as client:
                result = outcome(client, fixture, program, name)
            self.assertNotEqual(
                result, ("certified", "0"),
                "PA-1: the parent certified an artifact forged by research on the IPC channel",
            )
            self.assert_blocked(result, "PA-1: an IPC-corrupting program was not failed closed")

    # --- legitimate programs must keep working --------------------------------

    def test_self_contained_stdlib_program_with_local_helpers_still_certifies(self):
        result = self.run_single(
            "t5_valid_local",
            "import math\n"
            "from decimal import Decimal\n"
            "LOW = Decimal('0.1')\n"
            "class Scale:\n"
            "    def __init__(self, high):\n"
            "        self.high = high\n"
            "    def pick(self, signal):\n"
            "        return self.high if signal else LOW\n"
            "SCALE = Scale(Decimal('0.9'))\n"
            "def clamp(value):\n"
            "    return max(Decimal(0), min(Decimal(1), value))\n"
            "def predict(frame):\n"
            "    assert math.isfinite(1.0)\n"
            "    return str(clamp(SCALE.pick(frame.values()['signal'])))\n",
        )
        self.assertEqual(result, ("certified", "0.01"))

    def test_program_may_import_genesis_types_without_label_instances(self):
        result = self.run_single(
            "t5_valid_types",
            "from genesis.labels import DecisionFrame, FutureOutcomeLabel\n"
            "LABEL_TYPE = FutureOutcomeLabel\n"
            "def predict(frame):\n"
            "    return '0.9' if frame.values()['signal'] else '0.1'\n",
        )
        self.assertEqual(result, ("certified", "0.01"))


if __name__ == "__main__":
    unittest.main()
