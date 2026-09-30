"""Raw capture (design sections 7.6, 11.1, 15): credential safety dominates raw retention.

For every HTTP response that has a body this module, IN THIS ORDER:

1. scans every header NAME and VALUE and both the wire and the decoded body for the credential
   in every section-7.6 form;
2. decodes ``gzip``/``deflate`` bodies in memory under the size and ratio bounds (anything else,
   nested encodings, corrupt streams or bound breaches are UNINSPECTABLE);
3. on a secret hit or an uninspectable body persists NOTHING about the body (no raw object, no
   redacted derivative, no hash) - only secret-safe quarantine metadata, which is itself scanned;
4. otherwise publishes the exact decoded bytes to the frozen ``EvidenceStore`` under the raw
   contract (``PROSPECTIVE_CAPTURED``).

Content checks (clock skew, content type, strict JSON, closed envelope) run afterwards, keep the
raw bytes and only produce a verdict; they are pure with respect to the evidence store.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass
from datetime import timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Mapping

from genesis.evidence import EvidenceStore
from genesis.provenance import AvailabilityClass, SourceContract, SourceContractRegistry
from genesis.registry import AppendOnlyJsonl, RegistryConflict
from genesis.repro import ImmutableConflict, canonical_json
from genesis.time import parse_utc

from genesis_adapters import jsonstrict, schema
from genesis_adapters.errors import AdapterFailure
from genesis_adapters.ids import gid
from genesis_adapters.oddspapi.endpoints import PROVIDER_ID, RAW_CONTRACT_ID, RAW_URI_PATTERN, CanonicalRequest
from genesis_adapters.oddspapi.transport import TransportResult
from genesis_adapters.secrets import Secret, SecretScanner

RAW_SOURCE_TYPE = "oddspapi_v4_rest_response"
RAW_PARSER_VERSION = "raw-capture-v1"
QUARANTINE_SCHEMA = "quarantine-v1"
FALLBACK_CONTENT_TYPE = "application/octet-stream"
_ALLOWED_HEADERS = frozenset({"date", "content-type", "content-length", "content-encoding", "etag",
                              "last-modified", "retry-after"})
_ALLOWED_PATTERN = re.compile(r"^x-(ratelimit|requests)-[a-z-]{1,40}$")
_NAME = re.compile(r"^[a-z0-9-]{1,64}$")
_JSON_TYPE = re.compile(r"^application/json\s*(;.*)?$", re.IGNORECASE)
_GZIP = frozenset({"gzip", "x-gzip"})


class CaptureConflict(RuntimeError):
    """The evidence store refused the publication (immutability or identity conflict)."""


def raw_contract(licensing_note: str) -> SourceContract:
    return SourceContract(
        contract_id=RAW_CONTRACT_ID, provider=PROVIDER_ID, source_type=RAW_SOURCE_TYPE,
        uri_pattern=RAW_URI_PATTERN, availability_class=AvailabilityClass.PROSPECTIVE_CAPTURED,
        timestamp_precision="microsecond", availability_rule="retrieved_at = trusted T1",
        parser_version=RAW_PARSER_VERSION, licensing_note=licensing_note,
        supports_historical_reconstruction=False, supports_prospective_capture=True)


def register_raw_contract(registry: SourceContractRegistry, *, licensing_note: str) -> str:
    return registry.register(raw_contract(licensing_note))


@dataclass(frozen=True)
class Captured:
    kind: str                                   # STORED | SECRET | UNINSPECTABLE | NO_BODY
    raw_observation_id: str | None
    decoded: bytes | None                       # the inspected body; in memory only
    headers: tuple[tuple[str, str], ...]        # allowlisted, secret-clean
    content_encoding: str | None
    byte_length: int | None
    failure: AdapterFailure | None
    quarantine_id: str | None
    detection_classes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ContentVerdict:
    failure: AdapterFailure | None
    parsed: Any = None
    findings: tuple = ()


_JSON_FAILURES = {
    "OVERSIZE": AdapterFailure.OVERSIZE_BODY, "INVALID_UTF8": AdapterFailure.INVALID_UTF8,
    "EMPTY": AdapterFailure.NOT_JSON, "NOT_JSON": AdapterFailure.NOT_JSON,
    "DUPLICATE_KEYS": AdapterFailure.DUPLICATE_KEYS, "NONFINITE_NUMBER": AdapterFailure.NONFINITE_NUMBER,
}


def parse_http_date(value: str):
    """A UTC datetime from an RFC 7231 ``Date`` value, or None (naive, non-GMT or unparseable)."""

    try:
        moment = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if moment.tzinfo is None or moment.utcoffset() != timedelta(0):
        return None
    return moment.astimezone(timezone.utc)


class RawCapture:
    def __init__(self, *, root: Path, evidence: EvidenceStore, gate, config, secret: Secret | None,
                 require_date: bool, licensing_note: str):
        self.root = Path(root)
        self.evidence = evidence
        self.gate = gate
        self.config = config
        self.require_date = require_date
        self.licensing_note = licensing_note
        self.scanner = SecretScanner(secret, policy=config.policy) if secret is not None else None
        self.quarantine = AppendOnlyJsonl(self.root / "quarantine.jsonl")

    # -- helpers ---------------------------------------------------------------------------
    @property
    def scans_for_secret(self) -> bool:
        """True when a credential is configured, i.e. every response is scanned before storage."""

        return self.scanner is not None

    def _hit(self, data: bytes) -> bool:
        return self.scanner is not None and self.scanner.scan(data).hit

    def hits_secret(self, data: bytes) -> bool:
        """True when ``data`` carries the configured key in any section-7.6 form (never True without a key)."""

        return self._hit(data)

    @staticmethod
    def _encoding(headers) -> str:
        tokens = []
        for name, value in headers:
            if name.lower() == "content-encoding":
                tokens += [item.strip().lower() for item in value.split(",") if item.strip()]
        if not tokens or tokens == ["identity"]:
            return "none"
        if len(tokens) == 1 and tokens[0] in _GZIP:
            return "gzip"
        if len(tokens) == 1 and tokens[0] == "deflate":
            return "deflate"
        return "unsupported"

    def _decode(self, wire: bytes, encoding: str) -> bytes | None:
        """The decoded body, or None when it cannot be fully and safely inspected."""

        policy = self.config.policy
        if encoding == "none":
            return wire
        if encoding == "unsupported":
            return None
        wbits = zlib.MAX_WBITS | 16 if encoding == "gzip" else zlib.MAX_WBITS
        limit = min(policy.max_response_bytes, policy.max_decompression_ratio * max(len(wire), 1))
        stream = zlib.decompressobj(wbits=wbits)
        try:
            out = stream.decompress(wire, limit + 1)
            if len(out) > limit or stream.unconsumed_tail or not stream.eof or stream.unused_data:
                return None                                # incomplete, oversize or trailing/second member
        except zlib.error:
            return None
        return out

    def _allowlisted(self, headers) -> tuple[tuple[str, str], ...]:
        cap = self.config.policy.header_value_max_chars
        kept: dict[str, str] = {}
        for name, value in headers:
            key = name.lower()
            if (key in _ALLOWED_HEADERS or _ALLOWED_PATTERN.match(key)) and len(value) <= cap \
                    and key not in kept:
                kept[key] = value
        return tuple(sorted(kept.items()))

    def write_quarantine(self, aid: str, request: CanonicalRequest, result: TransportResult, t1: str | None,
                          reason: str, classes: set[str], byte_length: int | None) -> str:
        """Secret-safe metadata only; every field is scanned and a dirty one is dropped."""

        cap = self.config.policy.header_value_max_chars
        content_type = None
        names: list[str] = []
        for name, value in result.headers:
            key = name.lower()
            if _NAME.match(key) and not self._hit(key.encode("utf-8", "replace")):
                names.append(key)
            if key == "content-type" and len(value) <= cap and not self._hit(value.encode("utf-8", "replace")):
                content_type = value
        meta = {"acquisition_id": aid, "provider_request_hash": request.provider_request_hash, "T1": t1,
                "http_status": result.http_status, "byte_length": byte_length, "content_type": content_type,
                "header_names": sorted(set(names)), "detection_classes": sorted(classes), "reason": reason}
        if self._hit(canonical_json(meta)):                    # defence in depth: nothing optional survives
            meta.update(content_type=None, header_names=[])
        quarantine_id = gid("quar", acquisition_id=aid, reason=reason)
        self.quarantine.append({"record_type": "quarantine", "schema_version": QUARANTINE_SCHEMA,
                                "quarantine_id": quarantine_id, **meta})
        return quarantine_id

    # -- store ---------------------------------------------------------------------------------
    def store(self, *, aid: str, request: CanonicalRequest, result: TransportResult, t1: str) -> Captured:
        wire = result.body
        if wire is None:
            return Captured("NO_BODY", None, None, (), None, None, None, None)
        policy = self.config.policy
        classes: set[str] = set()
        if self.scanner is not None:
            for name, value in result.headers:
                if self._hit(name.encode("utf-8", "replace")):
                    classes.add("HEADER_NAME")
                if self._hit(value.encode("utf-8", "replace")):
                    classes.add("HEADER_VALUE")
        encoding = self._encoding(result.headers)
        oversize = len(wire) > policy.max_response_bytes
        inspected_wire = wire[:policy.max_response_bytes]
        decoded = None if (oversize and encoding != "none") else self._decode(inspected_wire, encoding)
        if self.scanner is not None:
            for label, data in (("BODY_", inspected_wire), ("BODY_", decoded)):
                if data is not None:
                    classes.update(label + item for item in self.scanner.scan(data).detection_classes)
        if classes:
            quarantine_id = self.write_quarantine(aid, request, result, t1, AdapterFailure.SECRET_ECHO.value,
                                                   classes, len(wire))
            return Captured("SECRET", None, None, (), None, len(wire), AdapterFailure.SECRET_ECHO,
                            quarantine_id, tuple(sorted(classes)))
        if decoded is None:
            quarantine_id = self.write_quarantine(aid, request, result, t1,
                                                   AdapterFailure.UNINSPECTABLE_BODY.value, set(), len(wire))
            return Captured("UNINSPECTABLE", None, None, (), None, len(wire),
                            AdapterFailure.UNINSPECTABLE_BODY, quarantine_id)
        headers = self._allowlisted(result.headers)
        content_type = next((v for k, v in headers if k == "content-type"), FALLBACK_CONTENT_TYPE)
        try:
            observation = self.evidence.publish(
                decoded, contract_id=RAW_CONTRACT_ID, source_uri=request.source_uri, provider=PROVIDER_ID,
                source_type=RAW_SOURCE_TYPE, retrieved_at=t1, parse_ready_at=t1, first_seen_at=t1,
                parser_version=RAW_PARSER_VERSION, content_type=content_type,
                licensing_note=self.licensing_note, availability_class=AvailabilityClass.PROSPECTIVE_CAPTURED,
                upstream_version=request.api_version)
        except (ImmutableConflict, RegistryConflict, ValueError):
            raise CaptureConflict("evidence publication was refused") from None
        return Captured("STORED", observation.observation_id, decoded, headers,
                        None if encoding == "none" else encoding, len(decoded),
                        AdapterFailure.OVERSIZE_BODY if oversize else None, None)

    # -- validate -------------------------------------------------------------------------------
    def _skew_failure(self, headers, t1: str) -> AdapterFailure | None:
        values = [value for name, value in headers if name == "date"]
        if not values:
            return AdapterFailure.CLOCK_SKEW if self.require_date else None
        moment = parse_http_date(values[0])
        if moment is None:
            return AdapterFailure.CLOCK_SKEW
        limit = timedelta(seconds=self.config.policy.clock_skew_max_seconds)
        return AdapterFailure.CLOCK_SKEW if abs(moment - parse_utc(t1)) > limit else None

    def validate(self, *, request: CanonicalRequest, captured: Captured, t1: str) -> ContentVerdict:
        """Clock skew, content type, strict JSON and the closed envelope, in that order."""

        failure = self._skew_failure(captured.headers, t1)
        if failure is not None:
            return ContentVerdict(failure)
        content_type = next((v for k, v in captured.headers if k == "content-type"), "")
        if not _JSON_TYPE.match(content_type):
            return ContentVerdict(AdapterFailure.WRONG_CONTENT_TYPE)
        try:
            parsed = jsonstrict.loads_strict(captured.decoded, max_bytes=self.config.policy.max_response_bytes)
        except jsonstrict.StrictJsonError as exc:
            return ContentVerdict(_JSON_FAILURES[exc.code])
        spec = self.config.endpoints[request.role]
        findings = schema.validate_closed(parsed, self.config.schemas[spec.response_schema_id])
        envelope = [f for f in findings if f.scope == "RESPONSE"]
        if any(f.kind in ("WRONG_TYPE", "MISSING_REQUIRED") for f in envelope):
            return ContentVerdict(AdapterFailure.ENVELOPE_SCHEMA_MISMATCH, findings=tuple(envelope))
        if envelope:
            return ContentVerdict(AdapterFailure.SCHEMA_DRIFT, findings=tuple(envelope))
        return ContentVerdict(None, parsed, findings)
