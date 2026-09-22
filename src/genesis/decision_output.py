"""Strict immutable v3 output contracts; a stored hash is not trust by itself."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol

from .policy import canonical_decimal
from .registry import AppendOnlyJsonl, RegistryConflict, StrategyDecisionContract
from .repro import canonical_json, immutable_write, sha256_bytes
from .time import iso_utc, parse_utc


OUTPUT_FIELDS = frozenset({
    "domain", "schema_version", "feature_manifest_hash", "evidence_pack_hash",
    "strategy_decision_contract_hash", "strategy_config_hash", "odds_profile_hash",
    "sport_adapter_version", "market_capability_id", "model_artifact_hash",
    "calibration_artifact_hash", "gate_policy_hash", "model_runner_hash",
    "calibration_runner_hash", "tier_rule_hash", "expiry_rule_hash",
    "resolver_binding_hash", "strategy_id", "strategy_version", "model_version",
    "sport", "market_family", "event_id", "market_id", "selection_id", "side",
    "evidence_cutoff_ts", "decision_at", "model_probability",
    "calibrated_probability", "conservative_probability", "model_support_status",
    "calibration_status", "uncertainty_status", "critical_uncertainty_flags",
    "support_region_id", "observed_odds", "requested_odds_min",
    "requested_odds_max", "approved_tier", "expires_at",
    "comparability_group_id", "selection_dependency_group",
    "correlation_cluster_ids", "meeting_id", "competition_id",
    "participant_ids", "shared_evidence_ids",
})
OUTPUT_DIGEST_FIELDS = frozenset({
    "feature_manifest_hash", "evidence_pack_hash", "strategy_decision_contract_hash",
    "strategy_config_hash", "odds_profile_hash", "model_artifact_hash",
    "calibration_artifact_hash", "gate_policy_hash", "model_runner_hash",
    "calibration_runner_hash", "tier_rule_hash", "expiry_rule_hash",
    "resolver_binding_hash",
})
OUTPUT_NULLABLE_FIELDS = frozenset({
    "meeting_id", "competition_id", "selection_dependency_group",
})
OUTPUT_ARRAY_FIELDS = frozenset({
    "critical_uncertainty_flags", "correlation_cluster_ids", "participant_ids",
    "shared_evidence_ids",
})
OUTPUT_DECIMAL_FIELDS = frozenset({
    "model_probability", "calibrated_probability", "conservative_probability",
    "observed_odds", "requested_odds_min", "requested_odds_max",
})
OUTPUT_TIME_FIELDS = frozenset({"evidence_cutoff_ts", "decision_at", "expires_at"})
OUTPUT_TIERS = frozenset({"1.0u", "1.5u", "2.0u", "2.5u", "3.0u"})


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate decision-output key: {key}")
        result[key] = value
    return result


def _digest(value: object, name: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or value.lower() != value:
        raise ValueError(f"{name} is not lowercase SHA-256 hex")
    int(value, 16)


def validate_decision_output(body: dict) -> dict:
    """Validate encoding only; trusted rule reproduction is a separate gate."""

    if not isinstance(body, dict) or set(body) != OUTPUT_FIELDS:
        raise ValueError("decision output is not the exact closed v1 schema")
    if (body["domain"], body["schema_version"]) != (
        "genesis.decision-output.v1", "decision-output-v1",
    ):
        raise ValueError("unsupported decision output domain/schema")
    for name in OUTPUT_DIGEST_FIELDS:
        _digest(body[name], name)
    for name in OUTPUT_FIELDS - OUTPUT_DIGEST_FIELDS - OUTPUT_ARRAY_FIELDS - OUTPUT_DECIMAL_FIELDS - OUTPUT_TIME_FIELDS - OUTPUT_NULLABLE_FIELDS - {"domain", "schema_version"}:
        if not isinstance(body[name], str) or not body[name]:
            raise ValueError(f"missing decision output identity: {name}")
    for name in OUTPUT_NULLABLE_FIELDS:
        if body[name] is not None and (
            not isinstance(body[name], str) or not body[name]
        ):
            raise ValueError(f"invalid nullable decision output field: {name}")
    for name in OUTPUT_ARRAY_FIELDS:
        items = body[name]
        if not isinstance(items, list) or any(
            not isinstance(item, str) or not item for item in items
        ) or items != sorted(set(items)):
            raise ValueError(f"{name} must be a sorted unique string array")
    for name in OUTPUT_TIME_FIELDS:
        if not isinstance(body[name], str) or body[name] != iso_utc(body[name]):
            raise ValueError(f"{name} must be canonical UTC")
    if not (
        parse_utc(body["evidence_cutoff_ts"]) <= parse_utc(body["decision_at"])
        < parse_utc(body["expires_at"])
    ):
        raise ValueError("output cutoff/decision/expiry order is invalid")
    decimals: dict[str, Decimal] = {}
    for name in OUTPUT_DECIMAL_FIELDS:
        value = body[name]
        if not isinstance(value, str):
            raise ValueError(f"{name} must be a decimal string")
        try:
            parsed = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"{name} is not a decimal") from exc
        if not parsed.is_finite() or value.startswith("-") or value != canonical_decimal(parsed):
            raise ValueError(f"{name} is not canonical nonnegative decimal")
        decimals[name] = parsed
    if any(decimals[name] > 1 for name in (
        "model_probability", "calibrated_probability", "conservative_probability",
    )):
        raise ValueError("decision probability is outside [0,1]")
    if any(decimals[name] <= 1 for name in (
        "observed_odds", "requested_odds_min", "requested_odds_max",
    )) or decimals["requested_odds_min"] > decimals["requested_odds_max"]:
        raise ValueError("decision odds or price bounds are invalid")
    if body["side"] not in {"back", "lay"}:
        raise ValueError("decision side is unsupported")
    if body["approved_tier"] not in OUTPUT_TIERS:
        raise ValueError("decision tier is outside the existing five tiers")
    return body


class DecisionOutputStore:
    """Content-addressed storage; publication alone cannot authorize a bet."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def publish(self, body: dict) -> str:
        validate_decision_output(body)
        digest = sha256_bytes(canonical_json(body))
        immutable_write(self.root / f"{digest}.json", canonical_json(body))
        return digest

    def get(self, digest: str) -> dict:
        _digest(digest, "decision output hash")
        raw = (self.root / f"{digest}.json").read_bytes()
        body = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
        )
        validate_decision_output(body)
        if raw != canonical_json(body) or sha256_bytes(raw) != digest:
            raise ValueError("decision output object hash mismatch")
        return body


