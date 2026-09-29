"""FR-04 (capture part), FR-05, FR-06, FR-07, F-34, F-42: metadata cache behaviour and retention."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from genesis.quota import CacheUnavailable, QuotaLedger, VerifiedCacheStore
from genesis.registry import RegistryConflict

from genesis_adapters import config as cfg
from genesis_adapters import errors as err

from . import static_scan as scan
from . import support as sup
from .support import FixedClock, build_rig, meta_item, odds_item, ok, read_jsonl, scratch_root, status, test_quota_policy

BASE = "2026-10-01T12:00:00.000000Z"
JSON = (("content-type", "application/json"),)
UTC = timezone.utc
TOURNAMENTS = (b'[{"tournamentId":17,"tournamentName":"Premier League","categoryName":"England",'
               b'"tournamentSlug":"premier-league","categorySlug":"england","futureFixtures":0,'
               b'"upcomingFixtures":0,"liveFixtures":0}]')
POLICY = cfg.load_policy(sup.CONFIG / "oddspapi_slice1_policy.json")


def rows_of(rig, record_type):
    return [r for r in read_jsonl(rig.acq_path) if r["record_type"] == record_type]


def quota_rows(rig):
    return [r for r in read_jsonl(rig.root / "quota" / "ledger.jsonl") if r["record_type"].startswith("quota_")]


def at(offset_seconds: int, base: str = BASE) -> str:
    moment = datetime.fromisoformat(base[:-1] + "+00:00") + timedelta(seconds=offset_seconds)
    return moment.isoformat(timespec="microseconds").replace("+00:00", "Z")


def cached_rig(root, script=None, **kw):
    return build_rig(root, capture=True, script=script if script is not None else [ok(TOURNAMENTS, headers=JSON)],
                     clock=FixedClock(BASE, step_micros=1000), **kw)


class CacheBehaviourTests(unittest.TestCase):
    def test_fr05_a_verified_metadata_cache_hit_costs_nothing_and_creates_no_observation(self):
        with scratch_root() as root:
            rig = cached_rig(root)
            first = rig.runner.acquire(meta_item(window="w1"))
            self.assertIsNone(first.failure)
            self.assertEqual(len(rig.gate._index.records()), 1)
            second = rig.runner.acquire(meta_item(window="w2"))
            self.assertEqual((second.outcome, second.failure), ("CACHE_HIT", None))
            self.assertEqual(second.cached_bytes, TOURNAMENTS)
            self.assertEqual(len(rig.transport.calls), 1)                       # nothing was sent
            quota = quota_rows(rig)
            self.assertEqual([r["record_type"] for r in quota], ["quota_billable_call", "quota_verified_cache_hit"])
            self.assertEqual(quota[1]["billable_units"], 0)
            decided = rows_of(rig, "acq_quota_decided")
            self.assertEqual((decided[1]["allowed"], decided[1]["genesis_units_debited"]), (True, 0))
            self.assertEqual(decided[1]["frozen_ledger_reason"], "verified_cache_hit")
            self.assertEqual(decided[1]["cache_entry_id"], quota[1]["cache_entry_id"])
            self.assertEqual(rig.evidence.verify_manifest(), 1)                    # still ONE raw observation
            self.assertEqual(len(rows_of(rig, "acq_sent")), 1)
            self.assertEqual(rig.quota_ledger.usage(at(60))[0], 1)

    def test_fr05_and_f34_expiry_is_a_billable_miss_with_a_recorded_reason(self):
        ttl = POLICY.cache_ttl_seconds["META_TOURNAMENTS"]
        with scratch_root() as root:
            rig = cached_rig(root, script=[ok(TOURNAMENTS, headers=JSON), ok(TOURNAMENTS, headers=JSON)])
            rig.runner.acquire(meta_item(window="w1"))
            rig.clock.set(at(ttl + 1))
            miss = rig.runner.acquire(meta_item(window="w2"))
            self.assertIsNone(miss.failure)
            self.assertEqual(miss.charge.reason, "billable_call_reserved")
            self.assertEqual(len(rig.transport.calls), 2)
            decided = rows_of(rig, "acq_quota_decided")[1]
            self.assertEqual(decided["genesis_units_debited"], 1)
            self.assertEqual(decided["cache_miss_reason"], "CACHE_EXPIRED_OR_INVALIDATED")
            self.assertIsNone(decided["cache_entry_id"])
            debits = [r for r in quota_rows(rig) if r["record_type"] == "quota_billable_call"]
            self.assertEqual(len(debits), 2)                                        # the miss is a Genesis debit
            fresh = rig.runner.acquire(meta_item(window="w3"))                      # the new capture is cached
            self.assertEqual(fresh.outcome, "CACHE_HIT")

    def test_f34_an_invalidated_entry_is_a_miss(self):
        with scratch_root() as root:
            rig = cached_rig(root, script=[ok(TOURNAMENTS, headers=JSON), ok(TOURNAMENTS, headers=JSON)])
            rig.runner.acquire(meta_item(window="w1"))
            entry_id = rig.gate._index.records()[0]["cache_entry_id"]
            rig.cache.invalidate(entry_id, invalidated_at=at(30), reason="test invalidation")
            rig.clock.set(at(60))
            miss = rig.runner.acquire(meta_item(window="w2"))
            self.assertEqual(miss.outcome, "RESPONSE")
            self.assertEqual(rows_of(rig, "acq_quota_decided")[1]["cache_miss_reason"],
                             "CACHE_EXPIRED_OR_INVALIDATED")
            self.assertEqual(len(rig.transport.calls), 2)

    def test_fr06_an_entry_for_a_different_request_hash_is_never_usable(self):
        with scratch_root() as root:
            rig = cached_rig(root, script=[ok(TOURNAMENTS, headers=JSON), ok(TOURNAMENTS, headers=JSON)])
            rig.runner.acquire(meta_item(window="w1"))
            entry_id = rig.gate._index.records()[0]["cache_entry_id"]
            other = meta_item("META_MARKETS", window="w2")
            outcome = rig.runner.acquire(other)                                     # a different request
            self.assertEqual(outcome.charge.reason, "billable_call_reserved")
            self.assertIsNone(outcome.charge.cache_entry_id)
            self.assertEqual(len(rig.transport.calls), 2)
            with self.assertRaises(CacheUnavailable):                              # and the frozen store agrees
                rig.cache.resolve(entry_id, at=at(10), provider_id="oddspapi",
                                  policy_digest=rig.quota_ledger.policy.policy_digest,
                                  provider_request_hash=other.request.provider_request_hash)

    def test_fr04_odds_responses_are_never_cached_and_a_hit_never_creates_an_observation(self):
        with scratch_root() as root:
            rig = cached_rig(root, script=[ok(b"[]", headers=JSON)] * 2)
            rig.runner.acquire(odds_item(window="w1"))
            rig.runner.acquire(odds_item(window="w2"))
            self.assertEqual(rig.gate._index.records(), [])
            self.assertFalse((root / "quota" / "cache" / "objects").exists()
                             and list((root / "quota" / "cache" / "objects").rglob("*")) != [])
            self.assertEqual(len(rig.transport.calls), 2)
            self.assertEqual(rig.evidence.verify_manifest(), 2)

    def test_a_metadata_response_that_fails_any_content_check_is_never_cached(self):
        # the raw bytes are kept as evidence, but only a fully validated response enters the cache,
        # which is retained forever and answers later requests for 0 units
        cases = {"not json": ok(b"{", headers=JSON), "wrong type": ok(b"[]", headers=(("content-type", "text/html"),)),
                 "envelope mismatch": ok(b'[{"tournamentId":"17"}]', headers=JSON),
                 "drift": ok(TOURNAMENTS.replace(b'"liveFixtures":0', b'"liveFixtures":0,"extra":1'), headers=JSON)}
        for label, scripted in cases.items():
            with self.subTest(label), scratch_root() as root:
                rig = cached_rig(root, script=[scripted])
                outcome = rig.runner.acquire(meta_item(window="w1"))
                self.assertIsNotNone(outcome.failure, label)
                self.assertEqual(rig.gate._index.records(), [], label)
                self.assertEqual(rig.evidence.verify_manifest(), 1, label)          # raw evidence retained

    def test_a_skew_quarantined_metadata_response_is_never_cached(self):
        with scratch_root() as root:
            skewed = sup.http_date(at(POLICY.clock_skew_max_seconds + 60))
            rig = cached_rig(root, script=[ok(TOURNAMENTS, headers=JSON + (("date", skewed),))],
                             require_date=True)
            outcome = rig.runner.acquire(meta_item(window="w1"))
            self.assertEqual(outcome.failure, err.AdapterFailure.CLOCK_SKEW)
            self.assertEqual(rig.gate._index.records(), [])

    def test_only_http_200_metadata_is_cached(self):
        with scratch_root() as root:
            rig = cached_rig(root, script=[status(500, b"oops"), status(429, b"slow")])
            rig.runner.acquire(meta_item(window="w1"))
            rig.runner.acquire(meta_item("META_MARKETS", window="w2"))
            self.assertEqual(rig.gate._index.records(), [])


class RetentionTests(unittest.TestCase):
    def prepare(self, root):
        rig = cached_rig(root)
        rig.runner.acquire(meta_item(window="w1"))
        hit = rig.runner.acquire(meta_item(window="w2"))
        self.assertEqual(hit.outcome, "CACHE_HIT")
        entry_id = rig.gate._index.records()[0]["cache_entry_id"]
        entry = rig.cache.get(entry_id)
        return rig, entry

    def reopen(self, rig):
        return QuotaLedger(rig.root / "quota" / "ledger.jsonl", policy=test_quota_policy(),
                           allow_test_policy=True, cache_store=VerifiedCacheStore(rig.root / "quota" / "cache"))

    def assert_halts(self, rig):
        with self.assertRaises(RegistryConflict):
            self.reopen(rig)
        with self.assertRaises(err.AcquisitionHalt) as caught:
            rig.runner.acquire(meta_item(window="w3"))
        self.assertEqual(caught.exception.code, err.AdapterFailure.QUOTA_REPLAY_BROKEN)
        self.assertEqual(rows_of(rig, "acq_halted")[-1]["reason"], "QUOTA_REPLAY_BROKEN")
        entry = read_jsonl(rig.coverage_path)[-1]
        self.assertEqual((entry["status"], entry["reason_codes"], entry["note"]),
                         ("quarantined", ["artifact_tampered"], "QUOTA_REPLAY_BROKEN"))
        self.assertEqual(len(rig.transport.calls), 1)
        again = rig.runner.acquire(meta_item(window="w4"))
        self.assertEqual(again.failure, err.AdapterFailure.CIRCUIT_OPEN)

    def test_fr07_and_f42_altering_a_referenced_cache_object_halts_all_acquisition(self):
        with scratch_root() as root:
            rig, entry = self.prepare(root)
            rig.cache.object_path(entry.artifact_hash).write_bytes(b"altered")
            self.assert_halts(rig)

    def test_fr07_and_f42_deleting_a_referenced_cache_object_halts_all_acquisition(self):
        with scratch_root() as root:
            rig, entry = self.prepare(root)
            rig.cache.object_path(entry.artifact_hash).unlink()
            self.assert_halts(rig)

    def test_fr07_and_f42_altering_the_cache_authority_row_halts_all_acquisition(self):
        with scratch_root() as root:
            rig, _entry = self.prepare(root)
            authority = root / "quota" / "cache" / "cache-authority.jsonl"
            authority.write_bytes(authority.read_bytes().replace(b"verified-cache-entry-v1",
                                                                  b"verified-cache-entry-v9"))
            self.assert_halts(rig)

    def test_fr07_the_adapter_package_has_no_code_path_that_deletes_or_moves_files(self):
        self.assertEqual(scan.scan_all(scan.scan_no_delete), [])
        for source in ("import os\nos.remove('x')\n", "from pathlib import Path\nPath('x').unlink()\n",
                       "import shutil\nshutil.rmtree('x')\n", "import os\nos.rename('a', 'b')\n",
                       "import shutil\nshutil.move('a', 'b')\n", "import os\nos.rmdir('x')\n"):
            self.assertTrue(scan.scan_no_delete("m.py", source), source)
        self.assertEqual(scan.scan_no_delete("m.py", "x = 'a'.replace('b', 'c')\n"), [])


if __name__ == "__main__":
    unittest.main()
