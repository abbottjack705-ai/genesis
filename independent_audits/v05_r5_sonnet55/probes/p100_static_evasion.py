"""Q: evasions of the implementer's static scanners (FRZ-05/06/07/08/10/11) using THEIR scanner functions."""
from boot import *
from adapter_tests import static_scan as ss
import textwrap
def c(s): return textwrap.dedent(s)
REL = "genesis_adapters/oddspapi/acquisition.py"
cases11 = {
 "plain except BaseException": c("""
    try: pass
    except BaseException: pass
    """),
 "alias name": c("""
    B = BaseException
    try: pass
    except B: pass
    """),
 "tuple variable": c("""
    T = (KeyboardInterrupt, ValueError)
    try: pass
    except T: pass
    """),
 "builtins attribute": c("""
    import builtins
    try: pass
    except builtins.BaseException: pass
    """),
 "except* (TryStar) BaseException": c("""
    try: pass
    except* BaseException: pass
    """),
 "except* KeyboardInterrupt": c("""
    try: pass
    except* KeyboardInterrupt: pass
    """),
 "suppress(KeyboardInterrupt)": c("""
    import contextlib
    with contextlib.suppress(KeyboardInterrupt): pass
    """),
 "from contextlib import suppress as s": c("""
    from contextlib import suppress as s
    with s(SystemExit): pass
    """),
 "suppress(*tuple)": c("""
    import contextlib
    X = (KeyboardInterrupt,)
    with contextlib.suppress(*X): pass
    """),
 "finally: return": c("""
    def f():
        try: pass
        finally: return 1
    """),
 "finally: continue": c("""
    def f():
        for i in range(2):
            try: pass
            finally: continue
    """),
 "finally: break": c("""
    def f():
        for i in range(2):
            try: pass
            finally: break
    """),
 "signal ignore SIGINT": c("""
    import signal
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    """),
 "except GeneratorExit": c("""
    try: pass
    except GeneratorExit: pass
    """),
 "bare except": c("""
    try: pass
    except: pass
    """),
 "except Exception clean": c("""
    try: pass
    except Exception: pass
    """),
}
print("== FRZ-11")
for name, src in cases11.items():
    try: r = ss.scan_frz11(REL, src)
    except Exception as e: r = ["scanner EXC " + type(e).__name__]
    print(f"{name:40s}", "FLAGGED" if r else "not flagged")
cases06 = {
 "import socket": "import socket\n", "__import__('socket')": "x = __import__('socket')\n",
 "importlib.import_module('ssl')": "import importlib\nx = importlib.import_module('ssl')\n",
 "from http import client": "from http import client\n", "import http.client": "import http.client\n",
 "from urllib import request": "from urllib import request\n", "import asyncio; open_connection": "import asyncio\n",
 "import ftplib": "import ftplib\n", "import smtplib": "import smtplib\n", "import xmlrpc.client": "import xmlrpc.client\n",
 "subprocess curl": "import subprocess\nsubprocess.run(['curl','https://x'])\n", "import socketserver": "import socketserver\n",
 "reveal_for_transport elsewhere": "def f(s):\n    return s.reveal_for_transport(None)\n",
 "getattr reveal": "def f(s):\n    return getattr(s, 'reveal_for_transport')(None)\n",
}
print("== FRZ-06 (production module that is not transport_http)")
for name, src in cases06.items():
    r = ss.scan_frz06(REL, src)
    print(f"{name:40s}", "FLAGGED" if r else "not flagged")
cases10 = {
 "time.sleep(5)": "import time\ntime.sleep(5)\n", "sleep(2+3)": "import time\ntime.sleep(2+3)\n",
 "timeout=30": "def f(x):\n    return x(timeout=30)\n", "settimeout(30)": "def f(s):\n    s.settimeout(30)\n",
 "named constant used as sleep": "import time\nPAUSE = 5\ntime.sleep(PAUSE)\n",
 "timedelta(seconds=3600)": "from datetime import timedelta\nd = timedelta(seconds=3600)\n",
 "hex literal 0x1c": "x = 0x1c\n", "60 * 60": "x = 60 * 60\n", "float 0.5 sleep": "import time\ntime.sleep(0.5)\n",
}
print("== FRZ-10")
for name, src in cases10.items():
    r = ss.scan_frz10(REL, src)
    print(f"{name:40s}", "FLAGGED" if r else "not flagged")
cases07 = {"RESERVE": "from genesis.quota import BudgetClass\nx = BudgetClass.RESERVE\n", "getattr RESERVE": "from genesis.quota import BudgetClass\nx = getattr(BudgetClass, 'RESERVE')\n",
           "BudgetClass['RESERVE']": "from genesis.quota import BudgetClass\nx = BudgetClass['RESERVE']\n",
           "grant_authorization": "def f(l):\n    l.grant_authorization()\n", "alias import": "from genesis.quota import QuotaReserveAuthorization as Q\n"}
print("== FRZ-07")
for name, src in cases07.items():
    r = ss.scan_frz07(REL, src)
    print(f"{name:40s}", "FLAGGED" if r else "not flagged")
cases08 = {"READY attr": "from genesis.pit import OperationalStatus\nx = OperationalStatus.READY\n", "getattr READY": "from genesis.pit import OperationalStatus\nx = getattr(OperationalStatus, 'READY')\n",
           "OperationalStatus('ready')": "from genesis.pit import OperationalStatus\nx = OperationalStatus('ready')\n", "string 'READY' status in SourceCapability": "x = {'operational_status': 'ready'}\n"}
print("== FRZ-08")
for name, src in cases08.items():
    r = ss.scan_frz08(REL, src)
    print(f"{name:40s}", "FLAGGED" if r else "not flagged")