BINDING_FIELDS = frozenset({
    "domain", "schema_version", "strategy_decision_contract_hash",
    "active_policy_digest", "approved_tier_policy_id", "model_artifact_hash",
    "calibration_artifact_hash", "feature_manifest_hash", "gate_policy_hash",
    "model_runner_hash", "calibration_runner_hash", "tier_rule_hash",
    "expiry_rule_hash", "resolver_artifact_hash", "scope", "valid_from",
    "valid_through", "human_approval_reference",
})
BINDING_DIGEST_FIELDS = frozenset({
    "strategy_decision_contract_hash", "active_policy_digest", "model_artifact_hash",
    "calibration_artifact_hash", "feature_manifest_hash", "gate_policy_hash",
    "model_runner_hash", "calibration_runner_hash", "tier_rule_hash",
    "expiry_rule_hash", "resolver_artifact_hash",
})


def validate_rule_binding(body: dict) -> dict:
    if not isinstance(body, dict) or set(body) != BINDING_FIELDS:
        raise ValueError("strategy output binding is not the exact closed v1 schema")
    if (body["domain"], body["schema_version"], body["scope"]) != (
        "genesis.strategy-output-rule-binding.v1", "strategy-output-rule-binding-v1",
        "PAPER",
    ):
        raise ValueError("unsupported output binding domain/schema/scope")
    for name in BINDING_DIGEST_FIELDS:
        _digest(body[name], name)
    for name in ("approved_tier_policy_id", "human_approval_reference"):
        if not isinstance(body[name], str) or not body[name]:
            raise ValueError(f"missing output binding authority: {name}")
    if not isinstance(body["valid_from"], str) or body["valid_from"] != iso_utc(body["valid_from"]):
        raise ValueError("binding valid_from must be canonical UTC")
    end = body["valid_through"]
    if end is not None and (not isinstance(end, str) or end != iso_utc(end)
                            or parse_utc(end) <= parse_utc(body["valid_from"])):
        raise ValueError("binding valid_through is invalid")
    return body


