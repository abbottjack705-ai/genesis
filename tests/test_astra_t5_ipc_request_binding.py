"""T5 / PA-1: every research reply is bound to the exact current request.

Parent/worker correctness properties for the research IPC channel:

* P1 an accepted result belongs to the exact current request;
* P2 an earlier result (stale, duplicated or pre-queued) is never accepted as
  the current one;
* P3 an accepted result stays bound to the intended program identity;
* P4 a restarted client carries no request state from before the restart;
* P5 duplicated, incomplete, reordered or malformed messages fail closed;
* P6 concurrent requests are never paired with another request's response;
* P7 the parent validates a reply completely before anything uses it;
* P8 worker-internal protocol state is not exposed through the research
  interface (the program module namespace and the frame argument).

Replies are injected by the trusted test process through the parent's reply
queue or its research round trip, with the per-request nonce made known by
patching the parent's nonce source, so every case is deterministic.
"""

from __future__ import annotations

import json
import queue
import shutil
import threading
import unittest
from pathlib import Path
from unittest import mock

import genesis.protected as protected
from genesis.evaluation import ProtectedEvaluationError
from genesis.protected import MAX_IPC_BYTES, FrozenPredictionArtifact
from genesis.repro import canonical_json

from ._support import scratch_directory
from .protected_research_programs import half_program, signal_program
from .test_astra_s5_process import (
    S5_LABEL_ROOTS,
    build_fixture,
    launch,
    program_ref,
    request_for,
)
from .test_astra_t3_protected_integrity import launch as launch_with_roots
from .test_astra_t3_protected_integrity import pin


FAILED = ("blocked", "protected evaluation failed")


def nonce(character: str) -> str:
    return character * 64


def outcome(client, request, program):
    try:
        certificate = client.run(request, program)
    except ProtectedEvaluationError as exc:
        return ("blocked", str(exc))
    return ("certified", certificate.metrics["brier"], certificate.strategy_id)


def known_nonces(*values: str):
    return mock.patch.object(protected.secrets, "token_hex", side_effect=list(values))


def artifact_reply(client, request, *, reply_nonce, probability="0.5", **overrides):
    predictions = {frame_id: probability for frame_id in client._sealed_frames.frame_ids}
    artifact = FrozenPredictionArtifact.create(
        overrides.pop("artifact_request", request),
        overrides.pop("frame_manifest_hash", client.frame_manifest_hash),
        overrides.pop("predictions", predictions),
    )
    reply = {
        "status": "artifact",
        "artifact": artifact.to_dict(),
        "research_pid": overrides.pop("research_pid", client.research_pid),
        "nonce": reply_nonce,
    }
    reply.update(overrides)
    return reply


def worker_alive(client) -> bool:
    return client._research_process.poll() is None


