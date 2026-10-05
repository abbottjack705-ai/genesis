"""Hostile Windows environment-name variants against production TLS context."""
import os, shutil, ssl, sys
from pathlib import Path
candidate = Path(sys.argv[1]).resolve()
sys.path[:0] = [str(candidate / "adapters"), str(candidate / "adapters" / "src"), str(candidate / "src")]
from adapter_tests import tls_support
from genesis_adapters.oddspapi.transport_http import tls_context
pki = tls_support.new_pki("localhost", authority_name="R7 synthetic hostile CA")
der = ssl.PEM_cert_to_DER_cert(pki.ca_file.read_text())
try:
    for spelling in ("SSL_CERT_FILE", "ssl_cert_file", "SsL_CeRt_FiLe"):
        os.environ[spelling] = str(pki.ca_file)
        os.environ["sslkeylogfile"] = str(pki.directory / "keylog.txt")
        context = tls_context()
        trusted = der in context.get_ca_certs(binary_form=True)
        print("variant", spelling, "canonical_present", "SSL_CERT_FILE" in os.environ,
              "attacker_trusted", trusted, "ca_count", len(context.get_ca_certs()),
              "verify", context.verify_mode.name, "hostname", context.check_hostname,
              "keylog", context.keylog_filename, "keylog_created", (pki.directory / "keylog.txt").exists())
        assert not trusted and context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
        assert context.keylog_filename is None
        os.environ.pop("SSL_CERT_FILE", None)
        os.environ.pop("SSLKEYLOGFILE", None)
finally:
    os.environ.pop("SSL_CERT_FILE", None)
    os.environ.pop("SSLKEYLOGFILE", None)
    shutil.rmtree(pki.directory)
