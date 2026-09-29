"""Q-03 (gate level), Q-10 and the gate's cache rules (FR-04 gate part)."""

from __future__ import annotations

import inspect
import unittest

from genesis.quota import BudgetClass, QuotaLedger, QuotaPolicy, VerifiedCacheStore, load_quota_policy

from genesis_adapters.oddspapi import endpoints as ep
from genesis_adapters.oddspapi import quota_gate
from genesis_adapters.config import load_policy

from .support import CONFIG, REPO, scratch_root, test_quota_policy

POLICY = load_policy(CONFIG / "oddspapi_slice1_policy.json")
SPECS = ep.load_endpoints(CONFIG / "oddspapi_v4_endpoints.json", POLICY)
ACTIVE_DIGEST = "3cdf9e3e52ec49a6a645ed1f690fe03a2ff3605527c0fb14dd51fab42389a0f9"


def request_for(role="ODDS"):
    if role == "ODDS":
        return ep.build_request(SPECS["ODDS"], bookmaker=["pinnacle"], tournamentIds=[17, 8],
                                oddsFormat="decimal")
    return ep.build_request(SPECS[role], **({"sportId": 10} if role == "META_TOURNAMENTS" else {}))


class Spy:
    def __init__(self, inner):
        self.inner = inner
        self.calls = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        return self.inner.request(**kwargs)

    def __getattr__(self, name):
        return getattr(self.inner, name)


