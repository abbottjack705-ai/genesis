"""R-1 (hostile audit F-01, oracle CR-08; design 7.6 item 3): "the scanner still guards the sanitized record".

A sanitized transport error is only ``{"class": <exception class name>, "errno": <int or None>}``, but a class
name is text, and text can carry the key. Every sanitized record is therefore scanned for every section-7.6 form
BEFORE it is persisted; a record that hits keeps its ``acq_completed`` row (the attempt still happened) but its
content is replaced by a fixed placeholder class and no errno. Covered here for the three places such a record
comes from: a transport that raises (the runner's ``sanitize_exception``), a transport that reports a sanitized
error, and the real HTTPS transport's own boundary. TX-01 repeats the check end to end in a subprocess.
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from genesis_adapters.oddspapi import acquisition as acq
from genesis_adapters.oddspapi import raw_capture
from genesis_adapters.oddspapi import transport_http as th
from genesis_adapters.oddspapi import verify
from genesis_adapters.secrets import Secret, SecretScanner

from . import parser_support as ps
from .pipeline_support import odds_item, open_rt
from .support import SENTINEL_KEY, no_response, raises, read_jsonl, scratch_root

PLACEHOLDER = {"class": "REDACTED_EXCEPTION_CLASS", "errno": None}
SCANNER = SecretScanner(Secret(SENTINEL_KEY), policy=ps.POLICY)


def named(name: str) -> type:
    """An exception class whose ``__name__`` is ``name`` (``type()`` accepts any text as a class name)."""

    return type(name, (OSError,), {})


# Class names carrying the key in different section-7.6 forms; each must be caught.
KEY_FORMS = {
    "identifier": "Err_" + SENTINEL_KEY.replace("-", "_"),
    "verbatim": SENTINEL_KEY,
    "lower case": "Err_" + SENTINEL_KEY.lower(),
    "hex": "Err_" + SENTINEL_KEY.encode().hex(),
    "fragment": "Err_" + SENTINEL_KEY[-16:],
    "percent-encoded": "Err_" + "".join(f"%{byte:02X}" for byte in SENTINEL_KEY.encode()),
}


def completed_rows(root) -> list[dict]:
    return [row for row in read_jsonl(root / "acquisition.jsonl") if row["record_type"] == "acq_completed"]


def shown(value) -> str:
    """A value for a failure message: withheld when it carries a form of the test sentinel, so no transcript of
    these tests (RED or otherwise) ever holds one."""

    text = json.dumps(value)
    return "<withheld: carries a form of the test sentinel>" if SCANNER.scan(text.encode()).hit else text


class Boom:
    """A fault-injecting connection for the real HTTPS transport: ``open`` raises ``exc_type``."""

    exc_type: type = OSError

    def __init__(self, *args):
        pass

    def open(self, timeout):
        raise self.exc_type()

    def close(self):
        pass


class SanitizedRecordScanTests(unittest.TestCase):
    def assert_redacted(self, root, outcome, errno=None):
        rows = completed_rows(root)
        self.assertEqual(len(rows), 1)                                        # the attempt is still recorded
        self.assertEqual((rows[0]["outcome"], rows[0]["failure"]), ("NO_RESPONSE", "NO_RESPONSE"))
        if rows[0]["sanitized_error"] != dict(PLACEHOLDER, errno=errno):
            self.fail("stored sanitized_error " + shown(rows[0]["sanitized_error"]) + " is not the placeholder")
        if outcome.detail != PLACEHOLDER["class"]:                           # what callers see is clean too
            self.fail("outcome detail " + shown(outcome.detail) + " is not the placeholder")
        self.assertEqual(verify.scan_runtime_for_secret(root, Secret(SENTINEL_KEY)), ())

    def test_r1_a_raising_transport_with_a_key_named_class_is_redacted_before_persistence(self):
        for label, name in KEY_FORMS.items():
            with self.subTest(label), scratch_root() as root:
                self.assertTrue(SCANNER.scan(name.encode()).hit, label)       # the form really is a key form
                rt = open_rt(root, script=[raises(named(name)())], secret=Secret(SENTINEL_KEY))
                self.assert_redacted(root, rt.runner.acquire(odds_item()))

    def test_r1_a_transport_reported_sanitized_error_is_scanned_too(self):
        for label, name in KEY_FORMS.items():
            with self.subTest(label), scratch_root() as root:
                rt = open_rt(root, script=[no_response(error_class=name, errno=104)], secret=Secret(SENTINEL_KEY))
                # HA-01 (controlling audit): only the tainted label is replaced; the integer errno keeps its meaning
                self.assert_redacted(root, rt.runner.acquire(odds_item()), errno=104)

    def test_r1_the_real_https_transport_boundary_is_scanned_too(self):
        for label in ("identifier", "verbatim"):
            with self.subTest(label), scratch_root() as root:
                faulty = type("Faulty", (Boom,), {"exc_type": named(KEY_FORMS[label])})
                transport = th.HttpsTransport(Secret(SENTINEL_KEY), credential_param="apiKey", policy=ps.POLICY,
                                              connection_factory=faulty)
                rt = open_rt(root, transport=transport, secret=Secret(SENTINEL_KEY))
                self.assert_redacted(root, rt.runner.acquire(odds_item()))

    def test_r1_clean_records_are_kept_exactly(self):
        cases = [(raises(TimeoutError()), {"class": "TimeoutError", "errno": None}),
                 (raises(ConnectionResetError(104, "reset")), {"class": "ConnectionResetError", "errno": 104}),
                 (no_response(error_class="SSLError", errno=1), {"class": "SSLError", "errno": 1})]
        for step, stored in cases:
            with self.subTest(stored["class"]), scratch_root() as root:
                rt = open_rt(root, script=[step], secret=Secret(SENTINEL_KEY))
                outcome = rt.runner.acquire(odds_item())
                self.assertEqual(completed_rows(root)[0]["sanitized_error"], stored)
                self.assertEqual(outcome.detail, stored["class"])

    def test_r1_without_a_configured_key_there_is_nothing_to_scan_for(self):
        # fixture mode: no credential exists, so no form of it can occur; the record is kept as sanitized
        with scratch_root() as root:
            rt = open_rt(root, script=[raises(named("Leaky")())])
            rt.runner.acquire(odds_item())
            self.assertEqual(completed_rows(root)[0]["sanitized_error"], {"class": "Leaky", "errno": None})

    def test_r1_the_record_passes_through_the_scanner_before_it_is_appended(self):
        events: list[tuple[str, object]] = []
        real_hit = raw_capture.RawCapture.hits_secret
        real_append = acq.AcquisitionLedger.append

        def spy_hit(capture, data):
            events.append(("scanned", bytes(data)))
            return real_hit(capture, data)

        def spy_append(ledger, kind, **fields):
            events.append(("appended", kind))
            return real_append(ledger, kind, **fields)

        name = KEY_FORMS["identifier"]
        with scratch_root() as root, mock.patch.object(raw_capture.RawCapture, "hits_secret", spy_hit), \
                mock.patch.object(acq.AcquisitionLedger, "append", spy_append):
            rt = open_rt(root, script=[raises(named(name)())], secret=Secret(SENTINEL_KEY))
            rt.runner.acquire(odds_item())
        scans = [i for i, (what, data) in enumerate(events) if what == "scanned" and name.encode() in data]
        completed = [i for i, (what, kind) in enumerate(events) if what == "appended" and kind == "acq_completed"]
        self.assertGreaterEqual(len(scans), 1)                                # the record itself was scanned
        self.assertEqual(len(completed), 1)
        self.assertLess(max(scans), completed[0])                             # ... every scan before it was persisted
        scanned = json.loads(events[scans[0]][1])                              # the first scan is the whole record
        self.assertTrue(scanned == {"class": name, "errno": None}, "the scanned bytes are not the sanitized record")


if __name__ == "__main__":
    unittest.main()
