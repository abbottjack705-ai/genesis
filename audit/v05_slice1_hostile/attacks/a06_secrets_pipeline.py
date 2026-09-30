"""Area 6 (SEC-01..05, REQ-04/07, F-11/F-11b) through the candidate's real runtime.

The key is configured as a ``Secret``; responses echo it in many forms (body, header value, header name,
decoded-gzip only, wire-only after a gzip member, UTF-16, percent, base64 at an odd alignment, hex, a
threshold-length fragment). After each run EVERY file under the runtime root is searched by an auditor
detector (independent of ``secrets.py``) for every section-7.6 form, the quarantine row is checked for a
body hash, and the halt/capability effects are checked. The corpus of ``oracle/SECRET_CORPUS.json`` is
also planted as files to test ``verify.scan_runtime_for_secret`` (SEC-05).

    python -B attacks/a06_secrets_pipeline.py --repo <candidate> --corpus oracle/SECRET_CORPUS.json
"""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import math
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

KEY = c.SENTINEL


def needles(key: str) -> list[tuple[str, bytes, bool]]:
    """(label, needle, case_insensitive). Auditor-side forms, written from design 7.6 alone."""

    raw = key.encode()
    width = max(8, math.ceil(len(key) / 3))
    out = [("raw", raw, True), ("utf16le", key.encode("utf-16-le"), True), ("utf16be", key.encode("utf-16-be"), True),
           ("utf32le", key.encode("utf-32-le"), True), ("hex", raw.hex().encode(), True),
           ("pct", "".join(f"%{b:02x}" for b in raw).encode(), True),
           ("json_u", "".join(f"\\u{ord(ch):04x}" for ch in key).encode(), True)]
    for off in range(3):
        for enc in (base64.b64encode, base64.urlsafe_b64encode):
            full = enc(b"\x00" * off + raw).rstrip(b"=")
            lead = math.ceil(off * 4 / 3)
            end = (off + len(raw)) * 8 // 6
            out.append((f"b64_{off}", full[lead:end], False))
    for i in range(len(key) - width + 1):
        frag = key[i:i + width]
        out.append(("frag", frag.encode(), True))
        out.append(("frag16", frag.encode("utf-16-le"), True))
        out.append(("fragpct", urllib.parse.quote(frag, safe="").encode(), True))
    hexed = raw.hex()
    for i in range(len(hexed) - 2 * width + 1):
        out.append(("hexfrag", hexed[i:i + 2 * width].encode(), True))
    return out


NEEDLES = needles(KEY)


def dirty_files(root: Path, extra: list[bytes] = ()) -> list[str]:
    found = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        data = path.read_bytes()
        low = data.lower()
        name = str(path.relative_to(root)).encode()
        for label, needle, ci in NEEDLES:
            if (ci and (needle.lower() in low or needle.lower() in name.lower())) or (not ci and needle in data):
                found.append(f"{path.relative_to(root)}:{label}")
                break
        for digest in extra:
            if digest in data:
                found.append(f"{path.relative_to(root)}:body-hash")
    return found


def run(repo: Path, label: str, status: int, headers, body: bytes, expect: str) -> None:
    from genesis_adapters.errors import AcquisitionHalt
    from genesis_adapters.secrets import Secret

    root = c.scratch(f"sec-{label[:10]}-")
    tr = c.CountingTransport(default=(status, headers, body))
    rt = c.open_runtime(repo, root, clock=c.StepClock(), transport=tr, secret=Secret(KEY))
    halted = None
    try:
        result = rt.acquire(c.odds_item(repo))
        outcome = result.outcome
    except AcquisitionHalt as exc:
        halted, outcome = str(exc.code), None
    body_hash = hashlib.sha256(body).hexdigest().encode()
    leaks = dirty_files(root, [body_hash] if expect != "CLEAN" else [])
    quarantine = c.jsonl(root / "quarantine.jsonl")
    raw_objects = [p for p in (root / "evidence" / "objects").rglob("*") if p.is_file()]
    caps = [r for r in c.jsonl(root / "capabilities.jsonl") if r.get("record_type") == "source_capability_registered"]
    if expect == "SECRET_ECHO":
        c.check("A6", f"{label}: SECRET_ECHO halt, no raw object, metadata-only quarantine, no form or body hash "
                      f"anywhere, capability BLOCKED",
                halted is not None and "SECRET_ECHO" in halted and not raw_objects and len(quarantine) == 1
                and not leaks and quarantine[0].get("reason") == "SECRET_ECHO"
                and any(r["operational_status"].upper() == "BLOCKED" for r in caps),
                halted=halted, leaks=leaks[:5], raw_objects=len(raw_objects), quarantine=len(quarantine),
                classes=quarantine[0].get("detection_classes") if quarantine else None,
                blocked=[r["operational_status"] for r in caps])
    elif expect == "UNINSPECTABLE_BODY":
        c.check("A6", f"{label}: UNINSPECTABLE quarantine, no raw object, no body hash, no halt",
                halted is None and not raw_objects and len(quarantine) == 1 and not leaks
                and quarantine[0].get("reason") == "UNINSPECTABLE_BODY",
                halted=halted, leaks=leaks[:5], raw_objects=len(raw_objects), quarantine=len(quarantine))
    else:
        c.check("A6", f"{label}: clean response stored; no form of the configured key anywhere under the root",
                halted is None and not leaks and raw_objects and not quarantine,
                outcome=getattr(outcome, "outcome", None), leaks=leaks[:5], raw_objects=len(raw_objects))
    c.remove(root)


