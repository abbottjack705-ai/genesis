import os, socket, fcntl, struct, sys, subprocess
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
fcntl.ioctl(s, 0x8914, struct.pack("16sh", b"lo", 0x1 | 0x40))     # SIOCSIFFLAGS lo up
t = socket.socket(); t.settimeout(2)
try:
    t.connect(("1.1.1.1", 443)); print("NETNS-CHECK: EXTERNAL REACHABLE (isolation failed)")
except OSError as e:
    print("NETNS-CHECK: external unreachable:", e.errno)
srv = socket.create_server(("127.0.0.1", 0)); print("NETNS-CHECK: loopback bind OK")
srv.close()
os.chdir(sys.argv[1])
os.environ["PYTHONPYCACHEPREFIX"] = subprocess.check_output(["mktemp", "-d"]).decode().strip()
os.execvp(sys.executable, [sys.executable, "-B", "-m", "unittest", "discover", "-s", "adapters/adapter_tests", "-t", "adapters"])
