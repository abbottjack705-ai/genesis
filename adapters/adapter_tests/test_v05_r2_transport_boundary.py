"""R2 - the credential and transport boundary (controlling hostile audit hostile_audit_cfcff3d).

HA-01 (design 7.6/7.7, F-11): an exception class name is untrusted text. The HTTPS transport screens it before a
    ``TransportResult`` exists: a label that is not a plain bounded identifier, or that carries any section-7.6
    form of the key, becomes a fixed placeholder; the integer errno keeps its meaning.
HA-02 (7.7(b), FRZ-11, TX-01): a KeyboardInterrupt/SystemExit raised while the connection is being CLOSED leaves
    through the same single process-control clause as one raised during the exchange: a fresh instance, the class
    and integer status kept, no text, cause, context, notes or keyed frame local.
HA-03 (14.6 enforcement 3): T0 is read immediately before the first request byte, and no byte is written at or
    after ``Tq + request_timeout_seconds`` - not after a slow connect/TLS set-up, not at exact equality.
HA-07 (7.6): header names and values are screened as the ORIGINAL wire octets (``http.client`` hands them over
    Latin-1 decoded), so a non-ASCII key echoed in a header is caught; nothing of such a response is kept.
HA-08 (7.6, F-06, F-11): every received body byte - including the cap+1 probe byte - is screened before any
    retention decision, for identity and content-encoded bodies alike.
HA-13 / P:HA-006 (7.6, 19 S7): the production ``run`` command has no CA or connect-address seam; the test TLS
    material is export-ignored and referenced by no production module.

No failure message of these tests ever prints a form of the (public, test-only) sentinel.
"""

from __future__ import annotations

import ast
import gzip
import json
import re
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

from genesis.evidence import EvidenceStore
from genesis.provenance import SourceContractRegistry
from genesis.repro import canonical_json

from genesis_adapters import cli
from genesis_adapters import errors as err
from genesis_adapters.oddspapi import transport as tr
from genesis_adapters.oddspapi import transport_http as th
from genesis_adapters.oddspapi import verify
from genesis_adapters.oddspapi.raw_capture import RawCapture, register_raw_contract
from genesis_adapters.oddspapi.transport import TransportResult
from genesis_adapters.secrets import Secret, SecretScanner

from . import parser_support as ps
from .pipeline_support import acquisition_rows, odds_item, odds_response, open_rt
from .support import REPO, SENTINEL_KEY, FixedClock, no_response, read_jsonl, scratch_root

PLACEHOLDER = "REDACTED_EXCEPTION_CLASS"
SCANNER = SecretScanner(Secret(SENTINEL_KEY), policy=ps.POLICY)
JSON = (("content-type", "application/json"),)
T0 = "2026-10-01T12:00:00.000000Z"
DEADLINE = "2026-10-01T12:01:00.000000Z"
UNICODE_KEY = "éèêëàáâãäåæçìíîï"                     # printable, non-ASCII: its wire octets are UTF-8
# an int whose decimal digits are a run of the key's hex form (a HEX_FRAGMENT key form), and one too large to print
KEY_DIGITS = int(max(re.findall(r"[1-9][0-9]{7,}", SENTINEL_KEY.encode().hex()), key=len))
HUGE_ERRNO = 10 ** (sys.get_int_max_str_digits() + 1)


def clean(value) -> bool:
    return not SCANNER.scan(repr(value).encode("utf-8", "backslashreplace")).hit


def shown(value) -> str:
    """A value for a failure message: plain ASCII text with no form of either test key, else withheld. (Every
    non-ASCII value in this module derives from the non-ASCII test key.)"""

    try:
        text = repr(value)
    except ValueError:                                    # an int too large to print
        return "<unprintable>"
    if not text.isascii() or SCANNER.scan(text.encode("ascii")).hit:
        return "<withheld: could carry a form of a test key>"
    return text


class SafeAsserts(unittest.TestCase):
    def same(self, actual, expected, what: str = "value") -> None:
        if actual != expected:
            self.fail(f"{what}: got {shown(actual)}, expected {shown(expected)}")


