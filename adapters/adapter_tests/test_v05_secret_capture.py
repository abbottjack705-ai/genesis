"""REQ-07, SEC-02, SEC-03, SEC-04, F-11, F-11b: credential safety dominates raw retention."""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import random
import unittest
import zlib

from genesis_adapters import config as cfg
from genesis_adapters import errors as err
from genesis_adapters import secrets as sec
from genesis_adapters.oddspapi import verify

from . import support as sup
from .support import SENTINEL_KEY, build_rig, meta_item, odds_item, ok, read_jsonl, scratch_root

JSON = (("content-type", "application/json"),)
KEY = SENTINEL_KEY.encode()
SECRET = sec.Secret(SENTINEL_KEY)
POLICY = cfg.load_policy(sup.CONFIG / "oddspapi_slice1_policy.json")


def rows_of(rig, record_type):
    return [r for r in read_jsonl(rig.acq_path) if r["record_type"] == record_type]


def coverage(rig):
    return read_jsonl(rig.coverage_path)


def all_file_bytes(root):
    for path in sorted(root.rglob("*")):
        if path.is_file():
            yield path, path.read_bytes()


def rig_for(root, script, **kw):
    return build_rig(root, capture=True, secret=SECRET, script=script, **kw)


def no_raw_evidence(test, rig):
    objects = list((rig.root / "evidence" / "objects").rglob("*")) if (rig.root / "evidence").exists() else []
    test.assertEqual([p for p in objects if p.is_file()], [])
    manifest = rig.root / "evidence" / "manifests" / "evidence.jsonl"
    test.assertTrue(not manifest.exists() or manifest.read_bytes() == b"")


