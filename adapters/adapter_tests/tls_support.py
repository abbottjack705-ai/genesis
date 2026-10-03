"""TEST-ONLY throwaway PKI, minted at test time with the standard library alone (hostile audit RA5-003).

Nothing here - and nothing under ``adapters/`` - is a committed certificate or key: the loopback tests generate a
fresh CA and leaf on every run (ECDSA P-256, a minimal DER writer), keep the keys in memory, write only the one file
``ssl`` cannot avoid (the loopback SERVER's private key, mode 0600) into a temporary directory that is removed at
exit, and trust the CA only through an explicit ``cadata=`` context. The earlier design committed a leaf private key
whose certificate named the production host, which turned ``SSL_CERT_FILE`` into a credential-theft primitive.

The implementation is deliberately small and checked by an independent verifier: OpenSSL (through ``ssl``) accepts or
rejects every certificate it makes (see ``test_v05_r6_tls_boundary``: valid chains verify, a wrong host name and a
name-constraint violation are refused). It is test scaffolding and is never imported by production code.
"""

from __future__ import annotations

import atexit
import base64
import hashlib
import os
import secrets
import shutil
import ssl
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --- NIST P-256 -------------------------------------------------------------------------------------
_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_A = _P - 3
_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_G = (0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
      0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5)


def _add(p, q):
    if p is None:
        return q
    if q is None:
        return p
    (x1, y1), (x2, y2) = p, q
    if x1 == x2 and (y1 + y2) % _P == 0:
        return None
    if p == q:
        slope = (3 * x1 * x1 + _A) * pow(2 * y1, -1, _P) % _P
    else:
        slope = (y2 - y1) * pow(x2 - x1, -1, _P) % _P
    x3 = (slope * slope - x1 - x2) % _P
    return x3, (slope * (x1 - x3) - y1) % _P


def _mul(k, point):
    result = None
    while k:
        if k & 1:
            result = _add(result, point)
        point = _add(point, point)
        k >>= 1
    return result


@dataclass(frozen=True)
class KeyPair:
    d: int
    x: int
    y: int

    @property
    def public_point(self) -> bytes:
        return b"\x04" + self.x.to_bytes(32, "big") + self.y.to_bytes(32, "big")


def new_keypair() -> KeyPair:
    d = secrets.randbelow(_N - 1) + 1
    x, y = _mul(d, _G)
    return KeyPair(d, x, y)


def _sign(key: KeyPair, message: bytes) -> bytes:
    z = int.from_bytes(hashlib.sha256(message).digest(), "big")
    while True:
        k = secrets.randbelow(_N - 1) + 1
        r = _mul(k, _G)[0] % _N
        s = pow(k, -1, _N) * (z + r * key.d) % _N
        if r and s:
            return _seq(_int(r), _int(s))


# --- DER ----------------------------------------------------------------------------------------------
def _len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(raw)]) + raw


def _tlv(tag: int, body: bytes) -> bytes:
    return bytes([tag]) + _len(len(body)) + body


