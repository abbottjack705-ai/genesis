"""REQ-05 (Secret), SEC-01 (detector matrix), SEC-05 (runtime-root scan)."""

from __future__ import annotations

import base64
import codecs
import copy
import hashlib
import json
import math
import pickle
import unittest
from urllib.parse import quote, quote_plus

from genesis_adapters import secrets as sec
from genesis_adapters.config import load_policy
from genesis_adapters.oddspapi import verify

from .support import CONFIG, SENTINEL_KEY, scratch_root

POLICY = load_policy(CONFIG / "oddspapi_slice1_policy.json")
PUNCTUATED = "K3y/with+odd=chars:and space-0123456789ab"


def fragment_len(key: str) -> int:
    return max(POLICY.secret_fragment_min_chars_floor,
               math.ceil(len(key) / POLICY.secret_fragment_min_chars_divisor))


def scan(data: bytes, key: str = SENTINEL_KEY):
    return sec.scan_for_secret(data, sec.Secret(key), policy=POLICY)


def embed(payload: bytes) -> bytes:
    return b'{"note":"before ' + payload + b' after","n":1.5}'


class SecretObjectTests(unittest.TestCase):
    def test_req05_repr_and_str_are_masked_with_the_fingerprint(self):
        secret = sec.Secret(SENTINEL_KEY)
        expected = hashlib.sha256(b"genesis.adapters.credential-fp.v1\0"
                                  + SENTINEL_KEY.encode()).hexdigest()[:12]
        self.assertEqual(secret.fingerprint, expected)
        self.assertEqual(repr(secret), f"Secret({expected})")
        self.assertEqual(str(secret), f"Secret({expected})")
        self.assertNotIn(SENTINEL_KEY, f"{secret!r} {secret} {[secret]} {{'k': {secret}}}")
        self.assertFalse(hasattr(secret, "__dict__"))

    def test_req05_serialization_and_copying_are_blocked(self):
        secret = sec.Secret(SENTINEL_KEY)
        for attempt in (lambda: pickle.dumps(secret), lambda: copy.copy(secret),
                        lambda: copy.deepcopy(secret), lambda: json.dumps(secret),
                        lambda: secret.__reduce__(), lambda: secret.__getstate__(),
                        lambda: pickle.dumps(secret, protocol=0)):
            with self.assertRaises((TypeError, sec.SecretError)):
                attempt()
        from genesis.repro import canonical_json
        with self.assertRaises(TypeError):
            canonical_json({"k": secret})

    def test_req05_reveal_requires_the_transport_capability(self):
        secret = sec.Secret(SENTINEL_KEY)
        for token in (None, object(), "token", 0):
            with self.assertRaises(sec.SecretError):
                secret.reveal_for_transport(token)
        self.assertEqual(secret.reveal_for_transport(sec.TRANSPORT_CAPABILITY), SENTINEL_KEY)

    def test_secret_validates_its_input(self):
        for bad in ("", "  ", "has\nnewline", "tab\tchar", b"", None, 5):
            with self.assertRaises((ValueError, TypeError)):
                sec.Secret(bad)
        self.assertEqual(sec.Secret(SENTINEL_KEY.encode()).fingerprint,
                         sec.Secret(SENTINEL_KEY).fingerprint)


