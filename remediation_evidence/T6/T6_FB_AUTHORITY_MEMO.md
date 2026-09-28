# T6 F-B authority memo — three E11 correctness findings + outer OS boundary

Classification: **A** (integrator remediation + evidence). This memo records
design decisions and evidence for a tranche of security hardening. It is **not**
an E11 pass and **not** an approval. E11 must be decided by a separate
independent hostile re-audit (see the handoff in
`a8/evidence/E11/FB_REAUDIT_HANDOFF.md`). Real protected activation remains
disabled; no adapter/strategy/campaign/live GO is created or implied.

- Repository (development clone): `C:\Users\abbot\a8\fa`, branch `t6-remediation`.
- Parent (pre-fix) HEAD: `bdb5fd80b3af16c2e69c3da4b0d219d5d45f2e63` (the F-A fix).
- Python: CPython 3.12.10, Windows 11; `core.autocrlf=false`; committed bytes LF.

## Scope

The F-A remediation (`bdb5fd8`) converted research *imports* to a fail-closed
allowlist. An independent E11 re-audit of `bdb5fd8` confirmed **three residual
correctness findings**, each with an inert reproduction. This tranche fixes all
three, adds RED→GREEN regressions matching the reproductions, and — separately —
reconciles ADR-0003 with the E11 filesystem/capability-confinement requirement
by adding a **disabled** outer OS-confinement scaffold (ADR-0004).

Only one production module changed for the three findings
(`src/genesis/protected_research_worker.py`). Part 2 adds one new production
module (`src/genesis/protected_isolation.py`), one ADR
(`DECISIONS/ADR-0004-...md`), and test files. No other production code, and no
lifecycle timing, changed.

**Reconciliation of two parallel remediations.** A second session independently
remediated the same three findings as uncommitted work in the authoritative repo
(`E11_FOLLOWUP_*`, `test_astra_t6_e11_defense_in_depth.py`). That work was
preserved verbatim (`a8/evidence/E11/authoritative_parallel_backup/`) and merged
into this one coherent implementation, taking the stronger mechanism per axis and
dropping the weaker/duplicate one. The full retained/dropped decision table is
`a8/evidence/E11/FB_RECONCILIATION.md`. In short: this work kept its default-deny
runtime hook, always-on positive import allowlist, native-event prefixes,
narrowed Genesis surface and Part 2; it adopted from the parallel work the
positive reachable-module policy in `_audit_capability`, the broader
`_TrustedDefinitionSnapshot` (extended here to cover `pathlib`), and the
pre-serialization `_send(verify=...)` check; it dropped the parallel work's
import-time export inspection as a near-duplicate of the post-exec audit plus the
runtime default-deny.

## Finding 1 — capability validation must cover indirectly reachable module/native capabilities

**Defect.** The allowlist gated import *statements*, not object reachability.
A native process loader stayed reachable purely by attribute traversal from an
allowlisted package —
`genesis.protected.multiprocessing.reduction._winapi.CreateProcess` — and
allowlisted stdlib modules leak references to non-allowlisted modules
(`collections._sys` → `sys`, `enum.bltns` → `builtins`). Reaching or calling
these named nothing in an `import`, so import gating never saw them; the
`_winapi.CreateProcess` audit event existed but was undenied.

**Fix (positive policy, three mutually reinforcing layers).**
1. **Runtime research-mode default-deny** (`_install_runtime_audit_hook`). While
   a research `mode` is active (module exec / callback) the audit hook admits
   only a small vetted benign event set (`builtins.id`, `open`, `os.scandir`,
   `os.listdir`) plus the specially-handled `import`/`compile`/`exec`/
   `object.__getattr__`; **every other event fails closed**. Measurement showed
   benign predictor compute raises no audit event at all, so this does not
   restrict legitimate research, yet any native/process/network/introspection
   capability — however reached, by import or by attribute — is refused at the
   point of use because exercising it raises a non-benign event. This is the
   positive policy applied to indirectly reachable *native* capabilities.
