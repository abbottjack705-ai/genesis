"""R6 / RA5-003 - the production TLS trust boundary (design 7.6: "TLS verification uses the system trust store and is
never disabled").

The defect: ``tls_context()`` was the interpreter's stock context, which obeys ``SSL_CERT_FILE`` / ``SSL_CERT_DIR``, and
the repository committed a test CA together with the PRIVATE KEY of a leaf certificate naming ``api.oddspapi.io``. An
environment variable alone then made the unmodified production transport trust that CA, complete a handshake and hand
the keyed request line (``apiKey=...``) to anyone holding the repository: a credential-theft primitive.

Closed three ways, each tested here:

* production never takes an environment-chosen CA (or key-log file): ``tls_context()`` builds the stock platform
  context with those variables hidden, so legitimate OS trust is kept and nothing else is added. The tests use the
  WORST-CASE attacker - a valid CA and a valid leaf for the production host name - through every route the audit
  named, in-process and in a child that was started with the variable already set;
* no certificate or private key is committed at all: the loopback tests mint a throwaway PKI per run
  (``tls_support``), and static checks fail if any key block or key/certificate file reaches ``adapters/``;
* the formerly committed CA is pinned as a RETIRED negative vector: injecting that exact certificate through
  ``SSL_CERT_FILE`` does not put it in the production trust store.

The PKI minter is test scaffolding verified by an independent oracle (OpenSSL, through ``ssl``).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from genesis_adapters.oddspapi import transport_http as th
from genesis_adapters.secrets import Secret

from . import parser_support as ps
from . import tls_support
from .loopback_support import PINNED_HOST, LoopbackHttps, Reply, process_pki, test_ca_context
from .support import ADAPTERS, REPO, SENTINEL_KEY, FixedClock, child_env, scratch_root
from .test_v05_transport_http import deadline, odds_request

T0 = "2026-10-01T12:00:00.000000Z"
ENVIRONMENT_NAMES = ("SSL_CERT_FILE", "SSL_CERT_DIR", "SSLKEYLOGFILE")

# The CA that was committed at b22263e (``adapters/adapter_tests/fixtures/tls/test-ca.pem``, subject "Genesis adapter
# TEST-ONLY loopback CA", valid to 2046, no name constraints). RETIRED: public data only (its private key was
# destroyed after it signed the one leaf), kept here solely as a negative test vector.
RETIRED_CA_PEM = """-----BEGIN CERTIFICATE-----
MIIBxTCCAWugAwIBAgIUc2jHhHqitjb9lbUhRgAmMfrlhCEwCgYIKoZIzj0EAwIw
MDEuMCwGA1UEAwwlR2VuZXNpcyBhZGFwdGVyIFRFU1QtT05MWSBsb29wYmFjayBD
QTAeFw0yNjA5MjkxMDQwMjdaFw00NjA5MjQxMDQwMjdaMDAxLjAsBgNVBAMMJUdl
bmVzaXMgYWRhcHRlciBURVNULU9OTFkgbG9vcGJhY2sgQ0EwWTATBgcqhkjOPQIB
BggqhkjOPQMBBwNCAAQ1k0tvnYedia9sEvIjMnHxHWYRw40Cqdzxa5GSLKoxHpUz
6AtIHTLttbEs5cZ1YWQgAh6t8ExQhrYR82grnHFXo2MwYTAdBgNVHQ4EFgQUCE3W
7ADJx99JHCg1r+pUABibnI4wHwYDVR0jBBgwFoAUCE3W7ADJx99JHCg1r+pUABib
nI4wDwYDVR0TAQH/BAUwAwEB/zAOBgNVHQ8BAf8EBAMCAQYwCgYIKoZIzj0EAwID
SAAwRQIgB1KexoOCztYptIe0G/0CzUFOhavp/ZsVOHajZD78sOMCIQDPqsC1F5Ms
kEs9bqnfekvWo10lRinjYtq6PPofBZdy6A==
-----END CERTIFICATE-----
"""
RETIRED_CA_SHA256 = "ee35ac3028859738353580d4a3de7ac15831351d3ff5ca8848fdaa47dc825830"


def send_through(context: ssl.SSLContext, server: LoopbackHttps):
    """One keyed request through the REAL transport with ``context``, to ``server`` on loopback."""

    transport = th.HttpsTransport(Secret(SENTINEL_KEY), credential_param="apiKey", policy=ps.POLICY,
                                  ssl_context=context, connect_address=server.address)
    return transport.send(odds_request(), clock=FixedClock(T0, step_micros=1000), deadline_at=deadline())


def server_with(pki: tls_support.Pki) -> LoopbackHttps:
    return LoopbackHttps([Reply(body=b"[]")], pki=pki)


class AttackerPkiCannotAuthorizeTheProductionPathTests(unittest.TestCase):
    """The worst case: the attacker owns a CA and a leaf for the pinned production host, and controls the
    environment of the runner."""

    def setUp(self):
        self.attacker = tls_support.new_pki(PINNED_HOST, authority_name="attacker CA")
        self.server = server_with(self.attacker)
        self.addCleanup(self.server.close)

    def refused(self, result):
        self.assertEqual(result.outcome, "NO_RESPONSE")
        self.assertEqual(result.sanitized_error["class"], "SSLCertVerificationError")
        self.assertEqual(self.server.seen, [], "a request line (the key!) reached the impostor")

    def test_control_a_context_that_trusts_the_attacker_explicitly_does_complete_the_handshake(self):
        # not vacuous: this PKI is valid for the pinned host, and what the impostor then sees is the keyed line
        result = send_through(self.attacker.client_context(), self.server)
        self.assertEqual((result.outcome, result.http_status), ("RESPONSE", 200))
        self.assertIn("apiKey=", self.server.seen[0].request_line)

    def test_ssl_cert_file_naming_the_attacker_ca_does_not_authorize_the_production_context(self):
        with mock.patch.dict(os.environ, {"SSL_CERT_FILE": str(self.attacker.ca_file)}):
            context = th.tls_context()
        self.refused(send_through(context, self.server))

    def test_ssl_cert_dir_naming_the_attacker_ca_does_not_authorize_the_production_context(self):
        with mock.patch.dict(os.environ, {"SSL_CERT_DIR": str(self.attacker.hashed_directory())}):
            context = th.tls_context()
        self.refused(send_through(context, self.server))

    def test_every_variable_at_once_does_not_authorize_the_production_context(self):
        with scratch_root() as root:
            env = {"SSL_CERT_FILE": str(self.attacker.ca_file), "SSL_CERT_DIR": str(self.attacker.hashed_directory()),
                   "SSLKEYLOGFILE": str(root / "keys.log")}
            with mock.patch.dict(os.environ, env):
                context = th.tls_context()
        self.refused(send_through(context, self.server))

    def test_the_variable_set_before_the_interpreter_starts_does_not_authorize_the_production_context(self):
        """The audit's p70 scenario, in a fresh process whose ENVIRONMENT already names the attacker CA."""

        code = (
            "import json, sys; sys.path.insert(0, 'adapters'); import adapter_tests\n"
            "import os\n"
            "from datetime import datetime, timedelta, timezone\n"
            "from genesis.time import iso_utc\n"
            "from genesis_adapters.clock import SystemUtcClock\n"
            "from genesis_adapters.oddspapi import transport_http as th\n"
            "from genesis_adapters.secrets import Secret\n"
            "from adapter_tests import parser_support as ps\n"
            "from adapter_tests.test_v05_transport_http import odds_request\n"
            "t = th.HttpsTransport(Secret(os.environ['K']), credential_param='apiKey', policy=ps.POLICY,\n"
            "                      ssl_context=th.tls_context(), connect_address=('127.0.0.1', int(os.environ['P'])))\n"
            "r = t.send(odds_request(), clock=SystemUtcClock(drift_max_ms=ps.POLICY.wall_monotonic_drift_max_ms),\n"
            "           deadline_at=iso_utc(datetime.now(timezone.utc) + timedelta(seconds=20)))\n"
            "print(json.dumps([r.outcome, (r.sanitized_error or {}).get('class')]))\n")
        for name, value in (("SSL_CERT_FILE", self.attacker.ca_file), ("SSL_CERT_DIR", self.attacker.hashed_directory())):
            with self.subTest(name):
                env = child_env({name: str(value), "K": SENTINEL_KEY, "P": str(self.server.port)})
                with scratch_root() as prefix:
                    env["PYTHONPYCACHEPREFIX"] = str(prefix)
                    proc = subprocess.run([sys.executable, "-B", "-c", code], env=env, cwd=str(REPO),
                                          capture_output=True, timeout=120)
                self.assertEqual(proc.returncode, 0, proc.stderr[-600:])
                self.assertEqual(json.loads(proc.stdout), ["NO_RESPONSE", "SSLCertVerificationError"])
                self.assertEqual(self.server.seen, [])


