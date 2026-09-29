"""Credential object and pre-persistence secret detection (design sections 7.4 and 7.6).

The module deliberately imports nothing from ``genesis``. ``Secret`` cannot be serialized,
copied, printed or logged. ``scan_for_secret`` detects the key in every form listed in
section 7.6 and only ever reports detection *classes* (never offsets, never matched text).
"""

from __future__ import annotations

import base64
import hashlib
import math
import re
from dataclasses import dataclass
from typing import Iterable, Sequence

# Capability tokens: plain Python objects, not a security boundary (design 7.4). Only
# ``oddspapi/transport_http.py`` passes TRANSPORT_CAPABILITY (static test FRZ-06).
TRANSPORT_CAPABILITY = object()
_SCAN_TOKEN = object()
_FINGERPRINT_DOMAIN = b"genesis.adapters.credential-fp.v1\0"


class SecretError(TypeError):
    """Refused operation on a Secret."""


class Secret:
    """A credential. Unserializable; ``repr``/``str`` show only a short fingerprint."""

    __slots__ = ("_key", "fingerprint")

    def __init__(self, value: str | bytes):
        if isinstance(value, bytes):
            try:
                value = value.decode("utf-8")
            except UnicodeDecodeError:
                raise ValueError("credential is not UTF-8") from None
        elif not isinstance(value, str):
            raise TypeError("credential must be text")
        if not value or value != value.strip() or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
            raise ValueError("credential must be non-empty, trimmed, single-line text")
        self._key = value
        self.fingerprint = hashlib.sha256(_FINGERPRINT_DOMAIN + value.encode("utf-8")).hexdigest()[:12]

    def __repr__(self) -> str:
        return f"Secret({self.fingerprint})"

    __str__ = __repr__

    def __reduce__(self):
        raise SecretError("Secret cannot be serialized")

    def __reduce_ex__(self, protocol):
        raise SecretError("Secret cannot be serialized")

    def __getstate__(self):
        raise SecretError("Secret cannot be serialized")

    def __copy__(self):
        raise SecretError("Secret cannot be copied")

    def __deepcopy__(self, memo):
        raise SecretError("Secret cannot be copied")

    def reveal_for_transport(self, token: object) -> str:
        if token is not TRANSPORT_CAPABILITY:
            raise SecretError("transport capability required")
        return self._key

    def reveal_for_scan(self, token: object) -> str:
        if token is not _SCAN_TOKEN:
            raise SecretError("scan capability required")
        return self._key


@dataclass(frozen=True)
class SecretScanResult:
    hit: bool
    detection_classes: tuple[str, ...]


_PERCENT = re.compile(rb"%([0-9a-fA-F]{2})")
_JSON_U = re.compile(rb"\\u([0-9a-fA-F]{4})")


def _percent_decode(data: bytes) -> bytes:
    return _PERCENT.sub(lambda m: bytes([int(m.group(1), 16)]), data)


def _json_unescape(data: bytes) -> bytes:
    data = _JSON_U.sub(lambda m: chr(int(m.group(1), 16)).encode("utf-8", "replace"), data)
    return data.replace(b"\\/", b"/")