def request():
    return odds_item().request


def transport(connection, *, secret=SENTINEL_KEY, policy=None):
    return th.HttpsTransport(Secret(secret), credential_param="apiKey", policy=policy or ps.POLICY,
                             connection_factory=lambda *args: connection)


class Scripted:
    """A fault-injecting connection: ``fail`` maps a stage to the exception (or callable) it raises there."""

    def __init__(self, fail=None, *, body=b"[]", on=None):
        self.fail = fail or {}
        self.on = on or {}
        self.body = body
        self.served = False
        self.writes = []

    def _stage(self, name):
        if name in self.on:
            self.on[name]()
        failure = self.fail.get(name)
        if failure is not None:
            raise failure() if isinstance(failure, type) else failure

    def open(self, timeout):
        self._stage("open")

    def settimeout(self, timeout):
        self._stage("settimeout")

    def write(self, method, target, headers):
        self._stage("write")
        self.writes.append(method)                        # never the target: it carries the key

    def read_head(self):
        self._stage("read_head")
        return 200, [("Content-Type", "application/json")]

    def read_chunk(self, size):
        self._stage("read_chunk")
        if self.served:
            return b""
        self.served = True
        return self.body

    def finished(self):
        return self.served

    def close(self):
        self._stage("close")


def named(name: str, base: type = OSError) -> type:
    return type(name, (base,), {})


