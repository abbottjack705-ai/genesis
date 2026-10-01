"""TEST-ONLY loopback HTTPS server with a throwaway test CA (``fixtures/tls``; the CA key was destroyed after
signing the one server certificate, which names the pinned host ``api.oddspapi.io``). Nothing here ever
leaves 127.0.0.1; the suite's audit hook refuses any other address."""

from __future__ import annotations

import socket
import ssl
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

TLS_DIR = Path(__file__).resolve().parent / "fixtures" / "tls"
TEST_CA = TLS_DIR / "test-ca.pem"
SERVER_CERT = TLS_DIR / "server.pem"
SERVER_KEY = TLS_DIR / "server.key"


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


@dataclass
class LoopbackHttps:
    replies: list = field(default_factory=list)
    seen: list = field(default_factory=list)
    handshake_failures: int = 0

    def __post_init__(self):
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(SERVER_CERT, SERVER_KEY)
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
        conn.sendall("\r\n".join(lines).encode("latin-1"))
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
    """A verifying client context that trusts ONLY the throwaway test CA (tests only; production uses the system
    trust store and has no way to take this CA)."""

    return ssl.create_default_context(cafile=str(TEST_CA))


def unused_loopback_port() -> int:
    probe = socket.create_server(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port
