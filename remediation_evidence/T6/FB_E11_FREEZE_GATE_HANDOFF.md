# Handoff — final foundation-wide hostile audit / freeze gate (post-E11)

| Field | Value |
| --- | --- |
| Certified / freeze target (immutable) | `4f11606615c7650f3bd74c7ccf5d2fb7a5a753c5` |
| E11 verdict + evidence recorded in | `remediation_evidence/T6/FB_E11_OS_CONTAINMENT_VERDICT.md` (commit `95f99e6`) |
| This document | Documentation/evidence-only. Changes no source, test, configuration, activation state, or the E11-certified containment implementation. Added as a later, non-source child commit; `4f11606` keeps its meaning. |
| Date | 2026-09-28 |
| Current decision | Real activation **DISABLED**. Freeze gate **PENDING** the independent hostile re-audit described below. |

## Freeze target and integrity verification

The state under audit and freeze is commit `4f11606`. The E11 verdict and the
witnessed Windows evidence are recorded at commit `95f99e6` under
`remediation_evidence/T6/`. Before review, verify integrity:

```text
sha256sum -c remediation_evidence/T6/FB_E11_EVIDENCE_HASHES.sha256
git log --oneline --decorate -n 15
```

Confirm `FB_E11_windows_evidence_raw.zip` matches its recorded SHA-256, and
cross-check the rest of the foundation against the frozen hashes in
`remediation_evidence/R10/HOSTILE_REAUDIT_HANDOFF.md`.

## Assignment

Review `4f11606` as a hostile architecture / statistics / implementation
auditor. Do not redesign the objective, praise the project, or authorize later
scope. Actively try to break the foundation enforcement boundary. Treat the E11
SATISFIED verdict below as a claim to falsify, not a given.

## Certified E11 status (to be re-attacked, not assumed)

E11 (OS-level research-process containment, ADR-0004) was assessed **SATISFIED at
`4f11606`** by static review plus witnessed Windows execution. Exact recorded
counts:

- Containment suite (`tests.test_astra_t6_fb_os_containment` +
  `tests.test_astra_t6_fb_os_confinement`, `-v`): **22 tests, 0 skipped, all OK.**
- Full discovery (`python -m unittest discover -s tests -t . -v`): **493 tests
  total, 1 skipped, 0 failures, 0 errors** (the single skip is
  `'this platform cannot create symlinks'`, unrelated to containment).
- Host / gates: Windows 11, build `10.0.26200`, client SKU; Python 3.12;
  `IS_WINDOWS=True`, `APPCONTAINER=True`.
- Enforcing services: `mpssvc` (Windows Defender Firewall) RUNNING; `BFE`
  (Base Filtering Engine) RUNNING.

## Do not take on trust — platform caveat

The E11 enforcement evidence comes from one Windows 11 host. On Linux, 13
containment tests **skip**, so the enforcement properties are unproven there.
Re-run on an independent Windows host and, ideally, a non-English-locale host
(see F-1). Do not accept the recorded summary or this verdict as a substitute
for hostile reruns.

## Non-blocking residual findings (carried forward; no fix applied)

- **F-1 — `icacls` success check is locale-dependent**
  (`src/genesis/protected_confinement_win.py:365`). Keys on the English string
  `"Successfully processed"`; a non-English Windows fails **closed** (confinement
  unavailable, never unconfined). Portability/availability, safety-preserving.
- **F-2 — attestation under-reports the confined environment**
  (`src/genesis/protected.py:1124` vs `:1023-1030`). `environment_keys` omits
  `LOCALAPPDATA` actually injected into the confined worker. Cosmetic accuracy.
- **F-7 — confined std streams rely on GC on the direct-`close()` path**
  (`ConfinedResearchProcess.close()` / `ConfinedWorkerProcess`). `ResourceWarning`
  on the test path; the production `dispose_research` path closes them first.
  Resource-hygiene.

None block E11. They are provided as weaponization targets for the re-audit, not
as accepted defects to leave unexamined.

## Mandatory attacks

Execute the 14 foundation-wide mandatory attacks in
`remediation_evidence/R10/HOSTILE_REAUDIT_HANDOFF.md`, **plus** these
containment-specific attacks against `4f11606`:

1. Escape or weaken the AppContainer: reach external network egress (not only
   loopback — #6 rests on the empty-capability model plus running firewall/BFE;
   re-test with BFE stopped), read an ungranted path, or spawn a process.
2. Race the suspend -> assign-to-job -> resume window so one worker instruction
   runs before the job/token is in force.
3. Defeat deterministic teardown: survive job-handle close, leak the job handle
   into the child, or achieve job breakaway.
4. Force `os_confinement=True` attestation without a real boundary (weaponize
   F-2's env-key gap).
5. On a non-English Windows, drive the F-1 `icacls` path; confirm it fails
   *closed* with no partial-grant window.
6. Exploit the F-7 confined-stream GC path for an fd/handle leak or a late IPC
   reply crossing the boundary.
7. Access labels from the confined research process; overspend attempts; reset
   lifecycle on restart; extract a label-dependent error/traceback.
8. Confirm real-activation cannot be flipped by configuration
   (`ACTIVATION_ENABLED` is decorative; the unconditional raises are the gate);
   attempt to reach real activation via any argument or path.

## Verification commands

```text
python -m unittest discover -s tests -t . -v                 # Linux baseline
python -m unittest -v tests.test_astra_t6_fb_os_containment  # ON WINDOWS: expect 0 skipped when APPCONTAINER=True
python -m compileall -q src tests
git diff --check
git status --short --branch
git log --oneline --decorate -n 15
```

Repeat concurrency/restart and the AppContainer enforcement tests independently.

## Required output

For each material finding: severity (CRITICAL/HIGH/MEDIUM), exact code/blueprint
location, failure mechanism, concrete exploit, minimal fix, proving test, and
whether code/text/both must change. Also: top residual risks, blueprint-vs-code
divergences, any mistaken prior recommendation (including in the E11 verdict), a
do-not-change list, and a freeze-gate GO/HOLD.

## Freeze-gate framing (unchanged)

Real protected activation stays **DISABLED**. Freeze requires no unresolved
CRITICAL/HIGH. A GO for real protected activation additionally requires
(a) operator approval of ADR-0004, (b) the deployment-time provisioning it
specifies (a stable container identity with once-provisioned ACLs, not
per-launch), and (c) this fresh independent hostile re-audit. The re-audit must
not itself begin any adapter, research, external-API, cloud, credential, live,
chaos, or canary phase. E11 SATISFIED is a precondition for that path, not a
grant of it.

## Scope of this document

Documentation/evidence-only. It modifies no source, test, configuration, or
activation state, and does not alter the E11-certified containment
implementation at `4f11606`. It records the certified SHA, the raw Windows test
counts, and the F-1/F-2/F-7 non-blocking residuals for the next auditor.