# ---------------------------------------------------------------------------------------------------------
class ExceptionLabelTests(SafeAsserts):
    """HA-01 at the transport itself: the TransportResult never carries an unsafe label."""

    def test_ha01_a_key_bearing_class_label_is_replaced_before_the_result_exists(self):
        forms = {"identifier": "Error_" + SENTINEL_KEY.replace("-", "_"), "verbatim": SENTINEL_KEY,
                 "lower case": SENTINEL_KEY.lower(), "fragment": "E_" + SENTINEL_KEY[-16:],
                 "hex": "E_" + SENTINEL_KEY.encode().hex()}
        for label, name in forms.items():
            for stage in ("open", "write", "read_head", "read_chunk"):
                with self.subTest(form=label, stage=stage):
                    result = transport(Scripted({stage: named(name)})).send(
                        request(), clock=FixedClock(T0, step_micros=1000), deadline_at=DEADLINE)
                    self.same(result.sanitized_error["class"], PLACEHOLDER, "class label")
                    self.assertTrue(clean(result), "a form of the key is in the TransportResult")

    def test_ha01_errno_keeps_its_meaning_when_only_the_label_is_tainted(self):
        failing = named("Error_" + SENTINEL_KEY.replace("-", "_"))(104, "reset")
        result = transport(Scripted({"write": failing})).send(request(), clock=FixedClock(T0, step_micros=1000),
                                                              deadline_at=DEADLINE)
        self.same(result.sanitized_error, {"class": PLACEHOLDER, "errno": 104}, "sanitized error")

    def test_ha01_a_structurally_unsafe_label_is_replaced_and_an_ordinary_one_kept(self):
        cap = ps.POLICY.header_value_max_chars
        for label, name in (("newline", "Bad\nName"), ("space", "Bad Name"), ("control", "Bad\x1bName"),
                            ("too long", "E" * (cap + 1)), ("empty", ""),
                            ("trailing newline", "BadName" + chr(10))):
            with self.subTest(label):
                result = transport(Scripted({"open": named(name)})).send(
                    request(), clock=FixedClock(T0, step_micros=1000), deadline_at=DEADLINE)
                self.same(result.sanitized_error["class"], PLACEHOLDER, "class label")
        kept = transport(Scripted({"open": ConnectionResetError(104, "reset")})).send(
            request(), clock=FixedClock(T0, step_micros=1000), deadline_at=DEADLINE)
        self.same(kept.sanitized_error, {"class": "ConnectionResetError", "errno": 104}, "sanitized error")

    def test_ha01_an_errno_carrying_key_digits_is_dropped_and_the_label_kept(self):
        failing = ConnectionResetError(KEY_DIGITS, "reset")
        result = transport(Scripted({"read_head": failing})).send(request(), clock=FixedClock(T0, step_micros=1000),
                                                                  deadline_at=DEADLINE)
        self.same(result.sanitized_error, {"class": "ConnectionResetError", "errno": None}, "sanitized error")
        self.assertTrue(clean(result), "a form of the key is in the TransportResult")

    def test_ha01_an_errno_too_large_to_serialize_is_dropped(self):
        failing = OSError()
        failing.errno = HUGE_ERRNO
        result = transport(Scripted({"open": failing})).send(request(), clock=FixedClock(T0, step_micros=1000),
                                                             deadline_at=DEADLINE)
        self.same(result.sanitized_error, {"class": "OSError", "errno": None}, "sanitized error")

    def test_ha01_sanitize_exception_applies_the_structural_rules_at_the_source(self):
        cap = ps.POLICY.header_value_max_chars
        self.same(tr.sanitize_exception(named("Bad Name")(), max_chars=cap), {"class": PLACEHOLDER, "errno": None})
        for code in (HUGE_ERRNO, 10 ** cap, "104", 1.5):                   # unprintable, too long, not an int
            odd = OSError()
            odd.errno = code
            self.same(tr.sanitize_exception(odd, max_chars=cap), {"class": "OSError", "errno": None})
        longest = 10 ** (cap - 1)                                            # exactly cap digits: kept
        self.same(tr.safe_errno(longest, max_chars=cap), longest)
        self.same(tr.sanitize_exception(ConnectionResetError(104, "x"), max_chars=cap),
                  {"class": "ConnectionResetError", "errno": 104})

    def test_ha01_through_the_acquisition_path_no_durable_file_carries_the_key(self):
        failing = named("Error_" + SENTINEL_KEY.replace("-", "_"))
        with scratch_root() as root:
            conn = Scripted({"open": failing})
            live = th.HttpsTransport(Secret(SENTINEL_KEY), credential_param="apiKey", policy=ps.POLICY,
                                     connection_factory=lambda *args: conn)
            rt = open_rt(root, transport=live, secret=Secret(SENTINEL_KEY))
            outcome = rt.runner.acquire(odds_item())
            self.same(outcome.detail, PLACEHOLDER, "outcome detail")
            completed = [r for r in acquisition_rows(rt) if r["record_type"] == "acq_completed"]
            self.assertEqual(len(completed), 1)
            self.assertTrue(completed[0]["sanitized_error"] == {"class": PLACEHOLDER, "errno": None},
                            "the stored record is not the placeholder")
            self.assertEqual(verify.scan_runtime_for_secret(root, Secret(SENTINEL_KEY)), ())


# ---------------------------------------------------------------------------------------------------------
class PersistedRecordTests(SafeAsserts):
    """HA-01 at the persistence point: whatever a transport reports, the stored record is structurally safe and
    scanner-clean, and each field keeps its meaning unless it is the tainted one."""

    def stored(self, root, error_class, errno, *, secret=True):
        rt = open_rt(root, script=[no_response(error_class=error_class, errno=errno)],
                     secret=Secret(SENTINEL_KEY) if secret else None)
        outcome = rt.runner.acquire(odds_item())
        completed = [r for r in acquisition_rows(rt) if r["record_type"] == "acq_completed"]
        self.assertEqual(len(completed), 1)                                   # the attempt is still recorded
        return completed[0]["sanitized_error"], outcome

    def test_ha01_an_unsafe_label_reported_by_a_transport_is_replaced_and_its_errno_kept(self):
        for keyed in (True, False):
            with self.subTest(keyed=keyed), scratch_root() as root:
                stored, outcome = self.stored(root, "Bad Name", 104, secret=keyed)
                self.same(stored, {"class": PLACEHOLDER, "errno": 104}, "stored record")
                self.same(outcome.detail, PLACEHOLDER, "outcome detail")

    def test_ha01_an_errno_carrying_key_digits_is_dropped_before_persistence(self):
        with scratch_root() as root:
            stored, _ = self.stored(root, "ConnectionResetError", KEY_DIGITS)
            self.assertTrue(stored == {"class": "ConnectionResetError", "errno": None}, "the errno was kept")
            self.assertEqual(verify.scan_runtime_for_secret(root, Secret(SENTINEL_KEY)), ())

    def test_ha01_an_errno_too_large_to_serialize_neither_crashes_nor_persists(self):
        for keyed in (True, False):
            with self.subTest(keyed=keyed), scratch_root() as root:
                stored, _ = self.stored(root, "OSError", HUGE_ERRNO, secret=keyed)
                self.same(stored, {"class": "OSError", "errno": None}, "stored record")

    def test_ha01_the_record_is_scanned_again_exactly_as_it_will_be_persisted(self):
        # a scanner that flags only the complete record (never either field alone): nothing of it may be kept
        flagged = canonical_json({"class": "ConnectionResetError", "errno": 104})
        with scratch_root() as root, mock.patch.object(RawCapture, "hits_secret", lambda capture, data: data == flagged):
            stored, _ = self.stored(root, "ConnectionResetError", 104)
        self.same(stored, {"class": PLACEHOLDER, "errno": None}, "stored record")


