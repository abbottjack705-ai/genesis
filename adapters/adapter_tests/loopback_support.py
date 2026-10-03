"""TEST-ONLY loopback HTTPS server. Its TLS material is a throwaway PKI minted at test time (``tls_support``): a CA and
a leaf for the pinned host name ``api.oddspapi.io`` that live for one test process, so the transport tests exercise
the real host-name verification while nothing - no CA, no certificate, no private key - is committed (hostile audit
RA5-003). Nothing here ever leaves 127.0.0.1; the suite's audit hook refuses any other address."""

from __future__ import annotations

import socket
import ssl
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import tls_support

PINNED_HOST = "api.oddspapi.io"
_PROCESS_PKI: list = []


def process_pki() -> tls_support.Pki:
    """The one throwaway PKI of this test process (minted on first use, removed at exit)."""

    if not _PROCESS_PKI:
        _PROCESS_PKI.append(tls_support.new_pki(PINNED_HOST))
    return _PROCESS_PKI[0]


def test_ca_file() -> Path:
    """The public CA certificate of this process's PKI, for a child process that must trust it."""

    return process_pki().ca_file


@dataclass
class Seen:
    request_line: str
    headers: list[tuple[str, str]]


@dataclass
class Reply:
    status_line: str = "HTTP/1.1 200 OK"
    headers: tuple = (("Content-Type", "application/json"),)
    body: bytes = b"[]"
    content_length: int | None = None            # None: the true length
    chunks: int = 1                              # send the body in this many pieces
    pause: float = 0.0                           # seconds between pieces (a slow server)
    close_early: bool = False                    # close before the whole body was sent
    head_pause: float = 0.0                      # seconds between single bytes of the status line and headers


@dataclass
class LoopbackHttps:
    replies: list = field(default_factory=list)
    seen: list = field(default_factory=list)
    handshake_failures: int = 0
    pki: object = None                           # a ``tls_support.Pki`` to present; the process PKI by default

    def __post_init__(self):
        self.context = (self.pki or process_pki()).server_context()
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.port = self.listener.getsockname()[1]
        self.stopping = False
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    @property
    def address(self) -> tuple[str, int]:
        return ("127.0.0.1", self.port)

    def _serve(self):
        self.listener.settimeout(0.2)
        while not self.stopping:
            try:
                raw, _ = self.listener.accept()
            except (TimeoutError, OSError):
                continue
            try:
                conn = self.context.wrap_socket(raw, server_side=True)
            except (ssl.SSLError, OSError):
                self.handshake_failures += 1
                raw.close()
                continue
            try:
                self._handle(conn)
            except OSError:
                pass
            finally:
                conn.close()

    def _handle(self, conn):
        conn.settimeout(5)
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = conn.recv(4096)
            if not chunk:
                return
            data += chunk
        head = data.split(b"\r\n\r\n", 1)[0].decode("latin-1").split("\r\n")
        self.seen.append(Seen(head[0], [tuple(part.strip() for part in line.split(":", 1)) for line in head[1:]]))
        reply = self.replies.pop(0) if self.replies else Reply()
        length = len(reply.body) if reply.content_length is None else reply.content_length
        lines = [reply.status_line, *[f"{k}: {v}" for k, v in reply.headers], f"Content-Length: {length}",
                 "Connection: close", "", ""]
        head = "\r\n".join(lines).encode("latin-1")
        if reply.head_pause:                                       # a slow-drip head: one byte at a time
            for index in range(len(head)):
                conn.sendall(head[index:index + 1])
                time.sleep(reply.head_pause)
        else:
            conn.sendall(head)
        body = reply.body if not reply.close_early else reply.body[: len(reply.body) // 2]
        size = max(1, -(-len(body) // reply.chunks))
        for start in range(0, len(body), size):
            conn.sendall(body[start:start + size])
            if reply.pause:
                time.sleep(reply.pause)

    def close(self):
        self.stopping = True
        self.listener.close()
        self.thread.join(timeout=5)


def test_ca_context() -> ssl.SSLContext:
    """A verifying client context that trusts ONLY this process's throwaway CA (tests only; production uses the
    system trust store and has no way to take any other CA)."""

    return process_pki().client_context()


def unused_loopback_port() -> int:
    probe = socket.create_server(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port
