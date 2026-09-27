"""E4: an append that returns success is a row its readers verify after restart.

Invariant: a hash-chained JSONL log appends only a line that every reader of
that log parses back to exactly the row written, with the log's own chain
fields: a caller never sets ``previous_hash``, ``sequence`` or
``record_hash``, and a record must be exact JSON (``dict`` with ``str`` keys,
``list``/``tuple``, ``str``, ``int``, ``float``, ``bool``, ``None``, of their
exact types), so a value cannot pass an owner's check as one thing and be read
back as another. An owner that replays its whole history additionally has its
storage refuse any row that replay rejects. A refused write leaves the log's
bytes unchanged; an accepted plain write is byte-identical to the pre-E4 line.
"""

from __future__ import annotations

import json
import random
import unittest
from collections import OrderedDict
from decimal import Decimal
from enum import IntEnum
from pathlib import Path

from genesis.config import OperationalMode
from genesis.decision_output import StrategyOutputApprovalStore
from genesis.execution import (
    CriticalEvidenceRefreshStore, ExecutionMarketStateStore, ModeState, ModeStateStore,
)
from genesis.pit import OperationalStatus, SourceCapability, SourceCapabilityRegistry
from genesis.registry import (
    AppendOnlyJsonl, RegistryConflict, StrategyArtifact, StrategyLifecycle, StrategyRegistry,
)
from genesis.repro import canonical_json
from genesis.risk import BankrollSnapshot, BankrollSnapshotStore, SafetyState, SafetyStateStore
from genesis.selection import QualificationRecordStore

from ._support import scratch_directory


class Liar(str):
    """Equal to everything, hashed apart from the text it serializes as."""

    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return False

    def __hash__(self):
        return id(self)


class Colliding(str):
    def __hash__(self):
        return id(self)

    def __eq__(self, other):
        return self is other


class Level(IntEnum):
    ONE = 1


def raw_bytes(path: Path) -> bytes:
    return path.read_bytes() if path.exists() else b""


def capability(version: str, recorded_at: str, **changes) -> SourceCapability:
    fields = dict(
        source_id="src", provider="p", access_method="m", cost_tier="t",
        entitlement_class="e", historical_availability_class="h",
        point_in_time_reliability="verified", revision_behaviour="r", coverage="c",
        rate_quota_limits="q", schema_version="1", operational_status=OperationalStatus.READY,
        recorded_at=recorded_at, version=version,
    )
    fields.update(changes)
    return SourceCapability(**fields)


def artifact(strategy_id: str = "s") -> StrategyArtifact:
    return StrategyArtifact(
        strategy_id, "v1", StrategyLifecycle.IDEA, "a" * 64, "b" * 64, "c" * 64, "r",
        "2026-01-01T00:00:00Z",
    )