class ProductionContextConstructionTests(unittest.TestCase):
    """R7 (hostile audit RA6-003) replaced the mechanism these tests first pinned. R6 hid the three variables by editing
    ``os.environ`` around ``ssl.create_default_context()`` and restored them afterwards; that is not thread-safe, so R7
    builds the context from scratch and never touches the environment (``test_v05_r7_tls_context``). The tests below keep
    every INVARIANT the R6 versions protected - unset variables stay unset, unrelated variables are untouched, the
    environment is unchanged even when the context cannot be built, the three properties are stated, verification and
    host-name checking are required, the interpreter's protocol ceiling is kept - and no longer pin the mechanism."""

    def test_the_environment_is_unchanged_while_the_context_is_built_and_afterwards(self):
        # was: "hidden while built, restored afterwards". Now there is nothing to hide and nothing to restore
        values = {"SSL_CERT_FILE": "/x/file.pem", "SSL_CERT_DIR": "/x/dir", "SSLKEYLOGFILE": "/x/keys.log"}
        seen = []
        real = ssl.SSLContext.load_verify_locations

        def spy(this, *args, **kwargs):
            seen.append({name: os.environ.get(name) for name in ENVIRONMENT_NAMES})
            return real(this, *args, **kwargs)

        with mock.patch.dict(os.environ, values), mock.patch.object(ssl.SSLContext, "load_verify_locations", spy):
            th.tls_context()
            self.assertEqual({name: os.environ.get(name) for name in ENVIRONMENT_NAMES}, values)
        self.assertTrue(seen, "the trust store was never loaded")
        self.assertTrue(all(snapshot == values for snapshot in seen), "the environment changed while the context was built")

    def test_the_environment_is_unchanged_even_when_the_context_cannot_be_built(self):
        def broken(*args, **kwargs):
            raise OSError("no trust store")

        values = {"SSL_CERT_FILE": "/x/file.pem", "SSL_CERT_DIR": "/x/dir", "SSLKEYLOGFILE": "/x/keys.log"}
        with mock.patch.dict(os.environ, values), mock.patch.object(ssl.SSLContext, "load_verify_locations", broken):
            with self.assertRaises(OSError):
                th.tls_context()
            self.assertEqual({name: os.environ.get(name) for name in ENVIRONMENT_NAMES}, values)

    def test_unset_variables_stay_unset(self):
        with mock.patch.dict(os.environ):
            for name in ENVIRONMENT_NAMES:
                os.environ.pop(name, None)
            th.tls_context()
            self.assertTrue(all(name not in os.environ for name in ENVIRONMENT_NAMES))

    def test_only_the_named_variables_are_touched(self):
        with mock.patch.dict(os.environ, {"GENESIS_R6_UNRELATED": "kept"}):
            th.tls_context()
            self.assertEqual(os.environ["GENESIS_R6_UNRELATED"], "kept")

    def test_the_stock_factory_is_never_consulted_so_what_it_would_hand_back_cannot_matter(self):
        # was: "whatever the stock factory hands back, the production context states its own three properties". The
        # factory is not used at all any more (it is what read the environment); the properties are stated on a context
        # built from scratch
        def forbidden(*args, **kwargs):
            raise AssertionError("the stock factory was consulted")

        with mock.patch.object(th.ssl, "create_default_context", forbidden):
            context = th.tls_context()
        self.assertEqual((context.keylog_filename, context.check_hostname, context.verify_mode),
                         (None, True, ssl.CERT_REQUIRED))

    def test_verification_and_host_name_checking_are_still_required(self):
        context = th.tls_context()
        self.assertEqual((context.verify_mode, context.check_hostname), (ssl.CERT_REQUIRED, True))
        # the protocol ceiling is the interpreter's own; the floor is stated (it used to be inherited from the build:
        # this host's 3.12 reports no floor where 3.11 and 3.13 report TLS 1.2) and is never below what the stock context
        # sets
        stock = ssl.create_default_context()
        self.assertEqual(context.maximum_version, stock.maximum_version)
        self.assertEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
        if stock.minimum_version not in (ssl.TLSVersion.MINIMUM_SUPPORTED, ssl.TLSVersion.SSLv3):
            self.assertGreaterEqual(context.minimum_version, stock.minimum_version)

    def test_the_key_log_file_named_by_the_environment_is_never_written(self):
        attacker = tls_support.new_pki(PINNED_HOST, authority_name="attacker CA")
        server = server_with(attacker)
        self.addCleanup(server.close)
        with scratch_root() as root:
            log = root / "keys.log"
            with mock.patch.dict(os.environ, {"SSLKEYLOGFILE": str(log)}):
                production = th.tls_context()
            self.assertIsNone(production.keylog_filename)
            self.assertFalse(log.exists(), "the environment-chosen key-log file was even opened")
            send_through(production, server)                                         # a (refused) handshake
            self.assertFalse(log.exists(), "TLS secrets were written to an environment-chosen file")
            with mock.patch.dict(os.environ, {"SSLKEYLOGFILE": str(log)}):
                stock = ssl.create_default_context()                                  # control: the env IS obeyed
            self.assertEqual(stock.keylog_filename, str(log))
            stock.keylog_filename = None                                               # release the file before the temp root is removed on Windows

    def test_the_transport_without_an_injected_context_uses_the_production_factory(self):
        sentinel = ssl.create_default_context()
        with mock.patch.object(th, "tls_context", return_value=sentinel) as factory:
            transport = th.HttpsTransport(Secret(SENTINEL_KEY), credential_param="apiKey", policy=ps.POLICY)
        factory.assert_called_once_with()
        self.assertIs(transport._context, sentinel)

    def test_the_retired_committed_ca_cannot_be_injected_into_the_production_trust_store(self):
        der = ssl.PEM_cert_to_DER_cert(RETIRED_CA_PEM)
        self.assertEqual(hashlib.sha256(der).hexdigest(), RETIRED_CA_SHA256)         # the vector is what it says
        with scratch_root() as root:
            injected = root / "retired-ca.pem"
            injected.write_text(RETIRED_CA_PEM, encoding="ascii")
            with mock.patch.dict(os.environ, {"SSL_CERT_FILE": str(injected)}):
                production = th.tls_context()
                stock = ssl.create_default_context()                                  # control: the env IS obeyed
        loaded = {hashlib.sha256(item).hexdigest() for item in production.get_ca_certs(binary_form=True)}
        self.assertNotIn(RETIRED_CA_SHA256, loaded)
        self.assertIn(RETIRED_CA_SHA256, {hashlib.sha256(item).hexdigest()
                                          for item in stock.get_ca_certs(binary_form=True)})