2. **Static reachability closure** (`_audit_capability`). A reachable module is
   refused unless it satisfies the fail-closed **positive** import allowlist
   (`_import_allowed`) — the form adopted from the parallel remediation, faithful
   to the finding's "positive policy" wording and stricter than a control-module
   denylist: every non-allowlisted module (`ntpath`/`os.path`, `collections._sys`
   → `sys`, `_winapi`, `multiprocessing`, …) fails closed even when reached purely
   by attribute, and the referenced-name walk propagates through module→module
   edges so an indirectly reachable module several hops out is validated to its
   leaf (`seen` bounds the walk). Combined with the narrowed Genesis surface, a
   reachable `genesis.protected` is refused too.
3. **Narrowed `genesis` import surface** (`_RESEARCH_GENESIS_ALLOWLIST`).
   Research may import only the Genesis data-type layer (`genesis`,
   `genesis.labels`, `genesis.evaluation`, `genesis.provenance`,
   `genesis.reasons`, `genesis.time`) — pure dataclasses/enums with no process/
   native/network capability. `genesis.protected` (which wraps multiprocessing/
   `_winapi`), this worker module, and every heavier Genesis module fail closed.

## Finding 2 — permanent enforcement must not depend on lifecycle mode

**Defect.** Forbidden-*event* enforcement was already permanent, but *import*
enforcement (and native-capability denial) sat inside the `mode is None`
early-return, so it lapsed during conversion/cleanup/shutdown — the exact
re-entrant window a finalizer or dunder exploits.

**Fix.** The audit hook now has an explicit **permanent tier** enforced in every
phase regardless of `mode`: forbidden sinks, native-capability event families
(`_winapi.*`, `_posixsubprocess.*`, `ctypes.*` added to the always-on set), and
the **fail-closed import allowlist** (`_import_allowed`, moved ahead of the mode
gate). Measurement confirmed the trusted worker raises **no** `import` event in
any phase after startup (allowlisted modules are pre-loaded before the hook is
installed), so an always-on import allowlist costs trusted activity nothing while
closing the teardown re-entry gap. `compile`/`exec`/reflection stay mode-gated
because trusted housekeeping legitimately performs them (`compile` at `mode` is
None, `gc.get_objects`/`builtins.id`/`object.__getattr__` during the scan), which
is why an always-on *default-deny* is not possible and the two-tier split is
necessary.

## Finding 3 — contamination checking must cover mutable nested trusted state

**Defect.** `_InterpreterBaseline` snapshotted trusted module namespaces only at
the top level by object identity, so an in-place mutation of a trusted authority
*type* reachable by research — adding or rebinding a member of
`FutureOutcomeLabel`/`DecisionFrame` — left the module-level identity unchanged
and went undetected, persisting into the next request in the reused worker.

**Fix (explicit integrity-checked authority objects; reconciled mechanism).**
- The checker's own authority snapshots (`builtins`, `environment`) are held in
  `MappingProxyType` views so they cannot be edited in place.
- `_TrustedDefinitionSnapshot` (adopted from the parallel remediation) captures a
  bounded snapshot of every **class and function** defined in a trusted-definition
  module, plus the exact built-in containers nested one level inside their
  namespaces (`dict`/`list`/`tuple`/`set`), and each function's
  code/defaults/kwdefaults/annotations. It reads the real class namespace via
  `type.__dict__['__dict__'].__get__` and only exact built-in containers, so it
  never dispatches user `__eq__`, `items`, hashing, repr or metaclass `__dict__`
  — the scan cannot itself re-enter research-controlled code. `require_clean`
  re-verifies it before and after `gc.collect`, and `_send(verify=...)` re-checks
  it after serialization, before any byte is emitted.
- Scope (`_is_trusted_definition_module`): every loaded `genesis.*` module, this
  worker module, and **`pathlib`**. The `pathlib` addition is this work's
  contribution to the merged snapshot (the parallel snapshot covered only
  `genesis.*` + worker): it closes the self-review variant in which research
  rebinds `pathlib.PurePath.is_relative_to`, a method the worker's OWN
  `require_clean`/`_inside` dispatches through, subverting the checker while the
  top-level identity is unchanged. The stdlib beyond `pathlib` is deliberately
  excluded because its mutating caches (`re._cache`, `functools`, …) would
  false-positive — which is exactly why an unbounded snapshot of everything is
  unsound.
