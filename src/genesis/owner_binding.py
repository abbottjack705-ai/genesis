"""Durable one-owner-per-kind binding of a risk authority (T5 / N2).

A risk authority acts through exactly one owner per authority kind: one
bankroll, safety, qualification (with its output, binding and approval stores),
strategy and mode owner, one order log with its market and refresh stores, and
one release-proof log with its settlement ledger. Individually valid but
different owners, such as a copied log at another path, must never admit,
consume, submit, prove or release on behalf of that authority.

An owner's identity is its resolved location relative to the risk log's
directory. The same owner reopened through another object or an equivalent
path is therefore the same owner, and a complete deployment relocated as one
tree keeps its bindings. A copy at another path is a different owner even when
its bytes are identical. A file with a second name (hard link), or reached
through a file symlink or its Windows short name, is not an owner under
either name: no transaction writes while its target or any read-lock
participant is or has such an alias (registry single-name rule, T6 F-3b).

The binding is kept in a sidecar append-only JSONL next to the risk log, not in
the risk log itself, so risk history and its row counts are unchanged. Each
kind is bound the first time a constructor presents an owner for it and is
never rebound. Actions verify every owner they use against the durable binding
and fail closed on a mismatch or an unbound kind; a constructor never raises for
a mismatch, so a mismatched composition can still be opened for audit reads.
Deleting the sidecar is a history rewrite, like editing any other JSONL
authority, and is outside the same-user trust boundary.

The binding is also enforced in the reverse direction for the owners that
carry portfolio capacity or candidate lineage: the bankroll, the qualification
log and the decision-output store. Each has a write-once claim sidecar naming
the one risk log it serves, so a second risk log composed over the same owners
can neither admit the same candidate again nor spend the same bankroll under a
separate open-liability ceiling. Safety, mode, strategy, market, refresh,
order, proof and ledger owners may legitimately be shared (one kill switch, one
strategy catalogue) and carry no claim.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from .registry import AppendOnlyJsonl, RegistryConflict


OWNER_BINDING_SCHEMA = "risk-owner-binding-v1"
OWNER_KINDS = frozenset({
    "bankroll",
    "safety",
    "qualification",
    "qualification_binding",
    "qualification_approval",
    "decision_output",
    "strategy",
    "mode",
    "order",
    "market",
    "refresh",
    "release_proof",
    "ledger",
})
EXCLUSIVE_KINDS = frozenset({"bankroll", "qualification", "decision_output"})
OWNER_CLAIM_SCHEMA = "risk-owner-claim-v1"
_ROW_FIELDS = frozenset({
    "record_type", "schema_version", "owners", "previous_hash", "sequence", "record_hash",
})
_CLAIM_FIELDS = frozenset({
    "record_type", "schema_version", "kind", "risk_log",
    "previous_hash", "sequence", "record_hash",
})


def log_path(owner: object) -> Path | None:
    """The JSONL path of a durable owner, or None for an absent/non-durable one."""

    log = getattr(owner, "log", None)
    return log.path if isinstance(log, AppendOnlyJsonl) else None


def owner_identity(path: str | Path, anchor: str | Path) -> str:
    """Owner location relative to the risk log directory.

    Only the directory is resolved; the final name is kept literally. This is
    exactly how an owner's coordinator lock (``<name>.coordinator.sqlite3``
    beside it) resolves, so one identity always means one lock. An owner
    reached through a file symlink takes another lock and is therefore
    another owner, which fails closed like the existing mode-owner check.
    """

    path = Path(path)
    located = path.parent.resolve() / path.name
    try:
        relative = os.path.relpath(located, Path(anchor).resolve())
    except ValueError:
        # Another Windows drive has no relative form; its absolute path is the
        # only identity, so relocating such a split deployment fails closed.
        return located.as_posix()
    return Path(relative).as_posix()


def _same(left: str, right: str) -> bool:
    return os.path.normcase(left) == os.path.normcase(right)


def claim_log(path: str | Path) -> AppendOnlyJsonl:
    """Write-once sidecar naming the single risk log an exclusive owner serves."""

    path = Path(path)
    return AppendOnlyJsonl(path.with_name(f"{path.name}.risk-authority.jsonl"))


def _claimed(kind: str, path: Path) -> str | None:
    rows = claim_log(path).records()
    if not rows:
        return None
    row = rows[0]
    if (
        len(rows) != 1
        or set(row) != _CLAIM_FIELDS
        or row.get("record_type") != "risk_owner_claimed"
        or row.get("schema_version") != OWNER_CLAIM_SCHEMA
        or row.get("kind") != kind
        or not isinstance(row.get("risk_log"), str)
        or not row["risk_log"]
    ):
        raise RegistryConflict("risk owner claim is invalid or ambiguous")
    return row["risk_log"]


class RiskOwnerBinding:
    """Sidecar owner manifest of exactly one risk log."""

    def __init__(self, risk_log: AppendOnlyJsonl):
        self.risk_log_path = risk_log.path
        self.anchor = risk_log.path.parent
        self.log = AppendOnlyJsonl(
            risk_log.path.with_name(f"{risk_log.path.name}.owners.jsonl")
        )

    @staticmethod
    def _replay(rows: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> dict[str, str]:
        bound: dict[str, str] = {}
        for row in rows:
            owners = row.get("owners")
            if (
                set(row) != _ROW_FIELDS
                or row.get("record_type") != "risk_owner_bound"
                or row.get("schema_version") != OWNER_BINDING_SCHEMA
                or not isinstance(owners, dict)
                or not owners
            ):
                raise RegistryConflict("unsupported risk owner binding row")
            for kind, identity in owners.items():
                if (
                    kind not in OWNER_KINDS
                    or not isinstance(identity, str)
                    or not identity
                    or kind in bound
                ):
                    raise RegistryConflict("risk owner binding is invalid or ambiguous")
                bound[kind] = identity
        return bound

    def bound(self) -> dict[str, str]:
        return self._replay(self.log.records())

    def _identities(self, owners: Mapping[str, Path | None]) -> dict[str, tuple[str, Path]]:
        unknown = set(owners) - OWNER_KINDS
        if unknown:
            raise ValueError(f"unknown risk owner kinds: {sorted(unknown)}")
        return {
            kind: (owner_identity(path, self.anchor), Path(path))
            for kind, path in owners.items() if path is not None
        }

    def _risk_log_from(self, owner_path: Path) -> str:
        """This risk log's identity as seen from an owner's directory."""

        return owner_identity(self.risk_log_path, owner_path.parent)

    def _claims_self(self, kind: str, owner_path: Path) -> bool:
        claimed = _claimed(kind, owner_path)
        return claimed is not None and _same(claimed, self._risk_log_from(owner_path))

    def register(
        self, owners: Mapping[str, Path | None], *, anchors: tuple[str, ...] = (),
    ) -> None:
        """Bind each presented, still-unbound kind; never rebind or raise on a mismatch.

        ``anchors`` are presented kinds that must already be this authority's
        owners (or be bound together now) before anything else is bound, so a
        composition over a foreign order log cannot claim an unbound ledger.
        An exclusive owner is claimed only once it is this authority's bound
        owner, so a mismatched copy never acquires a claim.
        """

        presented = self._identities(owners)

        def build(rows: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
            bound = self._replay(rows)
            if any(
                kind in bound and not _same(bound[kind], presented[kind][0])
                for kind in anchors if kind in presented
            ):
                return None
            new = {
                kind: identity for kind, (identity, _path) in presented.items()
                if kind not in bound
            }
            if not new:
                return None
            return {
                "record_type": "risk_owner_bound",
                "schema_version": OWNER_BINDING_SCHEMA,
                "owners": dict(sorted(new.items())),
            }

        self.log.transaction(build)
        bound = self.bound()
        for kind, (identity, path) in presented.items():
            if kind in EXCLUSIVE_KINDS and kind in bound and _same(bound[kind], identity):
                claim = {
                    "record_type": "risk_owner_claimed",
                    "schema_version": OWNER_CLAIM_SCHEMA,
                    "kind": kind,
                    "risk_log": self._risk_log_from(path),
                }
                claim_log(path).transaction(lambda rows, claim=claim: None if rows else claim)

    def mismatches(self, *owner_sets: Mapping[str, Path | None]) -> tuple[str, ...]:
        """Kinds whose presented owner is unbound, not the bound owner, or claimed elsewhere.

        Several sets may present the same kind (risk's and execution's
        strategy owner, for example); every presented owner must match.
        """

        bound = self.bound()
        found: set[str] = set()
        for owners in owner_sets:
            for kind, (identity, path) in self._identities(owners).items():
                if kind not in bound or not _same(bound[kind], identity):
                    found.add(kind)
                elif kind in EXCLUSIVE_KINDS and not self._claims_self(kind, path):
                    found.add(kind)
        return tuple(sorted(found))