# ---------------------------------------------------------------------------------------------------------
KEY_BLOCK = re.compile("-----BEGIN [A-Z0-9 ]*" + "PRIVATE KEY-----")
KEY_SUFFIXES = {".pem", ".key", ".crt", ".cer", ".der", ".p12", ".pfx", ".jks", ".p8"}


def adapter_files():
    for directory, names, files in os.walk(ADAPTERS):
        names[:] = [name for name in names if name not in ("__pycache__", ".git")]
        for name in files:
            yield Path(directory) / name


class NoTlsKeyMaterialIsCommittedTests(unittest.TestCase):
    def test_no_private_key_block_exists_anywhere_under_adapters(self):
        found = []
        for path in adapter_files():
            if path.stat().st_size > 5_000_000:
                continue
            if KEY_BLOCK.search(path.read_bytes().decode("utf-8", "ignore")):
                found.append(path.relative_to(ADAPTERS).as_posix())
        self.assertEqual(found, [], "a private key block is committed")

    def test_no_certificate_or_key_file_exists_anywhere_under_adapters(self):
        found = [path.relative_to(ADAPTERS).as_posix() for path in adapter_files() if path.suffix.lower() in KEY_SUFFIXES]
        self.assertEqual(found, [])

    def test_the_old_tls_fixture_directory_is_gone_and_no_attribute_rule_remains_for_it(self):
        self.assertFalse((ADAPTERS / "adapter_tests" / "fixtures" / "tls").exists())
        text = (ADAPTERS / ".gitattributes").read_text(encoding="utf-8")
        self.assertNotIn("fixtures/tls", text)

    def test_no_tracked_file_is_key_material_according_to_git(self):
        tracked = subprocess.run(["git", "ls-files", "--", "adapters"], capture_output=True, text=True, cwd=REPO,
                                 check=True).stdout.split()
        self.assertEqual([name for name in tracked if Path(name).suffix.lower() in KEY_SUFFIXES], [])

    def test_no_production_module_embeds_a_certificate_or_key_block(self):
        for path in (ADAPTERS / "src").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertFalse(KEY_BLOCK.search(text) or "-----BEGIN CERTIFICATE" in text, path.name)