def _int(value: int) -> bytes:
    return _tlv(0x02, value.to_bytes(max(1, (value.bit_length() + 8) // 8), "big"))


def _seq(*parts: bytes) -> bytes:
    return _tlv(0x30, b"".join(parts))


def _set(*parts: bytes) -> bytes:
    return _tlv(0x31, b"".join(parts))


def _oid(dotted: str) -> bytes:
    arcs = [int(part) for part in dotted.split(".")]
    body = bytearray([arcs[0] * 40 + arcs[1]])
    for arc in arcs[2:]:
        chunk = [arc & 0x7F]
        arc >>= 7
        while arc:
            chunk.append(0x80 | (arc & 0x7F))
            arc >>= 7
        body += bytes(reversed(chunk))
    return _tlv(0x06, bytes(body))


def _octets(body: bytes) -> bytes:
    return _tlv(0x04, body)


def _bits(body: bytes, unused: int = 0) -> bytes:
    return _tlv(0x03, bytes([unused]) + body)


def _time(moment: datetime) -> bytes:
    moment = moment.astimezone(timezone.utc)
    if 1950 <= moment.year < 2050:                                    # RFC 5280: UTCTime, else GeneralizedTime
        return _tlv(0x17, moment.strftime("%y%m%d%H%M%SZ").encode("ascii"))
    return _tlv(0x18, moment.strftime("%Y%m%d%H%M%SZ").encode("ascii"))


def _name(common_name: str) -> bytes:
    return _seq(_set(_seq(_oid("2.5.4.3"), _tlv(0x0C, common_name.encode("utf-8")))))


def _context(number: int, body: bytes, *, constructed: bool = True) -> bytes:
    return _tlv((0xA0 if constructed else 0x80) | number, body)


_ECDSA_SHA256 = _seq(_oid("1.2.840.10045.4.3.2"))
_EC_PUBLIC_KEY, _PRIME256V1 = "1.2.840.10045.2.1", "1.2.840.10045.3.1.7"


def _spki(key: KeyPair) -> bytes:
    return _seq(_seq(_oid(_EC_PUBLIC_KEY), _oid(_PRIME256V1)), _bits(key.public_point))


def _key_id(key: KeyPair) -> bytes:
    return hashlib.sha1(key.public_point).digest()


def _extension(oid: str, value: bytes, *, critical: bool = False) -> bytes:
    return _seq(_oid(oid), *([_tlv(0x01, b"\xff")] if critical else []), _octets(value))


def _pem(label: str, der: bytes) -> str:
    body = base64.b64encode(der).decode("ascii")
    lines = [body[index:index + 64] for index in range(0, len(body), 64)]
    return f"-----BEGIN {label}-----\n" + "\n".join(lines) + f"\n-----END {label}-----\n"


def subject_hash_filename(common_name: str) -> str:
    """The ``<hash>.0`` file name OpenSSL's hashed-directory lookup (``SSL_CERT_DIR``/``capath``) needs for a
    certificate whose subject is exactly ``CN=<common_name>``: SHA-1 of the canonical name (ASCII-lower-cased, space
    collapsed, re-encoded as a UTF8String, without the outer SEQUENCE), first four bytes little-endian."""

    canonical = " ".join(common_name.lower().split())
    encoded = _set(_seq(_oid("2.5.4.3"), _tlv(0x0C, canonical.encode("utf-8"))))
    digest = hashlib.sha1(encoded).digest()
    return f"{int.from_bytes(digest[:4], 'little'):08x}.0"


# --- certificates --------------------------------------------------------------------------------------
def _certificate(*, subject: str, issuer: str, subject_key: KeyPair, issuer_key: KeyPair, not_before: datetime,
                 not_after: datetime, extensions: list[bytes]) -> bytes:
    tbs = _seq(_context(0, _int(2)), _int(secrets.randbits(63) | 1), _ECDSA_SHA256, _name(issuer),
               _seq(_time(not_before), _time(not_after)), _name(subject), _spki(subject_key),
               _context(3, _seq(*extensions)))
    return _seq(tbs, _ECDSA_SHA256, _bits(_sign(issuer_key, tbs)))


@dataclass(frozen=True)
class Authority:
    name: str
    key: KeyPair
    cert_der: bytes

    @property
    def cert_pem(self) -> str:
        return _pem("CERTIFICATE", self.cert_der)


@dataclass(frozen=True)
class Leaf:
    key: KeyPair
    cert_der: bytes

    @property
    def cert_pem(self) -> str:
        return _pem("CERTIFICATE", self.cert_der)

    @property
    def key_pem(self) -> str:
        """SEC1 ``EC PRIVATE KEY`` (the form OpenSSL loads for a P-256 key)."""

        body = _seq(_int(1), _octets(self.key.d.to_bytes(32, "big")), _context(0, _oid(_PRIME256V1)),
                    _context(1, _bits(self.key.public_point)))
        return _pem("EC PRIVATE KEY", body)


def new_authority(name: str, *, permitted_dns: tuple[str, ...] | None = None, valid_days: int = 1,
                  now: datetime | None = None) -> Authority:
    """A self-signed CA. ``permitted_dns`` adds a critical name constraint: a leaf for any other host name is refused
    by OpenSSL at verification, even by a client that trusts this CA."""

    key = new_keypair()
    now = now or datetime.now(timezone.utc)
    extensions = [
        _extension("2.5.29.19", _seq(_tlv(0x01, b"\xff")), critical=True),                   # CA:TRUE
        _extension("2.5.29.15", _bits(b"\x06", 1), critical=True),                             # keyCertSign, cRLSign
        _extension("2.5.29.14", _octets(_key_id(key))),
    ]
    if permitted_dns:
        subtrees = b"".join(_seq(_context(2, host.encode("ascii"), constructed=False)) for host in permitted_dns)
        extensions.append(_extension("2.5.29.30", _seq(_context(0, subtrees)), critical=True))
    der = _certificate(subject=name, issuer=name, subject_key=key, issuer_key=key,
                       not_before=now - timedelta(minutes=5), not_after=now + timedelta(days=valid_days),
                       extensions=extensions)
    return Authority(name, key, der)


def issue_leaf(authority: Authority, hostname: str, *, valid_days: int = 1, now: datetime | None = None) -> Leaf:
    """A TLS server certificate for ``hostname`` (subject alternative name), signed by ``authority``."""

    key = new_keypair()
    now = now or datetime.now(timezone.utc)
    extensions = [
        _extension("2.5.29.19", _seq(), critical=True),                                        # CA:FALSE
        _extension("2.5.29.15", _bits(b"\x80", 7), critical=True),                             # digitalSignature
        _extension("2.5.29.37", _seq(_oid("1.3.6.1.5.5.7.3.1"))),                               # serverAuth
        _extension("2.5.29.17", _seq(_context(2, hostname.encode("ascii"), constructed=False))),
        _extension("2.5.29.14", _octets(_key_id(key))),
        _extension("2.5.29.35", _seq(_context(0, _key_id(authority.key), constructed=False))),
    ]
    der = _certificate(subject=hostname, issuer=authority.name, subject_key=key, issuer_key=authority.key,
                       not_before=now - timedelta(minutes=5), not_after=now + timedelta(days=valid_days),
                       extensions=extensions)
    return Leaf(key, der)


# --- a PKI on disk, for a loopback server ---------------------------------------------------------------------
_TEMP_DIRECTORIES: list[Path] = []


def _remove_temporary_directories() -> None:
    for path in _TEMP_DIRECTORIES:
        shutil.rmtree(path, ignore_errors=True)


atexit.register(_remove_temporary_directories)


@dataclass(frozen=True)
class Pki:
    """A CA and one leaf, plus the files a loopback server and a trusting client need. The leaf's private key is in
    ``key_file`` (mode 0600, a temporary directory removed at exit) and nowhere else on disk."""

    authority: Authority
    leaf: Leaf
    hostname: str
    directory: Path

    @property
    def ca_file(self) -> Path:
        return self.directory / "ca.pem"

    @property
    def cert_file(self) -> Path:
        return self.directory / "leaf.pem"

    @property
    def key_file(self) -> Path:
        return self.directory / "leaf.key"

    def server_context(self) -> ssl.SSLContext:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.cert_file, self.key_file)
        return context

    def client_context(self) -> ssl.SSLContext:
        """A verifying client context that trusts ONLY this CA (nothing from the platform, nothing from the
        environment)."""

        return ssl.create_default_context(cadata=self.authority.cert_pem)

    def hashed_directory(self) -> Path:
        """A directory holding the CA under its OpenSSL subject-hash name: what ``SSL_CERT_DIR`` expects."""

        path = self.directory / "hashed"
        path.mkdir(exist_ok=True)
        (path / subject_hash_filename(self.authority.name)).write_text(self.authority.cert_pem, encoding="ascii")
        return path


def new_pki(hostname: str, *, authority_name: str = "Genesis TEST-ONLY throwaway CA",
            permitted_dns: tuple[str, ...] | None = None) -> Pki:
    directory = Path(tempfile.mkdtemp(prefix="genesis-adapter-tls-"))
    _TEMP_DIRECTORIES.append(directory)
    authority = new_authority(authority_name, permitted_dns=permitted_dns)
    leaf = issue_leaf(authority, hostname)
    (directory / "ca.pem").write_text(authority.cert_pem, encoding="ascii")
    (directory / "leaf.pem").write_text(leaf.cert_pem, encoding="ascii")
    key_path = directory / "leaf.key"
    descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="ascii") as handle:
        handle.write(leaf.key_pem)
    return Pki(authority, leaf, hostname, directory)
