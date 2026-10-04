"""R7 / RA6-003 (LOW) - production TLS trust never depends on a process-global mutation race.

The defect (R6): ``tls_context()`` hid ``SSL_CERT_FILE`` / ``SSL_CERT_DIR`` / ``SSLKEYLOGFILE`` by popping them out of
``os.environ`` while the stock context was built, and put them back afterwards. That is correct for one thread and wrong
for two: the check-then-pop raced (``KeyError`` out of ``tls_context()``), a context built while another thread had
restored the variables trusted the environment's CA (9-14 of ~1200 contexts in the audit), and every other thread saw the
variables vanish while it happened. The same audit showed the TLS floor was never stated: on a build whose stock floor is
``MINIMUM_SUPPORTED`` an environment ``OPENSSL_CONF`` lowered the production floor to TLS 1.0.

The invariant: the production context is built WITHOUT reading or writing the environment, from the compiled-in platform
trust locations (and the Windows system stores), with certificate verification, host-name checking and a TLS 1.2 floor
stated explicitly. It is therefore the same under concurrent calls, whatever the environment holds.
"""

from __future__ import annotations

import ast
import inspect
import os
import ssl
import subprocess
import sys
import textwrap
import threading
import unittest
from pathlib import Path
from unittest import mock

from genesis_adapters.oddspapi import transport_http as th

from . import tls_support
from .loopback_support import PINNED_HOST
from .support import REPO, child_env, scratch_root

NAMES = ("SSL_CERT_FILE", "SSL_CERT_DIR", "SSLKEYLOGFILE")


def der_of(pki) -> bytes:
    return ssl.PEM_cert_to_DER_cert(Path(pki.ca_file).read_text(encoding="ascii"))


class Untouchable(dict):
    """An ``os.environ`` stand-in that refuses every write, and records every read of the three names."""

    def __init__(self, source):
        super().__init__(source)
        self.reads = []

    def _no(self, *args, **kwargs):
        raise AssertionError("tls_context() wrote the process environment")

    __setitem__ = __delitem__ = pop = popitem = update = setdefault = clear = _no

    def get(self, key, *args):
        if key in NAMES:
            self.reads.append(key)
        return super().get(key, *args)

    def __getitem__(self, key):
        if key in NAMES:
            self.reads.append(key)
        return super().__getitem__(key)

    def __contains__(self, key):
        if key in NAMES:
            self.reads.append(key)
        return super().__contains__(key)


class TheEnvironmentIsNeitherWrittenNorReadTests(unittest.TestCase):
    def test_building_the_context_writes_nothing_and_never_looks_at_the_key_log_variable(self):
        values = {"SSL_CERT_FILE": "/x/file.pem", "SSL_CERT_DIR": "/x/dir", "SSLKEYLOGFILE": "/x/keys.log"}
        environment = Untouchable({**os.environ, **values})
        with mock.patch.object(os, "environ", environment):
            context = th.tls_context()
        # a write raises (``Untouchable``); the key-log variable is how the stock factory opened an environment-chosen file,
        # and nothing here reads it. (``ssl.get_default_verify_paths`` itself looks at the two CA variables, but the fields
        # used - ``openssl_cafile`` / ``openssl_capath`` - are the compiled-in locations: the next test proves no value
        # of those variables can change what is trusted.)
        self.assertNotIn("SSLKEYLOGFILE", environment.reads)
        self.assertEqual({name: environment[name] for name in NAMES}, values)
        self.assertEqual((context.verify_mode, context.check_hostname, context.keylog_filename),
                         (ssl.CERT_REQUIRED, True, None))

    def test_the_function_contains_no_environment_access_at_all(self):
        tree = ast.parse(textwrap.dedent(inspect.getsource(th.tls_context)))
        touched = sorted({node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
                          and node.attr in ("environ", "putenv", "unsetenv", "getenv")})
        self.assertEqual(touched, [])

    def test_no_environment_variable_changes_what_is_trusted_or_written(self):
        attacker = tls_support.new_pki(PINNED_HOST, authority_name="attacker CA")
        with scratch_root() as root:
            env = {"SSL_CERT_FILE": str(attacker.ca_file), "SSL_CERT_DIR": str(attacker.hashed_directory()),
                   "SSLKEYLOGFILE": str(root / "keys.log")}
            with mock.patch.dict(os.environ, env):
                polluted = th.tls_context()
            with mock.patch.dict(os.environ):
                for name in NAMES:
                    os.environ.pop(name, None)
                clean = th.tls_context()
            self.assertFalse((root / "keys.log").exists())
        trusted = lambda context: sorted(context.get_ca_certs(binary_form=True))
        self.assertNotIn(der_of(attacker), trusted(polluted))
        self.assertEqual(trusted(polluted), trusted(clean))


