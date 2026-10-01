"""Dormant HTTPS transport (design 7.6, 7.7, 14.6 rule 3). Nothing sends through it before G1/G2.

Security properties, each tested (TX-01, BND-04, SEC-*):

* the credential is added to the request target HERE, in one local variable, after the canonical request
  was hashed and persisted; it is never stored on an object, in a closure, a log, an exception argument
  or a return value, and the variable is deleted on every path;
* TLS uses the system trust store, hostname verification is on and is never switched off; the production
  operator path has no way to add a CA or redirect the connection (tests construct the transport with a
  loopback-only test context themselves); redirects are never followed (a 3xx is just a status);
* the whole attempt is bounded by the hard deadline ``Tq + request_timeout_seconds``: every blocking
  operation gets the remaining time as its socket timeout, T0 is read immediately before the first request
  byte, and no request byte is written at or after the deadline (HA-03);
* ordinary failures (every ``Exception``) become a sanitized result carrying only a safe class label (a
  plain bounded identifier with no section-7.6 form of the key, else a fixed placeholder, HA-01) and an
  integer errno; warnings raised inside the send path are captured and discarded;
* process-control exceptions keep their meaning: the ONE ``except BaseException`` clause of the adapter
  package (FRZ-11) covers the exchange AND closing the connection (HA-02); it records only the class (and
  an integer ``SystemExit`` code), and after the block a FRESH instance is raised ``from None`` - no
  message, no cause, no context, no notes.
"""

from __future__ import annotations

import http.client
import socket
import ssl
import time
import warnings
from datetime import datetime
from typing import Any, Callable
from urllib.parse import urlencode

from genesis.time import parse_utc

from genesis_adapters.oddspapi.transport import TransportResult, safe_errno, safe_label
from genesis_adapters.secrets import TRANSPORT_CAPABILITY, Secret, SecretScanner

HTTPS_PORT = 443


class TransportConfigurationError(ValueError):
    """A transport that would weaken TLS or talk to a host other than the pinned one."""


class _Connection:
    """One HTTPS exchange over a socket this object owns. The keyed request target is only ever an
    argument of :meth:`write`; nothing here keeps it."""

    def __init__(self, host: str, port: int, context: ssl.SSLContext, address: tuple[str, int] | None):
        self.host, self.port, self.context, self.address = host, port, context, address
        self.tls = None
        self.http = None
        self.response = None

    def open(self, timeout: float) -> None:
        raw = socket.create_connection(self.address or (self.host, self.port), timeout=timeout)
        self.tls = self.context.wrap_socket(raw, server_hostname=self.host)
        self.http = http.client.HTTPConnection(self.host, self.port)
        self.http.set_debuglevel(0)
        self.http.sock = self.tls

    def settimeout(self, timeout: float) -> None:
        self.tls.settimeout(timeout)

    def write(self, method: str, target: str, headers) -> None:
        self.http.putrequest(method, target, skip_host=True, skip_accept_encoding=True)
        self.http.putheader("host", self.host)
        for name, value in headers:
            self.http.putheader(name, value)
        self.http.endheaders()

    def read_head(self):
        self.response = self.http.getresponse()
        return self.response.status, self.response.getheaders()

    def read_chunk(self, size: int) -> bytes:
        data = self.response.read(size)
        if not data and self.response.length:              # closed before Content-Length bytes arrived (F-06)
            raise http.client.IncompleteRead(b"", self.response.length)
        return data

    def finished(self) -> bool:
        """True once the body is complete: ``http.client`` closes the response (and may close the socket, so
        no further timeout may be set on it) as soon as the last Content-Length or chunked byte is read."""

        return self.response is not None and self.response.isclosed()

    def close(self) -> None:
        if self.http is not None:
            self.http.close()
        elif self.tls is not None:
            self.tls.close()


def _decode_headers(pairs) -> tuple[tuple[str, str], ...]:
    return tuple((str(name).lower(), str(value)) for name, value in pairs)


def _fresh_process_control(exc: BaseException) -> BaseException:
    """A new, argument-free instance of the same process-control class (design 7.7 b)."""

    if isinstance(exc, SystemExit):
        code = exc.code
        if code is None:
            return SystemExit()
        return SystemExit(code if type(code) is int else 1)          # text is never kept, status is
    if isinstance(exc, KeyboardInterrupt):
        return KeyboardInterrupt()
    try:
        return type(exc)()
    except Exception:
        return SystemExit(1)


def _reading_after(clock, earlier: str, budget_ms: int) -> str:
    """T1: a trusted-clock reading strictly later than T0 (design 6.2/6.3, ``T0 < T1``).

    A coarse wall clock (Windows before Python 3.13 ticks every 1-16 ms) returns T0 again when a whole
    exchange fits inside one tick. The clock is then read again, one wall-clock tick (the platform's reported
    resolution, never a literal: FRZ-10) at a time, until it has moved on: still a genuine reading taken after
    the last body byte, never an invented one. A clock that has not moved within the wall/monotonic drift
    budget is returned as read, and the runner's ordering check halts on it (CLOCK_FAULT); ``SystemUtcClock``
    itself raises ``ClockFault`` at that point."""

    reading = clock.now()
    tick = time.get_clock_info("time").resolution
    give_up = time.monotonic_ns() + budget_ms * 10 ** 6
    while parse_utc(reading) <= parse_utc(earlier) and time.monotonic_ns() < give_up:
        time.sleep(tick)
        reading = clock.now()
    return reading


