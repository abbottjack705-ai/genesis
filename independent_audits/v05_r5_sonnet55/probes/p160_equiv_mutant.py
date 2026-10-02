"""Q: is the R3 'equivalent' survivor really equivalent? Build, via PUBLIC store APIs, a RESPONSE document derived under a
scope that was NOT the one pinned on the sent row, publish it as the normalized observation, and ask verify_derivation."""
from boot import *
import dataclasses
from genesis_adapters.oddspapi import derivation, normalize, parser, scope as scope_mod, emit
from genesis.provenance import AvailabilityClass
with scratch_root() as root:
    clock = FixedClock(START, step_micros=1000)
    rt = open_rt(root, clock=clock, script=[odds_response()])
    rt.acquire(odds_item("w1")); approve(rt)
    rows = derivation.acquisition_rows(rt.stores.acquisition, [r for r in acquisition_rows(rt) if r["record_type"] == "acq_planned"][0]["acquisition_id"])
    aid = rows["acq_planned"]["acquisition_id"]
    pinned = rows["acq_sent"]["expected_scope_hash"]
    # a different scope: one fake expected book that the response does NOT contain -> yields an extra ABSENT tombstone
    real_scope = scope_mod.load_scope(root, pinned)
    some = next(iter(rt.stores.pit.log.records()))
    docs = documents(rt); d0 = docs[0]
    fake = scope_mod.ExpectedBook(entity_id="book:" + "ab" * 32, event_id=d0["event_id"], competition_id=d0["competition_id"],
                                  provider_fixture_id=d0["provider_fixture_id"], home_participant_id=d0["home_participant_id"],
                                  away_participant_id=d0["away_participant_id"], scheduled_start_as_known=d0["scheduled_start_as_known"],
                                  bookmaker_id=d0["bookmaker_id"], provider_bookmaker_key=d0["provider_bookmaker_key"], market_id=d0["market_id"],
                                  market_family=d0["market_family"], line=d0["line"], period=d0["period"])
    other = dict(real_scope); other[fake.entity_id] = fake
    other_hash = scope_mod.publish_scope(root, other.values(), as_of=START)
    prefix = rt.stores.identity.prefix(rows["acq_normalized"]["identity_registry_head"]["sequence"])
    inputs = derivation.odds_inputs(rt.stores, rt.config, rt.maps, aid, identity_prefix=prefix, expected_scope=other,
                                    expected_scope_hash=other_hash, fixture_join=None, request_root=root)
    parsed = parser.parse_odds_response(inputs.raw, inputs.ctx)
    built = {x.entity_id: x for x in normalize.build_documents(parsed, inputs.ctx)}
    victim = fake.entity_id
    doc = built[victim]
    print("alt-scope derivation produced an extra", doc.state, "document; pinned-scope hash differs:", other_hash != pinned)
    uri = emit.response_source_uri(rt.stores.derivation_version, doc.entity_id, inputs.ctx.raw_observation_id)
    obs = rt.stores.evidence.publish(doc.data, contract_id=rt.stores.contract_id, source_uri=uri, provider="oddspapi",
        source_type="oddspapi_v4_market_book", retrieved_at=inputs.ctx.response_received_at, parse_ready_at=parp.iso_add(inputs.ctx.response_received_at, seconds=1),
        first_seen_at=inputs.ctx.response_received_at, publisher_timestamp=doc.publisher_timestamp, valid_from=inputs.ctx.response_received_at, valid_to=doc.valid_to,
        upstream_version="v4", parser_version=rt.stores.derivation_version, content_type="application/json", licensing_note=rt.stores.licensing_note,
        availability_class=AvailabilityClass.DERIVED)
    try:
        rt.verify_derivation(obs.observation_id); print("RESULT: verify_derivation ACCEPTED a document derived under an unpinned scope")
    except Exception as e:
        print("RESULT: verify_derivation REJECTED:", type(e).__name__, str(e)[:90])
