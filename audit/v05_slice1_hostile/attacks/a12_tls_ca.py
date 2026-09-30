"""Area 12 (HA-006): the committed test TLS private key and the CA-injection seam.

K1 the key is a valid private key for the committed certificate, and that certificate names the REAL
   provider host (so anyone holding the repository can impersonate ``api.oddspapi.io`` to a client that
   trusts ``test-ca.pem``);
K2 the key ships in ``git archive`` and carries no ``export-ignore``;
K3 the production CLI ``run`` (the only live entry point) accepts ``--ca-file`` together with a loopback
   ``--connect``: the live transport then trusts ONLY the injected CA, verification still on;
K4 the loopback restriction itself (non-loopback ``--connect`` refused; ``--ca-file`` alone refused).

    python -B attacks/a12_tls_ca.py --repo <candidate> --commit cfcff3d
"""

from __future__ import annotations

import argparse
import io
import ssl
import subprocess
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--commit", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    repo = c.setup(args.repo)
    tls = repo / "adapters" / "adapter_tests" / "fixtures" / "tls"

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    matched = True
    try:
        context.load_cert_chain(tls / "server.pem", tls / "server.key")
    except ssl.SSLError:
        matched = False
    pem = (tls / "server.pem").read_text(encoding="ascii")
    decoded = ssl._ssl._test_decode_cert(str(tls / "server.pem")) if hasattr(ssl, "_ssl") else {}
    names = [value for kind, value in decoded.get("subjectAltName", ())]
    c.check("A12", "K1: committed key matches the committed server certificate, which names the real provider host",
            matched and "api.oddspapi.io" in names, key_matches_cert=matched, san=names)

    attr = subprocess.run(["git", "-C", str(repo), "check-attr", "export-ignore", "--",
                           "adapters/adapter_tests/fixtures/tls/server.key"], capture_output=True, text=True).stdout.strip()
    archive = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", args.commit], capture_output=True).stdout
    names_in_tar = tarfile.open(fileobj=io.BytesIO(archive)).getnames()
    c.check("A12", "K2: server.key has export-ignore and is absent from git archive (HA-006 remediation 1)",
            attr.endswith(": set") and "adapters/adapter_tests/fixtures/tls/server.key" not in names_in_tar,
            check_attr=attr, shipped="adapters/adapter_tests/fixtures/tls/server.key" in names_in_tar)

    from genesis_adapters import cli
    from genesis_adapters.config import load_policy
    from genesis_adapters.oddspapi.transport_http import HttpsTransport, tls_context
    from genesis_adapters.secrets import Secret

    injected = tls_context(str(tls / "test-ca.pem"))
    policy = load_policy(repo / "adapters" / "config" / "oddspapi_slice1_policy.json")
    accepted = True
    try:
        HttpsTransport(Secret(c.SENTINEL), credential_param="apiKey", policy=policy, ssl_context=injected,
                       connect_address=cli._loopback("127.0.0.1:8443"))
    except Exception:
        accepted = False
    parser = cli._parser()
    parsed = parser.parse_args(["run", "--root", "r", "--plan", "p", "--mode", "G2R", "--connect", "127.0.0.1:8443",
                                "--ca-file", str(tls / "test-ca.pem")])
    source = Path(cli.__file__).read_text(encoding="utf-8")
    wired = "ssl_context=tls_context(args.ca_file)" in source
    c.check("A12", "K3: the live CLI run path accepts an injected CA with a loopback address (seam reachable in live "
                   "mode; HA-006 remediation 2 NOT met)", not (accepted and parsed.ca_file and wired),
            transport_accepts_injected_ca=accepted, cli_parses_ca_file=bool(parsed.ca_file), cmd_run_wires_it=wired,
            trust_store_count=len(injected.get_ca_certs()))
    refused = []
    for value in ("10.0.0.1:443", "api.oddspapi.io:443"):
        try:
            cli._loopback(value)
            refused.append((value, False))
        except ValueError:
            refused.append((value, True))
    c.check("A12", "K4: non-loopback --connect values are refused", all(r for _, r in refused), cases=refused)
    return c.finish(args.out)


if __name__ == "__main__":
    sys.exit(main())
