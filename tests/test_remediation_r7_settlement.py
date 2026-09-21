from __future__ import annotations

import multiprocessing
import os
import unittest
from decimal import Decimal
from pathlib import Path

from genesis.accounting import BetSide, SettlementKind
from genesis.ledger import FillRecord, SettlementLedger
from genesis.registry import AppendOnlyJsonl, RegistryConflict
from ._support import scratch_directory


def digest(character: str) -> str:
    return character * 64


def fill(fill_id: str = "fill-1", order_id: str = "order-1") -> FillRecord:
    return FillRecord(
        fill_id,
        order_id,
        digest("a"),
        BetSide.BACK,
        "2.00",
        "2.50",
        "2026-01-01T00:00:00Z",
    )


def _settlement_worker(path_text: str, start, event_id: str) -> None:
    ledger = SettlementLedger(Path(path_text))
    start.wait()
    try:
        ledger.settle(
            event_id=event_id,
            fill_id="fill-1",
            kind=SettlementKind.WIN,
            occurred_at="2026-01-01T01:00:00Z",
        )
    except RegistryConflict:
        os._exit(2)
    os._exit(0)


class R7SettlementLineageTests(unittest.TestCase):
    def test_fill_fragment_has_exact_identity_decimal_types_and_liability(self):
        fragment = fill().fragment()
        self.assertEqual(fragment.fragment_id, "fill-1")
        self.assertEqual(fragment.side, BetSide.BACK)
        self.assertEqual(fragment.odds, Decimal("2.00"))
        self.assertEqual(fragment.stake, Decimal("2.50"))
        self.assertEqual(fragment.liability, Decimal("2.50"))

        lay = FillRecord(
            "fill-lay",
            "order-lay",
            digest("b"),
            BetSide.LAY,
            "3.00",
            "2.50",
            "2026-01-01T00:00:00Z",
        ).fragment()
        self.assertEqual(lay.liability, Decimal("5.0000"))

    def test_single_head_rejects_unlinked_duplicate_and_preserves_exact_schema(self):
        with scratch_directory() as root:
            path = root / "ledger.jsonl"
            ledger = SettlementLedger(path)
            ledger.record_fill(fill())
            first = ledger.settle(
                event_id="s1",
                fill_id="fill-1",
                kind=SettlementKind.WIN,
                occurred_at="2026-01-01T01:00:00Z",
            )
            self.assertEqual(first.delta_pnl, "2.50")
            self.assertEqual(first.effective_pnl, "2.50")
            self.assertEqual(first.pnl, "2.50")
            self.assertEqual(
                ledger.settle(
                    event_id="s1",
                    fill_id="fill-1",
                    kind=SettlementKind.WIN,
                    occurred_at="2026-01-01T01:00:00Z",
                ),
                first,
            )
            with self.assertRaises(RegistryConflict):
                ledger.settle(
                    event_id="s2-unlinked",
                    fill_id="fill-1",
                    kind=SettlementKind.WIN,
                    occurred_at="2026-01-01T02:00:00Z",
                )
            row = AppendOnlyJsonl(path).records()[-1]
            self.assertEqual(row["schema_version"], "ledger-event-v2")
            self.assertEqual(row["delta_pnl"], "2.50")
            self.assertEqual(row["effective_pnl"], "2.50")
            self.assertNotIn("pnl", row)

    def test_multi_step_corrections_conserve_final_effective_result(self):
        with scratch_directory() as root:
            ledger = SettlementLedger(root / "ledger.jsonl")
            ledger.record_fill(fill())
            win = ledger.settle(
                event_id="s1",
                fill_id="fill-1",
                kind=SettlementKind.WIN,
                occurred_at="2026-01-01T01:00:00Z",
            )
            loss = ledger.settle(
                event_id="s2",
                fill_id="fill-1",
                kind=SettlementKind.LOSS,
                occurred_at="2026-01-01T02:00:00Z",
                correction_of="s1",
            )
            final_win = ledger.settle(
                event_id="s3",
                fill_id="fill-1",
                kind=SettlementKind.WIN,
                occurred_at="2026-01-01T03:00:00Z",
                correction_of="s2",
            )
            self.assertEqual(
                [(event.delta_pnl, event.effective_pnl) for event in (win, loss, final_win)],
                [("2.50", "2.50"), ("-5.00", "-2.50"), ("5.00", "2.50")],
            )
            self.assertEqual(ledger.head("fill-1"), final_win)
            self.assertEqual(ledger.total_pnl(), "2.50")

    def test_cross_fill_stale_ancestor_and_conflicting_event_id_fail_closed(self):
        with scratch_directory() as root:
            ledger = SettlementLedger(root / "ledger.jsonl")
            ledger.record_fill(fill())
            ledger.record_fill(fill("fill-2", "order-2"))
            ledger.settle(
                event_id="s1",
                fill_id="fill-1",
                kind=SettlementKind.WIN,
                occurred_at="2026-01-01T01:00:00Z",
            )
            ledger.settle(
                event_id="other",
                fill_id="fill-2",
                kind=SettlementKind.WIN,
                occurred_at="2026-01-01T01:00:00Z",
            )
            with self.assertRaises(RegistryConflict):
                ledger.settle(
                    event_id="cross",
                    fill_id="fill-2",
                    kind=SettlementKind.LOSS,
                    occurred_at="2026-01-01T02:00:00Z",
                    correction_of="s1",
                )
            second = ledger.settle(
                event_id="s2",
                fill_id="fill-1",
                kind=SettlementKind.LOSS,
                occurred_at="2026-01-01T02:00:00Z",
                correction_of="s1",
            )
            with self.assertRaises(RegistryConflict):
                ledger.settle(
                    event_id="stale",
                    fill_id="fill-1",
                    kind=SettlementKind.WIN,
                    occurred_at="2026-01-01T03:00:00Z",
                    correction_of="s1",
                )
            with self.assertRaises(RegistryConflict):
                ledger.settle(
                    event_id="s2",
                    fill_id="fill-1",
                    kind=SettlementKind.WIN,
                    occurred_at="2026-01-01T02:00:00Z",
                    correction_of="s1",
                )
            self.assertEqual(ledger.head("fill-1"), second)

    def test_restart_and_void_cancellation_preserve_the_same_lineage(self):
        with scratch_directory() as root:
            path = root / "ledger.jsonl"
            ledger = SettlementLedger(path)
            ledger.record_fill(fill())
            ledger.settle(
                event_id="s1",
                fill_id="fill-1",
                kind=SettlementKind.WIN,
                occurred_at="2026-01-01T01:00:00Z",
            )
            cancelled = ledger.record_cancellation(
                event_id="void-1",
                fill_id="fill-1",
                occurred_at="2026-01-01T02:00:00Z",
                correction_of="s1",
            )
            self.assertEqual(cancelled.delta_pnl, "-2.50")
            self.assertEqual(cancelled.effective_pnl, "0.00")
            self.assertEqual(cancelled.settlement_kind, SettlementKind.VOID)
            with self.assertRaises(RegistryConflict):
                ledger.record_cancellation(
                    event_id="void-fork",
                    fill_id="fill-1",
                    occurred_at="2026-01-01T03:00:00Z",
                    correction_of="s1",
                )

            restarted = SettlementLedger(path)
            self.assertEqual(restarted.head("fill-1"), cancelled)
            self.assertEqual(restarted.total_pnl(), "0.00")
            self.assertEqual(restarted.verify(), 3)

    def test_legacy_one_level_lineage_migrates_but_duplicate_unlinked_fails(self):
        with scratch_directory() as root:
            safe_path = root / "safe.jsonl"
            safe = AppendOnlyJsonl(safe_path)
            safe.append({"record_type": "fill", **fill().to_dict()})
            safe.append(
                {
                    "record_type": "settlement",
                    "event_id": "s1",
                    "event_type": "settlement",
                    "occurred_at": "2026-01-01T01:00:00Z",
                    "fill_id": "fill-1",
                    "settlement_kind": "win",
                    "dead_heat_fraction": "1",
                    "commission_rate": "0",
                    "pnl": "2.50",
                    "correction_of": None,
                }
            )
            safe.append(
                {
                    "record_type": "settlement",
                    "event_id": "s2",
                    "event_type": "settlement",
                    "occurred_at": "2026-01-01T02:00:00Z",
                    "fill_id": "fill-1",
                    "settlement_kind": "loss",
                    "dead_heat_fraction": "1",
                    "commission_rate": "0",
                    "pnl": "-5.00",
                    "correction_of": "s1",
                }
            )
            migrated = SettlementLedger(safe_path)
            self.assertEqual(migrated.total_pnl(), "-2.50")
            self.assertEqual(migrated.head("fill-1").effective_pnl, "-2.50")

            ambiguous_path = root / "ambiguous.jsonl"
            ambiguous = AppendOnlyJsonl(ambiguous_path)
            ambiguous.append({"record_type": "fill", **fill().to_dict()})
            for event_id in ("s1", "s2"):
                ambiguous.append(
                    {
                        "record_type": "settlement",
                        "event_id": event_id,
                        "event_type": "settlement",
                        "occurred_at": f"2026-01-01T0{1 if event_id == 's1' else 2}:00:00Z",
                        "fill_id": "fill-1",
                        "settlement_kind": "win",
                        "dead_heat_fraction": "1",
                        "commission_rate": "0",
                        "pnl": "2.50",
                        "correction_of": None,
                    }
                )
            with self.assertRaises(RegistryConflict):
                SettlementLedger(ambiguous_path)

    def test_cross_process_initial_settlement_is_atomic(self):
        with scratch_directory() as root:
            path = root / "ledger.jsonl"
            ledger = SettlementLedger(path)
            ledger.record_fill(fill())
            context = multiprocessing.get_context("spawn")
            start = context.Event()
            processes = [
                context.Process(
                    target=_settlement_worker,
                    args=(str(path), start, event_id),
                )
                for event_id in ("race-a", "race-b")
            ]
            for process in processes:
                process.start()
            start.set()
            for process in processes:
                process.join(30)
            self.assertEqual(sorted(process.exitcode for process in processes), [0, 2])
            restarted = SettlementLedger(path)
            self.assertIn(restarted.head("fill-1").event_id, {"race-a", "race-b"})
            self.assertEqual(restarted.total_pnl(), "2.50")
            self.assertEqual(restarted.verify(), 2)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    unittest.main()
