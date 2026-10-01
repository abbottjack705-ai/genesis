"""A-3: a crash after ANY durable append is resumed by running the emission again.

The stage completes exactly once: existing artifacts are verified by exact identity and content and
reused, a conflicting artifact halts, and no history is ever duplicated. Times are never reused across
the restart, so nothing becomes admissible earlier than it really became durable.
"""

from __future__ import annotations

import unittest

from genesis_adapters import errors as err
from genesis_adapters.oddspapi import emit, parser

from . import emit_support as es
from . import parser_support as ps
from .emit_support import (
    CAPTURE_1, CAPTURE_2, build_stores, capture, durable_summary, iso, pit_rows, reopen, small_payload,
    structured_files,
)
from .parser_support import fixture_of, market_of, price_of
from .support import Crash, SequenceClock, scratch_root


def second_payload():
    """Every state in one response: OPEN, SUSPENDED, BLOCKED and (against the first scope) ABSENT."""

    payload = small_payload(bookmakers=("pinnacle", "fixture-book-a"))
    price_of(payload, "pinnacle", "1010", "2002")["active"] = False
    del market_of(payload, "fixture-book-a", "101")["outcomes"]["102"]
    del fixture_of(payload)["bookmakerOdds"]["pinnacle"]["markets"]["101"]
    return payload


def first_capture(stores):
    parsed = capture(stores, small_payload(bookmakers=("pinnacle", "fixture-book-a")))[0]
    return ps.scope_of(parsed)


def hook_at(target):
    def hook(name):
        if name == target:
            raise Crash()
    return hook


class CrashResumeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with scratch_root() as root:
            stores = build_stores(root)
            scope = first_capture(stores)
            cls.checkpoints = []
            _, _, result = capture(stores, second_payload(), t1=CAPTURE_2, expected_scope=scope,
                                   checkpoint=cls.checkpoints.append)
            cls.baseline_result = result
            cls.baseline = durable_summary(stores)
            cls.baseline_t2, cls.baseline_t3 = result.t2, result.t3

    def test_the_baseline_covers_every_state_and_every_step(self):
        self.assertEqual({"after_t2", "after_t3", "after_coverage", "after_normalized_row", "after_identity"},
                         {name for name in self.checkpoints if ":" not in name})
        kinds = {name.split(":")[0] for name in self.checkpoints}
        self.assertEqual(kinds, {"after_t2", "after_observation", "after_structured", "after_t3", "after_pit",
                                 "after_coverage", "after_normalized_row", "after_identity"})
        self.assertEqual(sum(1 for n in self.checkpoints if n.startswith("after_pit:")), 4)
        self.assertEqual(sum(1 for n in self.checkpoints if n.startswith("after_structured:")), 1)
        self.assertEqual(self.baseline["normalized_rows"], 2)                    # the first capture and this one
        self.assertEqual(set(self.baseline["observations_per_artifact"]), {1})

    def test_a3_a_crash_at_every_emission_checkpoint_resumes_to_the_same_durable_history(self):
        for name in self.checkpoints:
            with self.subTest(crash_after=name), scratch_root() as root:
                stores = build_stores(root)
                scope = first_capture(stores)
                raw = ps.dump(second_payload())
                ctx = es.make_capture_ctx(stores, raw, t1=CAPTURE_2, expected_scope=scope)
                parsed = parser.parse_odds_response(raw, ctx)
                es.seed_acquisition(stores, ctx)
                with self.assertRaises(Crash):
                    emit.emit_response(parsed, ctx, stores=stores, clock=SequenceClock(
                        [iso(CAPTURE_2, seconds=0.5), iso(CAPTURE_2, seconds=1), iso(CAPTURE_2, seconds=1.000001)]),
                        checkpoint=hook_at(name))
                durable_before = [r for r in pit_rows(stores) if r["available_at"] == CAPTURE_2]
                restarted = reopen(stores)
                resumed = emit.emit_response(parsed, ctx, stores=restarted, clock=SequenceClock(
                    [iso(CAPTURE_2, seconds=10), iso(CAPTURE_2, seconds=11), iso(CAPTURE_2, seconds=12)]))
                summary = durable_summary(restarted)
                for key, value in self.baseline.items():
                    if key == "normalized_rows":
                        self.assertEqual(summary[key], 2, name)
                    else:
                        self.assertEqual(summary[key], value, f"{key} after a crash at {name}")
                self.assertEqual(summary["coverage_duplicates"], 0, name)
                self.assertEqual(len(restarted.pit.log.records()), len(pit_rows(restarted)), name)
                # one T3 for the whole response (design 6.2, hostile audit HA-06): the durable one if any PIT record
                # survived the crash, else one stamped at the resume; never before its own observation
                rows = [r for r in pit_rows(restarted) if r["available_at"] == CAPTURE_2]
                self.assertEqual(len({row["ready_at"] for row in rows}), 1, name)
                expected_t3 = self.baseline_t3 if durable_before else None
                for row in rows:
                    if expected_t3 is not None:
                        self.assertEqual(row["ready_at"], expected_t3, name)
                    else:
                        self.assertIn(row["ready_at"], {iso(CAPTURE_2, seconds=10), iso(CAPTURE_2, seconds=11)}, name)
                    observation = restarted.evidence.get_observations(row["payload_hash"])[0]
                    self.assertGreaterEqual(row["ready_at"], observation.parse_ready_at, name)
                # a second resume is a no-op
                before = durable_summary(restarted)
                again = emit.emit_response(parsed, ctx, stores=reopen(restarted), clock=SequenceClock([]))
                self.assertTrue(again.already_normalized, name)
                self.assertEqual(durable_summary(restarted), before, name)

    def test_a_resume_after_the_normalized_row_only_finishes_the_identity_rows(self):
        with scratch_root() as root:
            stores = build_stores(root)
            raw = ps.dump(small_payload())
            ctx = es.make_capture_ctx(stores, raw, t1=CAPTURE_1)
            parsed = parser.parse_odds_response(raw, ctx)
            es.seed_acquisition(stores, ctx)
            with self.assertRaises(Crash):
                emit.emit_response(parsed, ctx, stores=stores, clock=SequenceClock(
                    [iso(CAPTURE_1, seconds=0.5), iso(CAPTURE_1, seconds=1), iso(CAPTURE_1, seconds=1.000001)]),
                    checkpoint=hook_at("after_normalized_row"))
            restarted = reopen(stores)
            self.assertEqual(restarted.identity.rows(), ())                    # the registry lags behind
            done = emit.emit_response(parsed, ctx, stores=restarted, clock=SequenceClock([]))
            self.assertTrue(done.already_normalized)
            self.assertEqual(done.identity_rows_applied, 3)
            self.assertEqual(len(restarted.identity.rows()), 3)

    def test_a_normalized_acquisition_whose_artifacts_are_gone_or_altered_is_a_conflict_not_a_pass(self):
        with scratch_root() as root:
            stores = build_stores(root)
            raw = ps.dump(small_payload())
            ctx = es.make_capture_ctx(stores, raw, t1=CAPTURE_1)
            parsed, ctx, result = capture(stores, raw, ctx=ctx)
            # the PIT log is replaced by an empty one: the acquisition claims records that no longer exist
            (root / "pit.jsonl").unlink()
            with self.assertRaises(emit.EmitConflict) as caught:
                emit.emit_response(parsed, ctx, stores=reopen(stores), clock=SequenceClock([]))
            self.assertEqual(caught.exception.failure, err.AdapterFailure.PIT_APPEND_CONFLICT)

    def test_a_crash_never_lets_a_second_observation_appear_for_the_same_artifact(self):
        with scratch_root() as root:
            stores = build_stores(root)
            raw = ps.dump(small_payload())
            ctx = es.make_capture_ctx(stores, raw, t1=CAPTURE_1)
            parsed = parser.parse_odds_response(raw, ctx)
            es.seed_acquisition(stores, ctx)
            with self.assertRaises(Crash):
                emit.emit_response(parsed, ctx, stores=stores, clock=SequenceClock(
                    [iso(CAPTURE_1, seconds=0.5)]), checkpoint=hook_at("after_observation:0"))
            restarted = reopen(stores)
            emit.emit_response(parsed, ctx, stores=restarted, clock=SequenceClock(
                [iso(CAPTURE_1, seconds=5), iso(CAPTURE_1, seconds=6), iso(CAPTURE_1, seconds=7)]))
            for row in pit_rows(restarted):
                found = [o for o in restarted.evidence.get_observations(row["payload_hash"])
                         if o.contract_id == restarted.contract_id]
                self.assertEqual(len(found), 1)
            first = restarted.evidence.get_observations(pit_rows(restarted)[0]["payload_hash"])[0]
            self.assertEqual(first.parse_ready_at, iso(CAPTURE_1, seconds=0.5))     # the pre-crash T2 stands
            second = restarted.evidence.get_observations(pit_rows(restarted)[1]["payload_hash"])[0]
            self.assertEqual(second.parse_ready_at, iso(CAPTURE_1, seconds=0.5))    # one T2 for the response (HA-06)


if __name__ == "__main__":
    unittest.main()
