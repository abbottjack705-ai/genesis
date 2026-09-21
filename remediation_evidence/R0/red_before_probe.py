"""Reproduce the audited F01-F15 unsafe baseline without changing production code.

The script exits successfully only when every expected unsafe behaviour is
observed.  It is deliberately outside ``tests/`` so the primary baseline suite
remains green while RED-before evidence is retained separately.
"""

from __future__ import annotations

import json
import multiprocessing
import shutil
import sys
import uuid
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from genesis.accounting import BetSide, SettlementKind
from genesis.canonical import CandidateBet, MarketSide, ResearchEvidence
from genesis.evaluation import EvaluationRequest
from genesis.evidence import EvidenceStore
from genesis.evidence_pack import EvidencePack
from genesis.execution import OrderIntent, OrderState, PaperExecutionAdapter
from genesis.labels import DecisionFact, DecisionFrame, FutureOutcomeLabel
from genesis.ledger import FillRecord, SettlementLedger
from genesis.pit import BitemporalRecord, PITStore
from genesis.protected import ProtectedAttemptLedger, ProtectedCampaign, ProtectedEvaluationBoundary
from genesis.provenance import AvailabilityClass, ProvenanceRef
from genesis.quota import QuotaLedger, QuotaPolicy
from genesis.registry import AppendOnlyJsonl
from genesis.risk import RiskAuditLog, RiskEngine
from genesis.selection import QualificationFacts, qualify_v04, rank_qualified


def digest(character: str) -> str:
    return character * 64


def candidate(
    candidate_id: str,
    *,
    odds: str = "2.00",
    probability: str = "0.55",
    tier: str | None = "2.0u",
    market_family: str = "match_winner",
) -> CandidateBet:
    return CandidateBet(
        candidate_id,
        "strategy",
        "v1",
        "football",
        "event",
        "market",
        candidate_id,
        MarketSide.BACK,
        "1.40",
        "3.00",
        odds,
        probability,
        probability,
        "model-v1",
        "pack-1",
        "2026-01-01T00:00:00Z",
        "2026-01-01T01:00:00Z",
        True,
        strategy_tier=tier,
        market_family=market_family,
        candidate_decision_hash=digest("c"),
    )


def provenance() -> ProvenanceRef:
    return ProvenanceRef(
        digest("a"),
        "synthetic-v1",
        "synthetic://fixture",
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:01Z",
        AvailabilityClass.PROSPECTIVE_CAPTURED,
        "parser-v1",
    )


def append_worker(path: str, worker: int, start: multiprocessing.synchronize.Event) -> None:
    start.wait()
    log = AppendOnlyJsonl(path)
    for item in range(10):
        log.append({"record_type": "stress", "worker": worker, "item": item})


def reproduce_f12(root: Path) -> dict[str, object]:
    context = multiprocessing.get_context("spawn")
    for attempt in range(1, 21):
        path = root / f"f12-{attempt}.jsonl"
        start = context.Event()
        processes = [context.Process(target=append_worker, args=(str(path), worker, start)) for worker in range(8)]
        for process in processes:
            process.start()
        start.set()
        for process in processes:
            process.join(20)
        errors = [process.exitcode for process in processes if process.exitcode != 0]
        try:
            count = AppendOnlyJsonl(path).verify()
            broken = count != 80
            detail = f"unexpected_count={count}" if broken else "chain_valid"
        except Exception as exc:  # expected unsafe baseline result
            broken = True
            detail = f"{type(exc).__name__}: {exc}"
        if broken:
            return {"unsafe": True, "attempt": attempt, "detail": detail, "worker_exitcodes": errors}
    return {"unsafe": False, "attempt": 20, "detail": "no fork reproduced", "worker_exitcodes": []}