def rule_binding_hash(body: dict) -> str:
    return sha256_bytes(canonical_json(validate_rule_binding(body)))


class StrategyOutputRuleBindingStore:
    """Operator-owned binding registry; registration is not human approval."""

    def __init__(self, path: str | Path):
        self.log = AppendOnlyJsonl(path)

    def register_approved(self, body: dict) -> str:
        validate_rule_binding(body)
        digest = rule_binding_hash(body)
        payload = {
            "record_type": "strategy_output_rule_binding_approved",
            "binding_hash": digest, "binding": body,
        }

        def build(rows: tuple[dict, ...]) -> dict | None:
            matching = [row for row in rows if row.get("binding_hash") == digest]
            if matching:
                if len(matching) != 1 or matching[0].get("record_type") != payload["record_type"] \
                        or matching[0].get("binding") != body:
                    raise RegistryConflict("ambiguous output rule binding")
                return None
            return payload

        self.log.transaction(build)
        return digest

    def revoke(self, binding_hash: str, *, revoked_at: str) -> None:
        _digest(binding_hash, "binding hash")
        timestamp = iso_utc(revoked_at)

        def build(rows: tuple[dict, ...]) -> dict:
            self._require_from_rows(rows, binding_hash, timestamp)
            if any(row.get("record_type") == "strategy_output_rule_binding_revoked"
                   and row.get("binding_hash") == binding_hash for row in rows):
                raise RegistryConflict("binding already revoked")
            return {"record_type": "strategy_output_rule_binding_revoked",
                    "binding_hash": binding_hash, "revoked_at": timestamp}

        self.log.transaction(build)

    @staticmethod
    def _require_from_rows(rows: tuple[dict, ...] | list[dict], digest: str, at: str) -> dict:
        matches = [row for row in rows if row.get("record_type") ==
                   "strategy_output_rule_binding_approved" and row.get("binding_hash") == digest]
        if len(matches) != 1:
            raise RegistryConflict("missing or ambiguous approved output binding")
        body = matches[0].get("binding")
        if rule_binding_hash(body) != digest:
            raise RegistryConflict("approved output binding content mismatch")
        for row in rows:
            if row.get("record_type") not in {
                "strategy_output_rule_binding_approved",
                "strategy_output_rule_binding_revoked",
            }:
                raise RegistryConflict("unsupported output binding history")
            if row.get("record_type") == "strategy_output_rule_binding_revoked":
                if row.get("binding_hash") == digest:
                    raise RegistryConflict("output binding is revoked")
        peers = [row for row in rows
                 if row.get("record_type") == "strategy_output_rule_binding_approved"
                 and row.get("binding", {}).get("strategy_decision_contract_hash")
                 == body["strategy_decision_contract_hash"]]
        active_peers = []
        for peer in peers:
            peer_body = peer.get("binding")
            peer_hash = peer.get("binding_hash")
            if rule_binding_hash(peer_body) != peer_hash:
                raise RegistryConflict("conflicting output binding history")
            if (parse_utc(peer_body["valid_from"]) <= parse_utc(at)
                    and (peer_body["valid_through"] is None
                         or parse_utc(at) <= parse_utc(peer_body["valid_through"]))
                    and not any(row.get("record_type") == "strategy_output_rule_binding_revoked"
                                and row.get("binding_hash") == peer_hash for row in rows)):
                active_peers.append(peer_hash)
        if len(active_peers) != 1:
            raise RegistryConflict("ambiguous active output binding")
        if parse_utc(at) < parse_utc(body["valid_from"]) or (
            body["valid_through"] is not None
            and parse_utc(at) > parse_utc(body["valid_through"])
        ):
            raise RegistryConflict("output binding is not active at decision time")
        return body

    def require_active(self, digest: str, at: str) -> dict:
        _digest(digest, "binding hash")
        return self._require_from_rows(self.log.records(), digest, at)


class PinnedDecisionResolver(Protocol):
    artifact_hash: str

    def reproduce(
        self, *, binding: dict, manifest: dict, pack: Any,
        contract: StrategyDecisionContract, policy: Any,
    ) -> dict: ...