class GateTests(unittest.TestCase):
    def make(self, root, policy=None):
        cache = VerifiedCacheStore(root / "quota" / "cache")
        ledger = QuotaLedger(root / "quota" / "ledger.jsonl", policy=policy or test_quota_policy(),
                             allow_test_policy=True, cache_store=cache)
        spy = Spy(ledger)
        gate = quota_gate.QuotaGate(spy, cache, cache_index_path=root / "quota" / "cache-index.jsonl")
        return gate, spy, ledger, cache

    def test_q03_the_221st_normal_unit_is_blocked_and_reserve_is_never_requested(self):
        with scratch_root() as root:
            gate, spy, ledger, _ = self.make(root, test_quota_policy(daily=250))
            request = request_for()
            charges = []
            for index in range(221):
                charges.append(gate.reserve(request=request, request_id=f"oddspapi-attempt:{index:064x}",
                                            occurred_at=f"2026-10-15T12:00:{index // 100:02d}.{index % 100:06d}Z",
                                            billable_units=1))
            self.assertTrue(all(c.allowed for c in charges[:220]))
            self.assertFalse(charges[220].allowed)
            self.assertEqual(charges[220].reason, "normal_monthly_budget_exhausted")
            self.assertEqual(len(spy.calls), 221)
            for call in spy.calls:
                self.assertIs(call["budget_class"], BudgetClass.NORMAL)
                self.assertIsNone(call["authorization_id"])
            rows = ledger.log.records()
            self.assertFalse([r for r in rows if r.get("budget_class") == "reserve"])
            self.assertFalse([r for r in rows if "authorization" in r.get("record_type", "")])
            self.assertEqual(ledger.usage("2026-10-15T13:00:00.000000Z")[1], 220)

    def test_reserve_units_are_never_used_even_when_the_normal_budget_is_exhausted(self):
        with scratch_root() as root:
            gate, _spy, ledger, _ = self.make(root, test_quota_policy(daily=50, normal=3, reserve=2, allowance=5))
            request = request_for()
            outcomes = [gate.reserve(request=request, request_id=f"oddspapi-attempt:{i:064x}",
                                     occurred_at=f"2026-10-1{i}T12:00:00.000000Z", billable_units=1).allowed
                        for i in range(1, 6)]
            self.assertEqual(outcomes, [True, True, True, False, False])
            self.assertEqual(ledger.usage("2026-10-31T00:00:00.000000Z")[1], 3)

    def test_q10_the_operational_ledger_loads_the_frozen_active_policy_unchanged(self):
        policy = load_quota_policy(REPO / "config" / "oddspapi_quota_policy_v2.json")
        self.assertEqual(policy.policy_digest, ACTIVE_DIGEST)
        with scratch_root() as root:
            ledger, cache = quota_gate.open_operational_ledger(root)
            self.assertEqual(ledger.policy.policy_digest, ACTIVE_DIGEST)
            self.assertFalse(ledger.policy.test_only)
            self.assertTrue(ledger.policy.approved_active)
            self.assertEqual((ledger.policy.provider_monthly_allowance, ledger.policy.normal_monthly_budget,
                              ledger.policy.reserve_units, ledger.policy.daily_billable_budget),
                             (250, 220, 30, 7))
            self.assertIs(ledger.cache_store, cache)
            self.assertEqual(ledger.policy.provider_id, "oddspapi")
        source = inspect.getsource(quota_gate)
        self.assertNotIn("from_active_config", source)        # it attaches no cache store
        self.assertNotIn("test_fixture", source)
        fixture = test_quota_policy()
        self.assertTrue(fixture.test_only)
        self.assertNotEqual(fixture.policy_digest, ACTIVE_DIGEST)
        with self.assertRaises(Exception):
            QuotaLedger(REPO / "runtime" / "never-created.jsonl", policy=fixture)   # test policy needs opt-in

    def test_odds_are_never_cached_and_never_looked_up(self):
        with scratch_root() as root:
            gate, spy, _ledger, _cache = self.make(root)
            with self.assertRaises(quota_gate.CachePolicyError):
                gate.publish_cache(request_for("ODDS"), b"[]", captured_at="2026-10-01T12:00:00.000000Z",
                                   ttl_seconds=60)
            gate.reserve(request=request_for("ODDS"), request_id="oddspapi-attempt:" + "1" * 64,
                         occurred_at="2026-10-01T12:00:00.000000Z", billable_units=1)
            self.assertIsNone(spy.calls[0]["cache"])
            self.assertEqual(len(spy.calls[0]["provider_request_hash"]), 64)

    def test_meta_cache_hit_is_free_and_returns_the_original_bytes(self):
        with scratch_root() as root:
            gate, spy, ledger, cache = self.make(root)
            request = request_for("META_TOURNAMENTS")
            first = gate.reserve(request=request, request_id="oddspapi-attempt:" + "2" * 64,
                                 occurred_at="2026-10-01T12:00:00.000000Z", billable_units=1)
            self.assertTrue(first.allowed)
            self.assertEqual(first.reason, "billable_call_reserved")
            gate.publish_cache(request, b'[{"tournamentId": 17}]', captured_at="2026-10-01T12:00:00.500000Z",
                               ttl_seconds=3600)
            second = gate.reserve(request=request, request_id="oddspapi-attempt:" + "3" * 64,
                                  occurred_at="2026-10-01T12:10:00.000000Z", billable_units=1)
            self.assertEqual((second.allowed, second.reason, second.billable_units),
                             (True, "verified_cache_hit", 0))
            self.assertIsNotNone(second.cache_entry_id)
            self.assertEqual(gate.cached_bytes(second, request), b'[{"tournamentId": 17}]')
            self.assertEqual(ledger.usage("2026-10-01T13:00:00.000000Z")[0], 1)
            expired = gate.reserve(request=request, request_id="oddspapi-attempt:" + "4" * 64,
                                   occurred_at="2026-10-01T14:00:00.000000Z", billable_units=1)
            self.assertEqual(expired.reason, "billable_call_reserved")
            self.assertIsNotNone(expired.cache_miss_reason)
            self.assertIsNone(gate.cached_bytes(expired, request))

    def test_headroom_reflects_the_frozen_budgets(self):
        with scratch_root() as root:
            gate, _spy, _ledger, _ = self.make(root, test_quota_policy(daily=2))
            request = request_for()
            self.assertTrue(gate.headroom("2026-10-01T12:00:00.000000Z", 2))
            self.assertFalse(gate.headroom("2026-10-01T12:00:00.000000Z", 3))
            gate.reserve(request=request, request_id="oddspapi-attempt:" + "5" * 64,
                         occurred_at="2026-10-01T12:00:00.000000Z", billable_units=1)
            self.assertTrue(gate.headroom("2026-10-01T12:00:01.000000Z", 1))
            self.assertFalse(gate.headroom("2026-10-01T12:00:01.000000Z", 2))
            self.assertTrue(gate.headroom("2026-10-02T12:00:01.000000Z", 2))

    def test_find_request_reads_the_frozen_ledger_publicly(self):
        with scratch_root() as root:
            gate, _spy, _ledger, _ = self.make(root)
            rid = "oddspapi-attempt:" + "6" * 64
            self.assertIsNone(gate.find_request(rid))
            gate.reserve(request=request_for(), request_id=rid, occurred_at="2026-10-01T12:00:00.000000Z",
                         billable_units=1)
            row = gate.find_request(rid)
            self.assertEqual(row["request_id"], rid)
            self.assertEqual(row["record_type"], "quota_billable_call")


if __name__ == "__main__":
    unittest.main()