# ---------------------------------------------------------------------------------------------------------
class CleanupProcessControlTests(SafeAsserts):
    """HA-02: process control raised by ``close()`` leaves fresh, like process control raised during the send."""

    def assert_fresh(self, caught, injected, cls, code=None):
        self.assertIs(type(caught), cls)
        self.assertTrue(caught is not injected, "the injected exception itself escaped")
        self.assertIsNone(caught.__cause__)
        self.assertIsNone(caught.__context__)
        self.assertFalse(hasattr(caught, "__notes__"))
        if cls is SystemExit:
            self.same(caught.code, code, "SystemExit code")
            self.same(caught.args, () if code is None else (code,), "args")
        else:
            self.same(caught.args, (), "args")
        frame = caught.__traceback__
        while frame is not None:
            if not frame.tb_frame.f_code.co_filename.endswith("transport_http.py"):
                frame = frame.tb_next                         # only the transport's own frames hold its locals
                continue
            for value in frame.tb_frame.f_locals.values():
                try:
                    text = repr(value)
                except Exception:
                    text = ""
                self.assertFalse(SCANNER.scan(text.encode("utf-8", "backslashreplace")).hit,
                                 "a traceback frame local carries a form of the key")
            frame = frame.tb_next

    def raise_from_close(self, injected, *, during=None):
        conn = Scripted({"close": injected, **({"read_head": during} if during is not None else {})})
        with self.assertRaises(BaseException) as raised:
            transport(conn).send(request(), clock=FixedClock(T0, step_micros=1000), deadline_at=DEADLINE)
        return raised.exception

    def test_ha02_keyboard_interrupt_from_close_leaves_fresh(self):
        injected = KeyboardInterrupt("close-error: " + SENTINEL_KEY)
        injected.add_note("note: " + SENTINEL_KEY)
        injected.__cause__ = ValueError(SENTINEL_KEY)
        self.assert_fresh(self.raise_from_close(injected), injected, KeyboardInterrupt)

    def test_ha02_system_exit_from_close_keeps_its_status_and_drops_its_text(self):
        for code, expected in ((37, 37), ("close-error: " + SENTINEL_KEY, 1), (None, None)):
            with self.subTest(code=type(code).__name__):
                injected = SystemExit(code)
                self.assert_fresh(self.raise_from_close(injected), injected, SystemExit, expected)

    def test_ha02_process_control_during_the_send_and_again_in_close_leaves_one_fresh_exception(self):
        injected = KeyboardInterrupt("close-error: " + SENTINEL_KEY)
        caught = self.raise_from_close(injected, during=KeyboardInterrupt("head-error: " + SENTINEL_KEY))
        self.assert_fresh(caught, injected, KeyboardInterrupt)

    def test_ha02_an_ordinary_error_in_close_changes_nothing_that_was_received(self):
        conn = Scripted({"close": OSError(9, "close-error: " + SENTINEL_KEY)}, body=b'[{"x": 1}]')
        result = transport(conn).send(request(), clock=FixedClock(T0, step_micros=1000), deadline_at=DEADLINE)
        self.assertEqual((result.outcome, result.body, result.sanitized_error), ("RESPONSE", b'[{"x": 1}]', None))


