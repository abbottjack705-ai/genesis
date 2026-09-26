"""T6 F-3 reproducer driver around the T5 auditor's unmodified owner/N3 probes.

Usage: python F3_AUDITOR_PROBES_DRIVER.py <clone> <workdir> <transcript> <label>

Copies probe_owner_alias.py and probe_hardlink_mirror.py from
C:/Users/abbot/gv/out into <workdir> after checking their SHA-256 against the
review's own hash list, then runs each twice against <clone> exactly as the
review did (AUDIT_REPO=<clone>, PYTHONPATH=<clone>/src) and compares the runs
and the review's recorded T5 results.

probe_owner_alias.py appends its colliding row outside any try block, so once
that append is refused the unmodified probe stops with the refusal instead of
printing. A variant is therefore also run that differs from the auditor's bytes
in exactly one block: the colliding append is wrapped so the refusal is
recorded, and if RiskAuditLog.append is absent the same row is offered to the
risk log storage (audit_log.log.append). Every other line is the auditor's.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CLONE, WORK, TRANSCRIPT = (Path(p).resolve() for p in sys.argv[1:4])
LABEL = sys.argv[4]
AUDIT = Path("C:/Users/abbot/gv/out")
REVIEW_HASHES = AUDIT / "GENESIS_V04_T5_REVIEW_HASHES.sha256"
PROBES = ("probe_owner_alias.py", "probe_hardlink_mirror.py")
RECORDED = {
    "probe_owner_alias.py": AUDIT / "probe_owner_alias_t5.txt",
    "probe_hardlink_mirror.py": AUDIT / "probe_hardlink_mirror_t5.txt",
}
COLLIDING_APPEND = (
    b'        e.audit_log.append("risk_exposure_recorded", {\n'
    b'            "schema_version": "risk-exposure-v2",\n'
    b'            **Exposure(d.approval_id, "f" * 64, "1", ExposureState.MATCHED).to_dict(),\n'
    b'            "recorded_at": "2026-01-01T00:20:00Z",\n'
    b'        })\n'
)
WRAPPED_APPEND = (
    b'        _payload = {\n'
    b'            "schema_version": "risk-exposure-v2",\n'
    b'            **Exposure(d.approval_id, "f" * 64, "1", ExposureState.MATCHED).to_dict(),\n'
    b'            "recorded_at": "2026-01-01T00:20:00Z",\n'
    b'        }\n'
    b'        try:\n'
    b'            e.audit_log.append("risk_exposure_recorded", _payload)\n'
    b'            R["t6_colliding_append_RiskAuditLog.append"] = "appended"\n'
    b'        except Exception as exc:  # noqa: BLE001\n'
    b'            R["t6_colliding_append_RiskAuditLog.append"] = f"refused: {type(exc).__name__}: {exc}"\n'
    b'            try:\n'
    b'                e.audit_log.log.append({"record_type": "risk_exposure_recorded", **_payload})\n'
    b'                R["t6_colliding_append_audit_log.log.append"] = "appended"\n'
    b'            except Exception as exc2:  # noqa: BLE001\n'
    b'                R["t6_colliding_append_audit_log.log.append"] = (\n'
    b'                    f"refused: {type(exc2).__name__}: {exc2}")\n'
)
LINES: list[str] = []


def emit(text: str = "") -> None:
    LINES.append(text)
    print(text, flush=True)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(CLONE), *args], capture_output=True, check=True, text=True,
    ).stdout


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(script: Path) -> dict:
    environment = dict(os.environ)
    environment.update({
        "AUDIT_REPO": str(CLONE),
        "PYTHONPATH": str(CLONE / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True,
        cwd=script.parent, env=environment,
    )
    parsed = None
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        pass
    return {"exit": result.returncode, "stdout": result.stdout, "stderr": result.stderr,
            "json": parsed}


listed = {}
for line in REVIEW_HASHES.read_text(encoding="ascii").splitlines():
    if not line.strip() or line.startswith("#"):
        continue
    digest, name = line.split(" *", 1)
    listed[name] = digest

emit(f"# T6 F-3 auditor probe transcript ({LABEL})")
emit(f"# started {now()}")
emit(f"# python {sys.version.split()[0]}; {platform.platform()}")
emit(f"# {git('--version').strip()}")
emit(f"# clone {CLONE} HEAD {git('rev-parse', 'HEAD').strip()}"
     f" branch {git('branch', '--show-current').strip()}"
     f" core.autocrlf={git('config', '--get', 'core.autocrlf').strip()}")
status = git("status", "--porcelain=v1", "--untracked-files=all").splitlines()
emit(f"# uncommitted paths: {len(status)}")
for line in status:
    path = CLONE / line[3:]
    emit(f"#   {line}  sha256 {sha256(path.read_bytes()) if path.is_file() else '-'}")
for name in ("src/genesis/registry.py", "src/genesis/risk.py", "src/genesis/owner_binding.py"):
    emit(f"# {name} sha256 {sha256((CLONE / name).read_bytes())}")
emit(f"# driver sha256 {sha256(Path(__file__).read_bytes())}")

probes_dir = WORK / "probes"
shutil.rmtree(probes_dir, ignore_errors=True)
probes_dir.mkdir(parents=True)
for name in PROBES:
    raw = (AUDIT / name).read_bytes()
    if sha256(raw) != listed[name]:
        raise SystemExit(f"auditor probe differs from the review hash list: {name}")
    (probes_dir / name).write_bytes(raw)
    emit(f"# auditor {name} sha256 {sha256(raw)} (equals review hash list: True)")
    recorded = RECORDED[name]
    emit(f"# auditor recorded T5 result {recorded.name} sha256 "
         f"{sha256(recorded.read_bytes())} (equals review hash list: "
         f"{sha256(recorded.read_bytes()) == listed[recorded.name]})")
original = (probes_dir / "probe_owner_alias.py").read_bytes()
if original.count(COLLIDING_APPEND) != 1:
    raise SystemExit("the colliding append block is not unique in probe_owner_alias.py")
variant_dir = WORK / "variant"
shutil.rmtree(variant_dir, ignore_errors=True)
variant_dir.mkdir(parents=True)
variant = variant_dir / "probe_owner_alias_t6_wrapped_append.py"
variant.write_bytes(original.replace(COLLIDING_APPEND, WRAPPED_APPEND))
emit(f"# variant {variant.name} sha256 {sha256(variant.read_bytes())}"
     " (one block changed: the colliding append is wrapped; see driver docstring)")
emit()

results: dict[str, list[dict]] = {}
for name, script in (
    ("probe_owner_alias.py", probes_dir / "probe_owner_alias.py"),
    ("probe_owner_alias_t6_wrapped_append.py", variant),
    ("probe_hardlink_mirror.py", probes_dir / "probe_hardlink_mirror.py"),
):
    results[name] = []
    for attempt in (1, 2):
        emit(f"$ AUDIT_REPO={CLONE} PYTHONPATH={CLONE / 'src'} python {script}   (run {attempt})")
        outcome = run(script)
        results[name].append(outcome)
        emit(f"exit={outcome['exit']}")
        if outcome["stdout"].strip():
            emit(outcome["stdout"].rstrip())
        if outcome["stderr"].strip():
            emit("stderr:")
            emit(outcome["stderr"].rstrip())
        emit()
    first, second = results[name]
    emit(f"## determinism {name}: identical exit, stdout and stderr across runs: "
         f"{(first['exit'], first['stdout'], first['stderr']) == (second['exit'], second['stdout'], second['stderr'])}")
    emit()

emit("## comparison with the review's recorded T5 results")
for name, compared in (
    ("probe_owner_alias.py", "probe_owner_alias.py"),
    ("probe_owner_alias_t6_wrapped_append.py", "probe_owner_alias.py"),
    ("probe_hardlink_mirror.py", "probe_hardlink_mirror.py"),
):
    recorded = json.loads(RECORDED[compared].read_text(encoding="utf-8"))
    now_json = results[name][0]["json"]
    emit(f"### {name} vs {RECORDED[compared].name}")
    if now_json is None:
        emit("  no JSON result (the probe stopped; see its stderr above)")
        continue
    for key in sorted(set(recorded) | set(now_json)):
        before, after = recorded.get(key, "<absent>"), now_json.get(key, "<absent>")
        emit(f"  {key}: {'same' if before == after else 'CHANGED'}")
        if before != after:
            emit(f"    T5 review: {json.dumps(before)}")
            emit(f"    now      : {json.dumps(after)}")
emit()

wrapped = results["probe_owner_alias_t6_wrapped_append.py"][0]["json"] or {}
mirror = results["probe_hardlink_mirror.py"][0]["json"] or {}
f3a_ok = (
    wrapped.get("riskauditlog_append_collision_then_replay") == "ok"
    and wrapped.get("riskauditlog_append_then_record_exposure") == "ok"
    and "appended" not in (
        wrapped.get("t6_colliding_append_RiskAuditLog.append"),
        wrapped.get("t6_colliding_append_audit_log.log.append"),
    )
)
f3b_ok = (
    mirror.get("append_inside_real_critical_section") != "both appended (no mutual exclusion)"
    and mirror.get("risk_log_after") == "verifies"
)
emit(f"VERDICT F-3a ({LABEL}): colliding public append "
     f"{wrapped.get('t6_colliding_append_RiskAuditLog.append')!r} / storage "
     f"{wrapped.get('t6_colliding_append_audit_log.log.append', 'not attempted')!r}; replay "
     f"{wrapped.get('riskauditlog_append_collision_then_replay')!r}; later exposure "
     f"{wrapped.get('riskauditlog_append_then_record_exposure')!r} -> "
     + ("GREEN" if f3a_ok else "VIOLATION PRESENT (RED)"))
emit(f"VERDICT F-3b ({LABEL}): interleaved hard-link append "
     f"{mirror.get('append_inside_real_critical_section')!r}; real risk log after "
     f"{mirror.get('risk_log_after')!r} -> " + ("GREEN" if f3b_ok else "VIOLATION PRESENT (RED)"))
emit(f"# finished {now()}")
TRANSCRIPT.parent.mkdir(parents=True, exist_ok=True)
TRANSCRIPT.write_bytes(("\n".join(LINES) + "\n").encode("utf-8"))