class DetectorMatrixTests(unittest.TestCase):
    def assertHit(self, data: bytes, label: str, key: str = SENTINEL_KEY, cls: str | None = None):
        result = scan(data, key)
        self.assertTrue(result.hit, label)
        if cls is not None:
            self.assertIn(cls, result.detection_classes, label)
        self.assertTrue(all(isinstance(c, str) for c in result.detection_classes))
        return result

    def assertClean(self, data: bytes, label: str, key: str = SENTINEL_KEY):
        self.assertFalse(scan(data, key).hit, label)

    def test_sec01_clean_content_is_clean(self):
        for body in (b"[]", b'{"fixtureId":"id1000001761301153","price":1.910}',
                     b'{"a":"GENESIS","b":"SENTINEL","c":"0123456","d":"KEY-"}',
                     ("x" * 4000).encode()):
            self.assertClean(embed(body), "clean")

    def test_sec01_raw_forms(self):
        self.assertHit(embed(SENTINEL_KEY.encode()), "raw", cls="RAW")
        self.assertHit(embed(SENTINEL_KEY.lower().encode()), "raw lower")
        self.assertHit(embed(SENTINEL_KEY.upper().encode()), "raw upper")
        self.assertHit(SENTINEL_KEY.encode(), "bare")

    def test_sec01_percent_forms(self):
        key = PUNCTUATED
        upper = quote(key, safe="")
        lower = upper.replace("%2F", "%2f").replace("%2B", "%2b").replace("%3D", "%3d") \
            .replace("%3A", "%3a").replace("%20", "%20")
        self.assertNotEqual(upper, lower)
        for label, text in (("percent upper", upper), ("percent lower", lower),
                            ("plus", quote_plus(key)), ("double", quote(upper, safe=""))):
            self.assertHit(embed(text.encode()), label, key)
        self.assertHit(embed(f"?apiKey={upper}&x=1".encode()), "name=value", key)
        # every character percent-encoded, including upper-case letters
        full = "".join(f"%{ord(c):02x}" for c in SENTINEL_KEY)
        full_mixed = "".join(f"%{ord(c):02X}" if i % 2 else c for i, c in enumerate(SENTINEL_KEY))
        self.assertHit(embed(full.encode()), "percent every char")
        self.assertHit(embed(full_mixed.encode()), "percent every other char")

    def test_sec01_json_escapes_full_and_mixed(self):
        full = "".join(f"\\u{ord(c):04x}" for c in SENTINEL_KEY)
        full_upper = "".join(f"\\u{ord(c):04X}" for c in SENTINEL_KEY)
        mixed_a = "".join(f"\\u{ord(c):04x}" if i % 2 == 0 else c for i, c in enumerate(SENTINEL_KEY))
        mixed_b = "".join(f"\\u{ord(c):04X}" if i % 3 == 0 else c for i, c in enumerate(SENTINEL_KEY))
        for label, text in (("json full", full), ("json full upper", full_upper),
                            ("json mixed a", mixed_a), ("json mixed b", mixed_b)):
            self.assertHit(embed(text.encode()), label)
        slashed = PUNCTUATED.replace("/", "\\/")
        self.assertHit(embed(slashed.encode()), "escaped slash", PUNCTUATED)

    def test_sec01_wide_encodings(self):
        key = SENTINEL_KEY
        forms = {
            "utf16le": key.encode("utf-16-le"), "utf16be": key.encode("utf-16-be"),
            "utf16le bom": codecs.BOM_UTF16_LE + key.encode("utf-16-le"),
            "utf16be bom": codecs.BOM_UTF16_BE + key.encode("utf-16-be"),
            "utf32le": key.encode("utf-32-le"), "utf32be": key.encode("utf-32-be"),
            "utf32le bom": codecs.BOM_UTF32_LE + key.encode("utf-32-le"),
        }
        for label, data in forms.items():
            self.assertHit(b"\x00\x01garbage" + data + b"tail", label)
            self.assertHit(data, label + " bare")
        self.assertHit(embed(b"x") + PUNCTUATED.encode("utf-16"), "utf-16 with BOM", PUNCTUATED)

    def test_sec01_base64_all_alignments_both_alphabets_with_and_without_padding(self):
        for key in (SENTINEL_KEY, PUNCTUATED):
            raw = key.encode()
            for offset in range(3):
                for suffix_len in range(3):
                    data = b"\xfa\xfb\xfc"[:offset] + raw + b"\xfd\xfe\xff"[:suffix_len]
                    std = base64.b64encode(data)
                    url = base64.urlsafe_b64encode(data)
                    for label, encoded in (("std", std), ("url", url),
                                           ("std nopad", std.rstrip(b"=")),
                                           ("url nopad", url.rstrip(b"="))):
                        self.assertHit(embed(encoded), f"b64 {label} o={offset} s={suffix_len} {key[:4]}",
                                       key, "BASE64")

    def test_sec01_hex_forms(self):
        raw = SENTINEL_KEY.encode()
        self.assertHit(embed(raw.hex().encode()), "hex lower", cls="HEX")
        self.assertHit(embed(raw.hex().upper().encode()), "hex upper", cls="HEX")

    def test_sec01_fragments_at_exactly_the_threshold(self):
        for key in (SENTINEL_KEY, PUNCTUATED, "A" * 8 + "b" * 8 + "C" * 8 + "d" * 8 + "E" * 8):
            m = fragment_len(key)
            self.assertGreaterEqual(m, POLICY.secret_fragment_min_chars_floor)
            for start in (0, 1, len(key) - m):
                frag = key[start:start + m]
                self.assertHit(embed(frag.encode()), f"fragment at {start} of {key[:4]}", key)
                self.assertHit(embed(quote(frag, safe="").encode()), "percent fragment", key)
                self.assertHit(frag.encode("utf-16-le"), "utf16le fragment", key)
                self.assertHit(frag.encode("utf-16-be"), "utf16be fragment", key)
            shorter = key[:m - 1]
            self.assertClean(embed(shorter.encode()), "one shorter", key)

    def test_sec01_hex_fragments_need_twice_the_threshold(self):
        key = SENTINEL_KEY
        m = fragment_len(key)
        hexed = key.encode().hex()
        self.assertHit(embed(hexed[4:4 + 2 * m].encode()), "hex fragment 2m", key)
        self.assertHit(embed(hexed[5:5 + 2 * m].encode().upper()), "hex fragment odd offset", key)
        self.assertClean(embed(hexed[4:4 + 2 * m - 1].encode()), "hex fragment 2m-1", key)

    def test_sec01_threshold_follows_the_policy_formula_for_long_keys(self):
        key = "".join(chr(ord("a") + (i * 7) % 26) for i in range(90))
        m = fragment_len(key)
        self.assertEqual(m, math.ceil(90 / POLICY.secret_fragment_min_chars_divisor))
        self.assertGreater(m, POLICY.secret_fragment_min_chars_floor)
        self.assertHit(key[10:10 + m].encode(), "long key fragment", key)
        self.assertClean(key[10:10 + m - 1].encode(), "long key shorter", key)

    def test_sec01_detection_classes_never_expose_offsets_or_text(self):
        result = self.assertHit(embed(SENTINEL_KEY.encode()), "x")
        self.assertNotIn(SENTINEL_KEY, repr(result))
        for value in result.detection_classes:
            self.assertRegex(value, r"^[A-Z0-9_]+$")

    def test_sec02_headers_names_and_values_are_scanned(self):
        secret = sec.Secret(SENTINEL_KEY)
        clean = [(b"content-type", b"application/json"), (b"x-request-id", b"abc")]
        self.assertFalse(sec.scan_headers(clean, secret, policy=POLICY).hit)
        in_value = clean + [(b"x-echo", SENTINEL_KEY.encode())]
        result = sec.scan_headers(in_value, secret, policy=POLICY)
        self.assertTrue(result.hit)
        self.assertIn("HEADER_VALUE", result.detection_classes)
        in_name = clean + [(SENTINEL_KEY.encode(), b"v")]
        result = sec.scan_headers(in_name, secret, policy=POLICY)
        self.assertTrue(result.hit)
        self.assertIn("HEADER_NAME", result.detection_classes)
        encoded = clean + [(b"x-b64", base64.b64encode(SENTINEL_KEY.encode()))]
        self.assertTrue(sec.scan_headers(encoded, secret, policy=POLICY).hit)


