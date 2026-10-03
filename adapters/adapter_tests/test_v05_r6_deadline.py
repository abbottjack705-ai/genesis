"""R6 / RA5-004 - the hard deadline ``Tq + request_timeout_seconds`` bounds the WHOLE attempt, response read included
(design 14.6 rule 3, BND-04): "at the deadline the connection is aborted". Per-``recv`` timeouts did not: a peer that
paces its bytes just inside the timeout got a fresh one every time, and a 3 s deadline held the transport - and with
it the single writer and its run lock - for 40.6 s and returned ``RESPONSE`` with ``T1`` 37 s past the deadline.

Three layers, none of which accepts "the runner discards the late body afterwards" as the fix:

* deterministic fake connections on a controlled clock: the transport re-derives the time left before EVERY blocking
  operation, never arms a non-positive timeout, and stops at exact equality (kills the audit's mutants M03 and M04);
* real loopback sockets (a slow-drip body, a slow-drip head, a handshake that never completes): ``send`` returns by the
  deadline whatever the peer does, and a drip that finishes in time is still a response;
* the runner: a late response is discarded at ``T1 >= deadline``, a send is never started at ``T0 >= deadline``
  (kills M07, M08 and M09), and through the real transport a slow peer ends in a recorded ``DeadlineExceeded``
  no-response with the writer released.
"""

from __future__ import annotations

import socket
import threading
import time
import unittest
from unittest import mock

from genesis_adapters import errors as err
from genesis_adapters.oddspapi import transport_http as th
from genesis_adapters.secrets import Secret

from . import parser_support as ps
from .loopback_support import LoopbackHttps, Reply, test_ca_context
from .support import SENTINEL_KEY, FixedClock, SequenceClock, build_rig, odds_item, ok, read_jsonl, scratch_root
from .test_v05_transport_http import odds_request

T0 = "2026-10-01T12:00:00.000000Z"
JSON = (("content-type", "application/json"),)
SLACK = 2.0            # seconds a loaded machine may add to a bound that is about 1 s: far below any drip total here


