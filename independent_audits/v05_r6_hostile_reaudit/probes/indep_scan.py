"""Independent secret detector for the audit (written from design 7.6; shares NO code with genesis_adapters.secrets)."""
import base64, binascii, math, os, re, urllib.parse

def forms(key: str):
    raw = key.encode("utf-8")
    n = len(key)
    width = max(8, math.ceil(n / 3))
    F = set()
    def addc(b):  # case variants for ASCII text forms
        F.add(b); F.add(b.lower()); F.add(b.upper())
    addc(raw)
    F.add(urllib.parse.quote(key, safe="").encode().replace(b"-", b"%2D"))   # all percent-encoded upper
    F.add("".join("%%%02x" % c for c in raw).encode()); F.add("".join("%%%02X" % c for c in raw).encode())
    F.add("".join("%%25%02X" % c for c in raw).encode()); F.add("".join("%%25%02x" % c for c in raw).encode())
    F.add("".join("\\u%04x" % ord(c) for c in key).encode()); F.add("".join("\\u%04X" % ord(c) for c in key).encode())
    for codec in ("utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"):
        F.add(key.encode(codec))
    F.add(raw.hex().encode()); F.add(raw.hex().upper().encode())
    for off in range(3):
        s = base64.b64encode(b"\x00" * off + raw)
        # inner stable core
        lead = -(-off * 8 // 6); end = (off + len(raw)) * 8 // 6
        core = s.rstrip(b"=")[lead:end]
        for c in (core, core.replace(b"+", b"-").replace(b"/", b"_")):
            if len(c) >= 8: F.add(c)
    # fragments (raw / pct / utf16)
    for i in range(0, n - width + 1):
        frag = key[i:i + width]
        F.add(frag.encode()); F.add(frag.lower().encode())
        F.add(frag.encode("utf-16-le")); F.add(frag.encode("utf-16-be"))
        F.add("".join("%%%02X" % c for c in frag.encode()).encode())
    return {f for f in F if f}

def views(data: bytes):
    yield data
    u = re.sub(rb"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)).encode("utf-8", "replace"), data).replace(b"\\/", b"/")
    yield u
    d = data
    for _ in range(3):
        d2 = re.sub(rb"%([0-9a-fA-F]{2})", lambda m: bytes([int(m.group(1), 16)]), d)
        if d2 == d: break
        d = d2; yield d
    yield re.sub(rb"%([0-9a-fA-F]{2})", lambda m: bytes([int(m.group(1), 16)]), data.replace(b"+", b" "))
    for tok in re.findall(rb"[A-Za-z0-9+/_-]{12,}={0,2}", data):
        t = tok.replace(b"-", b"+").replace(b"_", b"/")
        for off in range(4):
            seg = t[off:]; seg += b"=" * (-len(seg) % 4)
            try: yield base64.b64decode(seg)
            except (binascii.Error, ValueError): pass
    for tok in re.findall(rb"(?:[0-9a-fA-F]{2}){8,}", data):
        try: yield binascii.unhexlify(tok)
        except (binascii.Error, ValueError): pass
    # latin-1 / mojibake reverse views
    try: yield data.decode("utf-8", "ignore").encode("latin-1", "ignore")
    except Exception: pass
    for codec in ("utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"):
        for off in (0, 1):
            try: yield data[off:].decode(codec, "ignore").encode("utf-8", "ignore")
            except Exception: pass

def hits(data: bytes, key: str, fs=None):
    fs = fs or forms(key)
    found = set()
    for v in views(data):
        low = v.lower()
        for f in fs:
            if f in v or f.lower() in low:
                found.add(f[:6].hex()); 
                return True
    return False

def scan_tree(root, key):
    fs = forms(key)
    bad = []
    for d, _, files in os.walk(root):
        for name in files:
            p = os.path.join(d, name)
            rel = os.path.relpath(p, root).encode()
            data = open(p, "rb").read()
            if hits(rel, key, fs) or hits(data, key, fs):
                bad.append(os.path.relpath(p, root))
    return sorted(bad)
