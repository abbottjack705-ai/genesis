"""AREA I: provider completeness / ABSENT tombstones from unproven provider omission."""
from boot import *
import copy
def docs_by_state(rt):
    out = {}
    for d in documents(rt):
        out.setdefault(d["market_state"], 0); out[d["market_state"]] += 1
    return out

def two_captures(second_payload_fn, base_fn=None, second_headers=JSON):
    with scratch_root() as root:
        rt = open_rt(root, script=[odds_response((base_fn or (lambda p: p))(parp.odds_payload())),
                                   odds_response(second_payload_fn(parp.odds_payload()))])
        rt.acquire(odds_item("w1"))
        approve(rt)
        s1 = docs_by_state(rt)
        rt.clock.advance(seconds=900)
        r2 = rt.acquire(odds_item("w2"))
        s2 = docs_by_state(rt)
        cov = [c["note"] for c in coverage_rows(rt) if "PARTIAL" in c.get("note","") or "ABSENT" in c.get("note","")]
        return {"after1": s1, "after2": s2, "outcome": (r2.outcome.outcome, str(r2.outcome.failure)),
                "absent_cov": sorted(set(cov)), "pit_rows": len(pit_rows(rt))}

R = {}
only17 = lambda p: [f for f in p if f["tournamentId"] == 17]
R["V1_requested_tournament_8_omitted"] = two_captures(only17)
R["V2_all_omitted_empty_list"] = two_captures(lambda p: [])
def with_empty_8(p):
    for f in p:
        if f["tournamentId"] == 8:
            f["bookmakerOdds"] = {}; f["hasOdds"] = False
    return p
R["V5_tournament_8_present_but_empty"] = two_captures(with_empty_8)
def sport_wrong(p):
    for f in p:
        if f["tournamentId"] == 8: f["sportId"] = 11
    return p
R["V6_tournament_8_wrong_sport"] = two_captures(sport_wrong)
def str_tid(p):
    for f in p:
        if f["tournamentId"] == 8: f["tournamentId"] = "8"
    return p
R["V7_tournament_8_id_as_string"] = two_captures(str_tid)
# V4: fixture-level omission INSIDE a present tournament: base has 3 fixtures (two in T8), second returns only one of T8's
def three_fixtures(p):
    extra = copy.deepcopy([f for f in p if f["tournamentId"] == 8][0])
    extra["fixtureId"] = "id1000001761302000"; extra["participant1Id"] = 71; extra["participant2Id"] = 72
    p.append(extra); return p
def second_drops_one_t8_fixture(p):
    p = three_fixtures(p)
    return [f for f in p if f["fixtureId"] != "id1000001761302000"]
R["V4_fixture_level_omission_inside_present_tournament"] = two_captures(second_drops_one_t8_fixture, base_fn=three_fixtures)
for k, v in R.items():
    print(k, json.dumps(v))
