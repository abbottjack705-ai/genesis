"""Genuine Windows console Ctrl-C against candidate CLI hooks."""
import ctypes, os, subprocess, sys
from pathlib import Path
candidate = Path(sys.argv[1]).resolve()
child_code = "import time; from genesis_adapters import cli; cli.install_hooks(); print('READY',flush=True); exec('while True: time.sleep(1)')"
env = os.environ.copy()
env["PYTHONPATH"] = os.pathsep.join([str(candidate / "adapters" / "src"), str(candidate / "src")])
env["PYTHONDONTWRITEBYTECODE"] = "1"
startup = subprocess.STARTUPINFO()
startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
startup.wShowWindow = 0
child = subprocess.Popen([sys.executable, "-B", "-c", child_code], cwd=candidate, env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=startup)
print("CHILD_PID", child.pid, "READY", child.stdout.readline().strip(), flush=True)
kernel = ctypes.windll.kernel32
kernel.SetConsoleCtrlHandler(None, True)
try:
    print("DETACH_PARENT", kernel.FreeConsole(), flush=True)
    attached = kernel.AttachConsole(child.pid)
    print("ATTACH", attached, flush=True)
    if attached:
        print("SEND", kernel.GenerateConsoleCtrlEvent(0, 0), flush=True)
        kernel.FreeConsole()
    code = child.wait(timeout=10)
    print("EXIT", code, hex(code & 0xffffffff), flush=True)
    print("STDERR", child.stderr.read().strip(), flush=True)
    assert code == 0xc000013a
finally:
    kernel.SetConsoleCtrlHandler(None, False)
    if child.poll() is None:
        child.kill()
        child.wait()
