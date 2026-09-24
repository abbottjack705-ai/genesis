"""Proof of complete synthetic PAPER order settlement, never a venue adapter.

This owner derives a release proof from verified risk, order, qualification and
fill/settlement histories.  It has no API for a caller to assert terminality or
no-more-matchability. For matched orders, favorable execution odds, a terminal
PAPER disposition and terminal heads for *every* fill are mandatory. A
deterministic synthetic PAPER cancellation may prove either zero fills or a
closed unmatched remainder after partial fills; a live remainder has no
positive path. These proofs are deliberately local/offline and are not venue
reconciliation.

The proof is an issuance-time fact.  Later valid same-fill corrections remain
lawful; a new fill or changed order history makes the proof unusable for new
capacity.  Call ``validate_current_locked`` inside a risk transaction holding
``authority_logs`` plus this store's log.  The standalone ``validate_current``
method acquires that same set for diagnostic/test reads.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .accounting import BetSide, SettlementKind
from .registry import AppendOnlyJsonl, RegistryConflict
from .repro import canonical_json, sha256_bytes
from .time import iso_utc, parse_utc

if TYPE_CHECKING:
    from .execution import PaperExecutionAdapter
    from .ledger import SettlementLedger
    from .risk import RiskEngine


PROOF_SCHEMA = "offline-paper-release-proof-v1"
LEGACY_PROOF_SCHEMA = "offline-paper-legacy-release-proof-v1"
_PROOF_FIELDS = frozenset({
    "record_type", "schema_version", "proof_id", "scope", "approval_id",
    "qualification_record_id", "candidate_decision_hash", "decision_output_hash",
    "order_id", "order_head_record_hash", "fill_proofs", "matched_stake",
    "matched_liability", "release_reason", "no_more_matchability_basis", "occurred_at",
})
_LEGACY_PROOF_FIELDS = frozenset(
    (_PROOF_FIELDS - {"decision_output_hash"})
    | {"legacy_qualification_record_hash"}
)
_ENVELOPE_FIELDS = frozenset({"previous_hash", "sequence", "record_hash"})
_FILL_PROOF_FIELDS = frozenset({
    "fill_id", "fill_record_hash", "head_event_id", "head_record_hash",
})
_REASON_BASES = {
    "FILLS_SETTLED": frozenset({
        "FULL_INTENT_STAKE_MATCHED",
        "SYNTHETIC_PAPER_CANCELLED_REMAINDER_COMPLETE",
    }),
    "FILLS_VOID": frozenset({
        "FULL_INTENT_STAKE_MATCHED",
        "SYNTHETIC_PAPER_CANCELLED_REMAINDER_COMPLETE",
    }),
    "UNMATCHED_CANCEL_CONFIRMED": frozenset({
        "SYNTHETIC_PAPER_CANCELLED_ZERO_FILLS",
    }),
    "UNSENT_REJECTED": frozenset({
        "SYNTHETIC_PAPER_REJECTED_BEFORE_SEND",
        "UNCONSUMED_APPROVAL_NO_ORDER",
    }),
}


class OfflinePaperReleaseProofStore:
    """Synthetic PAPER full-settlement proof owner; no live or partial release."""

    def __init__(
        self,
        path: str | Path,
        *,
        risk: RiskEngine,
        execution: PaperExecutionAdapter,
        ledger: SettlementLedger,
    ) -> None:
        if any(owner is None for owner in (risk, execution, ledger)):
            raise TypeError("release proof requires risk, execution and ledger owners")
        self.log = AppendOnlyJsonl(path)
        self.risk = risk
        self.execution = execution
        self.ledger = ledger
        # These are precisely the mutable JSONL heads read in the derivation.
        # Immutable content-addressed output bytes are represented by the
        # verified V3 qualification identity; operational qualification is a
        # separate gate and is not granted by this proof.
        self.authority_logs = (
            risk.audit_log.log,
            risk.qualifications.log,
            execution._audit,
            ledger.log,
        )
        self._proofs(tuple(self.log.records()))

    @staticmethod
    def _proofs(rows: tuple[dict[str, Any], ...]) -> dict[str, dict[str, Any]]:
        by_order: dict[str, dict[str, Any]] = {}
        by_approval: set[str] = set()
        for row in rows:
            legacy = row.get("schema_version") == LEGACY_PROOF_SCHEMA
            fields = _LEGACY_PROOF_FIELDS if legacy else _PROOF_FIELDS
            expected_record_type = (
                "offline_paper_legacy_release_proof"
                if legacy else "offline_paper_release_proof"
            )
            expected_scope = (
                "LEGACY_AUDIT_SETTLEMENT_ONLY"
                if legacy else "SYNTHETIC_PAPER_ONLY"
            )
            if (
                set(row) != fields | _ENVELOPE_FIELDS
                or row.get("record_type") != expected_record_type
                or row.get("schema_version")
                != (LEGACY_PROOF_SCHEMA if legacy else PROOF_SCHEMA)
                or row.get("scope") != expected_scope
                or row.get("release_reason") not in _REASON_BASES
                or row.get("no_more_matchability_basis")
                not in _REASON_BASES.get(row.get("release_reason"), frozenset())
                or (
                    legacy
                    and row.get("release_reason") not in {"FILLS_SETTLED", "FILLS_VOID"}
                )
            ):
                raise RegistryConflict("unsupported offline PAPER release proof row")
            fill_proofs = row.get("fill_proofs")
            if (
                not isinstance(fill_proofs, list)
                or any(not isinstance(item, dict) or set(item) != _FILL_PROOF_FIELDS
                       for item in fill_proofs)
                or [item["fill_id"] for item in fill_proofs]
                != sorted({item["fill_id"] for item in fill_proofs})
                or (row["release_reason"] in {"FILLS_SETTLED", "FILLS_VOID"}
                    and not fill_proofs)
                or (row["release_reason"] in {
                    "UNMATCHED_CANCEL_CONFIRMED", "UNSENT_REJECTED",
                } and fill_proofs)
            ):
                raise RegistryConflict("release proof fill set is not closed and ordered")
            body = {key: row[key] for key in fields if key != "proof_id"}
            if row["proof_id"] != sha256_bytes(canonical_json(body)):
                raise RegistryConflict("release proof identity differs from its content")
            if any(
                not isinstance(row[field], str) or len(row[field]) != 64
                for field in (
                    "approval_id", "qualification_record_id", "candidate_decision_hash",
                    (
                        "legacy_qualification_record_hash"
                        if legacy else "decision_output_hash"
                    ),
                )
            ) or (
                row["order_id"] is None
                and row["order_head_record_hash"] is not None
            ) or (
                row["order_id"] is not None
                and (
                    not isinstance(row["order_id"], str) or len(row["order_id"]) != 64
                    or not isinstance(row["order_head_record_hash"], str)
                    or len(row["order_head_record_hash"]) != 64
                )
            ) or (
                row["order_id"] is None
                and (
                    row["release_reason"] != "UNSENT_REJECTED"
                    or row["no_more_matchability_basis"]
                    != "UNCONSUMED_APPROVAL_NO_ORDER"
                )
            ) or (legacy and row["order_id"] is None):
                raise RegistryConflict("release proof identity field is invalid")
            for item in fill_proofs:
                if (
                    not isinstance(item["fill_id"], str) or not item["fill_id"]
                    or not isinstance(item["head_event_id"], str) or not item["head_event_id"]
                    or any(not isinstance(item[field], str) or len(item[field]) != 64
                           for field in ("fill_record_hash", "head_record_hash"))
                ):
                    raise RegistryConflict("release proof fill identity is invalid")
            try:
                matched_stake = Decimal(row["matched_stake"])
                matched_liability = Decimal(row["matched_liability"])
                if matched_stake < 0 or matched_liability < 0:
                    raise RegistryConflict("release proof matched amount is invalid")
                if row["release_reason"] in {"FILLS_SETTLED", "FILLS_VOID"}:
                    if matched_stake <= 0:
                        raise RegistryConflict("settlement proof has no matched stake")
                elif matched_stake != 0 or matched_liability != 0:
                    raise RegistryConflict("zero-fill proof has matched exposure")
                parse_utc(row["occurred_at"])
            except (ValueError, TypeError) as exc:
                if isinstance(exc, RegistryConflict):
                    raise
                raise RegistryConflict("release proof amount/time is invalid") from exc
            order_id = row["order_id"] or f"approval:{row['approval_id']}"
            approval_id = row["approval_id"]
            if order_id in by_order or approval_id in by_approval:
                raise RegistryConflict("more than one release proof for an order/approval")
            by_order[order_id] = row
            by_approval.add(approval_id)
        return by_order

    def _snapshot(
        self,
        order_id: str,
        *,
        risk_rows: tuple[dict[str, Any], ...],
        qualification_rows: tuple[dict[str, Any], ...],
        order_rows: tuple[dict[str, Any], ...],
        ledger_rows: tuple[dict[str, Any], ...],
        at: str | None,
        enforce_order_void: bool = True,
        legacy_only: bool = False,
    ) -> dict[str, Any]:
        """Derive exact full-settlement facts; all supplied rows must be fenced."""

        from .risk import RiskApproval

        try:
            records = self.execution._replay(order_rows)
        except RegistryConflict:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise RegistryConflict("release proof order replay is invalid") from exc
        order = records.get(order_id)
        if order is None:
            raise RegistryConflict("release proof order is unknown")
        history = [state.value for state in order.state_history]
        if (
            order.intent.mode.value != "paper"
            or any(state in {"UNKNOWN", "RECONCILIATION_REQUIRED"} for state in history)
        ):
            raise RegistryConflict("synthetic PAPER terminal disposition is not trustworthy")
        order_events = [row for row in order_rows if row.get("order_id") == order_id]
        order_head = order_events[-1]
        sent_events = [
            row for row in order_events
            if row.get("record_type") == "order_state_transition"
            and row.get("to_state") == "SUBMISSION_SENT"
        ]
        if order.state.value in {"SETTLED", "VOID"}:
            if (
                order_head.get("to_state") != order.state.value
                or len(sent_events) != 1
                or "FULLY_MATCHED" not in history
            ):
                raise RegistryConflict("full synthetic PAPER settlement has not been proved")
            disposition = "FILLED"
        elif order.state.value == "CANCELLED":
            common_cancel = (
                order_head.get("to_state") == "CANCELLED"
                and len(sent_events) == 1
                and {"ACK_RECEIVED", "CANCEL_PENDING"}.issubset(history)
                and "FULLY_MATCHED" not in history
            )
            if not common_cancel:
                raise RegistryConflict("unmatched PAPER cancellation is not complete")
            if "PARTIALLY_MATCHED" in history:
                disposition = "PARTIAL_CANCELLED"
            elif "UNMATCHED" in history:
                disposition = "UNMATCHED_CANCELLED"
            else:
                raise RegistryConflict("cancelled PAPER order has no exact match disposition")
        elif order.state.value == "REJECTED":
            if (
                order_head.get("to_state") != "REJECTED"
                or sent_events
                or "SUBMISSION_PENDING" in history
            ):
                raise RegistryConflict("PAPER rejection was not conclusively pre-send")
            disposition = "UNSENT_REJECTED"
        else:
            raise RegistryConflict("order has no supported terminal PAPER disposition")
        if legacy_only and disposition != "FILLED":
            raise RegistryConflict("legacy proof is limited to matched terminal settlement")
        sent_at = parse_utc(sent_events[0]["occurred_at"]) if sent_events else None
        terminal_at = parse_utc(order_head["occurred_at"])
        if sent_at is not None and terminal_at < sent_at:
            raise RegistryConflict("terminal order head predates its send")

        approval_rows = [
            row for row in risk_rows
            if row.get("record_type") == "risk_approval_created"
            and row.get("schema_version") == "risk-approval-v2"
            and row.get("approval_id") == order.intent.risk_approval_id
        ]
        if len(approval_rows) != 1:
            raise RegistryConflict("order has no exact risk approval")
        try:
            fields = {
                key: approval_rows[0][key] for key in RiskApproval.__dataclass_fields__
            }
            fields["side"] = BetSide(fields["side"])
            approval = RiskApproval(**fields)
        except (KeyError, TypeError, ValueError) as exc:
            raise RegistryConflict("release proof risk approval is invalid") from exc
        consumptions = [
            row for row in risk_rows
            if row.get("record_type") == "risk_approval_consumed"
            and row.get("approval_id") == approval.approval_id
        ]
        if (
            len(consumptions) != 1
            or consumptions[0].get("order_id") != order_id
            or consumptions[0].get("candidate_decision_hash")
            != approval.candidate_decision_hash
            or order.intent.candidate_decision_hash != approval.candidate_decision_hash
            or order.intent.side != approval.side
            or Decimal(order.intent.stake) != Decimal(approval.approved_stake)
            or Decimal(order.intent.odds) != Decimal(approval.odds)
            or order.intent.liability != Decimal(approval.approved_liability)
        ):
            raise RegistryConflict("release proof lacks exact consumed approval binding")

        qualification_row_matches = [
            row for row in qualification_rows
            if row.get("record_type") == "qualification_record"
            and row.get("qualification_record_id") == approval.qualification_record_id
        ]
        if len(qualification_row_matches) != 1:
            raise RegistryConflict("release proof qualification is ambiguous")
        qualification_row = qualification_row_matches[0]
        qualification = self.risk.qualifications._from_row(qualification_row)
        if qualification.candidate_decision_hash != approval.candidate_decision_hash:
            raise RegistryConflict("release proof qualification/candidate lineage differs")
        if legacy_only:
            if qualification.schema_version != "qualification-record-v2":
                raise RegistryConflict("legacy proof requires exact V2 qualification lineage")
            lineage = {
                "legacy_qualification_record_hash": qualification_row["record_hash"],
            }
        else:
            if (
                qualification.schema_version != "qualification-record-v3"
                or qualification.decision_output_hash is None
            ):
                raise RegistryConflict("release proof lacks exact V3 output lineage")
            lineage = {"decision_output_hash": qualification.decision_output_hash}

        ledger_state = self.ledger._replay(ledger_rows)
        fills = sorted(
            (fill for fill in ledger_state.fills.values() if fill.order_id == order_id),
            key=lambda fill: fill.fill_id,
        )
        if disposition in {"UNMATCHED_CANCELLED", "UNSENT_REJECTED"}:
            if fills:
                raise RegistryConflict("zero-fill disposition has a recorded fill")
            if at is not None and parse_utc(order_head["occurred_at"]) > parse_utc(at):
                raise RegistryConflict("release proof predates the terminal order head")
            return {
                "approval_id": approval.approval_id,
                "qualification_record_id": approval.qualification_record_id,
                "candidate_decision_hash": approval.candidate_decision_hash,
                **lineage,
                "order_id": order_id,
                "order_head_record_hash": order_head["record_hash"],
                "fill_proofs": [],
                "matched_stake": "0",
                "matched_liability": "0",
                "release_reason": (
                    "UNMATCHED_CANCEL_CONFIRMED"
                    if disposition == "UNMATCHED_CANCELLED" else "UNSENT_REJECTED"
                ),
                "no_more_matchability_basis": (
                    "SYNTHETIC_PAPER_CANCELLED_ZERO_FILLS"
                    if disposition == "UNMATCHED_CANCELLED"
                    else "SYNTHETIC_PAPER_REJECTED_BEFORE_SEND"
                ),
            }
        if not fills:
            raise RegistryConflict("zero-fill sent order has no settlement proof")
        fill_rows = {
            row["fill_id"]: row for row in ledger_rows
            if row.get("record_type") == "fill"
        }
        head_rows = {
            row["event_id"]: row for row in ledger_rows
            if row.get("record_type") in {"settlement", "cancellation"}
        }
        fill_proofs: list[dict[str, str]] = []
        stake_total = Decimal("0")
        liability_total = Decimal("0")
        all_void = True
        for fill in fills:
            if (
                fill.candidate_decision_hash != approval.candidate_decision_hash
                or fill.side != order.intent.side
                or sent_at is None
                or parse_utc(fill.filled_at) < sent_at
                or parse_utc(fill.filled_at) > terminal_at
            ):
                raise RegistryConflict("fill is not in the exact sent order lineage")
            if (
                (fill.side == BetSide.BACK and Decimal(fill.odds) < Decimal(order.intent.odds))
                or (fill.side == BetSide.LAY and Decimal(fill.odds) > Decimal(order.intent.odds))
            ):
                raise RegistryConflict("fill price exceeds the approved exposure envelope")
            head = ledger_state.heads.get(fill.fill_id)
            if head is None or head.settlement_kind not in set(SettlementKind):
                raise RegistryConflict("every fill requires a current terminal head")
            all_void &= head.settlement_kind == SettlementKind.VOID
            if at is not None and (
                parse_utc(head.occurred_at) > parse_utc(at)
                or parse_utc(fill.filled_at) > parse_utc(at)
            ):
                raise RegistryConflict("release proof predates a fill or settlement head")
            stake_total += Decimal(fill.stake)
            liability_total += fill.fragment().liability
            fill_proofs.append({
                "fill_id": fill.fill_id,
                "fill_record_hash": fill_rows[fill.fill_id]["record_hash"],
                "head_event_id": head.event_id,
                "head_record_hash": head_rows[head.event_id]["record_hash"],
            })
        intent_stake = Decimal(order.intent.stake)
        stake_complete = (
            Decimal("0") < stake_total < intent_stake
            if disposition == "PARTIAL_CANCELLED"
            else stake_total == intent_stake
        )
        if not stake_complete or liability_total > Decimal(approval.approved_liability):
            raise RegistryConflict("recorded fills do not close the approved envelope")
        if enforce_order_void and order.state.value == "VOID" and not all_void:
            raise RegistryConflict("VOID order has a non-void current fill head")
        if at is not None and parse_utc(order_head["occurred_at"]) > parse_utc(at):
            raise RegistryConflict("release proof predates the terminal order head")
        return {
            "approval_id": approval.approval_id,
            "qualification_record_id": approval.qualification_record_id,
            "candidate_decision_hash": approval.candidate_decision_hash,
            **lineage,
            "order_id": order_id,
            "order_head_record_hash": order_head["record_hash"],
            "fill_proofs": fill_proofs,
            "matched_stake": format(stake_total, "f"),
            "matched_liability": format(liability_total, "f"),
            "release_reason": "FILLS_VOID" if all_void else "FILLS_SETTLED",
            "no_more_matchability_basis": (
                "SYNTHETIC_PAPER_CANCELLED_REMAINDER_COMPLETE"
                if disposition == "PARTIAL_CANCELLED"
                else "FULL_INTENT_STAKE_MATCHED"
            ),
        }

    def _unconsumed_snapshot(
        self,
        approval_id: str,
        *,
        risk_rows: tuple[dict[str, Any], ...],
        qualification_rows: tuple[dict[str, Any], ...],
        order_rows: tuple[dict[str, Any], ...],
        ledger_rows: tuple[dict[str, Any], ...],
        at: str | None,
    ) -> dict[str, Any]:
        """Derive the narrow no-order/no-consumption release case."""

        from .risk import RiskApproval

        matches = [
            row for row in risk_rows
            if row.get("record_type") == "risk_approval_created"
            and row.get("schema_version") == "risk-approval-v2"
            and row.get("approval_id") == approval_id
        ]
        if len(matches) != 1:
            raise RegistryConflict("unconsumed release approval is ambiguous")
        try:
            fields = {key: matches[0][key] for key in RiskApproval.__dataclass_fields__}
            fields["side"] = BetSide(fields["side"])
            approval = RiskApproval(**fields)
        except (KeyError, TypeError, ValueError) as exc:
            raise RegistryConflict("unconsumed release approval is invalid") from exc
        if any(
            row.get("record_type") == "risk_approval_consumed"
            and row.get("approval_id") == approval_id
            for row in risk_rows
        ):
            raise RegistryConflict("approval was already consumed")
        if any(
            row.get("record_type") == "order_intent_created"
            and row.get("risk_approval_id") == approval_id
            for row in order_rows
        ):
            raise RegistryConflict("approval already has an order intent")
        if any(
            row.get("record_type") == "fill"
            and row.get("candidate_decision_hash") == approval.candidate_decision_hash
            for row in ledger_rows
        ):
            raise RegistryConflict("unconsumed approval has an unexplained fill")
        qualification_matches = [
            self.risk.qualifications._from_row(row)
            for row in qualification_rows
            if row.get("record_type") == "qualification_record"
            and row.get("qualification_record_id") == approval.qualification_record_id
        ]
        if len(qualification_matches) != 1:
            raise RegistryConflict("unconsumed release qualification is ambiguous")
        qualification = qualification_matches[0]
        if (
            qualification.schema_version != "qualification-record-v3"
            or qualification.candidate_decision_hash != approval.candidate_decision_hash
            or qualification.decision_output_hash is None
        ):
            raise RegistryConflict("unconsumed release lacks exact V3 output lineage")
        if at is not None and parse_utc(at) < parse_utc(approval.issued_at):
            raise RegistryConflict("unconsumed release predates approval")
        return {
            "approval_id": approval.approval_id,
            "qualification_record_id": approval.qualification_record_id,
            "candidate_decision_hash": approval.candidate_decision_hash,
            "decision_output_hash": qualification.decision_output_hash,
            "order_id": None,
            "order_head_record_hash": None,
            "fill_proofs": [],
            "matched_stake": "0",
            "matched_liability": "0",
            "release_reason": "UNSENT_REJECTED",
            "no_more_matchability_basis": "UNCONSUMED_APPROVAL_NO_ORDER",
        }

    def validate_current_locked(
        self,
        proof_record_hash: str,
        *,
        proof_rows: tuple[dict[str, Any], ...],
        risk_rows: tuple[dict[str, Any], ...],
        qualification_rows: tuple[dict[str, Any], ...],
        order_rows: tuple[dict[str, Any], ...],
        ledger_rows: tuple[dict[str, Any], ...],
    ) -> dict[str, Any]:
        """Validate a proof under caller-held coordinator locks; return its row."""

        self._proofs(proof_rows)
        matches = [row for row in proof_rows if row["record_hash"] == proof_record_hash]
        if len(matches) != 1:
            raise RegistryConflict("release proof hash is unknown or ambiguous")
        proof = matches[0]
        legacy = proof["schema_version"] == LEGACY_PROOF_SCHEMA
        if proof["order_id"] is None:
            if legacy:
                raise RegistryConflict("legacy release proof cannot be unconsumed")
            current = self._unconsumed_snapshot(
                proof["approval_id"], risk_rows=risk_rows,
                qualification_rows=qualification_rows, order_rows=order_rows,
                ledger_rows=ledger_rows, at=None,
            )
        else:
            current = self._snapshot(
                proof["order_id"], risk_rows=risk_rows,
                qualification_rows=qualification_rows, order_rows=order_rows,
                ledger_rows=ledger_rows, at=None, enforce_order_void=False,
                legacy_only=legacy,
            )
        identity_names = (
            "approval_id", "qualification_record_id", "candidate_decision_hash",
            (
                "legacy_qualification_record_hash"
                if legacy else "decision_output_hash"
            ),
            "order_id", "order_head_record_hash",
            "matched_stake", "matched_liability", "no_more_matchability_basis",
        )
        for name in identity_names:
            if current[name] != proof[name]:
                raise RegistryConflict(f"release proof current {name} changed")
        old_fill_proofs = proof["fill_proofs"]
        current_fill_proofs = current["fill_proofs"]
        if [
            (item["fill_id"], item["fill_record_hash"]) for item in old_fill_proofs
        ] != [
            (item["fill_id"], item["fill_record_hash"]) for item in current_fill_proofs
        ]:
            raise RegistryConflict("release proof no longer covers the full fill set")
        ledger_state = self.ledger._replay(ledger_rows)
        proof_at = parse_utc(proof["occurred_at"])
        if proof["order_head_record_hash"] is not None:
            issuance_order_head = next(
                (row for row in order_rows
                 if row.get("record_hash") == proof["order_head_record_hash"]),
                None,
            )
            if (
                issuance_order_head is None
                or parse_utc(issuance_order_head["occurred_at"]) > proof_at
            ):
                raise RegistryConflict("release proof predates its order head")
        issuance_kinds: list[SettlementKind] = []
        for old, latest in zip(old_fill_proofs, current_fill_proofs):
            issuance_fill = next(
                (row for row in ledger_rows
                 if row.get("record_type") == "fill"
                 and row.get("record_hash") == old["fill_record_hash"]),
                None,
            )
            issuance_head = next(
                (row for row in ledger_rows
                 if row.get("event_id") == old["head_event_id"]),
                None,
            )
            old_event = ledger_state.events.get(old["head_event_id"])
            if (
                issuance_fill is None or issuance_head is None or old_event is None
                or old_event.fill_id != old["fill_id"]
                or issuance_head.get("record_hash") != old["head_record_hash"]
                or parse_utc(issuance_fill["filled_at"]) > proof_at
                or parse_utc(issuance_head["occurred_at"]) > proof_at
            ):
                raise RegistryConflict("release proof lacks issuance-time fill heads")
            issuance_kinds.append(old_event.settlement_kind)
            if old["head_event_id"] == latest["head_event_id"]:
                if old["head_record_hash"] != latest["head_record_hash"]:
                    raise RegistryConflict("release proof settlement head was rewritten")
                continue
            ancestor_id = latest["head_event_id"]
            while ancestor_id != old["head_event_id"]:
                ancestor = ledger_state.events.get(ancestor_id)
                if ancestor is None or ancestor.fill_id != old["fill_id"] \
                        or ancestor.correction_of is None:
                    raise RegistryConflict("release proof settlement head is not a same-fill descendant")
                if parse_utc(ancestor.occurred_at) <= proof_at:
                    raise RegistryConflict("release proof named a stale issuance head")
                ancestor_id = ancestor.correction_of
            ancestor_row = next(
                (row for row in ledger_rows if row.get("event_id") == ancestor_id), None
            )
            if ancestor_row is None or ancestor_row["record_hash"] != old["head_record_hash"]:
                raise RegistryConflict("release proof settlement ancestor was rewritten")
        expected_reason = (
            "FILLS_VOID"
            if issuance_kinds and all(kind == SettlementKind.VOID for kind in issuance_kinds)
            else "FILLS_SETTLED"
            if issuance_kinds
            else current["release_reason"]
        )
        if proof["release_reason"] != expected_reason:
            raise RegistryConflict("release proof issuance reason is false")
        return proof

    def validate_current(self, proof_record_hash: str) -> dict[str, Any]:
        """Standalone fenced read; risk admission should use the locked variant."""

        result: dict[str, Any] = {}

        def inspect(proof_rows: tuple[dict[str, Any], ...]) -> None:
            result["proof"] = self.validate_current_locked(
                proof_record_hash,
                proof_rows=proof_rows,
                risk_rows=tuple(self.risk.audit_log.log.records()),
                qualification_rows=tuple(self.risk.qualifications.log.records()),
                order_rows=tuple(self.execution._audit.records()),
                ledger_rows=tuple(self.ledger.log.records()),
            )
            return None

        self.log.transaction(inspect, read_locks=self.authority_logs)
        return result["proof"]

    def _issue(
        self,
        order_id: str,
        *,
        occurred_at: str,
        expected_reasons: frozenset[str],
        legacy: bool = False,
    ) -> str:
        occurred_at = iso_utc(occurred_at)
        result: dict[str, str] = {}

        def build(proof_rows: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
            existing = self._proofs(proof_rows).get(order_id)
            risk_rows = tuple(self.risk.audit_log.log.records())
            qualification_rows = tuple(self.risk.qualifications.log.records())
            order_rows = tuple(self.execution._audit.records())
            ledger_rows = tuple(self.ledger.log.records())
            if existing is not None:
                expected_schema = LEGACY_PROOF_SCHEMA if legacy else PROOF_SCHEMA
                if existing["schema_version"] != expected_schema:
                    raise RegistryConflict("release proof lineage schema differs from request")
                self.validate_current_locked(
                    existing["record_hash"], proof_rows=proof_rows,
                    risk_rows=risk_rows, qualification_rows=qualification_rows,
                    order_rows=order_rows, ledger_rows=ledger_rows,
                )
                if existing["release_reason"] not in expected_reasons:
                    raise RegistryConflict("release proof disposition differs from request")
                result["proof_record_hash"] = existing["record_hash"]
                return None
            snapshot = self._snapshot(
                order_id, risk_rows=risk_rows,
                qualification_rows=qualification_rows, order_rows=order_rows,
                ledger_rows=ledger_rows, at=occurred_at,
                legacy_only=legacy,
            )
            if snapshot["release_reason"] not in expected_reasons:
                raise RegistryConflict("order does not have the requested release disposition")
            payload = {
                "record_type": (
                    "offline_paper_legacy_release_proof"
                    if legacy else "offline_paper_release_proof"
                ),
                "schema_version": LEGACY_PROOF_SCHEMA if legacy else PROOF_SCHEMA,
                "scope": (
                    "LEGACY_AUDIT_SETTLEMENT_ONLY"
                    if legacy else "SYNTHETIC_PAPER_ONLY"
                ),
                **snapshot,
                "occurred_at": occurred_at,
            }
            payload["proof_id"] = sha256_bytes(canonical_json(payload))
            return payload

        appended = self.log.transaction(build, read_locks=self.authority_logs)
        if appended is not None:
            return appended
        return result["proof_record_hash"]

    def issue_unconsumed_approval(
        self, approval_id: str, *, occurred_at: str,
    ) -> str:
        """Prove an approval has never acquired an intent, order or fill."""

        occurred_at = iso_utc(occurred_at)
        result: dict[str, str] = {}

        def build(proof_rows: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
            existing = self._proofs(proof_rows).get(f"approval:{approval_id}")
            risk_rows = tuple(self.risk.audit_log.log.records())
            qualification_rows = tuple(self.risk.qualifications.log.records())
            order_rows = tuple(self.execution._audit.records())
            ledger_rows = tuple(self.ledger.log.records())
            if existing is not None:
                self.validate_current_locked(
                    existing["record_hash"], proof_rows=proof_rows,
                    risk_rows=risk_rows, qualification_rows=qualification_rows,
                    order_rows=order_rows, ledger_rows=ledger_rows,
                )
                result["proof_record_hash"] = existing["record_hash"]
                return None
            snapshot = self._unconsumed_snapshot(
                approval_id, risk_rows=risk_rows,
                qualification_rows=qualification_rows, order_rows=order_rows,
                ledger_rows=ledger_rows, at=occurred_at,
            )
            payload = {
                "record_type": "offline_paper_release_proof",
                "schema_version": PROOF_SCHEMA,
                "scope": "SYNTHETIC_PAPER_ONLY",
                **snapshot,
                "occurred_at": occurred_at,
            }
            payload["proof_id"] = sha256_bytes(canonical_json(payload))
            return payload

        appended = self.log.transaction(build, read_locks=self.authority_logs)
        if appended is not None:
            return appended
        return result["proof_record_hash"]

    def issue_full_settlement(self, order_id: str, *, occurred_at: str) -> str:
        """Persist a proof that the full approved PAPER stake is terminal."""

        return self._issue(
            order_id, occurred_at=occurred_at,
            expected_reasons=frozenset({"FILLS_SETTLED", "FILLS_VOID"}),
        )

    def issue_legacy_full_settlement(
        self, order_id: str, *, occurred_at: str,
    ) -> str:
        """Prove settlement of an existing v2 order without inventing v3 lineage.

        This audit-only operation cannot prove an unconsumed approval,
        cancellation, qualification, risk admission or new submission.
        """

        return self._issue(
            order_id,
            occurred_at=occurred_at,
            expected_reasons=frozenset({"FILLS_SETTLED", "FILLS_VOID"}),
            legacy=True,
        )

    def issue_unmatched_cancellation(self, order_id: str, *, occurred_at: str) -> str:
        """Prove a zero-fill synthetic PAPER cancellation after acknowledgement."""

        return self._issue(
            order_id, occurred_at=occurred_at,
            expected_reasons=frozenset({"UNMATCHED_CANCEL_CONFIRMED"}),
        )

    def issue_unsent_rejection(self, order_id: str, *, occurred_at: str) -> str:
        """Prove a bound synthetic PAPER intent was rejected before any send."""

        return self._issue(
            order_id, occurred_at=occurred_at,
            expected_reasons=frozenset({"UNSENT_REJECTED"}),
        )
