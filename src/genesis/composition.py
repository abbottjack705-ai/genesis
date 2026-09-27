"""Single pinned composition root of the offline PAPER authority graph (C-1).

One deployment manifest names the file of every owner kind relative to the
deployment root and pins the risk policy. ``compose_paper_deployment`` reads
it only when its SHA-256 equals the operator's pin, binds every owner kind to
the risk log in one durable row before any owner is used, constructs every
owner eagerly and verifies the complete binding at startup. A deployment whose
binding already names other owners, for example one first composed piecemeal
over a copied bankroll, is refused instead of operated, so the authority graph
cannot silently fork. A QualificationAuthority for the deployment must record
into ``PaperDeployment.qualifications`` (E1 binds an authority to its store).

PAPER only: the root wires no adapter, enables no live mode and creates no
qualification, strategy, mode or bankroll record.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from .decision_output import (
    DecisionOutputStore, StrategyOutputApprovalStore, StrategyOutputRuleBindingStore,
)
from .execution import (
    CriticalEvidenceRefreshStore, ExecutionMarketStateStore, ModeStateStore,
    PaperExecutionAdapter, RegistryStrategyExecutionView,
)
from .ledger import SettlementLedger
from .owner_binding import OWNER_KINDS, RiskOwnerBinding, same_owner_identity
from .policy import PolicySet
from .registry import RegistryConflict, StrategyRegistry
from .release_proof import OfflinePaperReleaseProofStore
from .repro import canonical_json, immutable_write, sha256_bytes
from .risk import BankrollSnapshotStore, RiskAuditLog, RiskEngine, SafetyStateStore
from .selection import QualificationRecordStore


MANIFEST_SCHEMA = "genesis-paper-deployment-manifest-v1"
MANIFEST_NAME = "deployment-manifest.json"
MANIFEST_OWNERS = frozenset(OWNER_KINDS | {"risk_log"})
DEFAULT_LAYOUT: dict[str, str] = {
    "risk_log": "risk/risk.jsonl",
    "bankroll": "risk/bankroll.jsonl",
    "safety": "risk/safety.jsonl",
    "qualification": "risk/qualifications.jsonl",
    "qualification_binding": "risk/strategy-output-bindings.jsonl",
    "qualification_approval": "risk/strategy-output-approvals-v2.jsonl",
    "decision_output": "risk/decision-outputs",
    "strategy": "risk/strategies.jsonl",
    "mode": "risk/mode.jsonl",
    "order": "orders.jsonl",
    "market": "markets.jsonl",
    "refresh": "refreshes.jsonl",
    "release_proof": "release-proofs.jsonl",
    "ledger": "ledger.jsonl",
}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RegistryConflict(f"deployment manifest repeats a key: {key}")
        result[key] = value
    return result


def _manifest_body(policy: PolicySet, owners: dict[str, str]) -> dict[str, Any]:
    body = {
        "schema_version": MANIFEST_SCHEMA,
        "scope": "PAPER",
        "policy_digest": policy.digest,
        "owners": dict(sorted(owners.items())),
    }
    _validate(body)
    return body


def _validate(body: Any) -> dict[str, Any]:
    if type(body) is not dict or set(body) != {"schema_version", "scope", "policy_digest", "owners"}:
        raise RegistryConflict("deployment manifest is not the exact closed schema")
    if (body["schema_version"], body["scope"]) != (MANIFEST_SCHEMA, "PAPER"):
        raise RegistryConflict("deployment manifest is not a PAPER deployment of this schema")
    digest = body["policy_digest"]
    if type(digest) is not str or len(digest) != 64 or digest.lower() != digest:
        raise RegistryConflict("deployment manifest policy digest is invalid")
    int(digest, 16)
    owners = body["owners"]
    if type(owners) is not dict or set(owners) != MANIFEST_OWNERS:
        raise RegistryConflict("deployment manifest must name every owner kind exactly once")
    seen: list[str] = []
    for kind, relative in owners.items():
        path = PurePosixPath(relative) if type(relative) is str else None
        if (
            path is None or not relative or path.is_absolute() or "\\" in relative
            or path.as_posix() != relative
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise RegistryConflict(f"deployment owner path is not a plain relative path: {kind}")
        if any(same_owner_identity(relative, other) for other in seen):
            raise RegistryConflict(f"deployment owners share a path: {kind}")
        seen.append(relative)
    return body


def write_deployment_manifest(
    root: str | Path, *, policy: PolicySet, owners: dict[str, str] | None = None,
) -> str:
    """Write the deployment's immutable manifest; return the SHA-256 to pin."""

    raw = canonical_json(_manifest_body(policy, dict(owners or DEFAULT_LAYOUT)))
    immutable_write(Path(root) / MANIFEST_NAME, raw)
    return sha256_bytes(raw)


