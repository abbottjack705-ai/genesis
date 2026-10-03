"""T02 (RA5-003): process-global environment mutation in ``tls_context()`` under threads.

``tls_context()`` pops SSL_CERT_FILE / SSL_CERT_DIR / SSLKEYLOGFILE from os.environ, builds the stock context and
restores them. With SSL_CERT_FILE pointing at the RETIRED test CA (restored from history by t01 into the scratch dir):
  R1 concurrent tls_context() calls: does any returned context trust the retired CA? (thread B can compute its
     "hidden" set while thread A has the variables popped, and then build its context after A restored them)
  R2 an unrelated thread reading os.environ during the window: does it observe the variable missing?
  R3 after everything: is the environment exactly restored?
Loopback/no network at all: only context construction and get_ca_certs().
usage: t02_tls_env_race.py <candidate_dir> [rounds]
"""
import os, sys, threading, pathlib, json, time
CAND = sys.argv[1]
ROUNDS = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
SCR = pathlib.Path(os.environ["AUDIT_SCRATCH"]) / "oldtls"
CA = str(SCR / "test-ca.pem")
assert os.path.exists(CA), "run t01 first (it restores the retired CA into the scratch dir)"
os.environ["SSL_CERT_FILE"] = CA
os.environ.pop("SSL_CERT_DIR", None)
sys.path.insert(0, CAND + "/adapters"); os.chdir(CAND)
import adapter_tests  # noqa: provenance guard + network hook
from genesis_adapters.oddspapi.transport_http import tls_context

def trusts_retired(ctx):
    return any("TEST-ONLY loopback CA" in dict(x[0] for x in c["subject"]).get("commonName", "")
               for c in ctx.get_ca_certs())

sys.setswitchinterval(1e-6)
poisoned = 0; built = 0; missing_seen = 0; reads = 0
lock = threading.Lock(); stop = False

errors = {}
def builder():
    global poisoned, built
    for _ in range(ROUNDS):
        try:
            ctx = tls_context()
        except Exception as exc:                       # an exception OUT OF tls_context() itself
            import traceback
            frame = traceback.extract_tb(exc.__traceback__)[-1]
            key = "%s at %s:%d" % (type(exc).__name__, frame.filename.split("/")[-1], frame.lineno)
            with lock:
                errors[key] = errors.get(key, 0) + 1
            continue
        bad = trusts_retired(ctx)
        with lock:
            built += 1
            poisoned += bad

def observer():
    global missing_seen, reads
    while not stop:
        value = os.environ.get("SSL_CERT_FILE")
        with lock:
            reads += 1
            missing_seen += value is None

t0 = time.time()
obs = threading.Thread(target=observer); obs.start()
threads = [threading.Thread(target=builder) for _ in range(4)]
[t.start() for t in threads]; [t.join() for t in threads]
stop = True; obs.join()
single = tls_context()
print(json.dumps({
    "python": sys.version.split()[0], "contexts_built_concurrently": built,
    "R1_contexts_trusting_retired_CA": poisoned,
    "R2_observer_reads": reads, "R2_reads_seeing_SSL_CERT_FILE_missing": missing_seen,
    "R4_exceptions_raised_by_tls_context": errors,
    "R3_env_restored": os.environ.get("SSL_CERT_FILE") == CA,
    "single_threaded_context_trusts_retired_CA": trusts_retired(single),
    "seconds": round(time.time() - t0, 1)}))