class SecretEchoTests(unittest.TestCase):
    def assert_secret_echo(self, rig, body_for_hash: bytes | None):
        self.assertEqual(rig.blocked, ["SECRET_ECHO"])
        no_raw_evidence(self, rig)
        done = rows_of(rig, "acq_completed")[0]
        self.assertIsNone(done["raw_observation_id"])
        self.assertEqual(done["failure"], "SECRET_ECHO")
        self.assertEqual(rows_of(rig, "acq_halted")[-1]["reason"], "SECRET_ECHO")
        self.assertEqual(len(rows_of(rig, "acq_quarantined")), 1)
        entry = coverage(rig)[-1]
        self.assertEqual((entry["status"], entry["reason_codes"], entry["note"]),
                         ("quarantined", ["artifact_tampered"], "SECRET_ECHO"))
        self.assertEqual(verify.scan_runtime_for_secret(rig.root, SECRET, policy=POLICY), ())
        if body_for_hash is not None:                    # no body hash in any form, anywhere
            digest = hashlib.sha256(body_for_hash).hexdigest().encode()
            for path, data in all_file_bytes(rig.root):
                self.assertNotIn(digest, data, path.name)
        quarantine = read_jsonl(rig.root / "quarantine.jsonl")
        self.assertEqual(len(quarantine), 1)
        return quarantine[0]

    def test_req07_and_f11_a_body_echoing_the_key_leaves_no_body_bytes_hash_or_derivative(self):
        body = b'[{"echo":"' + KEY + b'"}]'
        with scratch_root() as root:
            rig = rig_for(root, [ok(body, headers=JSON)])
            with self.assertRaises(err.AcquisitionHalt) as caught:
                rig.runner.acquire(odds_item())
            self.assertEqual(caught.exception.code, err.AdapterFailure.SECRET_ECHO)
            row = self.assert_secret_echo(rig, body)
            chain = {"previous_hash", "sequence", "record_hash", "record_type", "schema_version"}
            self.assertEqual(set(row) - chain, {"quarantine_id", "acquisition_id", "provider_request_hash",
                                                "T1", "http_status", "byte_length", "content_type",
                                                "header_names", "detection_classes", "reason"})
            self.assertEqual((row["reason"], row["http_status"], row["byte_length"], row["content_type"]),
                             ("SECRET_ECHO", 200, len(body), "application/json"))
            self.assertIn("BODY_RAW", row["detection_classes"])
            self.assertEqual(row["header_names"], ["content-type"])
            # the halt is durable: nothing more is sent until an operator resets it
            again = rig.runner.acquire(odds_item(window="w2"))
            self.assertEqual(again.failure, err.AdapterFailure.CIRCUIT_OPEN)
            self.assertEqual(len(rig.transport.calls), 1)

    def test_f11_every_documented_form_in_the_body_is_caught(self):
        raw = KEY
        forms = {
            "utf16le": raw.decode().encode("utf-16-le"), "utf16be": raw.decode().encode("utf-16-be"),
            "utf32le": raw.decode().encode("utf-32-le"), "base64": base64.b64encode(b"zz" + raw),
            "hex": raw.hex().encode(), "json escapes": "".join(f"\\u{ord(c):04x}" for c in SENTINEL_KEY).encode(),
            "fragment": SENTINEL_KEY[3:3 + 13].encode(), "percent": b"%47%45%4e%45%53%49%53-SENTINEL-KEY-0123456789abcdef",
        }
        for label, form in forms.items():
            with self.subTest(label), scratch_root() as root:
                body = b'[{"echo":"' + form + b'"}]'
                rig = rig_for(root, [ok(body, headers=JSON)])
                with self.assertRaises(err.AcquisitionHalt):
                    rig.runner.acquire(odds_item())
                self.assert_secret_echo(rig, body)

    def test_sec02_the_key_in_any_header_name_or_value_is_caught_even_outside_the_allowlist(self):
        cases = {
            "value outside allowlist": (("x-custom-echo", SENTINEL_KEY),),
            "value in allowlisted header": (("content-type", "application/json; note=" + SENTINEL_KEY),),
            "name": ((SENTINEL_KEY.lower(), "1"),),
            "encoded value": (("x-b64", base64.b64encode(KEY).decode()),),
        }
        for label, extra in cases.items():
            with self.subTest(label), scratch_root() as root:
                headers = tuple(h for h in JSON if h[0] not in {e[0] for e in extra}) + extra
                rig = rig_for(root, [ok(b"[]", headers=headers)])
                with self.assertRaises(err.AcquisitionHalt):
                    rig.runner.acquire(odds_item())
                row = self.assert_secret_echo(rig, b"[]")
                self.assertTrue({"HEADER_NAME", "HEADER_VALUE"} & set(row["detection_classes"]), label)

    def test_sec04_quarantine_metadata_is_itself_scanned_and_dirty_fields_are_dropped(self):
        headers = (("content-type", "application/json; x=" + SENTINEL_KEY), ("x-request-id", "abc"),
                   (SENTINEL_KEY.lower(), "1"))
        with scratch_root() as root:
            rig = rig_for(root, [ok(b"[]", headers=headers)])
            with self.assertRaises(err.AcquisitionHalt):
                rig.runner.acquire(odds_item())
            row = self.assert_secret_echo(rig, b"[]")
            self.assertIsNone(row["content_type"])                     # a dirty value is dropped
            self.assertEqual(row["header_names"], ["content-type", "x-request-id"])   # dirty name dropped
            for path, data in all_file_bytes(root):
                self.assertNotIn(KEY, data, path.name)
                self.assertNotIn(KEY.lower(), data.lower(), path.name)

    def test_a_clean_response_with_a_secret_configured_is_stored_normally(self):
        with scratch_root() as root:
            rig = rig_for(root, [ok(b"[]", headers=JSON + (("x-request-id", "abc"),))])
            outcome = rig.runner.acquire(odds_item())
            self.assertIsNone(outcome.failure)
            self.assertEqual(rig.blocked, [])
            self.assertFalse((root / "quarantine.jsonl").exists())
            self.assertIsNotNone(rows_of(rig, "acq_completed")[0]["raw_observation_id"])