class T5IpcRequestBindingTests(unittest.TestCase):
    def tearDown(self) -> None:
        while S5_LABEL_ROOTS:
            shutil.rmtree(S5_LABEL_ROOTS.pop(), ignore_errors=True)

    # --- P2 / P5: reply stream ordering ---------------------------------------

    def test_line_queued_before_the_request_is_never_accepted_as_its_reply(self):
        with scratch_directory() as root:
            fixture = build_fixture(root)
            program = program_ref(signal_program)
            request = request_for(fixture, program, strategy_id="prequeued")
            with launch(fixture) as client, known_nonces(nonce("a")):
                early = artifact_reply(client, request, reply_nonce=nonce("a"))
                client._research_messages.put(canonical_json(early))
                result = outcome(client, request, program)
                self.assertNotEqual(
                    result, ("certified", "0.25", "prequeued"),
                    "P2: a reply that existed before the request was certified",
                )
                self.assertEqual(result, FAILED)
                self.assertFalse(worker_alive(client), "P5: desynchronized stream kept running")
            self.assertEqual(fixture["attempts"].counts(fixture["campaign"]), (1, 1))

    def test_duplicate_of_a_completed_reply_is_not_paired_with_the_next_request(self):
        with scratch_directory() as root:
            fixture = build_fixture(root)
            program = program_ref(signal_program)
            first = request_for(fixture, program, strategy_id="first")
            second = request_for(fixture, program, strategy_id="second")
            with launch(fixture) as client, known_nonces(nonce("a"), nonce("b")):
                self.assertEqual(outcome(client, first, program), ("certified", "0.01", "first"))
                duplicate = artifact_reply(
                    client, first, reply_nonce=nonce("a"), probability="0.5",
                )
                client._research_messages.put(canonical_json(duplicate))
                self.assertEqual(outcome(client, second, program), FAILED)
                self.assertFalse(worker_alive(client))

    def test_reply_carrying_an_earlier_request_nonce_is_rejected(self):
        with scratch_directory() as root:
            fixture = build_fixture(root)
            program = program_ref(signal_program)
            first = request_for(fixture, program, strategy_id="first")
            second = request_for(fixture, program, strategy_id="second")
            with launch(fixture) as client, known_nonces(nonce("a"), nonce("b")):
                self.assertEqual(outcome(client, first, program), ("certified", "0.01", "first"))
                stale = artifact_reply(client, second, reply_nonce=nonce("a"))
                with mock.patch.object(client, "_research_roundtrip", return_value=stale), \
                        mock.patch.object(client, "_evaluate_reserved") as evaluate:
                    self.assertEqual(outcome(client, second, program), FAILED)
                    evaluate.assert_not_called()
                self.assertFalse(worker_alive(client))

    def test_unauthenticated_error_reply_is_a_protocol_violation(self):
        with scratch_directory() as root:
            fixture = build_fixture(root)
            program = program_ref(signal_program)
            request = request_for(fixture, program)
            unauthenticated = {"status": "error", "message": "protected evaluation failed"}
            with launch(fixture) as client, known_nonces(nonce("a")):
                with mock.patch.object(
                    client, "_research_roundtrip", return_value=unauthenticated,
                ):
                    self.assertEqual(outcome(client, request, program), FAILED)
                self.assertFalse(
                    worker_alive(client),
                    "P1: an error reply not bound to the request was accepted as its result",
                )

    def test_authenticated_error_fails_only_its_own_request(self):
        # The program is refused before it executes (its bytes no longer match
        # the pin), so the worker's contamination latch is not involved.
        with scratch_directory() as root:
            fixture = build_fixture(root)
            code = root / "code"
            code.mkdir()
            source = code / "t5_ipc_repinned.py"
            body = "def predict(frame):\n    return '0.5'\n"
            source.write_text(body, encoding="utf-8")
            program = pin(source.stem, source)
            with launch_with_roots(fixture, code) as client:
                pid = client.research_pid
                source.write_text("# changed\n" + body, encoding="utf-8")
                self.assertEqual(
                    outcome(client, request_for(fixture, program, strategy_id="stale"), program),
                    FAILED,
                )
                self.assertTrue(worker_alive(client), "an authenticated error broke the stream")
                source.write_text(body, encoding="utf-8")
                self.assertEqual(
                    outcome(client, request_for(fixture, program, strategy_id="after"), program),
                    ("certified", "0.25", "after"),
                )
                self.assertEqual(client.last_research_pid, pid)

    # --- P3 / P7: identity and validation before use ---------------------------

    def test_authenticated_reply_with_wrong_identity_is_rejected_before_use(self):
        with scratch_directory() as root:
            fixture = build_fixture(root, max_attempts=8)
            program = program_ref(signal_program)
            other = program_ref(half_program)
            request = request_for(fixture, program, strategy_id="bound")
            cases = {
                "other program digest": {
                    "artifact_request": request_for(fixture, other, strategy_id="bound"),
                },
                "other strategy id": {
                    "artifact_request": request_for(fixture, program, strategy_id="other"),
                },
                "other frame manifest": {"frame_manifest_hash": "f" * 64},
                "missing frame": {"predictions": {"frame-0": "0.5"}},
                "extra frame": {
                    "predictions": {"frame-0": "0.5", "frame-1": "0.5", "frame-9": "0.5"},
                },
                "other research pid": {"research_pid": 1},
                "extra reply field": {"certificate": {}},
            }
            with launch(fixture) as client:
                for index, (label, overrides) in enumerate(cases.items()):
                    current = nonce("0123456789abcdef"[index])
                    reply = artifact_reply(client, request, reply_nonce=current, **overrides)
                    with self.subTest(label), known_nonces(current), \
                            mock.patch.object(client, "_research_roundtrip", return_value=reply), \
                            mock.patch.object(client, "_evaluate_reserved") as evaluate:
                        self.assertEqual(outcome(client, request, program), FAILED)
                        evaluate.assert_not_called()
            self.assertEqual(fixture["attempts"].counts(fixture["campaign"]), (7, 7))

    def test_exact_authenticated_reply_is_the_one_evaluated(self):
        with scratch_directory() as root:
            fixture = build_fixture(root)
            program = program_ref(signal_program)
            request = request_for(fixture, program, strategy_id="exact")
            with launch(fixture) as client, known_nonces(nonce("a")):
                reply = artifact_reply(client, request, reply_nonce=nonce("a"), probability="0.5")
                with mock.patch.object(client, "_research_roundtrip", return_value=reply):
                    self.assertEqual(outcome(client, request, program), ("certified", "0.25", "exact"))

    # --- P5: message decoding ---------------------------------------------------

    def test_reply_decoder_rejects_malformed_duplicated_and_incomplete_lines(self):
        valid = {"nonce": nonce("a"), "status": "error", "message": "protected evaluation failed"}
        canonical = canonical_json(valid)
        cases = {
            "duplicate key": canonical.replace(
                b'"message"', b'"nonce":"' + nonce("b").encode() + b'","message"',
            ),
            "non-canonical spacing": json.dumps(valid, sort_keys=True).encode() + b"\n",
            "non-canonical key order": json.dumps(
                dict(reversed(list(valid.items()))), separators=(",", ":"),
            ).encode() + b"\n",
            "incomplete line": canonical[:-1],
            "truncated json": canonical[:20] + b"\n",
            "end of stream": None,
            "oversized": b'"' + b"x" * MAX_IPC_BYTES + b'"\n',
            "not an object": b"[]\n",
            "invalid utf-8": b'{"status":"\xff"}\n',
            "non-finite number": b'{"status":NaN}\n',
            "two messages on one line": canonical[:-1] + canonical,
        }
        self.assertEqual(self.decode(canonical), valid)
        for label, raw in cases.items():
            with self.subTest(label), self.assertRaises(ProtectedEvaluationError):
                self.decode(raw)

    @staticmethod
    def decode(raw):
        messages: "queue.Queue[bytes | None]" = queue.Queue()
        messages.put(raw)
        return protected._take_research_message(messages, timeout=1)

    def test_worker_rejects_duplicated_and_non_canonical_requests(self):
        with scratch_directory() as root:
            fixture = build_fixture(root)
            program = program_ref(half_program)
            request = request_for(fixture, program)
            payload = {
                "op": "predict",
                "request": request.to_dict(),
                "program": program.to_dict(),
                "nonce": nonce("a"),
            }
            canonical = canonical_json(payload)
            cases = {
                "duplicate nonce": canonical.replace(
                    b'"op"', b'"nonce":"' + nonce("b").encode() + b'","op"',
                ),
                "non-canonical": json.dumps(payload, sort_keys=True).encode() + b"\n",
            }
            generic = {"status": "error", "message": "protected evaluation failed"}
            with launch(fixture) as client:
                for label, raw in cases.items():
                    with self.subTest(label):
                        self.assertEqual(self.exchange(client, raw), generic)
                self.assertEqual(
                    outcome(client, request_for(fixture, program, strategy_id="after"), program),
                    ("certified", "0.25", "after"),
                )

    @staticmethod
    def exchange(client, raw: bytes):
        with client._research_lock:
            client._research_process.stdin.write(raw)
            client._research_process.stdin.flush()
            return protected._take_research_message(client._research_messages, timeout=10)

    # --- P6: concurrency --------------------------------------------------------

    def test_concurrent_requests_each_receive_their_own_result(self):
        with scratch_directory() as root:
            fixture = build_fixture(root, max_attempts=8)
            signal = program_ref(signal_program)
            half = program_ref(half_program)
            jobs = [
                (request_for(fixture, program, strategy_id=f"job-{index}"), program, expected)
                for index, (program, expected) in enumerate(
                    [(signal, "0.01"), (half, "0.25")] * 4
                )
            ]
            results: dict[str, tuple] = {}
            barrier = threading.Barrier(len(jobs))
            with launch(fixture) as client:
                def work(request, program):
                    barrier.wait(10)
                    results[request.strategy_id] = outcome(client, request, program)

                threads = [
                    threading.Thread(target=work, args=(request, program))
                    for request, program, _expected in jobs
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(60)
            for request, _program, expected in jobs:
                self.assertEqual(
                    results.get(request.strategy_id),
                    ("certified", expected, request.strategy_id),
                    "P6: a concurrent request was paired with another response",
                )

    # --- P4: restart --------------------------------------------------------------

    def test_restart_does_not_accept_a_reply_for_the_previous_worker(self):
        with scratch_directory() as root:
            fixture = build_fixture(root, max_attempts=4)
            program = program_ref(signal_program)
            before = request_for(fixture, program, strategy_id="before")
            with known_nonces(nonce("a"), nonce("b")):
                with launch(fixture) as client:
                    self.assertEqual(
                        outcome(client, before, program), ("certified", "0.01", "before"),
                    )
                    old_reply = artifact_reply(client, before, reply_nonce=nonce("a"))
                with launch(fixture) as restarted:
                    after = request_for(fixture, program, strategy_id="after")
                    replayed = dict(old_reply, research_pid=restarted.research_pid)
                    with mock.patch.object(
                        restarted, "_research_roundtrip", return_value=replayed,
                    ), mock.patch.object(restarted, "_evaluate_reserved") as evaluate:
                        self.assertEqual(outcome(restarted, after, program), FAILED)
                        evaluate.assert_not_called()
            with launch(fixture) as fresh:
                self.assertEqual(
                    outcome(fresh, request_for(fixture, program, strategy_id="fresh"), program),
                    ("certified", "0.01", "fresh"),
                )

    def test_request_after_a_protocol_violation_fails_closed_until_restart(self):
        with scratch_directory() as root:
            fixture = build_fixture(root, max_attempts=4)
            program = program_ref(signal_program)
            with launch(fixture) as client:
                client._research_messages.put(canonical_json({"status": "artifact"}))
                self.assertEqual(
                    outcome(client, request_for(fixture, program, strategy_id="one"), program),
                    FAILED,
                )
                self.assertEqual(
                    outcome(client, request_for(fixture, program, strategy_id="two"), program),
                    FAILED,
                )
            with launch(fixture) as restarted:
                self.assertEqual(
                    outcome(restarted, request_for(fixture, program, strategy_id="three"), program),
                    ("certified", "0.01", "three"),
                )

    # --- P8: research interface ---------------------------------------------------

    def test_research_interface_carries_no_worker_protocol_state(self):
        with scratch_directory() as root:
            fixture = build_fixture(root)
            code = root / "code"
            code.mkdir()
            trace = root / "research" / "interface-trace.json"
            source = code / "t5_ipc_interface_trace.py"
            source.write_text(
                "import json\n"
                "from pathlib import Path\n"
                "MODULE_NAMES = sorted(dir())\n"
                "def predict(frame):\n"
                "    seen = {'module': MODULE_NAMES, 'frame': frame.to_dict(),\n"
                "            'frame_repr': repr(frame), 'local': sorted(dir())}\n"
                f"    with Path({str(trace)!r}).open('a', encoding='utf-8') as handle:\n"
                "        handle.write(json.dumps(seen, sort_keys=True) + '\\n')\n"
                "    return '0.5'\n",
                encoding="utf-8",
            )
            program = pin(source.stem, source)
            request = request_for(fixture, program, strategy_id="interface")
            with launch_with_roots(fixture, code) as client, known_nonces(nonce("7")):
                self.assertEqual(outcome(client, request, program), ("certified", "0.25", "interface"))
                attempt_ids = {
                    row.get("attempt_id") for row in fixture["attempts"].log.records()
                } - {None}
            seen = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(seen), len(fixture["sealed"].frames))
            self.assertEqual(
                [entry["frame"] for entry in seen],
                [frame.to_dict() for frame in fixture["sealed"].frames],
            )
            text = trace.read_text(encoding="utf-8")
            self.assertNotIn(nonce("7"), text, "P8: the request nonce reached research")
            for attempt_id in attempt_ids:
                self.assertNotIn(attempt_id, text, "P8: the attempt id reached research")
            for entry in seen:
                self.assertEqual(entry["local"], ["frame"])
                self.assertEqual(
                    set(entry["module"]) - {"json", "Path"},
                    {"__builtins__", "__doc__", "__file__", "__loader__", "__name__",
                     "__package__", "__spec__"},
                )


if __name__ == "__main__":
    unittest.main()
