"""REQ-04: the whole fixture pipeline, with the sentinel credential configured and with the keyed URL thrown at
it in exceptions and echoed in a response, leaves no section-7.6 form of the key in any file under the runtime
root, in any log record or in any exception text that reaches the caller."""

from __future__ import annotations

import logging
import unittest

from genesis_adapters import errors as err
from genesis_adapters.config import load_policy
from genesis_adapters.oddspapi import verify
from genesis_adapters.secrets import Secret, SecretScanner

from .pipeline_support import JSON, fixture_body, fixtures_item, meta_item, odds_item, odds_response, open_rt
from .support import CONFIG, SENTINEL_KEY, ok, raises, scratch_root, status

KEYED_URL = "https://api.oddspapi.io/v4/odds-by-tournaments?apiKey=" + SENTINEL_KEY


class Collect(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records: list[str] = []

    def emit(self, record):
        self.records.append(self.format(record))


def leaky_exception() -> OSError:
    exc = OSError(104, KEYED_URL, KEYED_URL)
    exc.add_note("while fetching " + KEYED_URL)
    exc.__cause__ = ValueError(KEYED_URL)
    exc.url = KEYED_URL
    return exc


class RuntimeSecretTests(unittest.TestCase):
    def test_req04_no_form_of_the_key_survives_a_full_pipeline_run(self):
        secret = Secret(SENTINEL_KEY)
        scanner = SecretScanner(secret, policy=load_policy(CONFIG / "oddspapi_slice1_policy.json"))
        handler = Collect()
        root_logger = logging.getLogger()
        previous_level = root_logger.level
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.DEBUG)
        texts: list[str] = []
        try:
            with scratch_root() as root:
                rt = open_rt(root, secret=secret, script=[
                    ok(fixture_body("tournaments.json"), headers=JSON), ok(fixture_body("fixtures.json"), headers=JSON),
                    odds_response(), raises(leaky_exception()),
                    status(500, b"upstream said " + KEYED_URL.encode()),
                    ok(b'{"echo": "' + SENTINEL_KEY.encode() + b'"}', headers=JSON)])
                results = [rt.acquire(meta_item()), rt.acquire(fixtures_item()), rt.acquire(odds_item("w1"))]
                rt.clock.advance(seconds=600)
                results.append(rt.acquire(odds_item("w2")))                  # the transport raised the keyed URL
                self.assertEqual(results[-1].outcome.failure, err.AdapterFailure.NO_RESPONSE)
                with self.assertRaises(err.AcquisitionHalt) as first_halt:  # a 5xx body echoing the key
                    rt.acquire(odds_item("w3"))
                self.assertEqual(first_halt.exception.code, err.AdapterFailure.SECRET_ECHO)
                texts += [str(first_halt.exception), repr(first_halt.exception), repr(first_halt.exception.args)]
                refused = rt.acquire(odds_item("w4"))                        # halted: nothing more is sent
                self.assertEqual(refused.outcome.failure, err.AdapterFailure.CIRCUIT_OPEN)
                for result in results:
                    texts += [repr(result.outcome), repr(result.emitted)]
                self.assertEqual(verify.scan_runtime_for_secret(root, secret), ())
                self.assertEqual(len(rt.runner.transport.calls), 5)
                self.assertEqual(rt.verify_all(), 12)
        finally:
            root_logger.removeHandler(handler)
            root_logger.setLevel(previous_level)
        for text in texts + handler.records:
            self.assertFalse(scanner.scan(text.encode("utf-8", "replace")).hit, text[:120])


if __name__ == "__main__":
    unittest.main()