def _b64_cores(raw: bytes, minimum: int) -> set[bytes]:
    """Stable inner base64 cores of ``raw`` at all three alignments, both alphabets."""

    cores: set[bytes] = set()
    for offset in range(3):
        encoded = base64.b64encode(b"\x00" * offset + raw).rstrip(b"=")
        lead = -(-offset * 8 // 6)                       # chars touched by the unknown prefix
        end = (offset + len(raw)) * 8 // 6               # chars fully fixed by known bits
        core = encoded[lead:end]
        if len(core) >= minimum:
            cores.add(core)
            cores.add(core.replace(b"+", b"-").replace(b"/", b"_"))
    return cores


class SecretScanner:
    """Compiled detector for one secret under one policy (reuse it across many inputs)."""

    def __init__(self, secret: Secret, *, policy):
        key = secret.reveal_for_scan(_SCAN_TOKEN)
        raw = key.encode("utf-8")
        floor = policy.secret_fragment_min_chars_floor
        width = max(floor, math.ceil(len(key) / policy.secret_fragment_min_chars_divisor))
        self._ci: list[tuple[str, bytes]] = []           # matched against lower-cased data
        self._plain: list[tuple[str, bytes]] = []        # matched against normalized text forms
        self._exact: list[tuple[str, bytes]] = []        # matched case-sensitively

        def add(cls: str, needle: bytes) -> None:
            if needle:
                self._ci.append((cls, needle.lower()))

        add("RAW", raw)
        self._plain.append(("RAW", raw.lower()))
        for name, codec in (("UTF16", "utf-16-le"), ("UTF16", "utf-16-be"),
                            ("UTF32", "utf-32-le"), ("UTF32", "utf-32-be")):
            add(name, key.encode(codec))
        add("HEX", raw.hex().encode())
        for core in _b64_cores(raw, floor):
            self._exact.append(("BASE64", core))
        if len(key) >= width:
            for start in range(len(key) - width + 1):
                frag = key[start:start + width]
                fbytes = frag.encode("utf-8")
                add("FRAGMENT", fbytes)
                self._plain.append(("FRAGMENT", fbytes.lower()))
                add("FRAGMENT", frag.encode("utf-16-le"))
                add("FRAGMENT", frag.encode("utf-16-be"))
        hexed = raw.hex()
        span = 2 * width
        if len(hexed) >= span:
            for start in range(len(hexed) - span + 1):
                add("HEX_FRAGMENT", hexed[start:start + span].encode())
        self._ci = sorted(set(self._ci))
        self._plain = sorted(set(self._plain))
        self._exact = sorted(set(self._exact))

    def scan(self, data: bytes) -> SecretScanResult:
        data = bytes(data)
        lower = data.lower()
        found: set[str] = set()
        for cls, needle in self._ci:
            if needle in lower:
                found.add(cls)
        for cls, needle in self._exact:
            if needle in data:
                found.add(cls)
        # Normalized text views: percent-decoding (incl. double), '+' as space, JSON escapes.
        # Decoding always happens BEFORE lower-casing, so an encoded upper-case letter
        # (``%47``, ``G``) is compared like any other character.
        views: list[tuple[str, bytes]] = []
        decoded = data
        for _ in range(3):
            nxt = _percent_decode(decoded)
            if nxt == decoded:
                break
            decoded = nxt
            views.append(("PERCENT", decoded.lower()))
        plus = _percent_decode(data.replace(b"+", b" "))
        if plus != data:
            views.append(("PERCENT", plus.lower()))
        unescaped = _json_unescape(data)
        if unescaped != data:
            views.append(("JSON_ESCAPE", unescaped.lower()))
            views.append(("JSON_ESCAPE", _percent_decode(unescaped).lower()))
        for view_class, view in views:
            for cls, needle in self._plain:
                if needle in view:
                    found.add(view_class if cls == "RAW" else cls)
        return SecretScanResult(bool(found), tuple(sorted(found)))


def scan_for_secret(data: bytes, secret: Secret, *, policy) -> SecretScanResult:
    """Detect ``secret`` in ``data`` in every section-7.6 form."""

    return SecretScanner(secret, policy=policy).scan(data)


def scan_headers(headers: Sequence[tuple[bytes, bytes]], secret: Secret, *, policy) -> SecretScanResult:
    """Scan every header NAME and VALUE (before any allowlist is applied)."""

    scanner = SecretScanner(secret, policy=policy)
    found: set[str] = set()
    for name, value in headers:
        if scanner.scan(name).hit:
            found.add("HEADER_NAME")
        if scanner.scan(value).hit:
            found.add("HEADER_VALUE")
    return SecretScanResult(bool(found), tuple(sorted(found)))


def scan_many(items: Iterable[bytes], secret: Secret, *, policy) -> SecretScanResult:
    scanner = SecretScanner(secret, policy=policy)
    classes: set[str] = set()
    for item in items:
        classes.update(scanner.scan(item).detection_classes)
    return SecretScanResult(bool(classes), tuple(sorted(classes)))


def contains_raw(secret: Secret, text: str) -> bool:
    """True when ``text`` contains the key verbatim (used to refuse a key held in the environment, design 7.5)."""

    return bool(text) and secret.reveal_for_scan(_SCAN_TOKEN) in text
