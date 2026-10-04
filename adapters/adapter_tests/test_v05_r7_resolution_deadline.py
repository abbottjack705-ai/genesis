"""R7 / RA6-004 (LOW) - name resolution is inside the hard deadline too.

The defect (R6, disclosed as a known residual and measured by the audit in an isolated namespace): the interpreter has no
timeout for ``socket.getaddrinfo``, so a resolver that does not answer held the transport 10 s (one nameserver) or 28 s (three)
against a 3 s deadline - and with it the single writer and its run lock - before any bounded operation began. Availability
only (no request byte was ever written late), but design 14.6 rule 3 says the deadline bounds the whole attempt.

The fix runs the lookup in a helper thread joined with the deadline and abandons it when the resolver has not answered. The
tests drive the real connection and the real transport with an injected resolver that blocks for far longer than any bound
here: nothing in the suite touches a real resolver or a real network.
"""

from __future__ import annotations

import socket
import threading
import time
import unittest
from unittest import mock

from genesis_adapters import errors as err
from genesis_adapters.oddspapi import transport_http as th

from . import parser_support as ps
from .loopback_support import LoopbackHttps, Reply, test_ca_context
from .support import build_rig, odds_item, read_jsonl, scratch_root
from .test_v05_r6_deadline import SLACK, T0, ElapsedClock, bounded_transport
from .test_v05_transport_http import odds_request

STALL_S = 12.0          # how long the injected resolver blocks: far beyond every bound asserted below
ADDRESS = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 443))


class StalledResolver:
    """An injected ``socket.getaddrinfo`` that blocks until released (or ``STALL_S``), recording every call."""

    def __init__(self, answer=None, *, error=None):
        self.release = threading.Event()
        self.calls = []
        self.finished = []
        self.answer, self.error = answer, error

    def __call__(self, host, port, *args, **kwargs):
        self.calls.append((host, port, args, kwargs, threading.current_thread().name))
        self.release.wait(STALL_S)
        self.finished.append(True)
        if self.error is not None:
            raise self.error
        return self.answer


def connection(deadline_s: float | None = None) -> th._Connection:
    conn = th._Connection("api.oddspapi.io", 443, test_ca_context(), None)
    if deadline_s is not None:
        conn._bound(deadline_s)
    return conn


class ResolutionIsBoundedByTheDeadlineTests(unittest.TestCase):
    def stalled(self, **kw):
        resolver = StalledResolver(**kw)
        patcher = mock.patch.object(th.socket, "getaddrinfo", resolver)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(resolver.release.set)               # let the abandoned lookup end with the test
        return resolver

    def test_a_resolver_that_never_answers_costs_the_deadline_not_the_resolvers_patience(self):
        resolver = self.stalled(answer=[ADDRESS])
        conn = connection(0.4)
        began = time.monotonic()
        with self.assertRaises(TimeoutError):
            conn._resolve("api.oddspapi.io", 443)
        elapsed = time.monotonic() - began
        self.assertLess(elapsed, 0.4 + SLACK, f"name resolution held the attempt {elapsed:.1f}s")
        self.assertEqual(len(resolver.calls), 1)
        self.assertEqual(resolver.finished, [], "the lookup was waited for")      # it is abandoned, still running

    def test_the_connection_open_fails_at_the_deadline_when_the_resolver_stalls(self):
        resolver = self.stalled(answer=[ADDRESS])
        conn = connection()
        began = time.monotonic()
        with self.assertRaises(TimeoutError):
            conn.open(0.4)
        self.assertLess(time.monotonic() - began, 0.4 + SLACK)
        self.assertIsNone(conn.tls)                                                # nothing was connected or wrapped
        self.assertEqual(len(resolver.calls), 1)

    def test_the_abandoned_lookup_is_a_daemon_that_was_given_only_the_host_and_the_port(self):
        resolver = self.stalled(answer=[ADDRESS])
        with self.assertRaises(TimeoutError):
            connection(0.2)._resolve("api.oddspapi.io", 443)
        host, port, args, kwargs, name = resolver.calls[0]
        self.assertEqual((host, port, args, kwargs), ("api.oddspapi.io", 443, (), {"type": socket.SOCK_STREAM}))
        (worker,) = [t for t in threading.enumerate() if t.name == name]
        self.assertTrue(worker.daemon)
        resolver.release.set()
        worker.join(timeout=5)
        self.assertFalse(worker.is_alive())

    def test_a_resolver_that_answers_in_time_is_used_and_its_answer_returned_unchanged(self):
        resolver = StalledResolver(answer=[ADDRESS])
        resolver.release.set()
        with mock.patch.object(th.socket, "getaddrinfo", resolver):
            self.assertEqual(connection(5.0)._resolve("api.oddspapi.io", 443), [ADDRESS])

    def test_a_resolver_that_fails_raises_its_own_exception_in_the_attempt(self):
        failure = socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        resolver = StalledResolver(error=failure)
        resolver.release.set()
        with mock.patch.object(th.socket, "getaddrinfo", resolver):
            with self.assertRaises(socket.gaierror) as caught:
                connection(5.0)._resolve("api.oddspapi.io", 443)
        self.assertIs(caught.exception, failure)

    def test_a_deadline_that_has_already_passed_starts_no_lookup_at_all(self):
        resolver = self.stalled(answer=[ADDRESS])
        conn = connection(0.05)
        time.sleep(0.1)
        with self.assertRaises(TimeoutError):
            conn._resolve("api.oddspapi.io", 443)
        self.assertEqual(resolver.calls, [])

    def test_the_lookup_is_joined_with_exactly_the_time_that_is_left_no_spare_second(self):
        # the real-time bounds above have slack that would hide a constant; the arithmetic is pinned on a controlled clock
        now, joined = [100.0], []
        real_join = threading.Thread.join

        def join(this, timeout=None):
            joined.append(timeout)
            return real_join(this, timeout)

        resolver = StalledResolver(answer=[ADDRESS])
        resolver.release.set()
        with mock.patch.object(th.time, "monotonic", lambda: now[0]), \
                mock.patch.object(threading.Thread, "join", join), mock.patch.object(th.socket, "getaddrinfo", resolver):
            conn = connection(10.0)                                    # the deadline is 110.0 on the controlled clock
            now[0] = 103.0
            conn._resolve("api.oddspapi.io", 443)
        self.assertEqual(joined, [7.0])

    def test_the_time_left_for_the_connect_is_what_the_lookup_left(self):
        resolver = StalledResolver(answer=[ADDRESS])
        resolver.release.set()
        armed = []

        class Probe:
            def __init__(self, family, kind, proto):
                self.timeout = None

            def settimeout(self, value):
                armed.append(value)

            def connect(self, target):
                raise OSError("refused")

            def close(self):
                pass

        conn = connection(5.0)
        with mock.patch.object(th.socket, "getaddrinfo", resolver), mock.patch.object(th.socket, "socket", Probe):
            with self.assertRaises(OSError):
                conn._connect()
        self.assertEqual(len(armed), 1)
        self.assertLessEqual(armed[0], 5.0)
        self.assertGreater(armed[0], 4.0)


