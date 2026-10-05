"""AREA O: frozen-byte/module provenance: CRLF, 1-byte, same-length swap, unlisted file, shadow package; PATH-ONLY vs BYTES."""
import os, shutil, subprocess, sys, json
SP = os.environ.get("AUDIT_SCRATCH", "/tmp/v05_audit_scratch")
CAND0 = os.environ.get("CAND_DIR") or str(__import__("pathlib").Path(__file__).resolve().parents[3])
SRC = SP + "/provcopy"
if not os.path.isdir(SRC):      # minimal copy of the trees the guard needs (tracked files only)
    files = subprocess.check_output(["git", "-C", CAND0, "ls-files", "-z", "src", "adapters/src", "adapters/config", "config"]).decode().split("\0")
    for f in filter(None, files):
        os.makedirs(os.path.dirname(os.path.join(SRC, f)), exist_ok=True); shutil.copy2(os.path.join(CAND0, f), os.path.join(SRC, f))
def run_guard(repo, *, extra_env=None, pre="", cwd=None):
    code = f"""
import sys
sys.path[:0] = [r'{repo}/src', r'{repo}/adapters/src']
{pre}
from pathlib import Path
from genesis_adapters import provenance_guard
from genesis_adapters.oddspapi import verify
import importlib
for n in ("time","repro","registry","provenance","evidence","pit","feature_manifest","quota","coverage","reasons"):
    importlib.import_module("genesis."+n)
v = provenance_guard.verify_loaded_genesis_modules(Path(r'{repo}'), manifest_path=Path(r'{repo}/adapters/config/frozen_genesis_modules.json'), expected_manifest_sha256=verify.FROZEN_MANIFEST_SHA256)
print("PASS", len(v.get("modules", v)) if isinstance(v, dict) else "")
"""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONPYCACHEPREFIX")}
    env["PYTHONPYCACHEPREFIX"] = subprocess.check_output(["mktemp", "-d"]).decode().strip()
    env.update(extra_env or {})
    p = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, env=env, cwd=cwd or repo, timeout=120)
    out = (p.stdout + p.stderr).decode(errors="replace").strip().splitlines()
    return out[-1][:160] if out else f"rc={p.returncode}"
def fresh(name):
    d = SP + "/prov_" + name
    shutil.rmtree(d, ignore_errors=True); shutil.copytree(SRC, d); return d
R = {}
R["0_control_clean_copy"] = run_guard(fresh("clean"))
d = fresh("crlf"); f = d + "/src/genesis/time.py"; b = open(f, "rb").read(); open(f, "wb").write(b.replace(b"\n", b"\r\n")); R["1_CRLF_one_frozen_module"] = run_guard(d)
d = fresh("trail"); f = d + "/src/genesis/time.py"; open(f, "ab").write(b"\n"); R["2_extra_trailing_newline"] = run_guard(d)
d = fresh("swap"); f = d + "/src/genesis/time.py"; b = bytearray(open(f, "rb").read()); i = b.index(b"return"); b[i:i+6] = b"retarn"; open(f, "wb").write(bytes(b)); R["3_same_length_byte_swap"] = run_guard(d)
d = fresh("unlisted"); open(d + "/src/genesis/zz_extra.py", "w").write("X=1\n"); R["4_unlisted_module_file_never_imported"] = run_guard(d)
d = fresh("shadow"); os.makedirs(d + "/shadow/genesis"); open(d + "/shadow/genesis/__init__.py", "w").write("")
R["5_shadow_genesis_on_PYTHONPATH"] = run_guard(d, extra_env={"PYTHONPATH": d + "/shadow"})
d = fresh("pth"); sp = d + "/site"; os.makedirs(sp); open(sp + "/x.pth", "w").write(d + "/shadow\n")
R["6_pth_file_in_site"] = run_guard(d, pre=f"import site; site.addsitedir(r'{sp}')")
d = fresh("lower"); os.makedirs(d + "/other/genesis"); open(d + "/other/genesis/__init__.py", "w").write("")
R["7_competing_genesis_lower_precedence"] = run_guard(d, pre=f"sys.path.append(r'{d}/other')")
d = fresh("pyc"); R["8_without_-B_stale_pyc_flag"] = "(covered by suite FRZ-09 pyc test; see cli startup)"
d = fresh("mtime_only"); f = d + "/src/genesis/time.py"; os.utime(f, (0, 0)); R["9_mtime_only_change_must_PASS"] = run_guard(d)
for k, v in R.items(): print(f"{k:44s}", v)