# ---------------------------------------------------------------------------------------------------------
class WriteBoundaryDeadlineTests(SafeAsserts):
    """HA-03: the deadline and T0 are bound to the request-write boundary."""

    class SteppingClock:
        """A settable clock; a hook may move it between two operations of the transport."""

        def __init__(self, value):
            self.value = value

        def now(self):
            return self.value

    def test_ha03_the_deadline_arriving_after_the_timeout_setup_prevents_the_write(self):
        clock = self.SteppingClock(T0)
        conn = Scripted(on={"settimeout": lambda: setattr(clock, "value", DEADLINE)})   # the audit's HA-03 probe
        result = transport(conn).send(request(), clock=clock, deadline_at=DEADLINE)
        self.assertEqual(conn.writes, [])
        self.assertEqual((result.outcome, result.sanitized_error["class"]), ("NO_RESPONSE", "TimeoutError"))

    def test_ha03_a_slow_connect_and_tls_setup_that_reaches_the_deadline_prevents_the_write(self):
        clock = self.SteppingClock(T0)
        conn = Scripted(on={"open": lambda: setattr(clock, "value", DEADLINE)})
        result = transport(conn).send(request(), clock=clock, deadline_at=DEADLINE)
        self.assertEqual(conn.writes, [])
        self.assertEqual(result.outcome, "NO_RESPONSE")

    def test_ha03_one_microsecond_before_the_deadline_the_request_is_written(self):
        clock = self.SteppingClock(T0)
        just_before = ps.iso_add(DEADLINE, micros=-1)
        conn = Scripted(on={"settimeout": lambda: setattr(clock, "value", just_before)})
        transport(conn).send(request(), clock=clock, deadline_at=DEADLINE)
        self.assertEqual(len(conn.writes), 1)

    def test_ha03_t0_is_read_immediately_before_the_first_request_byte(self):
        clock = FixedClock(T0, step_micros=1000)
        seen = {}
        conn = Scripted(on={"write": lambda: seen.setdefault("at_write", clock.peek())}, body=b"[]")
        result = transport(conn).send(request(), clock=clock, deadline_at=DEADLINE)
        self.assertEqual(result.request_started_at, ps.iso_add(seen["at_write"], micros=-1000))
        self.assertLess(result.request_started_at, result.response_received_at)


# ---------------------------------------------------------------------------------------------------------
class CaptureFixture:
    def __init__(self, root, *, secret, policy=None):
        contracts = SourceContractRegistry(root / "contracts.jsonl")
        register_raw_contract(contracts, licensing_note="FIXTURE-ONLY-NO-PROVIDER-TERMS")
        self.evidence = EvidenceStore(root / "evidence", contracts=contracts)
        config = SimpleNamespace(policy=policy or ps.POLICY, endpoints=ps.CONFIG_BODY.endpoints,
                                 schemas=ps.CONFIG_BODY.schemas)
        self.capture = RawCapture(root=root, evidence=self.evidence, gate=None, config=config, secret=Secret(secret),
                                  require_date=False, licensing_note="FIXTURE-ONLY-NO-PROVIDER-TERMS")
        self.root = root

    def store(self, body, headers=JSON):
        result = TransportResult("RESPONSE", 200, tuple(headers), body, None, T0, ps.iso_add(T0, seconds=1))
        return self.capture.store(aid="d" * 64, request=request(), result=result, t1=ps.iso_add(T0, seconds=1))

    def published(self):
        return len(list((self.root / "evidence").rglob("*"))) if (self.root / "evidence").exists() else 0


