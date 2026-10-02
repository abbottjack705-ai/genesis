"""AREA A: exception / process-control containment at the real HttpsTransport (independent attack set)."""
from boot import *
import gc, sys, traceback, warnings
from indep_scan import hits, forms
from genesis_adapters.oddspapi.transport_http import HttpsTransport
from genesis_adapters.secrets import Secret
from genesis_adapters.config import load_policy
from genesis_adapters.oddspapi import endpoints as ep
KEY = "Zq8vLm2XpR7tYk4WnB9cD3fHsJ1aQ7"       # identifier-safe, so it can be a class name
DIGITS = "918273645546372819182736455463"      # digits-only key (errno attack)
pol = load_policy(CONFIG / "oddspapi_slice1_policy.json")
specs = ep.load_endpoints(CONFIG / "oddspapi_v4_endpoints.json", pol)
req = ep.build_request(specs["META_SPORTS"])
TQ = "2026-10-03T10:00:00.000000Z"; DEADLINE = parp.iso_add(TQ, seconds=60)
def keyed_url(k): return "https://api.oddspapi.io/v4/sports?apiKey=" + k

def make(key, raiser, stage):
    class Conn:
        def __init__(self, *a): pass
        def open(self, t):
            if stage == "open": raiser()
        def settimeout(self, t): pass
        def write(self, m, t, h):
            if stage == "write": raiser()
        def read_head(self):
            if stage == "head": raiser()
            return 200, [("content-type", "application/json")]
        def read_chunk(self, n):
            if stage == "body": raiser()
            return b""
        def finished(self): return False
        def close(self):
            if stage == "close": raiser()
    return HttpsTransport(Secret(key), credential_param="apiKey", policy=pol, connection_factory=lambda *a: Conn())

def frame_dump(exc):
    texts = []
    tb = exc.__traceback__
    while tb is not None:
        if "oddspapi/transport" not in tb.tb_frame.f_code.co_filename:   # only the product's frames, not this harness's
            tb = tb.tb_next; continue
        for k, v in tb.tb_frame.f_locals.items():
            try: texts.append(repr(v))
            except Exception: pass
        tb = tb.tb_next
    return "\n".join(texts)

R = {}
def attack(name, key, raiser, stage="write"):
    t = make(key, raiser, stage)
    clock = FixedClock(parp.iso_add(TQ, seconds=1), step_micros=10)
    caught = None; result = None
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        try:
            result = t.send(req, clock=clock, deadline_at=DEADLINE)
        except BaseException as e:
            caught = e
    fs = forms(key)
    text = ""
    if result is not None: text = repr(result)
    if caught is not None:
        text += repr(caught) + repr(caught.args) + repr(getattr(caught, "__notes__", None)) + repr(caught.__cause__) + repr(caught.__context__) + frame_dump(caught) + "".join(traceback.format_exception(caught))
    leaked = hits(text.encode(), key, fs)
    R[name] = {"result": (result.outcome, result.sanitized_error) if result else None,
               "raised": (type(caught).__name__, caught.args if caught else None, getattr(caught, "code", "-"), caught.__cause__ is None if caught else None, caught.__context__ is None if caught else None, hasattr(caught, "__notes__") if caught else None) if caught else None,
               "LEAK": leaked}

U = keyed_url
def exc_with(url):
    e = OSError(7, url); e.filename = url; e.add_note(url); return e
for stage in ("open", "write", "head", "body", "close"):
    attack(f"ordinary_{stage}", KEY, lambda: (_ for _ in ()).throw(exc_with(U(KEY))), stage)
# class named as the key
Named = type(KEY, (Exception,), {})
attack("class_named_as_key", KEY, lambda: (_ for _ in ()).throw(Named(U(KEY))), "write")
# errno that is the key digits
class E2(OSError): pass
def raise_errno():
    e = E2(); e.errno = int(DIGITS); raise e
attack("errno_is_key_digits", DIGITS, raise_errno, "write")
# chained cause/context
def chained():
    try:
        raise ValueError(U(KEY))
    except ValueError as a:
        raise RuntimeError("wrap " + U(KEY)) from a
attack("chained_cause_context", KEY, chained, "head")
# warnings carrying URL
def warn_then_fail():
    warnings.warn(U(KEY)); raise OSError("x")
attack("warning_with_url", KEY, warn_then_fail, "write")
# KeyboardInterrupt with url arg, notes, cause
def kbd():
    k = KeyboardInterrupt(U(KEY)); k.add_note(U(KEY)); raise k from ValueError(U(KEY))
for stage in ("open", "write", "head", "body", "close"):
    attack(f"KeyboardInterrupt_{stage}", KEY, kbd, stage)
for code in (37, None, U(KEY), True, 3.5, 2**70, -1):
    def sx(code=code): raise SystemExit(code)
    attack(f"SystemExit_{type(code).__name__}_{str(code)[:12]}", KEY, sx, "write")
# KeyboardInterrupt raised from INSIDE the ordinary handler (errno property)
class Evil(Exception):
    @property
    def errno(self): raise KeyboardInterrupt(U(KEY))
def evil(): raise Evil(U(KEY))
attack("KeyboardInterrupt_in_errno_property", KEY, evil, "write")
# GeneratorExit and a BaseException subclass without a no-arg ctor
class Odd(BaseException):
    def __init__(self, a, b): super().__init__(a, b)
attack("Odd_BaseException", KEY, lambda: (_ for _ in ()).throw(Odd(U(KEY), 1)), "write")
attack("GeneratorExit", KEY, lambda: (_ for _ in ()).throw(GeneratorExit(U(KEY))), "write")
for k, v in R.items():
    print(f"{k:42s} LEAK={v['LEAK']!s:5s} result={v['result']} raised={v['raised']}")
