"""T5 N1: one label-free research worker is bound to one program identity.

ADR-0003 requires the research worker to be ready before labels/evaluator exist,
so a client cannot replace its worker after labels are materialized.  The
stronger N1 lifecycle therefore binds the already-running worker (and parent
record of it) to the first ResearchProgramRef digest it is asked to execute.
A different digest fails closed in that client and may run only in a fresh
client.  The permanent audit hook is an additional runtime integrity layer;
the existing in-worker state checks remain authoritative defense in depth.
"""

from __future__ import annotations

import unittest

from genesis.evaluation import ProtectedEvaluationError

from ._support import scratch_directory
from .protected_research_programs import half_program, signal_program
from .test_astra_s5_process import build_fixture, launch, program_ref, request_for
from .test_astra_t3_protected_integrity import launch as launch_with_roots
from .test_astra_t3_protected_integrity import pin


class T5WorkerLifecycleTests(unittest.TestCase):
    def test_client_binds_to_first_program_identity_and_fresh_client_allows_another(self):
        with scratch_directory() as root:
            fixture = build_fixture(root, max_attempts=6)
            signal = program_ref(signal_program)
            half = program_ref(half_program)
            with launch(fixture) as client:
                first = client.run(request_for(fixture, signal, strategy_id="signal-1"), signal)
                self.assertEqual(first.metrics["brier"], "0.01")
                with self.assertRaisesRegex(ProtectedEvaluationError, "protected evaluation failed"):
                    client.run(request_for(fixture, half, strategy_id="half-same-client"), half)
                again = client.run(request_for(fixture, signal, strategy_id="signal-2"), signal)
                self.assertEqual(again.metrics["brier"], "0.01")
            with launch(fixture) as fresh:
                other = fresh.run(request_for(fixture, half, strategy_id="half-fresh"), half)
                self.assertEqual(other.metrics["brier"], "0.25")

    def test_first_requested_identity_stays_bound_even_when_preexecution_validation_fails(self):
        with scratch_directory() as root:
            fixture = build_fixture(root / "campaign", max_attempts=6)
            code = root / "code"
            code.mkdir()
            source = code / "t5_first_invalid_program.py"
            source.write_text("def predict(frame):\n    return '0.5'\n", encoding="utf-8")
            first = pin(source.stem, source)
            # Invalidate the bytes after pinning so the first request fails
            # before its program body executes.  The client/worker identity is
            # still permanently the first requested digest.
            source.write_text("def predict(frame):\n    return '0.4'\n", encoding="utf-8")
            signal = program_ref(signal_program)
            with launch_with_roots(fixture, code) as client:
                with self.assertRaisesRegex(ProtectedEvaluationError, "protected evaluation failed"):
                    client.run(request_for(fixture, first, strategy_id="first-invalid"), first)
                with self.assertRaisesRegex(ProtectedEvaluationError, "protected evaluation failed"):
                    client.run(request_for(fixture, signal, strategy_id="signal-same-client"), signal)
            with launch_with_roots(fixture, code) as fresh:
                certificate = fresh.run(
                    request_for(fixture, signal, strategy_id="signal-fresh"), signal,
                )
                self.assertEqual(certificate.metrics["brier"], "0.01")

    def test_worker_itself_rejects_a_second_program_identity(self):
        with scratch_directory() as root:
            fixture = build_fixture(root, max_attempts=4)
            signal = program_ref(signal_program)
            half = program_ref(half_program)
            with launch(fixture) as client:
                client.run(request_for(fixture, signal, strategy_id="bind"), signal)
                request = request_for(fixture, half, strategy_id="direct-worker-check")
                nonce = "a" * 64
                response = client._research_roundtrip(
                    {
                        "op": "predict",
                        "request": request.to_dict(),
                        "program": half.to_dict(),
                        "nonce": nonce,
                    }
                )
                self.assertEqual(
                    response,
                    {
                        "status": "error",
                        "message": "protected evaluation failed",
                        "nonce": nonce,
                    },
                )
                # A rejected second identity must not poison the bound program.
                again = client.run(request_for(fixture, signal, strategy_id="after"), signal)
                self.assertEqual(again.metrics["brier"], "0.01")

    def test_runtime_audit_layer_blocks_process_creation_during_research(self):
        with scratch_directory() as root:
            fixture = build_fixture(root / "campaign")
            code = root / "code"
            code.mkdir()
            source = code / "t5_runtime_process_program.py"
            source.write_text(
                "import os\n"
                "def predict(frame):\n"
                "    os.system('')\n"
                "    return '0.5'\n",
                encoding="utf-8",
            )
            program = pin(source.stem, source)
            with launch_with_roots(fixture, code) as client:
                with self.assertRaisesRegex(ProtectedEvaluationError, "protected evaluation failed"):
                    client.run(request_for(fixture, program, strategy_id="runtime-audit"), program)


if __name__ == "__main__":
    unittest.main()