class ElapsedClock:
    """A trusted-clock double that runs in REAL time from a fixed calendar base, strictly increasing: a slow-peer test
    is then deterministic about the date (never near a UTC day boundary) yet exercises real durations."""

    def __init__(self, start: str = T0):
        self.start = start
        self.origin = time.monotonic_ns()
        self.last = -1

    def now(self) -> str:
        micros = max((time.monotonic_ns() - self.origin) // 1000, self.last + 1)
        self.last = micros
        return ps.iso_add(self.start, micros=micros)


def bounded_transport(server=None, *, address=None, policy=None) -> th.HttpsTransport:
    return th.HttpsTransport(Secret(SENTINEL_KEY), credential_param="apiKey", policy=policy or ps.POLICY,
                             ssl_context=test_ca_context(), connect_address=address or server.address)


def drip(length: int = 20) -> bytes:
    return b"[" + b"1," * ((length - 2) // 2) + b"1]"


# ---------------------------------------------------------------------------------------------------------
class TimedConnection:
    """A fake connection on a controlled clock: a stage may advance the clock, and every timeout the transport arms
    is recorded together with the stage that armed it."""

    def __init__(self, clock: FixedClock, *, advance: dict | None = None, chunks=(b"[1,", b"2,", b"3]")):
        self.clock = clock
        self.advance = advance or {}
        self.chunks = list(chunks)
        self.armed: list[tuple[str, float]] = []
        self.writes = 0
        self.reads = 0

    def _tick(self, stage: str) -> None:
        seconds = self.advance.get(stage)
        if seconds:
            self.clock.advance(seconds=seconds)

    def open(self, timeout):
        self.armed.append(("open", timeout))
        self._tick("open")

    def settimeout(self, timeout):
        self.armed.append(("settimeout", timeout))

    def write(self, method, target, headers):
        self._tick("write")
        self.writes += 1

    def read_head(self):
        self._tick("read_head")
        return 200, [("Content-Type", "application/json")]

    def read_chunk(self, size):
        self._tick("read_chunk")
        self.reads += 1
        return self.chunks[self.reads - 1] if self.reads <= len(self.chunks) else b""

    def finished(self):
        return self.reads >= len(self.chunks)

    def close(self):
        pass


def fake_transport(connection, *, policy=None) -> th.HttpsTransport:
    return th.HttpsTransport(Secret(SENTINEL_KEY), credential_param="apiKey", policy=policy or ps.POLICY,
                             connection_factory=lambda *args: connection)


class RemainingTimeIsRederivedBeforeEveryOperationTests(unittest.TestCase):
    """Deterministic: the clock is advanced by the connection itself, so equality at the deadline is exact."""

    def setUp(self):
        self.timeout = ps.POLICY.request_timeout_seconds
        self.deadline = ps.iso_add(T0, seconds=self.timeout)

    def send(self, connection, clock):
        return fake_transport(connection).send(odds_request(), clock=clock, deadline_at=self.deadline)

    def test_a_connect_that_uses_up_the_deadline_writes_nothing_and_arms_no_non_positive_timeout(self):
        for overshoot in (0, 1):                                    # exactly at the deadline, and past it
            with self.subTest(overshoot=overshoot):
                clock = FixedClock(T0)
                connection = TimedConnection(clock, advance={"open": self.timeout + overshoot})
                result = self.send(connection, clock)
                self.assertEqual((result.outcome, result.sanitized_error["class"]), ("NO_RESPONSE", "TimeoutError"))
                self.assertEqual(connection.writes, 0)              # no request byte at or after the deadline (HA-03)
                self.assertTrue(all(value > 0 for _, value in connection.armed), connection.armed)

    def test_the_read_loop_stops_the_moment_the_deadline_is_reached(self):
        clock = FixedClock(T0)
        chunks = (b"[1,", b"2,", b"3,", b"4,", b"5]")
        step = self.timeout / 3                                      # each body read takes a third of the budget
        connection = TimedConnection(clock, advance={"read_chunk": step}, chunks=chunks)
        result = self.send(connection, clock)
        self.assertEqual((result.outcome, result.http_status), ("TRUNCATED", 200))
        self.assertEqual(result.sanitized_error, {"class": "TimeoutError", "errno": None})
        self.assertEqual(result.body, b"".join(chunks[:connection.reads]))
        self.assertLess(connection.reads, len(chunks))               # it did NOT read on past the deadline
        self.assertTrue(all(value > 0 for _, value in connection.armed), connection.armed)

    def test_exactly_at_the_deadline_nothing_more_is_read(self):
        clock = FixedClock(T0)
        connection = TimedConnection(clock, advance={"read_chunk": self.timeout / 2}, chunks=(b"[1,", b"2,", b"3]"))
        result = self.send(connection, clock)
        self.assertEqual(connection.reads, 2)                        # 2 reads reach t = timeout exactly: a 3rd is refused
        self.assertEqual((result.outcome, result.body), ("TRUNCATED", b"[1,2,"))
        self.assertNotIn(0, [value for _, value in connection.armed])

    def test_the_timeout_armed_before_each_operation_is_exactly_the_time_left(self):
        clock = FixedClock(T0)
        connection = TimedConnection(clock, advance={"open": 1, "write": 2, "read_head": 3, "read_chunk": 4})
        result = self.send(connection, clock)
        self.assertEqual(result.outcome, "RESPONSE")
        left = self.timeout
        expected = [("open", left)]
        left -= 1
        expected += [("settimeout", left)]                           # after connect, before the request write
        left -= 2
        expected += [("settimeout", left)]                           # after the write, before the head
        left -= 3
        # the three body reads: re-armed from what is left each time
        for _ in range(3):
            expected += [("settimeout", left)]
            left -= 4
        self.assertEqual(connection.armed, expected)

    def test_a_past_deadline_before_the_head_read_is_a_timeout_not_a_blocking_read(self):
        clock = FixedClock(T0)
        connection = TimedConnection(clock, advance={"write": self.timeout})
        result = self.send(connection, clock)
        self.assertEqual((result.outcome, result.sanitized_error["class"]), ("NO_RESPONSE", "TimeoutError"))
        self.assertEqual(connection.writes, 1)
        self.assertTrue(all(value > 0 for _, value in connection.armed), connection.armed)


# ---------------------------------------------------------------------------------------------------------
class SlowPeerOnRealSocketsTests(unittest.TestCase):
    """The attempt is aborted at the deadline however the peer paces its bytes (RA5-004)."""

    DEADLINE_S = 1

    def run_send(self, server=None, *, address=None):
        clock = ElapsedClock()
        deadline = ps.iso_add(T0, seconds=self.DEADLINE_S)
        began = time.monotonic()
        result = bounded_transport(server, address=address).send(odds_request(), clock=clock, deadline_at=deadline)
        return result, time.monotonic() - began, deadline

    def test_a_slow_drip_body_cannot_hold_the_transport_past_the_deadline(self):
        server = LoopbackHttps([Reply(body=drip(20), chunks=20, pause=0.4)])        # 8 s of dripping, 1 s deadline
        self.addCleanup(server.close)
        result, elapsed, deadline = self.run_send(server)
        self.assertLess(elapsed, self.DEADLINE_S + SLACK, f"held the transport {elapsed:.1f}s")
        self.assertNotEqual(result.outcome, "RESPONSE")
        self.assertIn(result.outcome, ("TRUNCATED", "NO_RESPONSE"))
        self.assertGreaterEqual(result.response_received_at or deadline, deadline)   # T1, if any, is not before the deadline

    def test_a_slow_drip_response_head_cannot_hold_the_transport_past_the_deadline(self):
        server = LoopbackHttps([Reply(body=b"[]", head_pause=0.1)])                  # ~8 s of header bytes
        self.addCleanup(server.close)
        result, elapsed, _ = self.run_send(server)
        self.assertLess(elapsed, self.DEADLINE_S + SLACK, f"held the transport {elapsed:.1f}s")
        self.assertEqual(result.outcome, "NO_RESPONSE")
        self.assertIsNone(result.http_status)

    def test_a_peer_that_accepts_but_never_completes_the_tls_handshake_cannot_hold_the_transport(self):
        listener = socket.create_server(("127.0.0.1", 0))
        release = threading.Event()
        held = []

        def accept():
            listener.settimeout(0.2)
            while not release.is_set():
                try:
                    held.append(listener.accept()[0])
                except OSError:
                    continue

        thread = threading.Thread(target=accept, daemon=True)
        thread.start()
        self.addCleanup(lambda: (release.set(), thread.join(timeout=5), [c.close() for c in held], listener.close()))
        result, elapsed, _ = self.run_send(address=("127.0.0.1", listener.getsockname()[1]))
        self.assertLess(elapsed, self.DEADLINE_S + SLACK, f"held the transport {elapsed:.1f}s")
        self.assertEqual(result.outcome, "NO_RESPONSE")

    def test_a_slow_drip_that_finishes_before_the_deadline_is_still_a_response(self):
        body = drip(10)
        server = LoopbackHttps([Reply(body=body, chunks=10, pause=0.02)])             # 0.2 s of dripping
        self.addCleanup(server.close)
        result, elapsed, _ = self.run_send(server)
        self.assertEqual((result.outcome, result.body), ("RESPONSE", body))
        self.assertLess(elapsed, self.DEADLINE_S + SLACK)


# ---------------------------------------------------------------------------------------------------------
class SocketPairWrapperTests(unittest.TestCase):
    """The deadline wrapper itself, with no TLS: bounded reads over a plain socket pair."""

    def pair(self):
        reader, writer = socket.socketpair()
        self.addCleanup(reader.close)
        self.addCleanup(writer.close)
        return reader, writer

    def test_reads_are_bounded_by_the_deadline_however_the_writer_paces_its_bytes(self):
        reader, writer = self.pair()
        stop = threading.Event()

        def trickle():
            while not stop.is_set():
                try:
                    writer.sendall(b"x")
                except OSError:
                    return
                stop.wait(0.05)

        thread = threading.Thread(target=trickle, daemon=True)
        thread.start()
        self.addCleanup(lambda: (stop.set(), thread.join(timeout=5)))
        edge = time.monotonic() + 0.4
        bounded = th._BoundedSocket(reader, lambda: reader.settimeout(_left(edge)))
        began = time.monotonic()
        with self.assertRaises(TimeoutError):
            bounded.makefile("rb").read(10_000)                          # would take ~500 s at one byte per 50 ms
        self.assertLess(time.monotonic() - began, 0.4 + SLACK)

    def test_a_connection_deadline_only_ever_shrinks(self):
        connection = th._Connection("api.oddspapi.io", 443, test_ca_context(), None)
        connection._bound(5.0)
        first = connection._deadline
        connection._bound(500.0)                                         # a later, larger budget must not extend it
        self.assertEqual(connection._deadline, first)
        connection._bound(0.5)
        self.assertLess(connection._deadline, first)

    def test_an_exhausted_deadline_arms_nothing(self):
        connection = th._Connection("api.oddspapi.io", 443, test_ca_context(), None)
        connection._bound(0.01)
        time.sleep(0.05)
        with self.assertRaises(TimeoutError):
            connection._left()


def _left(edge: float) -> float:
    left = edge - time.monotonic()
    if left <= 0:
        raise TimeoutError("deadline")
    return left


class RecordingTls:
    """The TLS socket as the wrapper sees it: every timeout armed and every call made, in order."""

    def __init__(self, journal=None):
        self.journal = [] if journal is None else journal
        self.timeouts: list[float] = []
        self.closed = False

    def settimeout(self, value):
        self.timeouts.append(value)
        self.journal.append(("settimeout", value))

    def recv_into(self, buffer):
        self.journal.append(("recv_into", len(buffer)))
        return 0

    def sendall(self, data):
        self.journal.append(("sendall", bytes(data)))

    def close(self):
        self.closed = True
        self.journal.append(("close", None))


class ConnectionArithmeticTests(unittest.TestCase):
    """The absolute deadline's arithmetic on a controlled monotonic clock (the mutants that grant a spare second to any
    blocking call, treat exact equality as time left, or let a later budget replace the deadline all survived the
    real-socket tests, whose slack hides a constant)."""

    def setUp(self):
        self.now = [100.0]
        patcher = mock.patch.object(th.time, "monotonic", lambda: self.now[0])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.connection = th._Connection("api.oddspapi.io", 443, test_ca_context(), None)
        self.connection.tls = RecordingTls()

    def test_time_left_is_the_distance_to_the_deadline_and_zero_is_already_a_timeout(self):
        connection = self.connection
        connection._bound(10.0)
        self.assertEqual(connection._left(), 10.0)
        self.now[0] = 104.0
        self.assertEqual(connection._left(), 6.0)
        for moment in (110.0, 110.000001, 500.0):                      # exactly at, just after, long after
            self.now[0] = moment
            with self.subTest(moment=moment), self.assertRaises(TimeoutError):
                connection._left()

    def test_every_blocking_operation_is_armed_with_exactly_the_time_left(self):
        connection = self.connection
        connection._bound(10.0)
        self.now[0] = 103.0
        connection._arm()
        wrapper = th._BoundedSocket(connection.tls, connection._arm)
        wrapper.recv_into(bytearray(1))
        wrapper.sendall(b"x")
        self.assertEqual(connection.tls.timeouts, [7.0, 7.0, 7.0])    # no spare second, none shorter

    def test_settimeout_can_only_pull_the_deadline_in(self):
        connection = self.connection
        connection._bound(10.0)
        connection.settimeout(2.0)
        self.assertEqual((connection._deadline, connection.tls.timeouts), (102.0, [2.0]))
        connection.settimeout(50.0)                                     # a larger budget changes nothing
        self.assertEqual((connection._deadline, connection.tls.timeouts), (102.0, [2.0, 2.0]))

    def fake_network(self, *behaviours):
        """``socket.getaddrinfo`` yielding one address per behaviour, and ``socket.socket`` instances that record the
        timeout they were armed with and what they connected to. A behaviour is ``(seconds its connect takes on the
        controlled clock, the exception it then raises or None)``."""

        sockets = []
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (f"192.0.2.{index + 1}", 443))
                     for index in range(len(behaviours))]
        now = self.now

        class FakeSocket:
            def __init__(self, family, kind, proto):
                self.index = len(sockets)
                self.timeout = None
                self.connected = None
                self.closed = False
                sockets.append(self)

            def settimeout(self, value):
                self.timeout = value

            def connect(self, target):
                seconds, failure = behaviours[self.index]
                self.connected = target
                now[0] += seconds
                if failure is not None:
                    raise failure

            def close(self):
                self.closed = True

        for patch in (mock.patch.object(th.socket, "getaddrinfo", lambda *args, **kwargs: addresses),
                      mock.patch.object(th.socket, "socket", FakeSocket)):
            patch.start()
            self.addCleanup(patch.stop)
        return sockets

    def test_each_resolved_address_is_tried_under_the_time_that_is_left(self):
        sockets = self.fake_network((3.0, OSError("timed out")), (1.0, None))
        self.connection._bound(10.0)
        self.assertIs(self.connection._connect(), sockets[1])
        self.assertEqual([item.timeout for item in sockets], [10.0, 7.0])     # the second gets what three seconds left
        self.assertEqual([item.closed for item in sockets], [True, False])    # the failed attempt is released

    def test_no_address_is_tried_once_an_earlier_attempt_used_up_the_deadline(self):
        sockets = self.fake_network((10.0, OSError("timed out")), (0.0, None))
        self.connection._bound(10.0)
        with self.assertRaises(TimeoutError):                                  # never a fresh full timeout per address
            self.connection._connect()
        self.assertEqual([item.connected is not None for item in sockets], [True, False])

    def test_nothing_is_connected_when_the_deadline_has_already_passed(self):
        sockets = self.fake_network((0.0, None), (0.0, None))
        self.connection._bound(10.0)
        self.now[0] = 110.0
        with self.assertRaises(TimeoutError):
            self.connection._connect()
        self.assertEqual([item.connected for item in sockets], [None, None])

    def test_the_last_failure_is_the_one_raised_when_every_address_fails(self):
        self.fake_network((0.0, OSError("first")), (0.0, OSError("second")))
        self.connection._bound(10.0)
        with self.assertRaises(OSError) as caught:
            self.connection._connect()
        self.assertEqual(str(caught.exception), "second")

    def test_closing_the_connection_closes_the_response_first_and_always_the_connection(self):
        events = []

        class Closer:
            def __init__(self, name, fail=False):
                self.name, self.fail = name, fail

            def close(self):
                events.append(self.name)
                if self.fail:
                    raise OSError("close failed")

        self.connection.response, self.connection.http = Closer("response"), Closer("http")
        self.connection.close()
        self.assertEqual(events, ["response", "http"])
        events.clear()
        self.connection.response = Closer("response", fail=True)         # a failing response close
        with self.assertRaises(OSError):
            self.connection.close()
        self.assertEqual(events, ["response", "http"])                   # still releases the connection