class RuntimeRootScanTests(unittest.TestCase):
    def test_sec05_every_form_planted_anywhere_under_the_root_is_found(self):
        secret = sec.Secret(SENTINEL_KEY)
        raw = SENTINEL_KEY.encode()
        planted = {
            "a/raw.txt": raw,
            "a/b/c/deep.jsonl": embed(raw),
            "u16.bin": SENTINEL_KEY.encode("utf-16"),
            "u32.bin": SENTINEL_KEY.encode("utf-32-be"),
            "b64.json": embed(base64.b64encode(b"zz" + raw + b"z")),
            "hex.txt": raw.hex().encode(),
            "esc.json": embed("".join(f"\\u{ord(c):04x}" for c in SENTINEL_KEY).encode()),
            "frag.txt": SENTINEL_KEY[5:5 + fragment_len(SENTINEL_KEY)].encode(),
            "pct.txt": quote(SENTINEL_KEY, safe="").encode(),
        }
        with scratch_root() as root:
            for name, data in planted.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            clean = root / "clean" / "ok.json"
            clean.parent.mkdir()
            clean.write_bytes(b'{"price":1.910,"fixtureId":"id1"}')
            hits = verify.scan_runtime_for_secret(root, secret, policy=POLICY)
            found = {p.relative_to(root).as_posix() for p in hits}
            self.assertEqual(found, set(planted))
            self.assertNotIn("clean/ok.json", found)

    def test_sec05_file_names_are_scanned_too(self):
        secret = sec.Secret(SENTINEL_KEY)
        with scratch_root() as root:
            (root / f"{SENTINEL_KEY}.json").write_bytes(b"{}")
            (root / "clean.json").write_bytes(b"{}")
            hits = verify.scan_runtime_for_secret(root, secret, policy=POLICY)
            self.assertEqual([p.name for p in hits], [f"{SENTINEL_KEY}.json"])

    def test_sec05_empty_and_missing_roots(self):
        secret = sec.Secret(SENTINEL_KEY)
        with scratch_root() as root:
            self.assertEqual(verify.scan_runtime_for_secret(root, secret, policy=POLICY), ())
            with self.assertRaises(FileNotFoundError):
                verify.scan_runtime_for_secret(root / "missing", secret, policy=POLICY)


if __name__ == "__main__":
    unittest.main()
