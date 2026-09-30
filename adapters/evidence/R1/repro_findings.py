"""Independent reproduction of hostile-audit findings F-01, F-02, F-03 against the CURRENT worktree.

Run from the repository root:
    PYTHONPATH=adapters PYTHONPYCACHEPREFIX=<fresh dir> python -B <this file>

Nothing here contacts a network: the adapter test package installs its loopback-only audit hook on import,
every transport is a fake or a fault-injecting connection, and every runtime root is a scratch directory.
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

import adapter_tests  # noqa: F401  (path setup + module-provenance guard + loopback-only audit hook)
from adapter_tests import parser_support as ps
from adapter_tests.parser_support import FIXTURE_A, FIXTURE_B, fixture_of
from adapter_tests.pipeline_support import coverage_rows, documents, odds_item, odds_response, open_rt
from adapter_tests.support import CONFIG, SENTINEL_KEY, FixedClock, no_response, raises, read_jsonl, scratch_root

from genesis_adapters.oddspapi import authority as auth
from genesis_adapters.oddspapi import transport_http as th
from genesis_adapters.secrets import Secret, SecretScanner

SCANNER = SecretScanner(Secret(SENTINEL_KEY), policy=ps.POLICY)
print("# reproduction of F-01, F-02, F-03")
print("# python:", sys.version.split()[0])


def stored_errors(root: Path) -> list:
    return [row["sanitized_error"] for row in read_jsonl(root / "acquisition.jsonl")
            if row["record_type"] == "acq_completed" and row["sanitized_error"] is not None]


def verdict_f01(label: str, errors: list) -> None:
    for error in errors:
        hit = SCANNER.scan(json.dumps(error).encode("utf-8"))
        # a value that carries a form of the (public, test-only) sentinel is described, never printed
        cls = (f"<{len(error['class'])}-char class name carrying a sentinel form>" if hit.hit
               else repr(error["class"]))
        print(f"F-01 [{label}] stored sanitized_error={{'class': {cls}, 'errno': {error['errno']!r}}} "
              f"-> section-7.6 scanner hit={hit.hit} classes={list(hit.detection_classes)}")


# -- F-01 -------------------------------------------------------------------------------------------
NAMED = type("Err_" + SENTINEL_KEY.replace("-", "_"), (OSError,), {})
with scratch_root() as root:           # (a) a transport that RAISES: the runner's sanitize_exception path
    rt = open_rt(root, script=[raises(NAMED())], secret=Secret(SENTINEL_KEY))
    rt.acquire(odds_item())
    verdict_f01("runner path: transport raised a sentinel-named class", stored_errors(root))
with scratch_root() as root:           # (b) a transport that REPORTS a sanitized error carrying the name
    rt = open_rt(root, script=[no_response(error_class=NAMED.__name__)], secret=Secret(SENTINEL_KEY))
    rt.acquire(odds_item())
    verdict_f01("transport-reported sanitized error", stored_errors(root))


class Boom:                           # (c) the real HTTPS transport, fault-injecting connection
    def __init__(self, *args):
        pass

    def open(self, timeout):
        raise NAMED()

    def close(self):
        pass


with scratch_root() as root:
    transport = th.HttpsTransport(Secret(SENTINEL_KEY), credential_param="apiKey", policy=ps.POLICY,
                                  connection_factory=Boom)
    rt = open_rt(root, transport=transport, secret=Secret(SENTINEL_KEY))
    rt.acquire(odds_item())
    verdict_f01("real HttpsTransport, connection raised", stored_errors(root))

# -- F-02 -------------------------------------------------------------------------------------------
relaxed = Path(tempfile.mkdtemp(prefix="r1_gate_"))
try:
    body = json.loads((CONFIG / auth.GATE_LIMITS_FILE).read_text(encoding="utf-8"))
    print("F-02 shipped limits:", {k: body[k] for k in sorted(body) if k != "schema"})
    body.update(g2_requests_cap=10000, g2_window_hours=87600, g2r_window_days=3650)
    (relaxed / auth.GATE_LIMITS_FILE).write_text(json.dumps(body), encoding="utf-8")
    try:
        limits = auth.load_gate_limits(relaxed)
        print(f"F-02 relaxed file ACCEPTED: {limits}")
        record = {"record_type": "gate_record", "schema_version": auth.SCHEMA_VERSION, "gate": "G2",
                  "approval_reference": "adr:synthetic-test-only", "approver": "synthetic-test-only",
                  "granted_at": "2026-10-01T00:00:00.000000Z", "request_hashes": [f"{n:064x}" for n in range(50)],
                  "max_calls": 50, "valid_from": "2026-10-01T00:00:00.000000Z",
                  "valid_through": "2026-12-31T00:00:00.000000Z"}
        auth.validate_record(record, limits)
        print("F-02 a G2 record for 50 requests over 91 days VALIDATES under the relaxed file")
    except Exception as exc:                                   # noqa: BLE001 - repro reports anything
        print(f"F-02 relaxed file REFUSED: {type(exc).__name__}: {exc}")
finally:
    shutil.rmtree(relaxed, ignore_errors=True)

# -- F-03 -------------------------------------------------------------------------------------------
def run_pair(second):
    root = Path(tempfile.mkdtemp(prefix="r1_f03_"))
    rt = open_rt(root, script=[odds_response(), odds_response(second)])
    rt.acquire(odds_item("w1"))                                    # both tournaments: OPEN heads for 17 and 8
    rt.clock.advance(seconds=600)
    rt.acquire(odds_item("w2"))                                    # the request names tournaments 17 and 8
    return root, rt


for label, second in (("tournament 8 omitted", [fixture_of(ps.odds_payload(), FIXTURE_A)]),
                      ("every requested tournament omitted", [])):
    root, rt = run_pair(second)
    try:
        request = json.loads(next((root / "requests").glob("*.json")).read_bytes())
        tournaments = dict(request["query"]).get("tournamentIds")
        absent = [d for d in documents(rt) if d["market_state"] == "ABSENT"]
        by_fixture = sorted({d["provider_fixture_id"]["value"] for d in absent})
        partial = [row["note"] for row in coverage_rows(rt) if row["note"].startswith("PARTIAL_RESPONSE")]
        print(f"F-03 [{label}] requested tournamentIds={tournaments}: ABSENT tombstones={len(absent)} "
              f"for fixtures {by_fixture}; PARTIAL_RESPONSE coverage entries={partial}")
    finally:
        shutil.rmtree(root, ignore_errors=True)
print("# end")