def wire_form(text: str) -> str:
    """What ``http.client`` hands over for header octets that are the UTF-8 encoding of ``text``."""

    return text.encode("utf-8").decode("latin-1")


class HeaderOctetTests(SafeAsserts):
    """HA-07: a non-ASCII key echoed in any header is caught from the original wire octets."""

    def test_ha07_a_non_ascii_key_echoed_in_an_allowlisted_header_value_is_a_secret_echo(self):
        for header in ("etag", "last-modified", "x-requests-used", "date", "content-type"):
            with self.subTest(header), scratch_root() as root:
                fixture = CaptureFixture(root, secret=UNICODE_KEY)
                captured = fixture.store(b"[]", headers=JSON + ((header, wire_form(UNICODE_KEY)),))
                self.same((captured.kind, captured.headers), ("SECRET", ()), "capture kind and kept headers")
                self.assertIn("HEADER_VALUE", captured.detection_classes)

    def test_ha07_a_non_ascii_key_echoed_in_a_header_name_is_a_secret_echo(self):
        with scratch_root() as root:
            fixture = CaptureFixture(root, secret=UNICODE_KEY)
            captured = fixture.store(b"[]", headers=JSON + (("x-" + wire_form(UNICODE_KEY), "1"),))
            self.assertEqual(captured.kind, "SECRET")
            self.assertIn("HEADER_NAME", captured.detection_classes)

    def test_ha07_through_the_runtime_nothing_reversible_to_the_key_is_durable(self):
        key = Secret(UNICODE_KEY)
        with scratch_root() as root:
            rt = open_rt(root, script=[odds_response(headers=JSON + (("etag", wire_form(UNICODE_KEY)),))], secret=key)
            with self.assertRaises(err.AcquisitionHalt):
                rt.acquire(odds_item())
            completed = [r for r in acquisition_rows(rt) if r["record_type"] == "acq_completed"]
            self.same((completed[0]["failure"], completed[0]["headers"]), ("SECRET_ECHO", []), "completed row")
            self.assertEqual(verify.scan_runtime_for_secret(root, key), ())

    def test_ha07_a_content_type_echo_leaves_no_trace_in_the_quarantine_or_anywhere(self):
        key = Secret(UNICODE_KEY)
        with scratch_root() as root:
            rt = open_rt(root, script=[odds_response(headers=(("content-type", wire_form(UNICODE_KEY)),))], secret=key)
            with self.assertRaises(err.AcquisitionHalt):
                rt.acquire(odds_item())
            quarantined = read_jsonl(root / "quarantine.jsonl")
            self.same([row["content_type"] for row in quarantined], [None], "quarantined content types")
            self.assertEqual(verify.scan_runtime_for_secret(root, key), ())

    def test_ha07_the_runtime_scan_finds_a_latin1_reversible_form_in_a_durable_file(self):
        key = Secret(UNICODE_KEY)
        with scratch_root() as root:
            (root / "planted.json").write_text(json.dumps({"etag": wire_form(UNICODE_KEY)}, ensure_ascii=False),
                                               encoding="utf-8")
            (root / "planted_escaped.json").write_text(json.dumps({"etag": wire_form(UNICODE_KEY)}), encoding="utf-8")
            self.assertEqual(sorted(path.name for path in verify.scan_runtime_for_secret(root, key)),
                             ["planted.json", "planted_escaped.json"])

    def test_ha07_ascii_keys_and_clean_headers_are_unaffected(self):
        with scratch_root() as root:
            fixture = CaptureFixture(root, secret=SENTINEL_KEY)
            captured = fixture.store(b"[]", headers=JSON + (("etag", wire_form("éèêë-clean")),))
            self.assertEqual(captured.kind, "STORED")


