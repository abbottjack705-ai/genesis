# E11 verdict — OS-level research-process containment (T6 F-B / ADR-0004)

| Field | Value |
| --- | --- |
| Audited commit (immutable) | `4f11606615c7650f3bd74c7ccf5d2fb7a5a753c5` |
| Audit type | Independent static review + witnessed Windows execution evidence |
| Record status | Doc-only. No audited source or test file changed. The meaning of `4f11606` is unchanged; this record is added as a later, non-source child commit. |
| Date recorded | 2026-09-28 |
| Verdict | **E11 — SATISFIED at `4f11606`.** Real activation remains **DISABLED**. This is not an activation, adapter, research-scope, shadow, or live GO. |

## Scope of this record

This preserves the E11 verdict (OS-level research-process containment) for the
T6 F-B / ADR-0004 tranche. It certifies the **containment architecture only**.
It authorizes no protected campaign, adapter, shadow research, research-scope
addition, or live-money activation; it changes no objective, risk law, odds
range, staking tier, quota, or hold-to-settlement rule; and it neither amends nor
approves ADR-0003 or ADR-0004. Adding this record modifies no audited source or
test file — the audited state is commit `4f11606`, which stands unchanged.

## Verdict

**E11 is SATISFIED at `4f11606`.** The committed implementation establishes the
intended OS-level containment architecture for the protected research worker, and
every property that could only be established by execution has been demonstrated
on a real Windows 11 host with AppContainer support and both enforcing services
running: default-deny filesystem with an ungranted path proven unreadable while
the workdir is read/write; no network capability (loopback connect blocked);
child-process creation blocked from inside the confined worker; deterministic
kill-on-close teardown; real fail-closed behaviour when job assignment fails;
truthful `os_confinement` attestation; and full preservation of label isolation,
attempt consumption, request binding, activation guards, and lifecycle semantics
(the confined path produces the same certificate while the real-activation guard
still refuses). No regressions across the full suite.

## Windows execution evidence — exact counts

- **Containment suite** (`tests.test_astra_t6_fb_os_containment` +
  `tests.test_astra_t6_fb_os_confinement`, `-v`): **22 tests, 0 skipped, all OK.**
  All 13 Windows-gated containment tests actually ran (0 skipped), including the
  enforcement-bearing classes `ConfinedWorkerLiveTests`,
  `ConfinedProtectedLaunchLiveTests`, `JobObjectLiveTests`,
  `ConfinedLaunchFailClosedTests`, `AppContainerLiveTests`,
  `OrchestratorFailClosedTests`, and `JobObjectMockedTests`.
- **Full discovery** (`python -m unittest discover -s tests -t . -v`):
  **493 tests total, 1 skipped, 0 failures, 0 errors.** The single skip is
  `'this platform cannot create symlinks'` — a git-binding test needing symlink
  privilege, unrelated to containment.
- **Host / gates:** Windows 11, build `10.0.26200`, client SKU; Python 3.12.
  `IS_WINDOWS=True`, `APPCONTAINER=True`.
- **Enforcing services:** `mpssvc` (Windows Defender Firewall) **RUNNING**;
  `BFE` (Base Filtering Engine) **RUNNING** — the OS layer that enforces
  AppContainer network isolation was active during the run.

## Properties established