class ARealAttemptWithAStalledResolverTests(unittest.TestCase):
    DEADLINE_S = 1

    def test_the_transport_returns_a_no_response_by_the_deadline_and_writes_no_request_byte(self):
        resolver = StalledResolver(answer=[ADDRESS])
        self.addCleanup(resolver.release.set)
        server = LoopbackHttps([Reply(body=b"[]")])
        self.addCleanup(server.close)
        clock = ElapsedClock()
        began = time.monotonic()
        with mock.patch.object(th.socket, "getaddrinfo", resolver):
            result = bounded_transport(server).send(odds_request(), clock=clock,
                                                    deadline_at=ps.iso_add(T0, seconds=self.DEADLINE_S))
        elapsed = time.monotonic() - began
        self.assertLess(elapsed, self.DEADLINE_S + SLACK, f"the transport was held {elapsed:.1f}s by name resolution")
        self.assertEqual(result.outcome, "NO_RESPONSE")
        self.assertEqual(result.sanitized_error["class"], "TimeoutError")
        self.assertEqual(server.seen, [], "a request reached the server")
        self.assertEqual(len(resolver.calls), 1)

    def test_a_stalled_resolver_through_the_runner_is_a_recorded_no_response_and_the_writer_is_released(self):
        resolver = StalledResolver(answer=[ADDRESS])
        self.addCleanup(resolver.release.set)
        policy = ps.policy_with(request_timeout_seconds=1)
        server = LoopbackHttps([Reply(body=b"[]")])
        self.addCleanup(server.close)
        transport = bounded_transport(server, policy=policy)
        with scratch_root() as root, mock.patch.object(th.socket, "getaddrinfo", resolver):
            rig = build_rig(root, capture=True, transport=transport, clock=ElapsedClock(), policy=policy)
            began = time.monotonic()
            outcome = rig.runner.acquire(odds_item())
            elapsed = time.monotonic() - began
            self.assertLess(elapsed, 1 + SLACK, f"the writer was held {elapsed:.1f}s")
            self.assertEqual((outcome.outcome, outcome.failure), ("NO_RESPONSE", err.AdapterFailure.NO_RESPONSE))
            (done,) = [r for r in read_jsonl(rig.acq_path) if r["record_type"] == "acq_completed"]
            self.assertEqual((done["outcome"], done["raw_observation_id"]), ("NO_RESPONSE", None))
            from genesis_adapters.oddspapi import quiescence
            with quiescence.run_lock(root):                                         # the run lock is free again
                pass

    def test_a_resolver_that_answers_promptly_changes_nothing_about_a_normal_exchange(self):
        server = LoopbackHttps([Reply(body=b"[]")])
        self.addCleanup(server.close)
        clock = ElapsedClock()
        result = bounded_transport(server).send(odds_request(), clock=clock, deadline_at=ps.iso_add(T0, seconds=10))
        self.assertEqual((result.outcome, result.body), ("RESPONSE", b"[]"))


if __name__ == "__main__":
    unittest.main()
