"""HA-015: the design's G2/G2R bounds live in an unpinned config file that any --config directory replaces.

c8dfafd 16.3 fixes G2 at <= 5 pinned requests inside a window <= 72 h and 16.4 fixes G2R at <= 35 days.
The candidate reads those numbers from ``adapters/config/oddspapi_gate_limits.json``; the file is not one
of the digest-pinned ``CONFIG_FILES``, so a copy of the config directory with a widened file is accepted.

    python -B attacks/a14_gate_limits.py --repo <candidate>
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    repo = c.setup(args.repo)
    from genesis_adapters import config as cfg
    from genesis_adapters.oddspapi import authority

    root = c.scratch("limits-")
    config = root / "config"
    shutil.copytree(repo / "adapters" / "config", config)
    before = cfg.load_config_digests(config)
    body = json.loads((config / authority.GATE_LIMITS_FILE).read_text(encoding="utf-8"))
    body.update(g2_window_hours=10000, g2_requests_cap=500, g2r_window_days=3650)
    (config / authority.GATE_LIMITS_FILE).write_bytes(json.dumps(body).encode())
    after = cfg.load_config_digests(config)
    limits = authority.load_gate_limits(config)
    record = {"record_type": "gate_record", "schema_version": authority.SCHEMA_VERSION, "gate": "G2",
              "approval_reference": "adr:probe", "approver": "probe", "granted_at": "2026-10-01T00:00:00.000000Z",
              "request_hashes": [f"{i:064x}" for i in range(1, 51)], "max_calls": 50,
              "valid_from": "2026-10-01T00:00:00.000000Z", "valid_through": "2026-11-12T00:00:00.000000Z"}
    accepted = True
    try:
        authority.validate_record(record, limits)
    except authority.AuthorityRecordInvalid:
        accepted = False
    c.check("A14", "16.3: a G2 record with 50 requests over 1000 hours is refused whatever config directory is used",
            not accepted, accepted=accepted, config_digests_changed=before != after)
    c.remove(root)
    return c.finish(args.out)


if __name__ == "__main__":
    sys.exit(main())
