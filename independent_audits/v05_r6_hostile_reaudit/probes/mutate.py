"""Independent mutation harness: apply ONE textual mutation to the scratch worktree 'mut', run the adapter suite
(fail-fast), report KILLED/SURVIVED; always restore the file. Usage: mutate.py <spec.json> <out.jsonl>"""
import json, os, subprocess, sys, tempfile, time, shutil
SP = os.environ.get("AUDIT_SCRATCH", "/tmp/v05_audit_scratch")   # needs a scratch git worktree of the candidate at $SP/mut (see REPRO_COMMANDS.md)
HERE = os.path.dirname(os.path.abspath(__file__))
MUT = SP + "/mut"
specs = json.load(open(sys.argv[1])); out = open(sys.argv[2], "a")
for spec in specs:
    path = os.path.join(MUT, spec["file"]); orig = open(path, "rb").read()
    text = orig.decode()
    n = text.count(spec["old"])
    rec = {"id": spec["id"], "file": spec["file"], "desc": spec["desc"], "occurrences": n}
    if n != spec.get("expect_count", 1):
        rec["result"] = "BAD_SPEC"; out.write(json.dumps(rec) + "\n"); out.flush(); continue
    mutated = text
    for old, new in spec.get("edits") or [[spec["old"], spec["new"]]]:
        if mutated.count(old) != 1: rec["result"] = "BAD_SPEC_EDIT"; break
        mutated = mutated.replace(old, new, 1)
    if rec.get("result") == "BAD_SPEC_EDIT":
        out.write(json.dumps(rec) + "\n"); out.flush(); continue
    open(path, "wb").write(mutated.encode())
    t0 = time.time()
    try:
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONPYCACHEPREFIX")}
        env["PYTHONPYCACHEPREFIX"] = tempfile.mkdtemp()
        mods = spec.get("modules")
        cmd = [sys.executable, "-B", HERE + "/runner_ff.py", MUT]
        p = subprocess.run(cmd, cwd=MUT, env=env, capture_output=True, timeout=900)
        tail = (p.stderr or b"").decode(errors="replace").strip().splitlines()
        rec["rc"] = p.returncode
        rec["result"] = "SURVIVED" if p.returncode == 0 else "KILLED"
        if p.returncode != 0:
            killers = [l for l in tail if l.startswith(("FAIL:", "ERROR:"))]
            rec["killed_by"] = killers[:2]
    except subprocess.TimeoutExpired:
        rec["result"] = "TIMEOUT"
    finally:
        open(path, "wb").write(orig)
    rec["secs"] = round(time.time() - t0)
    out.write(json.dumps(rec) + "\n"); out.flush()