- Original objects are retained (`_retained`) so verification is effectively by
  identity, not by a reusable `id()`. `id()` alone is unsafe: rebinding a member
  drops the original's last reference and CPython reuses the freed address for the
  replacement, so an `id()` signature can match after a rebind. (Both this session
  and the parallel one independently found this; the retained-original identity
  check is the sound form.)

## Part 2 — ADR-0003 ⇄ E11 reconciliation and the outer OS boundary (disabled)

ADR-0003 (approved, immutable) already states the in-process controls are not a
sandbox and defers OS least-privilege. `ADR-0004-s5-os-confinement-boundary.md`
(PROPOSED, **not** approved) makes the deferred boundary explicit and reconciles
the mismatch: the Python audit hook only *asserts* "explicit filesystem access,
no network, controlled native-code exposure" inside a cooperating same-user
interpreter; the OS does not enforce it. ADR-0004 specifies the smallest outer
boundary — Windows AppContainer (per-launch capability SID, ACL-scoped
filesystem, **no** network capability) + Job Object (single active process, no
breakaway, `KILL_ON_JOB_CLOSE` for fail-closed teardown), with a named POSIX
analog.

`src/genesis/protected_isolation.py` holds the policy + orchestration
(`ResearchProcessConfinement` encodes the four fixed properties and refuses to
relax network/child-process/teardown; `plan_confinement` emits the mechanism as
inspectable data; `apply_confinement`, the *real-activation* entry, stays
fail-closed). ADR-0003's real-activation guard on
`launch_trusted_protected_evaluator` is preserved (non-test launches still
raise). It does **not** claim the audit hook is a sandbox.

## Part 2b — the real Windows containment primitives (implemented, activation disabled)

The OS boundary is now **implemented and exercised**, not a scaffold
(`src/genesis/protected_confinement_win.py`):

- **Job Object** (`ConfinementJob`): `ACTIVE_PROCESS`=1 (no escaping child
  process, breakaway off), per-job/per-process memory cap, `KILL_ON_JOB_CLOSE`
  (closing the handle kills the tree → deterministic teardown).
- **AppContainer** (`AppContainerProfile`): a per-launch capability SID created
  with an **empty** capability set, so the process has **no** network capability;
  its `SECURITY_CAPABILITIES` is passed to the launch.
- **Explicit filesystem ACLs** (`grant_container_access`/`revoke_container_access`
  via `icacls`): read/execute on the runtime + Genesis source + import roots,
  read/write on the workdir; everything else denied by default; revoked on
  teardown.
- **Confined suspended launch** (`launch_confined_worker`): the worker is created
  `CREATE_SUSPENDED` inside the AppContainer with an explicit
  `PROC_THREAD_ATTRIBUTE_HANDLE_LIST` (only the three std handles inherited),
  **assigned to the Job Object before `ResumeThread`**, and fails closed —
  terminating any partially-created process — on any error.
- **Orchestration + teardown** (`ConfinedResearchProcess`/`launch_confined_research`):
  profile + job + grants + launch, tearing down job → ACLs → profile; fail-closed
  throughout.

Wiring: `_start_research_process(confine=…)` / `launch_trusted_protected_evaluator(
confine_research=…)` opt the **local checkpoint/test path** into confinement.
Default is off, so the 480-test baseline, lifecycle timing and the unconfined
launch are byte-for-byte unchanged. Real activation stays disabled
(`ACTIVATION_ENABLED=False`, `apply_confinement` fail-closed, launcher guard
intact).

