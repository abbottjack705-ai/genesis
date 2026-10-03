"""N01: run the whole adapter suite under an independent audit hook that records, for EVERY non-loopback
resolution/connect attempt, the running test id and the innermost adapter/test frames (call-site attribution),
plus whether the attempt was refused before any packet (the suite's own hook raises) or proceeded.
usage: n01_nonet_callsites.py <candidate_dir>
"""
import sys, os, json, unittest, traceback
LOG = []
CURRENT = {"test": None}
LOOP = ("127.0.0.1", "'::1'", "localhost")

def hook(event, args):
    if event in ("socket.connect", "socket.getaddrinfo", "socket.gethostbyname", "socket.sendto", "socket.bind"):
        target = repr(args[1]) if event in ("socket.connect", "socket.sendto", "socket.bind") else repr(args[:2])
        if any(t in target for t in LOOP):
            return
        frames = [f"{os.path.relpath(f.filename, CAND) if f.filename.startswith(CAND) else f.filename.split('/')[-1]}:{f.lineno}:{f.name}"
                  for f in traceback.extract_stack()[:-1]]
        relevant = [f for f in frames if f.startswith("adapters/")][-6:]
        LOG.append({"event": event, "target": target, "test": CURRENT["test"], "frames": relevant})

CAND = os.path.abspath(sys.argv[1])
sys.addaudithook(hook)                         # FIRST, before the suite installs its own hook
os.chdir(CAND); sys.path.insert(0, CAND + "/adapters")

class Result(unittest.TextTestResult):
    def startTest(self, test):
        CURRENT["test"] = test.id()
        super().startTest(test)

suite = unittest.defaultTestLoader.discover("adapters/adapter_tests", top_level_dir="adapters")
runner = unittest.TextTestRunner(verbosity=0, stream=open(os.devnull, "w"), resultclass=Result)
res = runner.run(suite)
print(json.dumps({"ran": res.testsRun, "failures": len(res.failures), "errors": len(res.errors),
                  "skipped": len(res.skipped), "nonloopback_attempts": LOG}, indent=1))
