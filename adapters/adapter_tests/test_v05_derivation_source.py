"""FR-08, PIT-07, F-31 and the capability downgrades adapter code may write (design 13.3, 16; G-03 in part)."""

from __future__ import annotations

import dataclasses
import unittest

from genesis.pit import BitemporalRecord, OperationalStatus
from genesis.registry import RegistryConflict

from genesis_adapters import config as cfg
from genesis_adapters import errors as err
from genesis_adapters.oddspapi import capability, emit, normalize
from genesis_adapters.oddspapi.reader import UsableBook, admissible_head

from . import emit_support as es
from . import parser_support as ps
from .emit_support import CAPABILITY_TIME, CAPTURE_1, CAPTURE_2, build_stores, capture, head_book, iso, pit_rows, small_payload
from .support import scratch_root


def version_for(policy) -> str:
    return cfg.derivation_version(normalize.CODE_VERSION, ps.CONFIG_BODY.digests, policy)


def record_at(stores, entity_id, t1):
    rows = [row for row in pit_rows(stores) if row["entity_id"] == entity_id and row["available_at"] == t1
            and row["source_id"] == stores.source_id]
    assert len(rows) == 1
    return BitemporalRecord(**{key: rows[0][key] for key in BitemporalRecord.__dataclass_fields__})


class PolicyVersioningTests(unittest.TestCase):
    def test_fr08_one_changed_policy_value_is_a_new_source_and_old_records_keep_their_valid_to(self):
        old_policy = ps.POLICY
        new_policy = ps.policy_with(price_ttl_seconds=old_policy.price_ttl_seconds + 1)
        old_version, new_version = version_for(old_policy), version_for(new_policy)
        self.assertEqual(old_version, ps.DERIVATION)
        self.assertNotEqual(old_policy.digest, new_policy.digest)
        self.assertNotEqual(old_version, new_version)
        self.assertNotEqual(cfg.normalized_contract_id(old_version), cfg.normalized_contract_id(new_version))
        self.assertNotEqual(cfg.market_book_source_id(old_version), cfg.market_book_source_id(new_version))
        with scratch_root() as root:
            old = build_stores(root)
            parsed, _, _ = capture(old, small_payload())
            entity = head_book(parsed).entity_id
            new = dataclasses.replace(es.with_version(old, new_version), policy=new_policy)
            ctx = es.make_capture_ctx(new, ps.dump(small_payload()), t1=CAPTURE_2, policy=new_policy)
            capture(new, small_payload(), t1=CAPTURE_2, ctx=ctx)
            first, second = record_at(old, entity, CAPTURE_1), record_at(new, entity, CAPTURE_2)
            self.assertEqual(first.valid_to, iso(CAPTURE_1, seconds=old_policy.price_ttl_seconds))
            self.assertEqual(second.valid_to, iso(CAPTURE_2, seconds=new_policy.price_ttl_seconds))
            self.assertEqual((first.source_id, second.source_id),
                             (cfg.market_book_source_id(old_version), cfg.market_book_source_id(new_version)))
            self.assertNotEqual(first.payload_hash, second.payload_hash)

    def test_f31_a_parse_context_from_another_configuration_is_refused(self):
        with scratch_root() as root:
            stores = build_stores(root)
            other = ps.policy_with(prematch_guard_seconds=ps.POLICY.prematch_guard_seconds + 1)
            raw = ps.dump(small_payload())
            ctx = es.make_capture_ctx(stores, raw, t1=CAPTURE_1, derivation_version=version_for(other), policy=other)
            with self.assertRaises(emit.EmitConflict) as caught:
                capture(stores, raw, ctx=ctx)
            self.assertEqual(caught.exception.failure, err.AdapterFailure.CONFIG_DIGEST_MISMATCH)
            self.assertEqual(err.reason_code(caught.exception.failure).value, "configuration_mismatch")
            self.assertEqual(pit_rows(stores), [])