One worker adaptation was required and is confined-only: the worker's strict path
resolution (`_program_module_path`, `_module_path`, `_audit_function`) now uses
`_resolve_strict_confined`, which falls back to a best-effort resolve **only** on
the AppContainer's `PermissionError` (raised because `GetFinalPathNameByHandle`
must read ancestor directory names the container is deliberately not granted).
Unconfined, strict resolution always succeeds, so the fallback is never taken and
behaviour is unchanged; confined, the OS boundary (read-only import root, no
symlink creation, no access outside the grants) preserves the import-root
containment guarantee the strict resolve gave. This keeps the fs boundary minimal
("explicit filesystem access only") rather than granting the container the
ancestor chain (which would let it enumerate the user's home/appdata).

Verification (`tests/test_astra_t6_fb_os_containment.py`, benign + inert): live
kill-on-close, one-process limit, memory limit, AppContainer SID/no-capability,
ACL grant/revoke, and a full confined launch asserting the AppContainer token,
denied network capability (loopback-listener only — no external host), restricted
filesystem (granted OK / ungranted DENIED), one-process, and deterministic
teardown; a full protected-path confined launch that still certifies and leaves
the guard intact; mocked fail-closed tests for the Job Object flags, the confined
launch, and the orchestrator. The plan/scaffold object is **not** relied on as
evidence. Live AppContainer tests skip cleanly where the environment cannot
create a container.

## Preserved invariants

Label separation (no `FutureOutcomeLabel` in the worker; gc label scan intact),
attempt-consumption semantics (reserve/abandon/nonrefundable unchanged),
immutable evidence, request/program binding (nonce, digest, single-program
worker), lifecycle timing (15 s readiness deadlines unchanged; no confinement
setup on the launch path), and the existing real-activation guard are all
preserved. The CPython audit-hook controls remain **defense in depth**, not the
boundary.

## Evidence (outside the repo, `C:\Users\abbot\a8\evidence\E11\`)

- `FB_RECONCILIATION.md` — the retained/dropped decision table for the two
  parallel remediations.
- `authoritative_parallel_backup/` — the parallel session's uncommitted worker
  diff, full worker copy, `E11_FOLLOWUP_*` and test, with SHA256SUMS (preserved
  before any change).
- `FB_RED_prefix.txt` — the reachability regressions RED on the pre-fix worker
  (`bdb5fd8`): 7 finding-reproductions fail, 3 guards pass.
- `FB_GREEN_postfix.txt` — F-B reachability + OS-confinement tests GREEN.
- `FB_RECONCILED_GREEN.txt` — the full reconciled test set (reachability +
  definition-snapshot + OS-confinement) GREEN.
- `FB_FULL_SUITE.txt` — full `unittest discover` on the final tree.
- `FB_PROTECTED_SET.txt` — targeted protected/lifecycle/scan-cost/contention set.
- `FB_CONTAINMENT.txt` — the OS-containment suite (`test_astra_t6_fb_os_containment.py`).
- `FB_SELFREVIEW.txt` — inert adversarial self-review sweep.
- `FB_REAUDIT_HANDOFF.md` — handoff for the independent E11 re-audit.

## Test results (exact counts from the raw logs)

- Full discovery (final tree): see `FB_FULL_SUITE.txt` for the exact
  `Ran N … OK (skipped=1[, +N environment skips])` line; the 1 always-present
  skip is the pre-existing H3 symlink test. Live AppContainer containment tests
  skip cleanly where the environment cannot create a container.
- New/reconciled regressions: RED 7/10 on the pre-fix worker (`bdb5fd8`) → GREEN
  post-fix across `test_astra_t6_fb_e11_reachability.py` (13, black-box),
  `test_astra_t6_fb_definition_snapshot.py` (16, white-box, reconciled from the
  parallel suite), `test_astra_t6_fb_os_confinement.py` (9, policy/guard) and
  `test_astra_t6_fb_os_containment.py` (13, real primitives — mocked + benign
  live).
- Targeted protected/lifecycle/contention set: OK (`FB_PROTECTED_SET.txt`),
  including the R9 eight-concurrent-request test and the scan-cost test; neither
  the broadened definition snapshot nor the confined-only resolve fallback added
  a timeout regression.
- Self-review sweep: 10 inert vectors blocked, 4 benign certify (`FB_SELFREVIEW.txt`).
- No `protected … unavailable` contention flakes observed in the committed runs;
  15 s timeouts unchanged.