class BoundedSocketContractTests(unittest.TestCase):
    """``_BoundedSocket`` against the contract ``http.client`` relies on: every blocking call is armed first, and a real
    close waits for the last reader (a ``Connection: close`` response closes the connection object as soon as it begins
    and goes on reading through its ``makefile`` reader)."""

    def setUp(self):
        self.journal = []
        self.tls = RecordingTls(self.journal)
        self.socket = th._BoundedSocket(self.tls, lambda: self.journal.append(("arm", None)))

    def test_a_send_and_a_receive_are_armed_before_they_block(self):
        self.socket.sendall(b"GET")
        self.socket.recv_into(bytearray(4))
        self.assertEqual(self.journal, [("arm", None), ("sendall", b"GET"), ("arm", None), ("recv_into", 4)])

    def test_a_close_with_no_reader_closes_the_connection_at_once(self):
        self.socket.close()
        self.assertTrue(self.tls.closed)

    def test_a_close_waits_for_every_reader_and_then_happens_exactly_once(self):
        first, second = self.socket.makefile("rb"), self.socket.makefile("rb")
        self.socket.close()
        self.assertFalse(self.tls.closed)
        first.close()
        self.assertFalse(self.tls.closed)
        second.close()
        self.assertTrue(self.tls.closed)
        self.assertEqual([entry for entry in self.journal if entry[0] == "close"], [("close", None)])

    def test_a_reader_that_closes_first_releases_nothing_until_the_connection_is_closed(self):
        reader = self.socket.makefile("rb")
        reader.close()
        self.assertFalse(self.tls.closed)
        self.socket.close()
        self.assertTrue(self.tls.closed)

    def test_closing_a_reader_twice_releases_it_once(self):
        first, second = self.socket.makefile("rb"), self.socket.makefile("rb")
        self.socket.close()
        first.close()
        first.close()
        self.assertFalse(self.tls.closed)                                 # the second reader is still open
        second.close()
        self.assertTrue(self.tls.closed)