| # | Property | How established | Anchor(s) at `4f11606` |
| --- | --- | --- | --- |
| 1 | Suspended worker creation | static + confined-launch tests | `protected_confinement_win.py:409,655-663` |
| 2 | Kernel containment before resume | static ordering + live token probe | `protected_confinement_win.py:634-638,668-669` |
| 3 | Job Object assignment | static + `JobObjectLiveTests` | `protected_confinement_win.py:114-116,178-184,668` |
| 4 | AppContainer / restricted authority | live: `appcontainer=True`, SID `S-1-15-2-`, `CapabilityCount=0` | `protected_confinement_win.py:257-263,317-325` |
| 5 | Filesystem ACL confinement | live: granted OK, **ungranted DENIED**; grant/revoke round-trip | `protected_confinement_win.py:372-394`; `protected_isolation.py:202-206` |
| 6 | Network denial | live: loopback `BLOCKED` + `mpssvc`/`BFE` running (external = capability-model, see F-3 note) | empty cap set (as #4); `protected_isolation.py:108-110` |
| 7 | Child-process restriction | live: `spawn=BLOCKED` + one-process-limit test | `protected_confinement_win.py:92-96,152-158` |
| 8 | Inherited-handle control | static: 3-handle allowlist; parent ends non-inheritable | `protected_confinement_win.py:614-615,639-644` |
| 9 | Kill-on-close / deterministic teardown | live: tree killed on close; pid dead after `close()` | `protected_confinement_win.py:95,156`; `protected_isolation.py:222-237` |
| 10 | Fail-closed on setup failure | live created-worker-terminated-on-assign-fail + mocked fail-closed | `protected_confinement_win.py:679-703`; `protected_isolation.py:214-216`; `protected.py:1064-1067,1111-1118` |
| 11 | Truthful metadata / attestation | live: `os_confinement=True` on real confined launch (F-2 nit) | `protected.py:1127` |
| 12 | Label isolation / attempts / request binding / guards / lifecycle | live: confined launch certifies `brier=0.25` and guard still raises | `protected.py:1462,1516-1524`; `protected_isolation.py:150` |

Note on #6: the live probe proves loopback denial with a real listener present;
external-egress denial rests on the empty-capability AppContainer model plus the
running firewall/BFE services rather than a live external connect (deliberately,
to avoid reaching an external host).

## Residual findings (non-blocking; carried to the next audit)

No fix was applied — this engagement is audit-only.

- **F-1 — `icacls` success check is locale-dependent** (`protected_confinement_win.py:365`).
  Keys on the English string `"Successfully processed"`. This English host passed;
  a non-English Windows would fail **closed** (confinement unavailable, never
  unconfined). Portability/availability defect, safety-preserving. Non-blocking.
- **F-2 — attestation under-reports the confined environment**
  (`protected.py:1124` vs `:1023-1030`). `research_boundary["environment_keys"]`
  reflects the unconfined env and omits `LOCALAPPDATA` actually injected into the
  confined worker. Cosmetic accuracy nit. Non-blocking.
- **F-7 — confined std streams rely on GC on the direct-`close()` path**
  (`ConfinedResearchProcess.close()` / `ConfinedWorkerProcess`). Live tests
  emitted `ResourceWarning: unclosed file` because `close()` closes the Win32
  handles but leaves the parent-side Python stdin/stdout file objects to GC; the
  production `dispose_research` path closes them first, so this is test-path only.
  Resource-hygiene nit. Non-blocking.

## Activation status (unchanged by this record)

Real protected-campaign activation remains **DISABLED**:
`launch_trusted_protected_evaluator` refuses any non-`local_checkpoint_test_only`
launch (`protected.py:1462`); `apply_confinement` refuses unconditionally
(`protected_isolation.py:150`); `confine_research` is honoured only on the test
path and is never set true in `src/`. Per ADR-0004, enabling real activation
still requires (a) operator approval of ADR-0004, (b) the deployment-time
provisioning it describes (a stable container identity with once-provisioned
ACLs, not per-launch), and (c) a fresh independent hostile re-audit. E11 being
satisfied is a precondition for that path, not a grant of it.

## Evidence artifacts and integrity

Stored alongside this record under `remediation_evidence/T6/`:

- `FB_E11_ENV.txt`, `FB_E11_SERVICES.txt`, `FB_E11_CONTAINMENT.txt`,
  `FB_E11_FULLSUITE.txt` — UTF-8/LF normalizations of the original PowerShell
  UTF-16 captures (normalization: UTF-16 → UTF-8, BOM stripped, CRLF → LF).
- `FB_E11_windows_evidence_raw.zip` — the byte-exact original bundle as delivered
  by the repo owner (preserves the raw UTF-16 captures verbatim).
- `FB_E11_EVIDENCE_HASHES.sha256` — SHA-256 of the original zip, the original
  UTF-16 files, and the normalized copies, for independent verification.

## Method and authenticity

Static review read the implementation and tests at `4f11606`. Runtime evidence
was produced by the repository owner on a real Windows 11 host and supplied as
the bundle hashed in `FB_E11_EVIDENCE_HASHES.sha256`. The evidence is internally
consistent and bears authentic artifacts (PowerShell `NativeCommandError`
stderr-wrapping, real pipe-fd `ResourceWarning`s, a `Python312` toolchain path,
and runtimes consistent with real AppContainer/`icacls` work). This verdict is
conditioned on the evidence being a faithful capture of that run, which it
appears to be, and makes no claim beyond E11 and the containment architecture.
