from __future__ import annotations
import concurrent.futures, hashlib, os, ssl, sys, tempfile
from pathlib import Path
repo = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(repo / "adapters" / "src"), str(repo / "src")]
from genesis_adapters.oddspapi.transport_http import tls_context

def fingerprints(ctx):
    return {hashlib.sha256(der).hexdigest() for der in ctx.get_ca_certs(binary_form=True)}
stock = ssl.create_default_context()
expected = fingerprints(stock)
with tempfile.TemporaryDirectory(prefix="genesis-r7-tls-concurrent-") as td:
    overrides = {"SSL_CERT_FILE": str(Path(td) / "attacker.pem"),
                 "SSL_CERT_DIR": str(Path(td) / "attacker-cadir"),
                 "SSLKEYLOGFILE": str(Path(td) / "session.keys"),
                 "OPENSSL_CONF": str(Path(td) / "attacker.cnf")}
    original = {k: os.environ.get(k) for k in overrides}
    try:
        os.environ.update(overrides)
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            contexts = list(pool.map(lambda _: tls_context(), range(80)))
        assert all(fingerprints(ctx) == expected for ctx in contexts)
        assert all(ctx.check_hostname and ctx.verify_mode == ssl.CERT_REQUIRED and
                   ctx.minimum_version >= ssl.TLSVersion.TLSv1_2 and ctx.keylog_filename is None
                   for ctx in contexts)
        assert all(os.environ.get(k) == v for k, v in overrides.items())
        assert not Path(overrides["SSLKEYLOGFILE"]).exists()
        print("contexts=80 workers=16 errors=0")
        print(f"stock_ca_count={len(expected)} production_ca_count={len(fingerprints(contexts[0]))} parity=True")
        print("hostname=True verify=CERT_REQUIRED floor=TLS1.2_or_higher keylog=None")
        print("environment_unchanged=True keylog_file_absent=True")
    finally:
        for k, v in original.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