class ConcurrentConstructionTests(unittest.TestCase):
    """The audit's t02: several threads build contexts while the environment names an attacker's CA."""

    THREADS, CALLS = 4, 120

    def test_concurrent_contexts_never_trust_the_environment_never_raise_and_never_disturb_other_threads(self):
        attacker = tls_support.new_pki(PINNED_HOST, authority_name="attacker CA")
        wanted = der_of(attacker)
        outcomes = {"trusting": 0, "raised": [], "built": 0}
        seen_missing, stop, lock = [], threading.Event(), threading.Lock()
        value = str(attacker.ca_file)

        def build():
            for _ in range(self.CALLS):
                try:
                    context = th.tls_context()
                except BaseException as exc:                              # noqa: BLE001 - the defect raised KeyError
                    with lock:
                        outcomes["raised"].append(type(exc).__name__)
                    continue
                trusting = wanted in context.get_ca_certs(binary_form=True)
                with lock:
                    outcomes["built"] += 1
                    outcomes["trusting"] += trusting

        def observe():                                                    # an unrelated thread reading its own environment
            while not stop.is_set():
                if os.environ.get("SSL_CERT_FILE") != value:
                    seen_missing.append(1)

        with mock.patch.dict(os.environ, {"SSL_CERT_FILE": value}):
            watcher = threading.Thread(target=observe, daemon=True)
            workers = [threading.Thread(target=build) for _ in range(self.THREADS)]
            watcher.start()
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=300)
            stop.set()
            watcher.join(timeout=10)
            self.assertEqual(os.environ.get("SSL_CERT_FILE"), value)
        self.assertEqual(outcomes["raised"], [])
        self.assertEqual(outcomes["trusting"], 0, "a concurrently built context trusted the environment's CA")
        self.assertEqual(outcomes["built"], self.THREADS * self.CALLS)
        self.assertEqual(seen_missing, [], "another thread saw its environment change while a context was built")


class PlatformTrustAndFloorTests(unittest.TestCase):
    def clean_environment(self):
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in NAMES:
            os.environ.pop(name, None)

    def test_the_platform_trust_is_exactly_what_the_stock_context_loads_when_the_environment_adds_nothing(self):
        self.clean_environment()
        production, stock = th.tls_context(), ssl.create_default_context()
        self.assertEqual(sorted(production.get_ca_certs(binary_form=True)), sorted(stock.get_ca_certs(binary_form=True)))
        self.assertEqual(production.cert_store_stats(), stock.cert_store_stats())
        self.assertGreater(production.cert_store_stats()["x509_ca"], 0, "no platform trust at all")

    def test_verification_is_required_and_nothing_the_stock_context_enforces_is_lost(self):
        self.clean_environment()
        production, stock = th.tls_context(), ssl.create_default_context()
        self.assertEqual((production.verify_mode, production.check_hostname), (ssl.CERT_REQUIRED, True))
        self.assertEqual(production.verify_flags & stock.verify_flags, stock.verify_flags,
                         "the production context verifies less strictly than the interpreter's own")
        self.assertEqual(production.options & stock.options, stock.options)
        self.assertEqual(production.maximum_version, stock.maximum_version)
        self.assertEqual(production.protocol, ssl.PROTOCOL_TLS_CLIENT)

    def test_the_floor_is_stated_not_inherited(self):
        self.clean_environment()
        self.assertEqual(th.tls_context().minimum_version, ssl.TLSVersion.TLSv1_2)

    def test_an_environment_openssl_configuration_cannot_lower_the_floor(self):
        """The audit's t03: ``OPENSSL_CONF`` with ``MinProtocol = TLSv1`` / ``SECLEVEL=0`` lowered the floor on a build whose
        stock floor is MINIMUM_SUPPORTED. In a fresh process the production context still refuses everything below 1.2."""

        with scratch_root() as root:
            config = root / "openssl.cnf"
            config.write_text("openssl_conf = default_conf\n[default_conf]\nssl_conf = ssl_sect\n[ssl_sect]\n"
                              "system_default = system_default_sect\n[system_default_sect]\nMinProtocol = TLSv1\n"
                              "CipherString = DEFAULT:@SECLEVEL=0\n", encoding="ascii")
            code = ("import sys; sys.path.insert(0, 'adapters'); import adapter_tests, ssl\n"
                    "from genesis_adapters.oddspapi import transport_http as th\n"
                    "print(th.tls_context().minimum_version.name)\n")
            env = child_env({"OPENSSL_CONF": str(config)}, pycache=root / "pyc")
            proc = subprocess.run([sys.executable, "-B", "-c", code], env=env, cwd=str(REPO), capture_output=True,
                                  timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr[-500:])
        self.assertEqual(proc.stdout.decode().strip(), "TLSv1_2")