class T6E4PrimitiveTests(unittest.TestCase):
    def assert_refused_unchanged(self, log: AppendOnlyJsonl, record) -> None:
        before = raw_bytes(log.path)
        with self.assertRaises((RegistryConflict, TypeError, ValueError)):
            log.append(record)
        self.assertEqual(raw_bytes(log.path), before)
        self.assertEqual(AppendOnlyJsonl(log.path).verify(), len(before.splitlines()))

    def test_e4_chain_fields_are_the_logs_own(self):
        with scratch_directory() as root:
            log = AppendOnlyJsonl(root / "log.jsonl")
            log.append({"record_type": "seed"})
            for field, value in (
                ("sequence", 9), ("sequence", 2), ("sequence", None),
                ("previous_hash", "0" * 64), ("record_hash", "0" * 64),
            ):
                with self.subTest(field=field, value=value):
                    self.assert_refused_unchanged(log, {"record_type": "x", field: value})
            self.assertEqual([row["sequence"] for row in AppendOnlyJsonl(log.path).records()], [1])

    def test_e4_values_that_would_not_read_back_as_written_are_refused(self):
        unstable = {
            "integer keys": {10: "a", 9: "b"},
            "float key": {1.5: "a"},
            "bool key": {True: "a"},
            "None key": {None: "a"},
            "colliding str-subclass keys": {Colliding("k"): 1, Colliding("k"): 2},
            "str-subclass key": {Liar("k"): 1},
            "str-subclass value": Liar("v"),
            "int-subclass value": Level.ONE,
            "dict subclass": OrderedDict(a=1),
            "set": {1, 2},
            "Decimal": Decimal("1.5"),
            "bytes": b"x",
            "object": object(),
            "not finite": float("nan"),
            "nested str subclass": [{"a": [Colliding("x")]}],
        }
        with scratch_directory() as root:
            log = AppendOnlyJsonl(root / "log.jsonl")
            log.append({"record_type": "seed"})
            for label, value in unstable.items():
                with self.subTest(label):
                    self.assert_refused_unchanged(log, {"record_type": "x", "value": value})
            with self.subTest("record is a dict subclass"):
                self.assert_refused_unchanged(log, OrderedDict(record_type="x"))

    def test_e4_plain_writes_are_byte_identical_to_the_pre_e4_line(self):
        records = [
            {"record_type": "a", "n": 1, "f": 1.25, "big": 10 ** 30, "neg": -0.0},
            {"record_type": "b", "t": ("x", "y"), "nested": {"z": [None, True, False]}},
            {"record_type": "c", "text": "café   £ \"q\" \\", "empty": {}},
        ]
        with scratch_directory() as root:
            path = root / "log.jsonl"
            expected = b""
            written: list[dict] = []
            for record in records:
                row = AppendOnlyJsonl.chained(written, record)
                expected += canonical_json(row)
                self.assertEqual(AppendOnlyJsonl(path).append(record), row["record_hash"])
                written.append(json.loads(canonical_json(row)))
            self.assertEqual(path.read_bytes(), expected)
            self.assertEqual(AppendOnlyJsonl(path).records(), written)

    def test_e4_property_every_accepted_append_is_reader_verifiable(self):
        rng = random.Random(20260927)

        def value(depth: int = 0):
            choice = rng.randrange(14 if depth < 3 else 9)
            if choice == 0:
                return rng.randrange(-10 ** 6, 10 ** 6)
            if choice == 1:
                return rng.choice([0.5, -2.25, 1e16, 3.0])
            if choice == 2:
                return rng.choice(["", "a", "é", " ", "x y"])
            if choice == 3:
                return rng.choice([True, False, None])
            if choice == 4:
                return Colliding(rng.choice(["k", "v"]))
            if choice == 5:
                return Level.ONE
            if choice == 6:
                return Decimal("1")
            if choice == 7:
                return float("inf")
            if choice == 8:
                return rng.choice(["s", "t"])
            if choice in (9, 10):
                return [value(depth + 1) for _ in range(rng.randrange(3))]
            if choice == 11:
                return tuple(value(depth + 1) for _ in range(rng.randrange(3)))
            keys = [rng.choice(["a", "b", "c", 1, 2, Colliding("a"), "sequence"])
                    for _ in range(rng.randrange(4))]
            return {key: value(depth + 1) for key in keys}

        accepted = refused = 0
        with scratch_directory() as root:
            path = root / "log.jsonl"
            for _ in range(400):
                record = {"record_type": "p", "value": value()}
                if rng.randrange(10) == 0:
                    record[rng.choice(["sequence", "previous_hash", "record_hash"])] = 1
                before = raw_bytes(path)
                try:
                    AppendOnlyJsonl(path).append(record)
                except (RegistryConflict, TypeError, ValueError, RecursionError):
                    refused += 1
                    self.assertEqual(raw_bytes(path), before)
                    continue
                accepted += 1
                rows = AppendOnlyJsonl(path).records()
                self.assertEqual(canonical_json(rows[-1]), path.read_bytes().splitlines(True)[-1])
            self.assertEqual(AppendOnlyJsonl(path).verify(), accepted)
        self.assertGreater(accepted, 50)
        self.assertGreater(refused, 50)

    def test_e4_a_logs_reader_is_asked_before_every_append(self):
        with scratch_directory() as root:
            seen: list[int] = []

            def reader(rows):
                seen.append(len(rows))
                if rows[-1].get("record_type") != "ok":
                    raise ValueError("owner cannot read this row")

            log = AppendOnlyJsonl(root / "log.jsonl", reader=reader)
            log.append({"record_type": "ok"})
            before = raw_bytes(log.path)
            with self.assertRaises(RegistryConflict):
                log.append({"record_type": "unreadable"})
            with self.assertRaises(RegistryConflict):
                log.transaction(lambda _rows: {"record_type": "unreadable"})
            self.assertEqual(raw_bytes(log.path), before)
            self.assertEqual(seen, [1, 2, 2])