class SourceChangeTests(unittest.TestCase):
    def test_pit07_a_derivation_change_hands_over_at_t_fix_and_two_ready_sources_fail_closed(self):
        with scratch_root() as root:
            old = build_stores(root)
            parsed, _, first = capture(old, small_payload())
            entity = head_book(parsed).entity_id
            new_version = "mb1-" + "1" * 16
            new = es.with_version(old, new_version)
            # the new source first exists as UNKNOWN (G2R capture); nothing of it is consumable yet
            capability.register_downgrade(new.capabilities, new.source_id, status=OperationalStatus.UNKNOWN,
                                          at=iso(CAPTURE_1, seconds=5), reason="G2R")
            ctx = es.make_capture_ctx(new, ps.dump(small_payload()), t1=CAPTURE_2, derivation_version=new_version)
            capture(new, small_payload(), t1=CAPTURE_2, ctx=ctx)
            t_fix = iso(CAPTURE_2, seconds=60)
            # a READY row for the new source while the old is still READY: both READY -> fail closed
            new.capabilities.register(es.source_capability(new, status=OperationalStatus.READY, at=t_fix,
                                                           suffix="ready-1"))
            new.bindings.register(source_id=new.source_id, source_contract_id=new.contract_id, provider="oddspapi",
                                  approval_reference="synthetic-test-only-binding-2")
            self.assertEqual(admissible_head(entity, t_fix, stores=old).code, err.AdapterFailure.AMBIGUOUS_SOURCE)
            # the old source is BLOCKED (a downgrade adapter code may make) -> the new one serves from there on
            capability.register_downgrade(old.capabilities, old.source_id, status=OperationalStatus.BLOCKED,
                                          at=iso(t_fix, micros=1), reason="DERIVATION_SOURCE_CHANGE")
            before = admissible_head(entity, iso(CAPTURE_2, seconds=30), stores=old)
            self.assertIsInstance(before, UsableBook)
            self.assertEqual((before.source_id, before.record.source_id), (old.source_id, old.source_id))
            during = admissible_head(entity, t_fix, stores=old)
            self.assertEqual(during.code, err.AdapterFailure.AMBIGUOUS_SOURCE)          # both READY at t_fix
            after = admissible_head(entity, iso(t_fix, micros=1), stores=old)
            self.assertIsInstance(after, UsableBook)
            self.assertEqual(after.source_id, new.source_id)
            self.assertEqual(after.record.source_id, new.source_id)
            with self.assertRaises(Exception):
                old.capabilities.require_ready_at(old.source_id, iso(t_fix, micros=1))
            # the old source's still-current price is no longer reachable through it
            self.assertLess(iso(t_fix, micros=1), record_at(old, entity, CAPTURE_1).valid_to)


class DowngradeTests(unittest.TestCase):
    def test_adapter_code_can_only_write_blocked_or_unknown_rows(self):
        with scratch_root() as root:
            stores = build_stores(root, ready=False)
            with self.assertRaises(capability.CapabilityDowngradeError):
                capability.register_downgrade(stores.capabilities, stores.source_id,
                                              status=OperationalStatus("ready"), at=CAPABILITY_TIME, reason="x")
            capability.register_downgrade(stores.capabilities, stores.source_id, status=OperationalStatus.UNKNOWN,
                                          at=CAPABILITY_TIME, reason="G2R")
            row = stores.capabilities.history(stores.source_id)[-1]
            self.assertEqual((row.operational_status.value, row.point_in_time_reliability), ("unknown", "unverified"))
            self.assertFalse(row.is_ready())

    def test_a_downgrade_copies_the_descriptive_fields_and_is_never_ready(self):
        with scratch_root() as root:
            stores = build_stores(root)
            ready = stores.capabilities.history(stores.source_id)[-1]
            capability.register_downgrade(stores.capabilities, stores.source_id, status=OperationalStatus.BLOCKED,
                                          at=iso(CAPABILITY_TIME, seconds=1), reason="AUTH_REJECTED")
            blocked = stores.capabilities.history(stores.source_id)[-1]
            self.assertEqual(blocked.operational_status.value, "blocked")
            self.assertFalse(blocked.is_ready())
            for name in ("provider", "access_method", "cost_tier", "coverage", "schema_version"):
                self.assertEqual(getattr(blocked, name), getattr(ready, name))
            with self.assertRaises(RegistryConflict):                          # recorded_at must advance
                capability.register_downgrade(stores.capabilities, stores.source_id,
                                              status=OperationalStatus.BLOCKED, at=CAPABILITY_TIME, reason="again")

    def test_g04_block_every_known_market_book_source(self):
        with scratch_root() as root:
            stores = build_stores(root)
            other = es.with_version(stores, "mb1-" + "2" * 16)
            es.approve_source(other, at=iso(CAPABILITY_TIME, seconds=1))
            at = iso(CAPABILITY_TIME, seconds=2)
            blocked = capability.block_market_book_sources(stores.capabilities, at=at, reason="AUTH_REJECTED")
            self.assertEqual(set(blocked), {stores.source_id, other.source_id})
            for source_id in blocked:
                with self.assertRaises(Exception):
                    stores.capabilities.require_ready_at(source_id, at)
            parsed, _, result = capture(stores, small_payload(), t1=CAPTURE_1)
            self.assertEqual(admissible_head(head_book(parsed).entity_id, result.t3, stores=stores).code,
                             err.AdapterFailure.DATA_CAPABILITY_NOT_READY)


if __name__ == "__main__":
    unittest.main()