def main() -> int:
    facts = QualificationFacts(**{name: True for name in QualificationFacts.__dataclass_fields__})
    results: dict[str, dict[str, object]] = {}
    root = ROOT / "work" / "r0_runtime" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    try:

        spoof = candidate("f01", tier="2.0u")
        results["F01"] = {"unsafe": qualify_v04(spoof, now="2026-01-01T00:10:00Z", facts=facts).action == "QUALIFY"}

        execution = PaperExecutionAdapter()
        execution.create_intent(OrderIntent(digest("2"), "key-a", "2.50", "2.00", "2026-01-01T00:00:00Z"))
        execution.create_intent(OrderIntent(digest("2"), "key-b", "2.50", "2.00", "2026-01-01T00:00:00Z"))
        results["F02"] = {"unsafe": True, "intents": 2}

        direct = PaperExecutionAdapter()
        direct.create_intent(OrderIntent(digest("3"), "key", "2.50", "2.00", "2026-01-01T00:00:00Z"))
        results["F03"] = {"unsafe": direct.transition("key", OrderState.RISK_APPROVED).state == OrderState.RISK_APPROVED}

        ledger = SettlementLedger(root / "f04.jsonl")
        ledger.record_fill(FillRecord("fill", "order", digest("4"), BetSide.BACK, "2.00", "2.50", "2026-01-01T00:00:00Z"))
        ledger.settle(event_id="s1", fill_id="fill", kind=SettlementKind.WIN, occurred_at="2026-01-01T01:00:00Z")
        ledger.settle(event_id="s2", fill_id="fill", kind=SettlementKind.WIN, occurred_at="2026-01-01T02:00:00Z")
        results["F04"] = {"unsafe": Decimal(ledger.total_pnl()) == Decimal("5.00"), "total_pnl": ledger.total_pnl()}

        risk = RiskEngine()
        decision = risk.approve(candidate_decision_hash=digest("5"), bankroll="100", requested_liability="50")
        results["F05"] = {"unsafe": decision.passed, "approval_id": decision.approval_id}

        pit = PITStore()
        pit.append(BitemporalRecord("r1", "e1", "unverified", digest("6"), "2025-12-31T23:00:00Z", None, "2025-12-31T23:01:00Z", "2025-12-31T23:02:00Z", "2025-12-31T23:00:00Z"))
        results["F06"] = {"unsafe": len(pit.as_of_query("e1", "2026-01-01T00:00:00Z")) == 1}

        short = candidate("short", odds="1.45", probability="0.51")
        normal = candidate("normal", odds="2.00", probability="0.80")
        ranked = rank_qualified([(short, qualify_v04(short, now="2026-01-01T00:10:00Z", facts=facts)), (normal, qualify_v04(normal, now="2026-01-01T00:10:00Z", facts=facts))])
        results["F07"] = {"unsafe": ranked[0].candidate_id == "short", "first": ranked[0].candidate_id}

        alpha = candidate("alpha", probability="0.51", market_family="aaa")
        omega = candidate("omega", probability="0.80", market_family="zzz")
        ranked = rank_qualified([(alpha, qualify_v04(alpha, now="2026-01-01T00:10:00Z", facts=facts)), (omega, qualify_v04(omega, now="2026-01-01T00:10:00Z", facts=facts))])
        results["F08"] = {"unsafe": ranked[0].candidate_id == "alpha", "first": ranked[0].candidate_id}

        missing_tier = candidate("f09", tier=None)
        decision = qualify_v04(missing_tier, now="2026-01-01T00:10:00Z", facts=facts)
        results["F09"] = {"unsafe": decision.action == "QUALIFY" and rank_qualified([(missing_tier, decision)]) == [missing_tier]}

        store = EvidenceStore(root / "f10")
        kwargs = dict(source_uri="synthetic://same", provider="test", source_type="fixture", retrieved_at="2026-01-01T00:00:00Z", parse_ready_at="2026-01-01T00:00:01Z", parser_version="v1", content_type="text/plain", licensing_note="synthetic", availability_class=AvailabilityClass.PROSPECTIVE_CAPTURED)
        store.publish(b"same", **kwargs)
        conflict = None
        try:
            store.publish(b"same", **(kwargs | {"retrieved_at": "2026-01-01T00:10:00Z", "parse_ready_at": "2026-01-01T00:10:01Z"}))
        except Exception as exc:
            conflict = type(exc).__name__
        results["F10"] = {"unsafe": conflict is not None, "error": conflict}

        evidence_a = ResearchEvidence("e", "event", "team", "claim-a", provenance(), None, "2026-01-01T00:00:00Z", "confirmed", None)
        evidence_b = ResearchEvidence("e", "event", "team", "claim-b", provenance(), None, "2026-01-01T00:00:00Z", "confirmed", None)
        pack_a = EvidencePack.freeze(pack_id="pack", evidence_cutoff_ts="2026-01-01T00:00:00Z", frozen_at="2026-01-01T00:01:00Z", source_artifact_hashes=(digest("a"),), extractor_versions=("v1",), prompt_schema_hash=digest("b"), contradiction_links=(), freshness_state=("fresh",), feature_manifest_hash=digest("c"))
        pack_b = EvidencePack.freeze(pack_id="pack", evidence_cutoff_ts="2026-01-01T00:00:00Z", frozen_at="2026-01-01T00:01:00Z", source_artifact_hashes=(digest("a"),), extractor_versions=("v1",), prompt_schema_hash=digest("b"), contradiction_links=(), freshness_state=("fresh",), feature_manifest_hash=digest("c"))
        results["F11"] = {"unsafe": evidence_a.normalized_claim != evidence_b.normalized_claim and pack_a.pack_hash == pack_b.pack_hash, "pack_hash": pack_a.pack_hash}

        results["F12"] = reproduce_f12(root)

        frame = DecisionFrame("d", "entity", "2026-01-01T00:00:00Z", (DecisionFact("signal", 1, "2025-12-31T23:00:00Z", "2025-12-31T23:01:00Z", provenance()),), "dataset", digest("c"))
        label = FutureOutcomeLabel("l", "entity", 1, "2026-01-01T01:00:00Z", provenance(), "v1")
        boundary = ProtectedEvaluationBoundary(ProtectedCampaign("campaign", "family", 1, digest("e"), minimum_cell_size=1), [frame], [label], ProtectedAttemptLedger())
        leaked = getattr(boundary._service, "_ProtectedEvaluationService__labels")
        results["F13"] = {"unsafe": leaked[0].outcome_value == 1, "leaked_label": leaked[0].outcome_value}

        quota = QuotaLedger(policy=QuotaPolicy(daily_billable_limit=999, monthly_billable_limit=220, monthly_reserve=30))
        for index in range(190):
            quota.request(request_id=str(index), occurred_at="2026-01-01T00:00:00Z")
        call_191 = quota.request(request_id="191", occurred_at="2026-01-01T00:00:00Z")
        results["F14"] = {"unsafe": not call_191.allowed, "reason": call_191.reason, "monthly_used": call_191.monthly_used}

        risk_path = root / "f15-risk.jsonl"
        original_risk = RiskEngine(audit_log=RiskAuditLog(risk_path))
        original_risk.approve(candidate_decision_hash=digest("f"), bankroll="100", requested_liability="5")
        replayed_risk = RiskEngine(audit_log=RiskAuditLog(risk_path))
        order_path = root / "f15-order.jsonl"
        original_order = PaperExecutionAdapter(order_path)
        original_order.create_intent(OrderIntent(digest("d"), "restart-key", "2.50", "2.00", "2026-01-01T00:00:00Z"))
        replayed_order = PaperExecutionAdapter(order_path)
        order_missing = False
        try:
            replayed_order.get("restart-key")
        except KeyError:
            order_missing = True
        results["F15"] = {"unsafe": not replayed_risk.reserved_exposures() and order_missing, "risk_reservations": len(replayed_risk.reserved_exposures()), "order_missing": order_missing}
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print(json.dumps(results, indent=2, sort_keys=True))
    missing = [finding for finding, result in results.items() if not result.get("unsafe")]
    if missing:
        print(f"Expected unsafe behaviour not reproduced: {', '.join(missing)}", file=sys.stderr)
        return 1
    print("ALL_EXPECTED_UNSAFE_BEHAVIOURS_REPRODUCED")
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