# ---------------------------------------------------------------------------------------------------------
def handshake(pki: tls_support.Pki, *, server_hostname: str, context: ssl.SSLContext | None = None) -> str:
    """One TLS handshake against a one-shot server presenting ``pki``: "OK" or the exception class name."""

    listener = socket.create_server(("127.0.0.1", 0))
    server_context = pki.server_context()

    def serve():
        try:
            raw, _ = listener.accept()
            try:
                server_context.wrap_socket(raw, server_side=True).close()
            except (ssl.SSLError, OSError):
                raw.close()
        except OSError:
            pass

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        client = (context or pki.client_context()).wrap_socket(
            socket.create_connection(listener.getsockname(), timeout=10), server_hostname=server_hostname)
        client.close()
        return "OK"
    except Exception as exc:
        return type(exc).__name__
    finally:
        listener.close()
        thread.join(timeout=5)


class PkiMinterTests(unittest.TestCase):
    """The throwaway PKI is accepted or refused by an independent verifier (OpenSSL), exactly as a real one would be."""

    def test_a_minted_chain_verifies_for_its_host_and_only_its_host(self):
        pki = tls_support.new_pki(PINNED_HOST)
        self.assertEqual(handshake(pki, server_hostname=PINNED_HOST), "OK")
        self.assertEqual(handshake(pki, server_hostname="other.example"), "SSLCertVerificationError")

    def test_a_client_that_does_not_trust_the_minted_ca_refuses_it(self):
        pki = tls_support.new_pki(PINNED_HOST)
        stranger = tls_support.new_pki(PINNED_HOST)
        self.assertEqual(handshake(pki, server_hostname=PINNED_HOST, context=stranger.client_context()),
                         "SSLCertVerificationError")

    def test_a_name_constrained_authority_cannot_vouch_for_the_production_host_even_when_trusted(self):
        constrained = tls_support.new_pki(PINNED_HOST, permitted_dns=("loopback.test",))
        self.assertEqual(handshake(constrained, server_hostname=PINNED_HOST), "SSLCertVerificationError")
        allowed = tls_support.new_pki("host.loopback.test", permitted_dns=("loopback.test",))
        self.assertEqual(handshake(allowed, server_hostname="host.loopback.test"), "OK")

    def test_an_expired_certificate_is_refused(self):
        from datetime import datetime, timedelta, timezone

        past = datetime.now(timezone.utc) - timedelta(days=30)
        authority = tls_support.new_authority("expired CA", valid_days=1, now=past)
        leaf = tls_support.issue_leaf(authority, PINNED_HOST, valid_days=1, now=past)
        with scratch_root() as root:
            for name, text in (("leaf.pem", leaf.cert_pem), ("leaf.key", leaf.key_pem)):
                (root / name).write_text(text, encoding="ascii")
            pki = tls_support.Pki(authority, leaf, PINNED_HOST, root)
            self.assertEqual(handshake(pki, server_hostname=PINNED_HOST), "SSLCertVerificationError")

    def test_subject_hash_file_names_are_what_openssl_computes(self):
        # known answers produced by ``openssl x509 -subject_hash`` over certificates minted with these subjects
        vectors = {"genesis-r6-hash-vector": "96e51a94.0", "Genesis TEST-ONLY throwaway CA": "fadec2d0.0",
                   "  Mixed   CASE name ": "f7ef3b8c.0", "a": "20b69a40.0", "attacker CA": "09ce2d30.0"}
        for name, expected in vectors.items():
            with self.subTest(name):
                self.assertEqual(tls_support.subject_hash_filename(name), expected)

    def test_the_server_key_is_owner_only_and_the_process_pki_is_removed_at_exit(self):
        pki = process_pki()
        if os.name != "nt":
            self.assertEqual(pki.key_file.stat().st_mode & 0o777, 0o600)
        code = ("import sys; sys.path.insert(0, 'adapters'); import adapter_tests\n"
                "from adapter_tests.loopback_support import process_pki\n"
                "print(process_pki().directory)\n")
        with scratch_root() as prefix:
            env = child_env({"PYTHONPYCACHEPREFIX": str(prefix)})
            proc = subprocess.run([sys.executable, "-B", "-c", code], env=env, cwd=str(REPO), capture_output=True,
                                  timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr[-400:])
        self.assertFalse(Path(proc.stdout.decode().strip()).exists(), "the throwaway PKI outlived its process")

    def test_the_default_test_context_trusts_only_the_process_ca(self):
        server = LoopbackHttps([Reply(body=b"[]")])
        self.addCleanup(server.close)
        self.assertEqual(send_through(test_ca_context(), server).outcome, "RESPONSE")
        self.assertEqual(send_through(th.tls_context(), server).sanitized_error["class"], "SSLCertVerificationError")