class TrustedDecisionOutputAuthority:
    """Recompute exact outputs from approved rules, never from candidate copies."""

    def __init__(
        self, *, outputs: DecisionOutputStore,
        bindings: StrategyOutputRuleBindingStore,
        resolver: PinnedDecisionResolver | None,
        approval_root: str | Path | None = None,
    ):
        self.outputs = outputs
        self.bindings = bindings
        self.resolver = resolver
        self.approval_root = Path(approval_root) if approval_root is not None else None

    def _validate_approval_reference(
        self, reference: str, *, binding_hash: str, decision_at: str,
    ) -> None:
        """Resolve a separate operator-owned exact approval, not a caller string."""

        if self.approval_root is None:
            raise ValueError("no separately approved strategy-output authority exists")
        _digest(reference, "human approval reference")
        raw = (self.approval_root / f"{reference}.json").read_bytes()
        note = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        if (not isinstance(note, dict) or set(note) != {
            "domain", "schema_version", "binding_hash", "approved_by",
            "approved_at", "scope",
        } or note["domain"] != "genesis.strategy-output-approval.v1"
                or note["schema_version"] != "strategy-output-approval-v1"
                or note["scope"] != "PAPER"
                or note["binding_hash"] != binding_hash
                or not isinstance(note["approved_by"], str)
                or not note["approved_by"]
                or note["approved_at"] != iso_utc(note["approved_at"])
                or parse_utc(note["approved_at"]) > parse_utc(decision_at)
                or raw != canonical_json(note)
                or sha256_bytes(raw) != reference):
            raise ValueError("separate strategy-output approval is missing or mismatched")

    def verify(
        self, output_hash: str, *, manifest: dict, pack: Any,
        contract: StrategyDecisionContract, policy: Any,
    ) -> dict:
        output = self.outputs.get(output_hash)
        binding = self.bindings.require_active(
            output["resolver_binding_hash"], output["decision_at"]
        )
        self._validate_approval_reference(
            binding["human_approval_reference"],
            binding_hash=output["resolver_binding_hash"],
            decision_at=output["decision_at"],
        )
        if self.resolver is None or self.resolver.artifact_hash != binding["resolver_artifact_hash"]:
            raise ValueError("exact approved resolver is unavailable")
        for field, expected in (
            ("strategy_decision_contract_hash", contract.contract_hash),
            ("active_policy_digest", policy.digest),
            ("approved_tier_policy_id", contract.approved_tier_policy_id),
            ("model_artifact_hash", contract.model_artifact_hash),
            ("calibration_artifact_hash", contract.calibration_artifact_hash),
            ("feature_manifest_hash", contract.feature_manifest_hash),
            ("gate_policy_hash", contract.gate_policy_hash),
        ):
            if binding[field] != expected:
                raise ValueError(f"binding {field} differs from active strategy/policy")
        for field, expected in (
            ("feature_manifest_hash", pack.feature_manifest_hash),
            ("evidence_pack_hash", pack.pack_hash),
            ("strategy_decision_contract_hash", contract.contract_hash),
            ("strategy_config_hash", contract.strategy_config_hash),
            ("odds_profile_hash", contract.odds_profile_hash),
            ("sport_adapter_version", contract.sport_adapter_version),
            ("market_capability_id", contract.market_capability_id),
            ("model_artifact_hash", contract.model_artifact_hash),
            ("calibration_artifact_hash", contract.calibration_artifact_hash),
            ("gate_policy_hash", contract.gate_policy_hash),
            ("comparability_group_id", contract.comparability_group_id),
            ("strategy_id", contract.strategy_id),
            ("strategy_version", contract.strategy_version),
            ("support_region_id", contract.support_region),
            ("event_id", manifest["event_id"]),
            ("market_id", manifest["market_id"]),
            ("evidence_cutoff_ts", manifest["evidence_cutoff_ts"]),
            ("resolver_binding_hash", output["resolver_binding_hash"]),
        ):
            if output[field] != expected:
                raise ValueError(f"output {field} differs from exact authority")
        for field in ("model_runner_hash", "calibration_runner_hash",
                      "tier_rule_hash", "expiry_rule_hash"):
            if output[field] != binding[field]:
                raise ValueError(f"output {field} differs from approved binding")
        reproduced = self.resolver.reproduce(
            binding=binding, manifest=manifest, pack=pack,
            contract=contract, policy=policy,
        )
        validate_decision_output(reproduced)
        if canonical_json(reproduced) != canonical_json(output):
            raise ValueError("trusted resolver did not reproduce decision outputs")
        return output
