from __future__ import annotations

import itertools
import unittest
from dataclasses import replace

from genesis.canonical import CandidateBet, MarketSide
from genesis.repro import sha256_bytes
from genesis.selection import SelectionDecision, rank_qualified


def identity(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def candidate(
    candidate_id: str,
    *,
    tier: str = "2.0u",
    group: str | None = "group-1",
    odds: str = "2.00",
    probability: str = "0.60",
    market_family: str = "match_winner",
    stable_identity: str | None = None,
) -> CandidateBet:
    return CandidateBet(
        candidate_id=candidate_id,
        strategy_id="strategy",
        strategy_version="v1",
        sport="football",
        event_id=f"event-{candidate_id}",
        market_id=f"market-{candidate_id}",
        selection_id=f"selection-{candidate_id}",
        side=MarketSide.BACK,
        requested_odds_min="1.40",
        requested_odds_max="3.00",
        observed_odds=odds,
        model_probability=probability,
        conservative_probability=probability,
        model_version="model-v1",
        evidence_pack_id=identity("pack"),
        decision_at="2026-01-01T00:00:00Z",
        expires_at="2026-01-01T01:00:00Z",
        evidence_complete=True,
        strategy_tier=tier,
        market_family=market_family,
        comparability_group_id=group,
        candidate_decision_hash=stable_identity or identity(candidate_id),
    )


def qualified(item: CandidateBet) -> tuple[CandidateBet, SelectionDecision]:
    return (
        item,
        SelectionDecision(
            item.candidate_id,
            "QUALIFY",
            (),
            identity(f"qualification-{item.candidate_id}"),
        ),
    )


def ranked_ids(items) -> list[str]:
    return [item.candidate_id for item in rank_qualified([qualified(item) for item in items])]


class R4RankingTests(unittest.TestCase):
    def test_short_price_has_no_region_bonus_within_comparable_group(self):
        short = candidate("short", odds="1.45", probability="0.51")
        normal = candidate("normal", odds="2.00", probability="0.80")
        self.assertEqual(ranked_ids((short, normal)), ["normal", "short"])

    def test_crossing_exceptional_boundary_alone_does_not_change_order(self):
        first = candidate("first", odds="1.50", probability="0.60")
        second = candidate("second", odds="1.50", probability="0.60")
        before = ranked_ids((first, second))
        after = ranked_ids((replace(first, observed_odds="1.49"), second))
        self.assertEqual(before, after)

    def test_incomparable_groups_use_round_robin_not_global_probability(self):
        low = candidate(
            "low",
            group="group-low",
            odds="1.45",
            probability="0.51",
            stable_identity="1" * 64,
        )
        high_one = candidate(
            "high-one",
            group="group-high",
            odds="2.00",
            probability="0.90",
            stable_identity="2" * 64,
        )
        high_two = candidate(
            "high-two",
            group="group-high",
            odds="2.00",
            probability="0.80",
            stable_identity="3" * 64,
        )
        # One item is taken per group before the second item from any group.
        self.assertEqual(ranked_ids((high_two, low, high_one)), ["low", "high-one", "high-two"])

    def test_market_and_group_label_renames_have_no_quality_effect(self):
        first = candidate("first", group="aaa", market_family="aaa", probability="0.70")
        second = candidate("second", group="zzz", market_family="zzz", probability="0.90")
        before = ranked_ids((first, second))
        renamed = (
            replace(first, comparability_group_id="zzz-renamed", market_family="zzz-renamed"),
            replace(second, comparability_group_id="aaa-renamed", market_family="aaa-renamed"),
        )
        self.assertEqual(ranked_ids(renamed), before)

    def test_tier_then_within_group_quality_then_stable_identity_is_deterministic(self):
        items = (
            candidate("low-tier", tier="1.0u", probability="0.99"),
            candidate("strong", tier="2.0u", probability="0.80"),
            candidate("tie-b", tier="2.0u", probability="0.60", stable_identity="b" * 64),
            candidate("tie-a", tier="2.0u", probability="0.60", stable_identity="a" * 64),
        )
        expected = ["strong", "tie-a", "tie-b", "low-tier"]
        for permutation in itertools.permutations(items):
            self.assertEqual(ranked_ids(permutation), expected)

    def test_missing_comparability_group_is_rejected(self):
        with self.assertRaises(ValueError):
            rank_qualified([qualified(candidate("missing", group=None))])


if __name__ == "__main__":
    unittest.main()