@unittest.skipUnless(os.name == "nt", "NTFS ACLs are Windows-specific")
class WindowsPkiAclTests(unittest.TestCase):
    def test_directory_is_owner_only_before_key_creation_and_key_is_owner_only(self):
        from genesis_adapters.credential import _windows_principals, _windows_user

        owner = {_windows_user()}
        real_open = tls_support.os.open
        checked_key_creation = []

        def open_after_acl(path, flags, mode=0o777):
            if Path(path).name == "leaf.key":
                self.assertEqual(_windows_principals(Path(path).parent), owner)
                checked_key_creation.append(True)
            return real_open(path, flags, mode)

        with mock.patch.object(tls_support.os, "open", side_effect=open_after_acl):
            pki = tls_support.new_pki(PINNED_HOST)
        try:
            self.assertEqual(checked_key_creation, [True])
            self.assertEqual(_windows_principals(pki.key_file), owner)
            self.assertIsInstance(pki.server_context(), ssl.SSLContext)
        finally:
            shutil.rmtree(pki.directory)
        self.assertFalse(pki.key_file.exists())
        self.assertFalse(pki.directory.exists())

    def test_acl_failure_does_not_write_private_key_material(self):
        real_mkdtemp = tls_support.tempfile.mkdtemp
        real_secure = tls_support._secure_windows_acl
        for fail_directory in (True, False):
            with self.subTest(fail_directory=fail_directory):
                created = []

                def record_directory(*args, **kwargs):
                    path = real_mkdtemp(*args, **kwargs)
                    created.append(Path(path))
                    return path

                def fail_acl(path, *, directory):
                    if directory == fail_directory:
                        raise PermissionError("synthetic ACL failure")
                    return real_secure(path, directory=directory)

                with mock.patch.object(tls_support.tempfile, "mkdtemp", side_effect=record_directory), \
                        mock.patch.object(tls_support, "_secure_windows_acl", side_effect=fail_acl), \
                        mock.patch.object(tls_support.Leaf, "key_pem", new_callable=mock.PropertyMock) as key_pem:
                    with self.assertRaisesRegex(PermissionError, "synthetic ACL failure"):
                        tls_support.new_pki(PINNED_HOST)
                    key_pem.assert_not_called()
                self.assertEqual(len(created), 1)
                self.assertFalse(created[0].exists())


if __name__ == "__main__":
    unittest.main()
