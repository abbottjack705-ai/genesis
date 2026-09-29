"""The dormant HTTPS transport, exercised ONLY against a loopback server with an injected test CA: credential
injection at send time, TLS verification, no redirects, the hard deadline (BND-04), truncation, oversize,
connection failures, and the socket audit hook that keeps every adapter test on loopback."""

from __future__ import annotations

import socket
import ssl
import time
import unittest
from urllib.parse import parse_qsl, urlsplit

from genesis_adapters.oddspapi import endpoints as ep
from genesis_adapters.oddspapi import transport_http as th
from genesis_adapters.secrets import Secret

from . import parser_support as ps
from .loopback_support import TEST_CA, LoopbackHttps, Reply, unused_loopback_port
from .pipeline_support import SPECS
from .support import SENTINEL_KEY, FixedClock, SequenceClock

T0 = "2026-10-01T12:00:00.000000Z"


def odds_request():
    return ep.build_request(SPECS["ODDS"], bookmaker=["pinnacle"], tournamentIds=[17, 8], oddsFormat="decimal")


def transport(server=None, *, policy=None, context=None, address=None):
    return th.HttpsTransport(Secret(SENTINEL_KEY), credential_param="apiKey", policy=policy or ps.POLICY,
                             ssl_context=context or th.tls_context(str(TEST_CA)),
                             connect_address=address or (server.address if server else None))


def deadline(seconds=None):
    return ps.iso_add(T0, seconds=seconds if seconds is not None else ps.POLICY.request_timeout_seconds)