class T6E4OwnerTests(unittest.TestCase):
    """The audit's sibling owners: bankroll, safety, mode, strategy registry,
    source capability and approval reservations, plus the replaying owners."""

    def assert_owner_refuses(self, path: Path, write, read) -> None:
        before = raw_bytes(path)
        with self.assertRaises((RegistryConflict, TypeError, ValueError)):
            write()
        self.assertEqual(raw_bytes(path), before)
        read()  # a fresh reader over the same file, as after restart

    def test_e4_owner_writes_of_values_that_read_back_differently_are_refused(self):
        with scratch_directory() as root:
            bank = root / "bankroll.jsonl"
            head = BankrollSnapshot.create(
                bankroll="100", captured_at="2026-01-01T00:00:00Z", rebase_reason="initial",
            )
            BankrollSnapshotStore(bank).append(head)
            self.assert_owner_refuses(
                bank,
                lambda: BankrollSnapshotStore(bank).append(BankrollSnapshot.create(
                    bankroll="90", captured_at="2026-01-01T00:01:00Z", rebase_reason="x",
                    parent_snapshot_id=Liar("not-the-head"),
                )),
                lambda: BankrollSnapshotStore(bank).history(),
            )
            nxt = BankrollSnapshot.create(
                bankroll="90", captured_at="2026-01-01T00:01:00Z", rebase_reason="x",
                parent_snapshot_id=head.snapshot_id,
            )
            BankrollSnapshotStore(bank).append(nxt)
            self.assertEqual(BankrollSnapshotStore(bank).current(), nxt)

            safety = root / "safety.jsonl"
            SafetyStateStore(safety).append(SafetyState.create(
                kill_switch_active=False, recorded_at="2026-01-01T00:00:00Z", reason="mode:paper",
            ))
            self.assert_owner_refuses(
                safety,
                lambda: SafetyStateStore(safety).append(SafetyState.create(
                    kill_switch_active=True, recorded_at="2026-01-01T00:01:00Z", reason="x",
                    parent_state_id=Liar("not-the-head"),
                )),
                lambda: SafetyStateStore(safety).history(),
            )

            mode = root / "mode.jsonl"
            ModeStateStore(mode).append(ModeState.create(
                mode=OperationalMode.PAPER, occurred_at="2026-01-01T00:00:00Z",
                authorization_id="e4", parent_state_id=None,
            ))
            self.assert_owner_refuses(
                mode,
                lambda: ModeStateStore(mode).append(ModeState.create(
                    mode=OperationalMode.PAPER, occurred_at="2026-01-01T00:01:00Z",
                    authorization_id="e4", parent_state_id=Liar("not-the-head"),
                )),
                lambda: ModeStateStore(mode).current(),
            )

            strategies = root / "strategies.jsonl"
            StrategyRegistry(strategies).register(artifact())
            self.assert_owner_refuses(
                strategies,
                lambda: StrategyRegistry(strategies).register(artifact(Colliding("s"))),
                lambda: StrategyRegistry(strategies),
            )

            sources = root / "sources.jsonl"
            SourceCapabilityRegistry(sources).register(capability("v1", "2026-01-01T00:00:00Z"))
            self.assert_owner_refuses(
                sources,
                lambda: SourceCapabilityRegistry(sources).register(capability(
                    "v2", "2026-01-01T00:01:00Z", coverage={10: "a", 9: "b"},
                )),
                lambda: SourceCapabilityRegistry(sources).require_ready("src"),
            )

            ledger = root / "approvals.jsonl"
            StrategyOutputApprovalStore(ledger).reserve(
                request_id="req", reserved_by="op", reserved_at="2026-01-01T00:00:00Z",
            )
            self.assert_owner_refuses(
                ledger,
                lambda: StrategyOutputApprovalStore(ledger).reserve(
                    request_id=Colliding("req"), reserved_by="op2",
                    reserved_at="2026-01-01T00:01:00Z",
                ),
                lambda: StrategyOutputApprovalStore(ledger).verify(),
            )

    def test_e4_owner_storage_refuses_a_row_its_replay_rejects(self):
        """A generic write through an owner's own storage cannot break its reader."""

        with scratch_directory() as root:
            owners = {
                "bankroll": BankrollSnapshotStore(root / "bankroll.jsonl"),
                "safety": SafetyStateStore(root / "safety.jsonl"),
                "mode": ModeStateStore(root / "mode.jsonl"),
                "strategy registry": StrategyRegistry(root / "strategies.jsonl"),
                "approvals": StrategyOutputApprovalStore(root / "approvals.jsonl"),
                "source capability": SourceCapabilityRegistry(root / "sources.jsonl"),
                "qualification": QualificationRecordStore(root / "q" / "qualifications.jsonl"),
                "refresh": CriticalEvidenceRefreshStore(root / "refreshes.jsonl"),
                "market": ExecutionMarketStateStore(root / "markets.jsonl"),
            }
            unreadable = {
                "source capability": {"record_type": "source_capability_registered",
                                      "source_id": "src"},
                "refresh": {"record_type": "critical_evidence_refresh",
                            "schema_version": "critical-evidence-refresh-v2",
                            "candidate_decision_hash": "a" * 64},
                "market": {"record_type": "execution_market_snapshot",
                           "schema_version": "execution-market-snapshot-v2",
                           "candidate_decision_hash": "a" * 64},
            }
            for name, owner in owners.items():
                with self.subTest(name):
                    row = unreadable.get(name, {"record_type": "not_an_event_this_owner_reads"})
                    before = raw_bytes(owner.log.path)
                    for write in (lambda: owner.log.append(dict(row)),
                                  lambda: owner.log.transaction(lambda _rows: dict(row))):
                        with self.assertRaises(RegistryConflict):
                            write()
                    self.assertEqual(raw_bytes(owner.log.path), before)


if __name__ == "__main__":
    unittest.main()