def sec05(repo: Path, corpus: dict) -> None:
    from genesis_adapters.oddspapi import verify
    from genesis_adapters.secrets import Secret

    root = c.scratch("sec05-")
    for case in corpus["cases"]:
        (root / f"{case['name']}.bin").write_bytes(base64.b64decode(case["payload_b64"]))
    hits = {p.stem for p in verify.scan_runtime_for_secret(root, Secret(corpus["sentinel"]))}
    wrong = [(case["name"], case["expect_hit"]) for case in corpus["cases"] if (case["name"] in hits) != case["expect_hit"]]
    c.check("A6", "SEC-05: scan_runtime_for_secret flags exactly the corpus files expected to hit", not wrong,
            wrong=wrong[:10], hits=len(hits))
    c.remove(root)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    repo = c.setup(args.repo)
    clean = c.fixture_bytes(repo, "odds_by_tournaments.json")
    J = c.JSON_HEADERS
    width = max(8, math.ceil(len(KEY) / 3))
    raw = KEY.encode()
    run(repo, "clean fixture response (REQ-04 shape)", 200, J, clean, "CLEAN")
    run(repo, "raw key in body", 200, J, b'{"echo":"' + raw + b'"}', "SECRET_ECHO")
    run(repo, "utf-16be key in body", 200, J, b"x" + KEY.encode("utf-16-be"), "SECRET_ECHO")
    run(repo, "percent-encoded upper key", 200, J, "".join(f"%{b:02X}" for b in raw).encode(), "SECRET_ECHO")
    run(repo, "base64 at offset 1", 200, J, base64.b64encode(b"q" + raw), "SECRET_ECHO")
    run(repo, "hex upper key", 200, J, raw.hex().upper().encode(), "SECRET_ECHO")
    run(repo, "threshold-length fragment", 200, J, b'["' + KEY[5:5 + width].encode() + b'"]', "SECRET_ECHO")
    run(repo, "key in a non-allowlisted header value", 200, J + (("x-debug", "k=" + KEY),), clean, "SECRET_ECHO")
    run(repo, "key in a header name", 200, J + (("x-" + KEY.lower(), "1"),), clean, "SECRET_ECHO")
    run(repo, "key in a 500 error body", 500, J, b'{"error":"bad key ' + raw + b'"}', "SECRET_ECHO")
    run(repo, "key only inside the gzip-decoded body", 200, J + (("content-encoding", "gzip"),),
        gzip.compress(b'{"e":"' + raw + b'"}'), "SECRET_ECHO")
    run(repo, "key only in wire bytes after a gzip member", 200, J + (("content-encoding", "gzip"),),
        gzip.compress(clean) + raw, "SECRET_ECHO")
    run(repo, "unsupported content-encoding", 200, J + (("content-encoding", "br"),), b"\x0b\x02\x80clean",
        "UNINSPECTABLE_BODY")
    run(repo, "nested content-encoding", 200, J + (("content-encoding", "gzip, gzip"),),
        gzip.compress(gzip.compress(clean)), "UNINSPECTABLE_BODY")
    run(repo, "gzip bomb over the ratio bound", 200, J + (("content-encoding", "gzip"),),
        gzip.compress(b"[" + b"0," * 3_000_000 + b"0]"), "UNINSPECTABLE_BODY")
    sec05(repo, json.loads(Path(args.corpus).read_text(encoding="utf-8")))
    return c.finish(args.out)


if __name__ == "__main__":
    sys.exit(main())