class CoarseClock:
    """A wall clock that moves only in whole ``tick_ms`` steps of real (monotonic) time, counted from its first
    reading: the Windows / Python 3.12 shape (1-16 ms ticks), exaggerated so one loopback exchange fits in a tick."""

    def __init__(self, start: str, *, tick_ms: int):
        self.start, self.tick_ns, self.origin = start, tick_ms * 10 ** 6, None

    def now(self) -> str:
        current = time.monotonic_ns()
        if self.origin is None:
            self.origin = current
        return ps.iso_add(self.start, micros=(current - self.origin) // self.tick_ns * self.tick_ns // 1000)


class LoopbackTests(unittest.TestCase):
    def setUp(self):
        self.server = LoopbackHttps()
        self.addCleanup(self.server.close)

    def test_a_response_is_read_and_the_key_is_added_only_on_the_wire(self):
        request = odds_request()
        self.server.replies.append(Reply(body=b'[{"x": 1}]', headers=(("Content-Type", "application/json"),
                                                                      ("X-Requests-Used", "3"))))
        clock = FixedClock(T0, step_micros=1000)
        result = transport(self.server).send(request, clock=clock, deadline_at=deadline())
        self.assertEqual((result.outcome, result.http_status, result.body), ("RESPONSE", 200, b'[{"x": 1}]'))
        self.assertIn(("x-requests-used", "3"), result.headers)
        self.assertLess(result.request_started_at, result.response_received_at)
        seen = self.server.seen[0]
        method, target, _ = seen.request_line.split(" ")
        query = dict(parse_qsl(urlsplit(target).query))
        self.assertEqual((method, urlsplit(target).path), ("GET", request.path))
        self.assertEqual(query["apiKey"], SENTINEL_KEY)                        # on the wire, and only there
        self.assertEqual({k: v for k, v in query.items() if k != "apiKey"}, dict(request.query))
        headers = {k.lower(): v for k, v in seen.headers}
        self.assertEqual((headers["host"], headers["accept-encoding"], headers["accept"]),
                         ("api.oddspapi.io", "identity", "application/json"))
        self.assertNotIn(SENTINEL_KEY, repr(result))
        self.assertNotIn("apiKey", request.canonical_bytes().decode())

    def test_redirects_are_never_followed(self):
        self.server.replies.append(Reply(status_line="HTTP/1.1 302 Found",
                                         headers=(("Location", "https://elsewhere.example/steal"),), body=b"moved"))
        result = transport(self.server).send(odds_request(), clock=FixedClock(T0, step_micros=1000),
                                             deadline_at=deadline())
        self.assertEqual((result.outcome, result.http_status), ("RESPONSE", 302))
        self.assertEqual(len(self.server.seen), 1)

    def test_tls_is_verified_against_the_trust_store_and_never_disabled(self):
        result = transport(self.server, context=th.tls_context()).send(
            odds_request(), clock=FixedClock(T0, step_micros=1000), deadline_at=deadline())
        self.assertEqual(result.outcome, "NO_RESPONSE")
        self.assertEqual(result.sanitized_error["class"], "SSLCertVerificationError")
        self.assertEqual(self.server.seen, [])                                 # no request byte was sent
        weak = ssl.create_default_context()
        weak.check_hostname = False
        weak.verify_mode = ssl.CERT_NONE
        with self.assertRaises(th.TransportConfigurationError):
            th.HttpsTransport(Secret(SENTINEL_KEY), credential_param="apiKey", policy=ps.POLICY, ssl_context=weak)

    def test_bnd04_nothing_is_written_at_or_after_the_deadline(self):
        result = transport(self.server).send(odds_request(), clock=SequenceClock([deadline()]), deadline_at=deadline())
        self.assertEqual((result.outcome, result.sanitized_error["class"]), ("NO_RESPONSE", "DeadlineElapsedBeforeSend"))
        self.assertEqual(self.server.seen, [])

    def test_bnd04_the_attempt_is_cut_at_exactly_the_deadline(self):
        self.server.replies.append(Reply(body=b"[" + b"1," * 400 + b"1]", chunks=8, pause=0.05))
        edge = deadline()
        # started, open, write, head, then two body reads; the next reading is exactly the deadline
        times = [T0, ps.iso_add(T0, seconds=1), ps.iso_add(T0, seconds=2), ps.iso_add(T0, seconds=3),
                 ps.iso_add(T0, seconds=4), ps.iso_add(T0, seconds=5), edge, ps.iso_add(edge, seconds=1)]
        policy = ps.policy_with(read_chunk_bytes=64)
        result = transport(self.server, policy=policy).send(odds_request(), clock=SequenceClock(times),
                                                           deadline_at=edge)
        self.assertEqual((result.outcome, result.http_status), ("TRUNCATED", 200))
        self.assertEqual(result.sanitized_error, {"class": "TimeoutError", "errno": None})
        self.assertLess(0, len(result.body))
        self.assertLess(len(result.body), 803)

    def test_a_short_body_is_truncated_with_its_partial_bytes(self):
        self.server.replies.append(Reply(body=b'[{"x": 1}, {"y": 2}]', close_early=True))
        result = transport(self.server).send(odds_request(), clock=FixedClock(T0, step_micros=1000),
                                             deadline_at=deadline())
        self.assertEqual((result.outcome, result.http_status), ("TRUNCATED", 200))
        self.assertEqual(result.sanitized_error["class"], "IncompleteRead")

    def test_reading_stops_one_byte_past_the_size_cap(self):
        policy = ps.policy_with(max_response_bytes=1024, read_chunk_bytes=100)
        self.server.replies.append(Reply(body=b"[" + b"1," * 2000 + b"1]"))
        result = transport(self.server, policy=policy).send(odds_request(), clock=FixedClock(T0, step_micros=1000),
                                                           deadline_at=deadline())
        self.assertEqual(result.outcome, "RESPONSE")
        self.assertEqual(len(result.body), 1025)                              # raw capture flags it OVERSIZE

    def test_a_complete_body_is_a_response_however_it_is_chunked(self):
        body = b"[" + b"1," * 400 + b"1]"
        for chunks in (1, 7):
            with self.subTest(chunks=chunks):
                self.server.replies.append(Reply(body=body, chunks=chunks))
                result = transport(self.server, policy=ps.policy_with(read_chunk_bytes=64)).send(
                    odds_request(), clock=FixedClock(T0, step_micros=1000), deadline_at=deadline())
                self.assertEqual((result.outcome, result.body, result.sanitized_error), ("RESPONSE", body, None))

    def test_t1_is_a_later_clock_tick_than_t0_even_on_a_coarse_clock(self):
        self.server.replies.append(Reply(body=b'[{"x": 1}]'))
        result = transport(self.server).send(odds_request(), clock=CoarseClock(T0, tick_ms=400),
                                             deadline_at=deadline())
        self.assertEqual((result.outcome, result.request_started_at), ("RESPONSE", T0))
        self.assertGreater(result.response_received_at, T0)                   # design 6.3: T0 < T1

    def test_a_clock_that_never_moves_is_returned_as_read_within_the_drift_budget(self):
        self.server.replies.append(Reply(body=b"[]"))
        began = time.monotonic()
        result = transport(self.server, policy=ps.policy_with(wall_monotonic_drift_max_ms=50)).send(
            odds_request(), clock=FixedClock(T0), deadline_at=deadline())
        self.assertEqual((result.outcome, result.request_started_at, result.response_received_at),
                         ("RESPONSE", T0, T0))                                # the runner's T0 < T1 check halts on it
        self.assertLess(time.monotonic() - began, 10)


class ConnectionFailureTests(unittest.TestCase):
    def test_a_refused_connection_is_a_sanitized_no_response(self):
        port = unused_loopback_port()
        result = transport(address=("127.0.0.1", port)).send(odds_request(), clock=FixedClock(T0, step_micros=1000),
                                                             deadline_at=deadline())
        self.assertEqual(result.outcome, "NO_RESPONSE")
        self.assertEqual(set(result.sanitized_error), {"class", "errno"})
        self.assertIn(result.sanitized_error["class"], {"ConnectionRefusedError", "TimeoutError", "OSError"})

    def test_the_suite_refuses_any_non_loopback_contact(self):
        from adapter_tests import NON_LOOPBACK_ATTEMPTS

        before = len(NON_LOOPBACK_ATTEMPTS)
        with self.assertRaises(RuntimeError):
            socket.create_connection(("192.0.2.1", 443), timeout=1)
        with self.assertRaises(RuntimeError):
            socket.getaddrinfo("genesis.example.invalid", 443)
        self.assertEqual(len(NON_LOOPBACK_ATTEMPTS), before + 2)
        del NON_LOOPBACK_ATTEMPTS[before:]                                     # these two were deliberate

    def test_the_production_host_is_pinned_in_every_request(self):
        for role, spec in SPECS.items():
            self.assertEqual((spec.scheme, spec.host), ("https", "api.oddspapi.io"), role)

if __name__ == "__main__":
    unittest.main()
