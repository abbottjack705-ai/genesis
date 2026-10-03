"""AREA H: derivation verifier vs altered observation metadata with byte-identical normalized output; unknown kind; missing inputs."""
from boot import *
import dataclasses, copy
from genesis.provenance import AvailabilityClass
from genesis_adapters.oddspapi import derivation
R = {}
def base():
    root_cm = scratch_root(); root = root_cm.__enter__()
    rt = open_rt(root, script=[odds_response()])
    rt.acquire(odds_item()); approve(rt)
    row = pit_rows(rt)[0]
    obs = [o for o in rt.stores.evidence.get_observations(row["payload_hash"]) if o.contract_id == rt.stores.contract_id][0]
    return root_cm, root, rt, row, obs
cm, root, rt, row, obs = base()
data = rt.stores.evidence.get_bytes(row["payload_hash"])
R["0_control_verifies"] = "ok"
try: rt.verify_derivation(obs.observation_id)
except Exception as e: R["0_control_verifies"] = type(e).__name__ + str(e)[:60]
fields = dict(contract_id=obs.contract_id, source_uri=obs.source_uri, provider=obs.provider, source_type=obs.source_type,
              retrieved_at=obs.retrieved_at, first_seen_at=obs.first_seen_at, publisher_timestamp=obs.publisher_timestamp,
              valid_from=obs.valid_from, valid_to=obs.valid_to, upstream_version=obs.upstream_version, parser_version=obs.parser_version,
              content_type=obs.content_type, licensing_note=obs.licensing_note, availability_class=AvailabilityClass.DERIVED)
alt = {
  "retrieved_at_1h_earlier": dict(retrieved_at=parp.iso_add(obs.retrieved_at, seconds=-3600), first_seen_at=parp.iso_add(obs.first_seen_at, seconds=-3600), valid_from=parp.iso_add(obs.valid_from, seconds=-3600)),
  "valid_to_plus_10_days": dict(valid_to=parp.iso_add(obs.valid_to, seconds=864000)),
  "valid_to_removed": dict(valid_to=None),
  "publisher_timestamp_changed": dict(publisher_timestamp="2026-10-01T11:00:00.000000Z"),
  "upstream_version_changed": dict(upstream_version="v5"),
  "content_type_changed": dict(content_type="application/x-evil"),
  "parse_ready_at_earlier_than_T1": dict(),   # handled below via publish arg
}
for name, change in alt.items():
    f = dict(fields); f.update(change)
    pr = parp.iso_add(obs.parse_ready_at, seconds=-7200) if name == "parse_ready_at_earlier_than_T1" else parp.iso_add(obs.parse_ready_at, seconds=1)
    try:
        new = rt.stores.evidence.publish(data, parse_ready_at=pr, **f)
    except Exception as e:
        R["H_" + name] = "publish refused: " + type(e).__name__ + " " + str(e)[:50]; continue
    try:
        rt.verify_derivation(new.observation_id); R["H_" + name] = "VERIFIER PASSED (accepts altered metadata)"
    except Exception as e:
        R["H_" + name] = "verifier rejects: " + type(e).__name__ + " " + str(e)[:60]
# unknown derivation kind / non-dict document: publish a doc with unknown kind under the contract
doc = json.loads(data); doc["derivation_kind"] = "BOGUS"
import json as j
from genesis.repro import canonical_json
bogus = canonical_json(doc)
f = dict(fields); f["source_uri"] = obs.source_uri + "x"
try:
    new = rt.stores.evidence.publish(bogus, parse_ready_at=parp.iso_add(obs.parse_ready_at, seconds=2), **f)
    try: rt.verify_derivation(new.observation_id); R["H_unknown_kind"] = "VERIFIER PASSED"
    except Exception as e: R["H_unknown_kind"] = "verifier rejects: " + type(e).__name__ + " " + str(e)[:60]
except Exception as e: R["H_unknown_kind"] = "publish refused: " + str(e)[:60]
# missing input: remove the stored scope file / request file, then verify
import os
scope_files = list((root / "scopes").glob("*.json")); req_files = list((root / "requests").glob("*.json"))
os.chmod(scope_files[0], 0o644); scope_bak = scope_files[0].read_bytes(); scope_files[0].unlink()
try: rt.verify_derivation(obs.observation_id); R["H_missing_scope_file"] = "VERIFIER PASSED (by omission!)"
except Exception as e: R["H_missing_scope_file"] = "verifier rejects: " + type(e).__name__
scope_files[0].write_bytes(scope_bak)
os.chmod(req_files[0], 0o644); req_bak = req_files[0].read_bytes(); req_files[0].unlink()
try: rt.verify_derivation(obs.observation_id); R["H_missing_request_file"] = "VERIFIER PASSED (by omission!)"
except Exception as e: R["H_missing_request_file"] = "verifier rejects: " + type(e).__name__
req_files[0].write_bytes(req_bak)
# altered scope content (same hash name impossible; write different bytes under same name)
scope_files[0].write_bytes(scope_bak.replace(b"2026", b"2025", 1))
try: rt.verify_derivation(obs.observation_id); R["H_scope_bytes_altered"] = "VERIFIER PASSED"
except Exception as e: R["H_scope_bytes_altered"] = "verifier rejects: " + type(e).__name__
scope_files[0].write_bytes(scope_bak)
# raw evidence replaced? (content-addressed): tamper raw object bytes on disk
raw_row = [r for r in read_jsonl(root / "acquisition.jsonl") if r["record_type"] == "acq_completed"][0]
rawobs = rt.stores.evidence.get_observation(raw_row["raw_observation_id"])
rawfile = rt.stores.evidence.object_path(rawobs.artifact_hash) if hasattr(rt.stores.evidence, "object_path") else None
R["H_raw_tamper_api"] = "n/a" if rawfile is None else str(rawfile)[-20:]
if rawfile is not None:
    b = rawfile.read_bytes(); os.chmod(rawfile, 0o644); rawfile.write_bytes(b.replace(b"1.", b"9.", 1))
    try: rt.verify_derivation(obs.observation_id); R["H_raw_bytes_tampered"] = "VERIFIER PASSED"
    except Exception as e: R["H_raw_bytes_tampered"] = "verifier rejects: " + type(e).__name__
    rawfile.write_bytes(b)
for k, v in R.items(): print(f"{k:38s}", v)