class WindowsSystemStoresTests(unittest.TestCase):
    """The Windows branch, driven on any host through the standard library's own public hook (``ssl.enum_certificates``).
    This proves the logic only; real system-store behaviour is the Windows recertification's (WINDOWS_RECERTIFICATION.md)."""

    def test_the_system_stores_are_loaded_and_the_environment_still_adds_nothing(self):
        platform_ca = tls_support.new_pki(PINNED_HOST, authority_name="platform store CA")
        attacker = tls_support.new_pki(PINNED_HOST, authority_name="attacker CA")
        asked = []

        def enum_certificates(store):
            asked.append(store)
            return [(der_of(platform_ca), "x509_asn", True)] if store == "ROOT" else [(b"\x00", "pkcs_7_asn", True)]

        with mock.patch.object(sys, "platform", "win32"), \
                mock.patch.object(ssl, "enum_certificates", enum_certificates, create=True), \
                mock.patch.dict(os.environ, {"SSL_CERT_FILE": str(attacker.ca_file)}):
            context = th.tls_context()
        loaded = context.get_ca_certs(binary_form=True)
        self.assertIn(der_of(platform_ca), loaded)
        self.assertNotIn(der_of(attacker), loaded)
        self.assertEqual(sorted(asked), ["CA", "ROOT"])
        self.assertEqual((context.verify_mode, context.check_hostname), (ssl.CERT_REQUIRED, True))

    def test_only_certificates_trusted_for_server_authentication_are_loaded_and_nothing_raises(self):
        import warnings

        good, other, unlisted = (tls_support.new_pki(PINNED_HOST, authority_name=name) for name in
                                 ("trusted CA", "client-auth-only CA", "garbage"))
        server_auth, client_auth = ssl.Purpose.SERVER_AUTH.oid, ssl.Purpose.CLIENT_AUTH.oid

        def enum_certificates(store):
            if store == "ROOT":
                return [(der_of(good), "x509_asn", {server_auth}),          # trusted for the purpose: loaded
                        (der_of(other), "x509_asn", {client_auth}),         # trusted for another purpose only: not
                        (b"\x00 not a certificate", "x509_asn", True)]      # cannot be loaded: a warning, not a failure
            raise PermissionError("store not readable")                     # a store that cannot be read: a warning too

        with mock.patch.object(sys, "platform", "win32"), \
                mock.patch.object(ssl, "enum_certificates", enum_certificates, create=True), \
                warnings.catch_warnings(record=True) as raised:
            warnings.simplefilter("always")
            context = th.tls_context()
        loaded = context.get_ca_certs(binary_form=True)
        self.assertIn(der_of(good), loaded)
        self.assertNotIn(der_of(other), loaded)
        self.assertEqual(sorted(str(item.message).split(":")[0] for item in raised if item.category is UserWarning),
                         ["Bad certificate in Windows certificate store", "unable to enumerate Windows certificate store"])
        self.assertEqual((context.verify_mode, context.check_hostname), (ssl.CERT_REQUIRED, True))

    def test_a_pkcs7_entry_is_never_loaded_as_a_certificate(self):
        import warnings

        def enum_certificates(store):
            return [(b"\x30\x00", "pkcs_7_asn", True)] if store == "CA" else []

        with mock.patch.object(sys, "platform", "win32"), \
                mock.patch.object(ssl, "enum_certificates", enum_certificates, create=True), \
                warnings.catch_warnings(record=True) as raised:
            warnings.simplefilter("always")
            th.tls_context()
        self.assertEqual([item for item in raised if item.category is UserWarning], [])


if __name__ == "__main__":
    unittest.main()
