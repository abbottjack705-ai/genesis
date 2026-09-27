"""Astra A6: cache use must resolve immutable authority, not caller truth."""

from __future__ import annotations

import unittest
from threading import Event, Thread
from pathlib import Path

import genesis.quota as quota_module
from genesis.quota import BudgetClass, CachedData, QuotaLedger, load_quota_policy
from genesis.registry import AppendOnlyJsonl, RegistryConflict

from ._support import scratch_directory


ACTIVE_POLICY_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "oddspapi_quota_policy_v2.json"
)


def digest(character: str) -> str:
    return character * 64


NOW = "2026-01-01T00:30:00Z"
REQUEST_HASH = digest("b")
VerifiedCacheStore = getattr(quota_module, "VerifiedCacheStore", None)
CacheReference = getattr(quota_module, "CacheReference", None)


def exhaust_daily(ledger: QuotaLedger) -> None:
    for index in range(7):
        decision = ledger.request(
            request_id=f"bill-{index}", occurred_at=f"2026-01-01T00:0{index}:00Z",
        )
        if not decision.allowed:
            raise AssertionError(decision.reason)


class AstraCacheAuthorityTests(unittest.TestCase):
    def authority(self, root, policy):
        self.assertIsNotNone(VerifiedCacheStore, "no immutable cache authority exists")
        self.assertIsNotNone(CacheReference, "no authority reference type exists")
        return VerifiedCacheStore(root / "cache-authority")

    def publish(self, store, policy, *, payload=b'{"price":"2.0"}', **changes):
        fields = {
            "cache_key": "market-1",
            "provider_request_hash": REQUEST_HASH,
            "provider_id": policy.provider_id,
            "quota_policy_digest": policy.policy_digest,
            "captured_at": "2026-01-01T00:00:00Z",
            "expires_at": "2026-01-01T01:00:00Z",
        }
        fields.update(changes)
        return store.publish(payload, **fields)

    def test_caller_verified_flag_cannot_authorize_nonexistent_cache(self):
        with scratch_directory() as root:
            policy = load_quota_policy(ACTIVE_POLICY_PATH)
            ledger = QuotaLedger(root / "quota.jsonl", policy=policy)
            exhaust_daily(ledger)
            invented = CachedData(
                "invented", digest("a"), policy.provider_id, policy.policy_digest,
                "2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z", True,
            )
            decision = ledger.request(
                request_id="invented", occurred_at=NOW, cache=invented,
            )
            self.assertFalse(decision.allowed, "caller verified=True bypassed quota")
            self.assertNotEqual(decision.reason, "verified_cache_hit")
            self.assertEqual(ledger.usage(NOW), (7, 7))

    def test_genuine_resolved_object_is_fresh_nonbillable_and_restarts(self):
        with scratch_directory() as root:
            policy = load_quota_policy(ACTIVE_POLICY_PATH)
            store = self.authority(root, policy)
            reference = self.publish(store, policy)
            ledger = QuotaLedger(root / "quota.jsonl", policy=policy, cache_store=store)
            exhaust_daily(ledger)
            first = ledger.request(
                request_id="cache-hit", occurred_at=NOW, cache=reference,
                provider_request_hash=REQUEST_HASH,
            )
            self.assertTrue(first.allowed)
            self.assertEqual((first.reason, first.billable_units), ("verified_cache_hit", 0))
            self.assertEqual(ledger.usage(NOW), (7, 7))
            restarted = QuotaLedger(root / "quota.jsonl", policy=policy, cache_store=store)
            self.assertEqual(
                restarted.request(
                    request_id="cache-hit", occurred_at=NOW, cache=reference,
                    provider_request_hash=REQUEST_HASH,
                ),
                first,
            )
            self.assertEqual(restarted.verify(), 8)

    def test_missing_store_or_nonexistent_entry_never_becomes_cache_hit(self):
        with scratch_directory() as root:
            policy = load_quota_policy(ACTIVE_POLICY_PATH)
            store = self.authority(root, policy)
            reference = CacheReference(digest("a"))
            for name, cache_store in (("missing-store", None), ("missing-entry", store)):
                with self.subTest(name=name):
                    ledger = QuotaLedger(root / f"{name}.jsonl", policy=policy,
                                         cache_store=cache_store)
                    exhaust_daily(ledger)
                    result = ledger.request(
                        request_id=name, occurred_at=NOW, cache=reference,
                        provider_request_hash=REQUEST_HASH,
                    )
                    self.assertFalse(result.allowed)
                    self.assertNotEqual(result.reason, "verified_cache_hit")

    def test_tampered_or_missing_actual_bytes_fail_closed(self):
        with scratch_directory() as root:
            policy = load_quota_policy(ACTIVE_POLICY_PATH)
            for case in ("tampered", "missing"):
                with self.subTest(case=case):
                    store = self.authority(root / case, policy)
                    reference = self.publish(store, policy)
                    entry = store.get(reference.cache_entry_id)
                    path = store.object_path(entry.artifact_hash)
                    if case == "tampered":
                        path.write_bytes(b"different")
                    else:
                        path.unlink()
                    ledger = QuotaLedger(root / f"{case}.jsonl", policy=policy,
                                         cache_store=store)
                    exhaust_daily(ledger)
                    result = ledger.request(
                        request_id=case, occurred_at=NOW, cache=reference,
                        provider_request_hash=REQUEST_HASH,
                    )
                    self.assertFalse(result.allowed)
                    self.assertNotEqual(result.reason, "verified_cache_hit")

    def test_provider_policy_and_request_mismatch_fail_closed(self):
        with scratch_directory() as root:
            policy = load_quota_policy(ACTIVE_POLICY_PATH)
            cases = (
                ("provider", {"provider_id": "other-provider"}, REQUEST_HASH),
                ("policy", {"quota_policy_digest": digest("c")}, REQUEST_HASH),
                ("request", {}, digest("d")),
            )
            for name, changes, request_hash in cases:
                with self.subTest(name=name):
                    store = self.authority(root / name, policy)
                    reference = self.publish(store, policy, **changes)
                    ledger = QuotaLedger(root / f"{name}.jsonl", policy=policy,
                                         cache_store=store)
                    exhaust_daily(ledger)
                    result = ledger.request(
                        request_id=name, occurred_at=NOW, cache=reference,
                        provider_request_hash=request_hash,
                    )
                    self.assertFalse(result.allowed)
                    self.assertNotEqual(result.reason, "verified_cache_hit")

    def test_expired_or_invalidated_observation_fails_closed(self):
        with scratch_directory() as root:
            policy = load_quota_policy(ACTIVE_POLICY_PATH)
            for case in ("expired", "invalidated"):
                with self.subTest(case=case):
                    store = self.authority(root / case, policy)
                    reference = self.publish(
                        store, policy,
                        expires_at=("2026-01-01T00:15:00Z" if case == "expired"
                                    else "2026-01-01T01:00:00Z"),
                    )
                    if case == "invalidated":
                        store.invalidate(
                            reference.cache_entry_id,
                            invalidated_at="2026-01-01T00:20:00Z",
                            reason="observation-superseded",
                        )
                    ledger = QuotaLedger(root / f"{case}.jsonl", policy=policy,
                                         cache_store=store)
                    exhaust_daily(ledger)
                    result = ledger.request(
                        request_id=case, occurred_at=NOW, cache=reference,
                        provider_request_hash=REQUEST_HASH,
                    )
                    self.assertFalse(result.allowed)
                    self.assertNotEqual(result.reason, "verified_cache_hit")

    def test_hash_valid_unsupported_cache_history_fails_closed(self):
        with scratch_directory() as root:
            policy = load_quota_policy(ACTIVE_POLICY_PATH)
            store = self.authority(root, policy)
            reference = self.publish(store, policy)
            unsupported = {"record_type": "future_cache_authority_event", "value": 1}
            # E4: the cache owner's storage refuses a row its replay rejects;
            # the same bytes are seeded as a raw writer outside it would.
            with self.assertRaises(RegistryConflict):
                store.log.append(dict(unsupported))
            AppendOnlyJsonl(store.log.path).append(unsupported)
            ledger = QuotaLedger(root / "quota.jsonl", policy=policy, cache_store=store)
            exhaust_daily(ledger)
            with self.assertRaises(RegistryConflict):
                ledger.request(
                    request_id="unsupported", occurred_at=NOW, cache=reference,
                    provider_request_hash=REQUEST_HASH,
                )

    def test_cache_proof_is_part_of_idempotent_request_identity(self):
        with scratch_directory() as root:
            policy = load_quota_policy(ACTIVE_POLICY_PATH)
            store = self.authority(root, policy)
            first = self.publish(store, policy, payload=b"first")
            second = self.publish(store, policy, payload=b"second")
            ledger = QuotaLedger(root / "quota.jsonl", policy=policy, cache_store=store)
            accepted = ledger.request(
                request_id="same", occurred_at=NOW, cache=first,
                provider_request_hash=REQUEST_HASH,
            )
            self.assertEqual(accepted.reason, "verified_cache_hit")
            with self.assertRaises(RegistryConflict):
                ledger.request(
                    request_id="same", occurred_at=NOW, cache=second,
                    provider_request_hash=REQUEST_HASH,
                )
            with self.assertRaises(RegistryConflict):
                ledger.request(
                    request_id="same", occurred_at=NOW, cache=first,
                    provider_request_hash=digest("e"),
                )

    def test_invalidation_at_quota_transaction_entry_is_observed(self):
        with scratch_directory() as root:
            policy = load_quota_policy(ACTIVE_POLICY_PATH)
            store = self.authority(root, policy)
            reference = self.publish(store, policy)
            ledger = QuotaLedger(root / "quota.jsonl", policy=policy, cache_store=store)
            exhaust_daily(ledger)
            original = ledger.log.transaction

            def invalidate_then_enter(builder, **kwargs):
                store.invalidate(
                    reference.cache_entry_id,
                    invalidated_at="2026-01-01T00:20:00Z",
                    reason="changed-before-admission",
                )
                return original(builder, **kwargs)

            ledger.log.transaction = invalidate_then_enter
            result = ledger.request(
                request_id="raced", occurred_at=NOW, cache=reference,
                provider_request_hash=REQUEST_HASH,
            )
            self.assertFalse(result.allowed)
            self.assertNotEqual(result.reason, "verified_cache_hit")
            self.assertEqual(ledger.usage(NOW), (7, 7))

    def test_invalidation_writer_is_ordered_after_durable_cache_decision(self):
        with scratch_directory() as root:
            policy = load_quota_policy(ACTIVE_POLICY_PATH)
            store = self.authority(root, policy)
            reference = self.publish(store, policy)
            ledger = QuotaLedger(root / "quota.jsonl", policy=policy, cache_store=store)
            entered, release, attempting, done = Event(), Event(), Event(), Event()
            decision_holder = []
            original_quota = ledger.log.transaction
            original_cache = store.log.transaction

            def gated_quota(builder, **kwargs):
                def inside(rows):
                    entered.set()
                    if not release.wait(10):
                        raise TimeoutError("cache-decision barrier timed out")
                    return builder(rows)
                return original_quota(inside, **kwargs)

            def observed_invalidation(builder, **kwargs):
                attempting.set()
                try:
                    return original_cache(builder, **kwargs)
                finally:
                    done.set()

            ledger.log.transaction = gated_quota
            store.log.transaction = observed_invalidation
            requester = Thread(target=lambda: decision_holder.append(ledger.request(
                request_id="linearized-hit", occurred_at=NOW, cache=reference,
                provider_request_hash=REQUEST_HASH,
            )))
            invalidator = Thread(target=lambda: store.invalidate(
                reference.cache_entry_id,
                invalidated_at="2026-01-01T00:31:00Z",
                reason="newer-observation",
            ))
            requester.start()
            try:
                self.assertTrue(entered.wait(10))
                invalidator.start()
                self.assertTrue(attempting.wait(10))
                self.assertFalse(done.wait(0.2), "invalidation crossed cache decision fence")
                release.set()
                requester.join(10)
                invalidator.join(10)
                self.assertFalse(requester.is_alive())
                self.assertFalse(invalidator.is_alive())
            finally:
                release.set()
                requester.join(10)
                if invalidator.ident is not None:
                    invalidator.join(10)
            self.assertEqual(decision_holder[0].reason, "verified_cache_hit")
            future = ledger.request(
                request_id="after-invalidation", occurred_at="2026-01-01T00:32:00Z",
                cache=reference, provider_request_hash=REQUEST_HASH,
            )
            self.assertNotEqual(future.reason, "verified_cache_hit")

    def test_replay_requires_store_and_exact_persisted_proof(self):
        with scratch_directory() as root:
            policy = load_quota_policy(ACTIVE_POLICY_PATH)
            store = self.authority(root, policy)
            reference = self.publish(store, policy)
            ledger = QuotaLedger(root / "quota.jsonl", policy=policy, cache_store=store)
            result = ledger.request(
                request_id="cached", occurred_at=NOW, cache=reference,
                provider_request_hash=REQUEST_HASH,
            )
            self.assertEqual(result.reason, "verified_cache_hit")
            with self.assertRaises(RegistryConflict):
                QuotaLedger(root / "quota.jsonl", policy=policy)
            rows = ledger.log.records()
            self.assertEqual(rows[-1]["schema_version"], "quota-cache-hit-event-v3")
            self.assertEqual(rows[-1]["cache_entry_id"], reference.cache_entry_id)
            self.assertEqual(rows[-1]["provider_request_hash"], REQUEST_HASH)
            self.assertEqual(rows[-1]["cache_artifact_hash"], store.get(
                reference.cache_entry_id
            ).artifact_hash)


if __name__ == "__main__":
    unittest.main()