# ---------------------------------------------------------------------------------------------------------
class RunnerDeadlineBranchTests(unittest.TestCase):
    """The runner's own deadline checks, at their exact edges (the audit's mutants M07, M08, M09 all survived)."""

    def rig(self, root, script, clock):
        return build_rig(root, capture=True, script=script, clock=clock)

    def acquire_with_t1(self, t1_offset_micros: int):
        """One attempt whose response is stamped ``deadline + offset`` (a late or an in-time receipt)."""

        with scratch_root() as root:
            timeout = ps.POLICY.request_timeout_seconds
            clock = FixedClock(T0, step_micros=1000)
            tq = T0                                                # the first reading of the attempt is Tq
            stamp = ps.iso_add(tq, seconds=timeout, micros=t1_offset_micros)
            rig = self.rig(root, [ok(b"[]", headers=JSON, t1=stamp)], clock)
            outcome = rig.runner.acquire(odds_item())
            return outcome, read_jsonl(rig.acq_path), tq

    def test_a_response_received_exactly_at_the_deadline_is_discarded(self):
        outcome, rows, _ = self.acquire_with_t1(0)
        self.assertEqual((outcome.outcome, outcome.detail), ("NO_RESPONSE", "DeadlineExceeded"))
        done = [row for row in rows if row["record_type"] == "acq_completed"][0]
        self.assertEqual((done["outcome"], done["sanitized_error"]["class"], done["raw_observation_id"]),
                         ("NO_RESPONSE", "DeadlineExceeded", None))   # nothing of the late body was kept

    def test_a_response_after_the_deadline_is_discarded(self):
        outcome, _, _ = self.acquire_with_t1(1)
        self.assertEqual((outcome.outcome, outcome.detail), ("NO_RESPONSE", "DeadlineExceeded"))

    def test_a_response_one_microsecond_before_the_deadline_is_accepted(self):
        outcome, _, _ = self.acquire_with_t1(-1)
        self.assertEqual((outcome.outcome, outcome.failure), ("RESPONSE", None))

    def test_no_request_is_started_at_or_after_the_deadline(self):
        timeout = ps.POLICY.request_timeout_seconds
        tq = T0
        deadline = ps.iso_add(tq, seconds=timeout)
        # readings: Tq, the post-reservation stamp, then T0 (the stamp just before the send) - the third decides
        for t0, sent in ((deadline, False), (ps.iso_add(deadline, micros=1), False), (ps.iso_add(deadline, micros=-1), True)):
            with self.subTest(t0=t0, sent=sent), scratch_root() as root:
                clock = SequenceClock([tq, ps.iso_add(tq, micros=1), t0] + [ps.iso_add(t0, seconds=1 + i) for i in range(20)])
                rig = self.rig(root, [ok(b"[]", headers=JSON, latency=0)], clock)
                outcome = rig.runner.acquire(odds_item())
                self.assertEqual(len(rig.transport.calls), 1 if sent else 0)
                if not sent:
                    self.assertEqual((outcome.outcome, outcome.detail), ("NO_RESPONSE", "DeadlineElapsedBeforeSend"))
                    self.assertEqual([r["record_type"] for r in read_jsonl(rig.acq_path)
                                      if r["record_type"] == "acq_sent"], [])    # the sent row is never written