def _read_manifest(root: Path, pin: str) -> dict[str, Any]:
    raw = (root / MANIFEST_NAME).read_bytes()
    if sha256_bytes(raw) != pin:
        raise RegistryConflict("deployment manifest does not match its pinned SHA-256")
    try:
        body = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RegistryConflict("deployment manifest is not canonical JSON") from exc
    if canonical_json(body) != raw:
        raise RegistryConflict("deployment manifest is not canonical JSON")
    return _validate(body)


@dataclass(frozen=True)
class PaperDeployment:
    """The one verified PAPER authority graph of a deployment root."""

    root: Path
    manifest_sha256: str
    policy: PolicySet
    risk: RiskEngine
    execution: PaperExecutionAdapter
    ledger: SettlementLedger
    release_proofs: OfflinePaperReleaseProofStore
    qualifications: QualificationRecordStore
    strategies: StrategyRegistry
    modes: ModeStateStore


def compose_paper_deployment(
    root: str | Path,
    *,
    manifest_sha256: str,
    policy: PolicySet,
    action_clock: Callable[[str], str] | None = None,
) -> PaperDeployment:
    """Compose, bind and verify every owner of a pinned PAPER deployment (C-1)."""

    root = Path(root).resolve(strict=True)
    manifest = _read_manifest(root, manifest_sha256)
    if not isinstance(policy, PolicySet) or policy.digest != manifest["policy_digest"]:
        raise RegistryConflict("risk policy differs from the deployment manifest")
    paths = {kind: root / relative for kind, relative in manifest["owners"].items()}
    for path in paths.values():
        if not path.resolve().is_relative_to(root):
            raise RegistryConflict("deployment owner path leaves the deployment root")
    owners = {kind: paths[kind] for kind in OWNER_KINDS}

    # Eager binding: every owner kind in one durable row, before any owner acts.
    audit_log = RiskAuditLog(paths["risk_log"])
    binding = RiskOwnerBinding(audit_log.log)
    binding.register(owners)
    if set(binding.bound()) != OWNER_KINDS or binding.mismatches(owners):
        raise RegistryConflict("deployment owner binding differs from its pinned manifest")

    qualifications = QualificationRecordStore(
        paths["qualification"],
        outputs=DecisionOutputStore(paths["decision_output"]),
        bindings=StrategyOutputRuleBindingStore(paths["qualification_binding"]),
        approvals=StrategyOutputApprovalStore(paths["qualification_approval"]),
    )
    strategies = StrategyRegistry(paths["strategy"])
    modes = ModeStateStore(paths["mode"])
    risk = RiskEngine(
        policy=policy,
        bankrolls=BankrollSnapshotStore(paths["bankroll"]),
        qualifications=qualifications,
        safety=SafetyStateStore(paths["safety"]),
        audit_log=audit_log,
        strategies=strategies,
        modes=modes,
        action_clock=action_clock,
    )
    execution = PaperExecutionAdapter(
        paths["order"],
        risk=risk,
        markets=ExecutionMarketStateStore(paths["market"]),
        refreshes=CriticalEvidenceRefreshStore(paths["refresh"]),
        strategy_view=RegistryStrategyExecutionView(strategies),
        modes=modes,
        action_clock=action_clock,
    )
    ledger = SettlementLedger(paths["ledger"])
    release_proofs = OfflinePaperReleaseProofStore(
        paths["release_proof"], risk=risk, execution=execution, ledger=ledger,
    )
    risk.attach_release_proofs(release_proofs)

    # Startup verification over every owner the composed graph actually uses.
    if risk.owner_mismatches(
        execution._execution_owner_paths(execution.strategy_view, modes),
        release_proofs=release_proofs,
    ):
        raise RegistryConflict("composed deployment owners differ from their binding")
    return PaperDeployment(
        root=root, manifest_sha256=manifest_sha256, policy=policy, risk=risk,
        execution=execution, ledger=ledger, release_proofs=release_proofs,
        qualifications=qualifications, strategies=strategies, modes=modes,
    )
