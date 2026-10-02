"""Run the adapter suite under an INDEPENDENT audit hook that logs every connect/getaddrinfo/bind target."""
import sys, os, json, unittest
LOG = []
def hook(event, args):
    if event == "socket.connect":
        LOG.append(("connect", repr(args[1])))
    elif event == "socket.getaddrinfo":
        LOG.append(("getaddrinfo", repr(args[:2])))
    elif event == "socket.gethostbyname":
        LOG.append(("gethostbyname", repr(args)))
    elif event == "socket.sendto":
        LOG.append(("sendto", repr(args[1])))
sys.addaudithook(hook)       # registered FIRST (before the suite's own hook)
os.chdir(sys.argv[1]); sys.path.insert(0, sys.argv[1] + "/adapters")
suite = unittest.defaultTestLoader.discover("adapters/adapter_tests", top_level_dir="adapters")
res = unittest.TextTestRunner(verbosity=0, stream=open(os.devnull, "w")).run(suite)
nonloop = [e for e in LOG if not any(t in e[1] for t in ("127.0.0.1", "'::1'", "localhost"))]
print(json.dumps({"ran": res.testsRun, "errors": [str(t[0]).split(" ")[0] for t in res.errors], "failures": [str(t[0]).split(" ")[0] for t in res.failures], "skipped": len(res.skipped),
                  "total_net_events": len(LOG), "nonloopback_events": nonloop[:20], "n_nonloopback": len(nonloop)}))