class SlowPeerThroughTheRunnerTests(unittest.TestCase):
    """End to end: the real transport under the runner. The slow peer costs a recorded no-response and ~1 s of the
    writer's time - not 40 s with the run lock held."""

    def test_a_slow_drip_is_a_recorded_deadline_exceeded_and_the_writer_is_released(self):
        policy = ps.policy_with(request_timeout_seconds=1)
        server = LoopbackHttps([Reply(body=drip(20), chunks=20, pause=0.4)])
        self.addCleanup(server.close)
        transport = th.HttpsTransport(Secret(SENTINEL_KEY), credential_param="apiKey", policy=policy,
                                      ssl_context=test_ca_context(), connect_address=server.address)
        with scratch_root() as root:
            rig = build_rig(root, capture=True, transport=transport, clock=ElapsedClock(), policy=policy)
            began = time.monotonic()
            outcome = rig.runner.acquire(odds_item())
            elapsed = time.monotonic() - began
            self.assertLess(elapsed, 1 + SLACK, f"the writer was held {elapsed:.1f}s")
            self.assertEqual((outcome.outcome, outcome.failure), ("NO_RESPONSE", err.AdapterFailure.NO_RESPONSE))
            self.assertEqual(outcome.detail, "DeadlineExceeded")
            (done,) = [r for r in read_jsonl(rig.acq_path) if r["record_type"] == "acq_completed"]
            self.assertEqual((done["outcome"], done["raw_observation_id"]), ("NO_RESPONSE", None))
            # the run lock is free again: another phase can start at once
            from genesis_adapters.oddspapi import quiescence
            with quiescence.run_lock(root):
                pass


if __name__ == "__main__":
    unittest.main()
