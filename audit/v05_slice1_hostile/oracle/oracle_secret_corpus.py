#!/usr/bin/env python3
"""Oracle 6 - secret detector attack corpus (audit area 6, SEC-01).

Generates every c8dfafd 7.6 form of a sentinel plus adversarial extras that the
implementer's own SEC-01 matrix may not cover, with the EXPECTED verdict per 7.6.
With --repo it imports the candidate's genesis_adapters.secrets and compares.

  python oracle_secret_corpus.py [--sentinel GENESIS-SENTINEL-KEY-0123456789abcdef]
                                 [--min-chars 8 --divisor 3] [--repo <checkout>] --out SECRET_CORPUS.json

Expected-hit rules (7.6): raw; percent upper/lower; '+' form; double-encoded %25XX;
name=value fragment; JSON \\u full and mixed; escaped '/'; UTF-16 LE/BE +/- BOM;
UTF-32 LE/BE; base64 std/url-safe at offsets 0/1/2 with/without padding; hex upper/lower;
fragments >= max(min_chars, ceil(n/divisor)) in raw, percent and UTF-16 forms; hex
fragments >= 2 x threshold. Expected-miss: fragment of threshold-1 chars; unrelated text.
Adversarial extras (expected per the rule text): fragment split across two headers
(each part below threshold -> MISS per 7.6, but a HIT is safe); key with case flipped
(text forms are ASCII-case-insensitive -> HIT for raw/percent/JSON forms; base64/hex of
the flipped key are different strings -> not required); ROT/XOR are out of scope.
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import sys
import urllib.parse
from pathlib import Path


def b64_alignments(k: bytes, urlsafe: bool):
    enc = base64.urlsafe_b64encode if urlsafe else base64.b64encode
    out = {}
    for off in range(3):
        padded = b"x" * off + k
        e = enc(padded).decode()
        core = e[math.ceil(off * 4 / 3):] if off else e   # stable inner core after the prefix bytes
        out[f"off{off}"] = core.rstrip("=")
        out[f"off{off}_padded"] = core
    return out


def build(sentinel: str, min_chars: int, divisor: int) -> list[dict]:
    k = sentinel
    kb = k.encode()
    n = len(k)
    thr = max(min_chars, math.ceil(n / divisor))
    c: list[dict] = []

    def add(name, payload: bytes, expect: bool, cls: str):
        c.append({"name": name, "payload_b64": base64.b64encode(payload).decode(), "expect_hit": expect, "class": cls})

    add("raw", b'{"x":"' + kb + b'"}', True, "RAW")
    add("percent_lower", urllib.parse.quote(k, safe="").replace("%2D", "%2d").encode(), True, "PERCENT")
    add("percent_upper_all", "".join(f"%{b:02X}" for b in kb).encode(), True, "PERCENT")
    add("percent_lower_all", "".join(f"%{b:02x}" for b in kb).encode(), True, "PERCENT")
    add("plus_form", ("a b " + k.replace("-", "+")).encode() if "-" in k else (k + "+x").encode(), "-" in k, "PLUS")
    add("double_encoded", urllib.parse.quote(urllib.parse.quote(k, safe=""), safe="").encode(), True, "PERCENT_DOUBLE")
    add("query_fragment", b"GET /v4/odds?apiKey=" + kb + b"&x=1", True, "QUERY")
    add("json_u_full", ("".join(f"\\u{ord(ch):04x}" for ch in k)).encode(), True, "JSON_ESCAPE")
    add("json_u_mixed", ("".join(f"\\u{ord(ch):04x}" if i % 2 else ch for i, ch in enumerate(k))).encode(), True, "JSON_ESCAPE")
    add("json_escaped_slash", json.dumps("https://h/" + k + "/").encode(), True, "JSON_ESCAPE")
    for enc in ("utf-16-le", "utf-16-be", "utf-16", "utf-32-le", "utf-32-be"):
        add(f"{enc}", k.encode(enc), True, enc.upper())
    for urlsafe in (False, True):
        for name, val in b64_alignments(kb, urlsafe).items():
            add(f"b64_{'url' if urlsafe else 'std'}_{name}", val.encode(), True, "BASE64")
    add("hex_lower", kb.hex().encode(), True, "HEX")
    add("hex_upper", kb.hex().upper().encode(), True, "HEX")
    frag = k[2:2 + thr]
    add(f"fragment_exact_thr_{thr}", b"zz" + frag.encode() + b"zz", True, "FRAGMENT")
    add(f"fragment_thr_minus_1", b"zz" + frag[:-1].encode() + b"zz", False, "FRAGMENT")
    add("fragment_percent", urllib.parse.quote(frag, safe="").encode(), True, "FRAGMENT_PERCENT")
    add("fragment_utf16le", frag.encode("utf-16-le"), True, "FRAGMENT_UTF16")
    add("fragment_hex_2thr", kb[1:1 + thr].hex().encode(), True, "FRAGMENT_HEX")
    add("fragment_hex_2thr_minus_2", kb[1:1 + thr].hex()[:-2].encode(), False, "FRAGMENT_HEX")
    add("case_flipped_raw", k.swapcase().encode(), True, "RAW_CASEFOLD")
    add("tail_fragment", k[-thr:].encode(), True, "FRAGMENT")
    add("clean_control", b'{"odds":[{"home":"1.91","away":"3.40"}],"note":"no key here"}', False, "CLEAN")
    add("near_miss_prefix", b"GENESIS-SENTINEL-KEY-", "GENESIS-SENTINEL-KEY-" in k and len("GENESIS-SENTINEL-KEY-") >= thr, "FRAGMENT")
    add("split_two_chunks_below_thr", (k[:thr - 1] + "\r\n" + k[thr - 1:2 * thr - 2]).encode(), False, "SPLIT")
    return c


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sentinel", default="GENESIS-SENTINEL-KEY-0123456789abcdef")
    ap.add_argument("--min-chars", type=int, default=8)
    ap.add_argument("--divisor", type=int, default=3)
    ap.add_argument("--repo", default="")
    ap.add_argument("--out", default="SECRET_CORPUS.json")
    a = ap.parse_args()
    corpus = build(a.sentinel, a.min_chars, a.divisor)
    Path(a.out).write_text(json.dumps({"sentinel": a.sentinel, "threshold": max(a.min_chars, math.ceil(len(a.sentinel) / a.divisor)),
                                       "cases": corpus}, indent=1))
    print(f"{len(corpus)} cases, expected hits={sum(c['expect_hit'] for c in corpus)}; wrote {a.out}")
    if not a.repo:
        return 0
    sys.path.insert(0, str(Path(a.repo) / "src")); sys.path.insert(0, str(Path(a.repo) / "adapters/src"))
    try:
        from genesis_adapters import secrets as S
        from genesis_adapters import config as C
    except Exception as exc:
        print(f"ADAPTATION_NEEDED: cannot import candidate modules: {type(exc).__name__}: {exc}")
        return 2
    try:
        policy = C.load_slice_policy(Path(a.repo) / "adapters/config/oddspapi_slice1_policy.json")  # name per 17 may differ
    except Exception:
        policy = None
        for name in dir(C):
            if name.lower().startswith("load") and "polic" in name.lower():
                try:
                    policy = getattr(C, name)(Path(a.repo) / "adapters/config/oddspapi_slice1_policy.json"); break
                except Exception:
                    pass
    if policy is None:
        print("ADAPTATION_NEEDED: could not load SlicePolicy; edit this script to the candidate's loader name")
        return 2
    secret = S.Secret(a.sentinel) if callable(getattr(S, "Secret", None)) else None
    mism = []
    for case in corpus:
        payload = base64.b64decode(case["payload_b64"])
        try:
            res = S.scan_for_secret(payload, secret, policy=policy)
            hit = bool(getattr(res, "hit", res))
        except Exception as exc:
            hit = f"ERROR:{type(exc).__name__}"
        if hit != case["expect_hit"]:
            mism.append({"case": case["name"], "expected": case["expect_hit"], "got": hit})
    print(json.dumps({"mismatches": mism, "count": len(mism)}, indent=2))
    return 0 if not mism else 1


if __name__ == "__main__":
    sys.exit(main())
