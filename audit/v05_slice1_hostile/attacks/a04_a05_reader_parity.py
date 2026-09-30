"""Areas 4 and 5 (HA-002): PIT head selection and differential verifier parity.

For every scenario of ``oracle/EXPECTED_PIT_HEADS.json`` (generated from the FROZEN PIT store) the attack
rebuilds the records in real frozen stores (contract, READY capability, approved binding, one normalized
observation + PIT record per oracle record, with the oracle's exact times), then at every oracle cutoff:

1. compares ``reader.admissible_head`` with the oracle verdict;
2. builds, for EVERY record of the scenario, a manifest pinning it and runs the FROZEN
   ``FeatureInputManifestStore.verify_for_pack`` (auditor-built bodies; the candidate's builder is not used),
   so the verifier's accepted set ``V`` is known independently;
3. requires: reader usable => its record is in ``V`` (never looser, never another head); reader unusable
   while ``V`` is non-empty => the refusal is a documented adapter-only one (state, STALE-after-newer,
   AMBIGUOUS_SOURCE for two READY sources). ``|V| <= 1`` always.

    python -B attacks/a04_a05_reader_parity.py --repo <candidate> --expected oracle/EXPECTED_PIT_HEADS.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

NOTE = "FIXTURE-ONLY-NO-PROVIDER-TERMS"
EVENT, MARKET = "evt:" + "1" * 64, "mkt:" + "2" * 64
STATE_OF = {"INV": "INVALIDATED", "SUSP": "SUSPENDED"}
DOCUMENTED_STRICTER = {"STALE", "AMBIGUOUS_SOURCE", "SUSPENDED", "INVALIDATED", "ABSENT", "BLOCKED",
                       "PREMATCH_WINDOW_CLOSED"}


def build(repo: Path, root: Path, records: list[dict]):
    import dataclasses

    from genesis.evidence import EvidenceStore, StructuredEvidenceStore
    from genesis.feature_manifest import SourceInputBindingStore
    from genesis.pit import BitemporalRecord, OperationalStatus, PITStore, SourceCapability, SourceCapabilityRegistry
    from genesis.provenance import AvailabilityClass, SourceContractRegistry
    from genesis.repro import canonical_json

    from genesis_adapters import config as cfg
    from genesis_adapters.oddspapi import emit, pipeline
    from genesis_adapters.oddspapi.normalize import NormalizedDocument

    policy = cfg.load_policy(repo / "adapters" / "config" / "oddspapi_slice1_policy.json")
    sources = sorted({r["source_id"] for r in records})
    versions = {s: s[len("oddspapi.v4.soccer.market_book."):] for s in sources}
    stores_by_source = {}
    contracts = SourceContractRegistry(root / "contracts.jsonl")
    evidence = EvidenceStore(root / "evidence", contracts=contracts)
    capabilities = SourceCapabilityRegistry(root / "capabilities.jsonl")
    bindings = SourceInputBindingStore(root / "bindings.jsonl")
    pit = PITStore(root / "pit.jsonl", capabilities=capabilities)
    structured = StructuredEvidenceStore(root / "structured", evidence=evidence)
    first_time = min(c.parse(r["available_at"]) for r in records)
    for source in sources:
        version = versions[source]
        emit.register_normalized_contract(contracts, derivation_version=version, licensing_note=NOTE)
        stores = pipeline.build_stores(root, derivation_version=version, policy=policy, licensing_note=NOTE)
        stores = dataclasses.replace(stores, contracts=contracts, evidence=evidence, capabilities=capabilities,
                                     bindings=bindings, pit=pit, structured=structured)
        at = c.add(c.iso(first_time), seconds=-24 * 3600)
        capabilities.register(SourceCapability(
            source_id=source, provider="oddspapi", access_method="rest_pregame_v4", cost_tier="t",
            entitlement_class="e", historical_availability_class="none",
            point_in_time_reliability="prospective_verified", revision_behaviour="append_only_supersede",
            coverage="c", rate_quota_limits="r", schema_version="v1", operational_status=OperationalStatus.READY,
            recorded_at=at, version=f"{version}-ready-1"))
        bindings.register(source_id=source, source_contract_id=stores.contract_id, provider="oddspapi",
                          approval_reference="synthetic-test-only-audit")
        stores_by_source[source] = stores
    made = []
    for r in records:
        stores = stores_by_source[r["source_id"]]
        label = r["record_id"][4:]
        state = STATE_OF.get(label, "OPEN")
        doc = {"schema": "genesis.adapters.oddspapi.market-book.v1", "derivation_kind": "RESPONSE",
               "audit_label": label, "event_id": EVENT, "market_id": MARKET, "bookmaker_id": "bk.audit",
               "entity_id": r["entity_id"], "line": None, "market_state": state, "state_reasons": [],
               "scheduled_start_as_known": "2026-10-10T00:00:00.000000Z", "valid_from": r["valid_from"],
               "valid_to": r["valid_to"]}
        if state == "OPEN":
            doc["selections"] = {"HOME": {"odds_decimal": "2.1"}, "DRAW": {"odds_decimal": "3.3"},
                                 "AWAY": {"odds_decimal": "3.6"}}
        data = canonical_json(doc)
        document = NormalizedDocument(r["entity_id"], state, data, r["valid_from"], r["valid_to"], r["published_at"])
        observation = evidence.publish(
            data, contract_id=stores.contract_id,
            source_uri=emit.response_source_uri(stores.derivation_version, r["entity_id"], "f" * 64),
            provider="oddspapi", source_type=emit.NORMALIZED_SOURCE_TYPE, retrieved_at=r["retrieved_at"],
            first_seen_at=r["retrieved_at"], parse_ready_at=r["ready_at"], publisher_timestamp=r["published_at"],
            valid_from=r["valid_from"], valid_to=r["valid_to"], upstream_version="v4",
            parser_version=stores.derivation_version, content_type="application/json", licensing_note=NOTE,
            availability_class=AvailabilityClass.DERIVED)
        research = None
        if state == "OPEN":
            research = emit.research_evidence(document, observation, doc, stores)
            structured.publish(research)
        record = BitemporalRecord(
            record_id=emit.pit_record_id(r["source_id"], document.artifact_hash), entity_id=r["entity_id"],
            source_id=r["source_id"], payload_hash=document.artifact_hash, available_at=r["available_at"],
            published_at=r["published_at"], retrieved_at=r["retrieved_at"], ready_at=r["ready_at"],
            valid_from=r["valid_from"], valid_to=r["valid_to"], superseded_by=None, superseded_at=None)
        pit.append(record)
        made.append({"label": label, "record": record, "observation": observation, "stores": stores,
                     "research": research})
    return stores_by_source, made


def verifier_accepts(root: Path, item: dict, D: str, n: int) -> tuple[bool, str]:
    from genesis.evidence_pack import EvidencePack
    from genesis.feature_manifest import FeatureInputManifestStore, identity_transform_hash

    stores, record, observation = item["stores"], item["record"], item["observation"]
    field = "$.selections.HOME.odds_decimal"
    caps = [row for row in stores.capabilities.log.records()
            if row.get("record_type") == "source_capability_registered" and row["source_id"] == record.source_id
            and c.parse(row["recorded_at"]) <= c.parse(D)]
    pit_row = [row for row in stores.pit.log.records() if row.get("record_id") == record.record_id][0]
    if not caps:
        return False, "no capability row"
    cap = max(caps, key=lambda row: c.parse(row["recorded_at"]))
    structured = [item["research"].digest] if item["research"] is not None else []
    body = {"domain": "genesis.feature-input-manifest.v1", "schema_version": "feature-input-manifest-v1",
            "event_id": EVENT, "market_id": MARKET, "evidence_cutoff_ts": D,
            "required_inputs": [{"role": "feature", "input_key": "odds.bk.audit.HOME", "entity_id": record.entity_id,
                                 "event_id": EVENT, "market_id": MARKET, "source_id": record.source_id,
                                 "source_contract_id": stores.contract_id,
                                 "source_capability_version": cap["version"],
                                 "source_capability_record_hash": cap["record_hash"],
                                 "raw_artifact_hash": observation.artifact_hash,
                                 "observation_id": observation.observation_id, "pit_record_id": record.record_id,
                                 "pit_record_hash": pit_row["record_hash"], "field_id": field,
                                 "transform_artifact_hash": identity_transform_hash(field)}],
            "structured_evidence_hashes": structured}
    store = FeatureInputManifestStore(root / "manifests", bindings=stores.bindings)
    try:
        digest = store.publish(body)
        pack = EvidencePack.freeze(pack_id=f"audit-{n}", evidence_cutoff_ts=D, frozen_at=D,
                                   source_artifact_hashes=(observation.artifact_hash,),
                                   extractor_versions=(stores.derivation_version,), prompt_schema_hash="0" * 64,
                                   contradiction_links=(), freshness_state=(), feature_manifest_hash=digest,
                                   structured_evidence_hashes=tuple(structured) if structured else None)
        store.verify_for_pack(pack, event_id=EVENT, market_id=MARKET, pit=stores.pit, evidence=stores.evidence,
                              structured_evidence=stores.structured)
        return True, ""
    except Exception as exc:
        return False, type(exc).__name__ + ": " + str(exc)[:80]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--expected", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    repo = c.setup(args.repo)
    from genesis_adapters.oddspapi import reader

    expected = json.loads(Path(args.expected).read_text(encoding="utf-8"))
    n = 0
    table: list[dict] = []
    for scenario, spec in expected.items():
        root = c.scratch(f"{scenario[:12]}-")
        stores_by_source, made = build(repo, root, spec["records"])
        any_stores = next(iter(stores_by_source.values()))
        entity = spec["records"][0]["entity_id"]
        problems = []
        for row in spec["grid"]:
            D, verdict, sid = row["D"], row["expected"], row["source_id"]
            got = reader.admissible_head(entity, D, stores=any_stores)
            usable = isinstance(got, reader.UsableBook)
            got_label = next((m["label"] for m in made if usable and m["record"] == got.record), None)
            code = None if usable else got.code.value
            accepted = []
            for item in made:
                if item["record"].source_id != sid:
                    continue
                n += 1
                ok, _why = verifier_accepts(root, item, D, n)
                if ok:
                    accepted.append(item["label"])
            entry = {"scenario": scenario, "D": D, "source": sid[-10:], "oracle": verdict,
                     "reader": f"USABLE:{got_label}" if usable else f"UNUSABLE:{code}", "verifier_accepts": accepted}
            table.append(entry)
            # oracle vs frozen verifier (sanity of the oracle itself)
            if len(accepted) > 1:
                problems.append(("VERIFIER_NOT_UNIQUE", entry))
            if usable and got_label not in accepted:
                problems.append(("READER_LOOSER_THAN_VERIFIER", entry))
            if not usable and accepted and code not in DOCUMENTED_STRICTER:
                problems.append(("READER_UNDOCUMENTED_REFUSAL", entry))
            oracle_head = verdict.split("|")[0][5:] if verdict.startswith("HEAD:") else None
            if usable and (oracle_head != got_label or "NO_FALLBACK" in verdict):
                problems.append(("READER_DIFFERS_FROM_ORACLE", entry))
        c.check("A4/A5", f"{scenario}: reader never looser than the frozen verifier and never another head",
                not [p for p in problems if p[0] in ("READER_LOOSER_THAN_VERIFIER", "READER_DIFFERS_FROM_ORACLE",
                                                     "VERIFIER_NOT_UNIQUE")],
                problems=[(p[0], p[1]["D"], p[1]["reader"], p[1]["oracle"], p[1]["verifier_accepts"]) for p in problems][:6])
        c.check("A4/A5", f"{scenario}: every refusal where the verifier accepts is a documented adapter-only one",
                not [p for p in problems if p[0] == "READER_UNDOCUMENTED_REFUSAL"],
                problems=[(p[1]["D"], p[1]["reader"]) for p in problems if p[0] == "READER_UNDOCUMENTED_REFUSAL"][:6])
        c.remove(root)
    # HA-002: S4 window where the frozen verifier revives the OLDER open price
    s4 = [e for e in table if e["scenario"] == "S4_newer_expires_first" and e["oracle"] == "HEAD:OLD"
          and e["verifier_accepts"] == ["OLD"] and c.parse(e["D"]) >= c.parse("2026-10-03T10:30:00.000000Z")]
    c.check("A4/A5", "HA-002: in [valid_to_new, valid_to_old) the verifier revives OLD and the reader refuses STALE",
            bool(s4) and all(e["reader"] == "UNUSABLE:STALE" for e in s4), cutoffs=len(s4),
            readers=sorted({e["reader"] for e in s4}))
    s7 = [e for e in table if e["scenario"] == "S7_published_after_D" and "NO_FALLBACK" in e["oracle"]]
    c.check("A4/A5", "S7: head published after D -> NOT_PUBLISHED_AT_CUTOFF, never a fallback to OLD",
            bool(s7) and all(e["reader"] == "UNUSABLE:NOT_PUBLISHED_AT_CUTOFF" and not e["verifier_accepts"]
                             for e in s7), cutoffs=len(s7), readers=sorted({e["reader"] for e in s7}))
    s8 = [e for e in table if e["scenario"] == "S8_two_sources"]
    c.check("A4/A5", "S8: two READY market-book sources -> AMBIGUOUS_SOURCE at every cutoff (13.4)",
            all(e["reader"] == "UNUSABLE:AMBIGUOUS_SOURCE" for e in s8), readers=sorted({e["reader"] for e in s8}))
    if args.out:
        Path(args.out).with_suffix(".table.json").write_bytes((json.dumps(table, indent=0) + "\n").encode())
    return c.finish(args.out)


if __name__ == "__main__":
    sys.exit(main())