def tls_context() -> ssl.SSLContext:
    """The system trust store with hostname verification. The production path never takes any other CA."""

    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


class HttpsTransport:
    """The live transport. ``ssl_context``, ``connect_address`` and ``connection_factory`` exist only for loopback
    tests and fault injection; the operator CLI never passes them (hostile audit P:HA-006), so production always
    verifies against the system trust store. The TLS server name and the Host header are always the request's
    pinned host."""

    def __init__(self, secret: Secret, *, credential_param: str, policy, ssl_context: ssl.SSLContext | None = None,
                 connect_address: tuple[str, int] | None = None,
                 connection_factory: Callable[..., Any] | None = None):
        if not isinstance(secret, Secret):
            raise TransportConfigurationError("the transport needs a Secret")
        context = ssl_context if ssl_context is not None else tls_context()
        if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
            raise TransportConfigurationError("TLS verification is never disabled")
        self._secret = secret
        self._scanner = SecretScanner(secret, policy=policy)
        self._credential_param = credential_param
        self._policy = policy
        self._context = context
        self._address = connect_address
        self._factory = connection_factory or _Connection

    @staticmethod
    def _remaining(clock, deadline: datetime) -> float:
        return (deadline - parse_utc(clock.now())).total_seconds()

    def _hit(self, data: bytes) -> bool:
        return self._scanner.scan(data).hit

    def send(self, request, *, clock, deadline_at: str) -> TransportResult:
        deadline = parse_utc(deadline_at)
        started = clock.now()                                 # replaced by T0 at the request-write boundary
        if parse_utc(started) >= deadline:                    # at/after the deadline: nothing is even opened
            return TransportResult("NO_RESPONSE", None, (), None,
                                   {"class": "DeadlineElapsedBeforeSend", "errno": None}, started, None)
        status = None
        headers: tuple[tuple[str, str], ...] = ()
        body = bytearray()
        error = None
        control = None
        complete = False
        connection = None
        closing = None
        target = None
        cap = self._policy.max_response_bytes + 1
        with warnings.catch_warnings(record=True) as seen:   # a warning may name the URL: kept from everyone
            warnings.simplefilter("always")
            try:
                try:
                    connection = self._factory(request.host, HTTPS_PORT, self._context, self._address)
                    remaining = self._remaining(clock, deadline)
                    if remaining <= 0:
                        raise TimeoutError("deadline")
                    connection.open(remaining)                # connect and TLS, bounded by the remaining time
                    remaining = self._remaining(clock, deadline)
                    if remaining <= 0:
                        raise TimeoutError("deadline")
                    connection.settimeout(remaining)
                    target = request.path + "?" + urlencode(
                        list(request.query) + [(self._credential_param,
                                                self._secret.reveal_for_transport(TRANSPORT_CAPABILITY))])
                    started = clock.now()                     # T0: immediately before the first request byte
                    if parse_utc(started) >= deadline:
                        raise TimeoutError("deadline")        # no request byte at or after the deadline (HA-03)
                    connection.write(request.method, target, request.headers)
                    target = None
                    remaining = self._remaining(clock, deadline)
                    if remaining <= 0:
                        raise TimeoutError("deadline")
                    connection.settimeout(remaining)
                    code, raw_headers = connection.read_head()
                    headers = _decode_headers(raw_headers)
                    status = code
                    while len(body) < cap and not connection.finished():
                        remaining = self._remaining(clock, deadline)
                        if remaining <= 0:
                            raise TimeoutError("deadline")
                        connection.settimeout(remaining)
                        chunk = connection.read_chunk(min(self._policy.read_chunk_bytes, cap - len(body)))
                        if not chunk:
                            break
                        body += chunk
                    complete = True
                except Exception as exc:                      # ordinary failure: a safe label and errno only (HA-01)
                    bound = self._policy.header_value_max_chars
                    error = {"class": safe_label(type(exc).__name__, max_chars=bound, hit=self._hit),
                             "errno": safe_errno(getattr(exc, "errno", None), max_chars=bound, hit=self._hit)}
                    exc.__traceback__ = None
                    del exc
                finally:
                    target = None
                    closing, connection = connection, None    # it may still hold an unsent request line
                    try:
                        if closing is not None:
                            try:
                                closing.close()
                            except Exception:                 # a failed close changes nothing that was received
                                pass
                    finally:
                        closing = None
            except BaseException as exc:                      # the single process-control clause (FRZ-11): it covers
                control = _fresh_process_control(exc)         # the exchange AND closing the connection (HA-02)
                exc.__traceback__ = None
                del exc
                target = None
            seen.clear()
        del target, connection, closing
        if control is not None:
            raise control from None
        if status is None:
            return TransportResult("NO_RESPONSE", None, (), None, error, started, None)
        received = _reading_after(clock, started, self._policy.wall_monotonic_drift_max_ms)
        if complete:
            return TransportResult("RESPONSE", status, headers, bytes(body), None, started, received)
        return TransportResult("TRUNCATED", status, headers, bytes(body), error, started, received)