class FullWireScreeningTests(SafeAsserts):
    """HA-08: every received byte is screened, including the cap+1 probe byte."""

    KEY = "ABCDEFGH12345678"                              # 8-character fragments are key forms (width 8)

    def fixture(self, root):
        return CaptureFixture(root, secret=self.KEY, policy=ps.policy_with(max_response_bytes=32))

    def test_ha08_a_fragment_ending_at_the_cap_probe_byte_is_a_secret_echo(self):
        with scratch_root() as root:
            fixture = self.fixture(root)
            captured = fixture.store(b"x" * 25 + b"ABCDEFGH")                 # 33 bytes = cap + 1
            self.assertEqual(captured.kind, "SECRET")
            self.assertIsNone(captured.raw_observation_id)

    def test_ha08_a_fragment_at_every_position_around_the_cap_is_caught(self):
        for end in range(26, 34):                                             # fragment ends at byte 26 .. 33
            with self.subTest(end=end), scratch_root() as root:
                wire = (b"x" * (end - 8) + b"ABCDEFGH" + b"y" * 33)[:33]
                self.assertEqual(self.fixture(root).store(wire).kind, "SECRET")

    def test_ha08_a_content_encoded_oversize_body_is_screened_on_its_wire_bytes(self):
        with scratch_root() as root:
            wire = (gzip.compress(b"[]") + b"z" * 33)[:25] + b"ABCDEFGH"   # 33 bytes: the fragment ends at cap+1
            captured = self.fixture(root).store(wire, headers=JSON + (("content-encoding", "gzip"),))
            self.assertEqual(captured.kind, "SECRET")                         # secret precedence (F-11 over F-11b)

    def test_ha08_a_clean_oversize_identity_body_is_still_stored_truncated(self):
        with scratch_root() as root:
            captured = self.fixture(root).store(b"[" + b"1," * 20)
            self.assertEqual((captured.kind, captured.failure), ("STORED", err.AdapterFailure.OVERSIZE_BODY))


# ---------------------------------------------------------------------------------------------------------
class ProductionTrustBoundaryTests(SafeAsserts):
    """HA-13 / P:HA-006: no CA or connect-address seam in the production run path; test TLS stays test-only."""

    def test_p006_the_production_run_command_has_no_ca_or_connect_option(self):
        base = ["run", "--root", "r", "--plan", "p", "--mode", "G2"]
        for extra in (["--ca-file", "test-ca.pem"], ["--connect", "127.0.0.1:8443"]):
            with self.subTest(extra[0]), mock.patch("sys.stderr"), self.assertRaises(SystemExit):
                cli._parser().parse_args(base + extra)

    def test_p006_run_builds_the_transport_with_the_system_trust_store_and_the_pinned_host(self):
        import os
        from .test_v05_tx01 import prepare
        seen = []
        real = th.HttpsTransport

        class Recorder(real):
            def __init__(self, secret, **kw):
                seen.append(sorted(kw))
                super().__init__(secret, **kw)

        with scratch_root() as base, mock.patch.object(th, "HttpsTransport", Recorder), \
                mock.patch("sys.stderr"), mock.patch("sys.stdout"):
            root, plan, env = prepare(base)
            plan.write_text("[]", encoding="utf-8")
            with mock.patch.dict(os.environ, {"GENESIS_ODDSPAPI_CREDENTIAL_FILE": env["GENESIS_ODDSPAPI_CREDENTIAL_FILE"]}):
                cli.cmd_run(SimpleNamespace(config=None, root=str(root), plan=str(plan), mode="G2"))
        self.assertEqual(seen, [["credential_param", "policy"]])

    def test_p006_no_production_module_references_the_test_tls_material(self):
        for path in (REPO / "adapters" / "src").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for marker in ("fixtures/tls", "test-ca", "server.key", "server.pem", "ca_file", "cafile"):
                self.assertFalse(marker in text, f"{path.name} mentions {marker}")

    def test_ha13_the_test_tls_material_is_export_ignored(self):
        for name in ("server.key", "server.pem", "test-ca.pem"):
            out = subprocess.run(["git", "check-attr", "export-ignore", f"adapters/adapter_tests/fixtures/tls/{name}"],
                                 capture_output=True, text=True, cwd=REPO).stdout.strip()
            self.assertTrue(out.endswith(": set"), name)


if __name__ == "__main__":
    unittest.main()