class EncodedBodyTests(unittest.TestCase):
    def enc(self, name, body=None):
        return (("content-type", "application/json"), ("content-encoding", name))

    def test_sec03_secret_in_the_decoded_gzip_body_is_a_secret_echo(self):
        wire = gzip.compress(b'["' + KEY + b'"]')
        self.assertNotIn(KEY, wire)
        with scratch_root() as root:
            rig = rig_for(root, [ok(wire, headers=self.enc("gzip"))])
            with self.assertRaises(err.AcquisitionHalt):
                rig.runner.acquire(odds_item())
            no_raw_evidence(self, rig)
            self.assertIn("BODY_RAW", read_jsonl(root / "quarantine.jsonl")[0]["detection_classes"])
            self.assertEqual(verify.scan_runtime_for_secret(root, SECRET, policy=POLICY), ())

    def test_sec03_secret_only_in_the_wire_bytes_is_still_a_secret_echo(self):
        wire = gzip.compress(b"[]") + KEY                                   # trailing bytes outside the stream
        with scratch_root() as root:
            rig = rig_for(root, [ok(wire, headers=self.enc("gzip"))])
            with self.assertRaises(err.AcquisitionHalt):
                rig.runner.acquire(odds_item())
            no_raw_evidence(self, rig)
            self.assertEqual(verify.scan_runtime_for_secret(root, SECRET, policy=POLICY), ())

    def test_f11b_uninspectable_bodies_are_not_persisted_and_do_not_halt(self):
        zeros = gzip.compress(b"0" * 200000)
        self.assertLess(len(zeros), 2000)
        cases = {
            "unsupported encoding": ok(b"[]", headers=self.enc("br")),
            "nested encodings": ok(gzip.compress(gzip.compress(b"[]")), headers=self.enc("gzip, gzip")),
            "corrupt gzip": ok(b"\x1f\x8b\x08corrupt", headers=self.enc("gzip")),
            "over the decompression ratio": ok(zeros, headers=self.enc("gzip")),
            "unknown token": ok(b"[]", headers=self.enc("compress")),
        }
        for label, scripted in cases.items():
            with self.subTest(label), scratch_root() as root:
                rig = rig_for(root, [scripted, ok(b"[]", headers=JSON)])
                outcome = rig.runner.acquire(odds_item(window="w1"))
                self.assertEqual(outcome.failure, err.AdapterFailure.UNINSPECTABLE_BODY, label)
                no_raw_evidence(self, rig)
                done = rows_of(rig, "acq_completed")[0]
                self.assertIsNone(done["raw_observation_id"])
                self.assertEqual(done["failure"], "UNINSPECTABLE_BODY")
                entry = coverage(rig)[-1]
                self.assertEqual((entry["status"], entry["reason_codes"], entry["note"]),
                                 ("quarantined", ["schema_rejected"], "UNINSPECTABLE_BODY"))
                quarantine = read_jsonl(root / "quarantine.jsonl")
                self.assertEqual([q["reason"] for q in quarantine], ["UNINSPECTABLE_BODY"])
                self.assertEqual(quarantine[0]["detection_classes"], [])
                self.assertEqual(rows_of(rig, "acq_halted"), [])            # F-11b is not a halt
                self.assertEqual(rig.blocked, [])
                self.assertIsNone(rig.runner.acquire(odds_item(window="w2")).failure)

    def test_f11b_decoded_size_bound(self):
        body = json.dumps(["x" * 5000]).encode()
        policy = cfg.parse_policy(dict(json.loads((sup.CONFIG / "oddspapi_slice1_policy.json").read_text()),
                                       max_response_bytes=4096, max_decompression_ratio=10 ** 6))
        wire = zlib.compress(body)
        self.assertLess(len(wire), 4096)
        with scratch_root() as root:
            rig = rig_for(root, [ok(wire, headers=self.enc("deflate"))], policy=policy)
            outcome = rig.runner.acquire(odds_item())
            self.assertEqual(outcome.failure, err.AdapterFailure.UNINSPECTABLE_BODY)
            no_raw_evidence(self, rig)

    def test_clean_gzip_and_deflate_are_decoded_and_the_decoded_bytes_are_stored(self):
        for name, compress in (("gzip", gzip.compress), ("deflate", zlib.compress), ("identity", lambda b: b)):
            with self.subTest(name), scratch_root() as root:
                rig = rig_for(root, [ok(compress(b"[ ]"), headers=self.enc(name))])
                outcome = rig.runner.acquire(odds_item())
                self.assertIsNone(outcome.failure, name)
                done = rows_of(rig, "acq_completed")[0]
                obs = rig.evidence.get_observation(done["raw_observation_id"])
                self.assertEqual(rig.evidence.get_bytes(obs.artifact_hash), b"[ ]")
                self.assertEqual(obs.artifact_hash, hashlib.sha256(b"[ ]").hexdigest())
                self.assertEqual(done["content_encoding"], None if name == "identity" else name)
                self.assertEqual(outcome.parsed, [])

    def test_unrelated_random_bytes_do_not_trigger_the_detector(self):
        rng = random.Random(20260928)
        for index in range(20):
            noise = rng.randbytes(64).hex().encode()
            data = (b'[{"tournamentId":17,"tournamentName":"' + noise + b'","categoryName":"England",'
                    b'"tournamentSlug":"premier-league","categorySlug":"england","futureFixtures":0,'
                    b'"upcomingFixtures":0,"liveFixtures":0}]')
            with scratch_root() as root:
                rig = rig_for(root, [ok(data, headers=JSON)])
                outcome = rig.runner.acquire(meta_item("META_TOURNAMENTS"))
                self.assertIsNone(outcome.failure, index)
                self.assertEqual(read_jsonl(root / "quarantine.jsonl"), [])


class LiveScannerRequirementTests(unittest.TestCase):
    def test_f04_live_mode_without_a_secret_scanner_halts_before_any_quota_call(self):
        from genesis_adapters.clock import SystemUtcClock
        from genesis_adapters.oddspapi.quota_gate import open_operational_ledger

        class Gate:
            def require_gate(self, gate, *, at, **pins):
                return {}

        for capture in (False, True):                      # no capture at all / capture without a secret
            with self.subTest(capture=capture), scratch_root() as root:
                ledger, cache = open_operational_ledger(root)
                rig = build_rig(root, live=True, clock=SystemUtcClock(drift_max_ms=1000), quota_ledger=ledger,
                                cache=cache, authority=Gate(), capture=capture, secret=None)
                with self.assertRaises(err.AcquisitionHalt) as caught:
                    rig.runner.acquire(odds_item())
                self.assertEqual(caught.exception.code, err.AdapterFailure.CREDENTIAL_MISSING)
                self.assertEqual(rig.transport.calls, [])
                quota = [r for r in read_jsonl(root / "quota" / "ledger.jsonl")
                         if r["record_type"].startswith("quota_")]
                self.assertEqual(quota, [])
                self.assertEqual(rows_of(rig, "acq_halted")[-1]["reason"], "CREDENTIAL_MISSING")

    def test_gzip_with_trailing_or_second_member_data_is_uninspectable(self):
        member = gzip.compress(b"[ ]")
        for label, wire in (("trailing garbage", member + b"garbage"), ("second member", member + member)):
            with self.subTest(label), scratch_root() as root:
                rig = rig_for(root, [ok(wire, headers=JSON + (("content-encoding", "gzip"),))])
                outcome = rig.runner.acquire(odds_item())
                self.assertEqual(outcome.failure, err.AdapterFailure.UNINSPECTABLE_BODY)
                no_raw_evidence(self, rig)


if __name__ == "__main__":
    unittest.main()
