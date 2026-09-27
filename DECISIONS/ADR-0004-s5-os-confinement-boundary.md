# ADR-0004 v1: S5 outer OS-level confinement for the research process

Date drafted: 2026-09-27

Status: **PROPOSED — NOT APPROVED; no S5 real-activation authority**

Scope: Astra A8, offline/local-checkpoint protected-evaluation plumbing only.
This record supplements — it does not amend — the immutable, approved
`ADR-0003-s5-protected-process-boundary.md`. It adds the outer operating-system
containment boundary that ADR-0003 explicitly deferred, in response to the E11
re-audit. It authorizes no real protected campaign, research, adapter, shadow
or live GO, and it does not change ADR-0003's topology, program identity,
handle/path/environment contract, attempt lifecycle or real-activation guard.

## Why this ADR exists (the E11 filesystem/capability-confinement mismatch)

ADR-0003's launch contract states that the research callback runs in a process
that "receives … a dedicated label-free working directory," with a "fixed
minimal environment," no network endpoint, and no inheritable handles beyond the
research pipes. The v0.4 implementation delivers that **topology** (a fresh,
label-free interpreter, disjoint working directory, closed handles) and adds a
CPython audit-hook layer inside the worker as defense in depth.

E11 confirmed a mismatch that ADR-0003 itself already flagged as deferred:

- The CPython audit hook is **not a sandbox**. It is advisory enforcement inside
  a cooperating interpreter. A denylist of dangerous modules/events is
  structurally unsound (F-A), and even a fail-closed allowlist plus a
  default-deny event policy (this tranche's finding-1/2 fixes) is still an
  in-process control: it constrains what the audited interpreter *chooses* to
  permit, not what the operating system *allows the process* to do.
- The research process today is a **same-user process**. Same-user means it
  shares the user's filesystem, network and token. "Explicit filesystem access,
  no network, controlled native-code exposure" is therefore asserted by the
  Python layer but **not enforced by the OS**. That is acceptable only for the
  synthetic checkpoint (labels never leave trusted memory; no real label store
  exists), which is why ADR-0003 disabled real activation.

This ADR does not claim, and forbids claiming, that Python audit hooks form a
sandbox. It specifies the smallest outer OS boundary that would make ADR-0003's
capability grants real, and it keeps real activation disabled until that
boundary is approved and implemented.

## Decision: the smallest outer confinement boundary (required before real activation)

For any real protected activation on the local Windows development target, the
launcher must place the research process inside an OS confinement with exactly
these four properties, and no more:

1. **Explicit filesystem access (default-deny).** The process runs under a
   low-privilege principal that has *no* access to the user's files by default.
   It is granted read/traverse to the resolved absolute program import roots and
   read/write to the dedicated research working directory only. It is denied all
   trusted label roots (already required disjoint by ADR-0003). On Windows this
   is an **AppContainer** principal (a per-launch capability SID) plus explicit
   ACL grants on those two path sets; on POSIX the analog is a dedicated
   unprivileged uid/gid with a bind-mounted working set (or equivalent).

2. **No network.** The confinement grants **no** network capability. Under an
   AppContainer this means withholding the `internetClient`,
   `internetClientServer` and `privateNetworkClientServer` capabilities, so the
   process cannot open a socket to any endpoint; on POSIX, an empty network
   namespace (or a deny-all local firewall scope) achieves the same. This
   enforces at the OS level what the audit hook's `socket.__new__` denial only
   asserts in-process.

3. **Controlled native-code exposure (no new processes, no arbitrary native
   load).** The process is placed in a **Job Object** configured so it cannot
   create child processes that escape the job: `JOB_OBJECT_LIMIT_ACTIVE_PROCESS`
   = 1 and breakaway **off** (`JOB_OBJECT_LIMIT_BREAKAWAY_OK` and
   `SILENT_BREAKAWAY_OK` cleared). Combined with the AppContainer's inability to
   load drivers or acquire debug/impersonate privileges, this makes the native
   process-creation and code-loading sinks the audit hook refuses in-process
   (`_winapi.*`, `subprocess.Popen`, `os.*` spawn, `ctypes.*`) also unavailable
   at the OS level, so an in-process bypass cannot cross the boundary.

4. **Fail-closed teardown.** The Job Object sets
   `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. When the trusted parent closes the job
   handle — deliberately, on error, or on parent death — the entire research
   process tree is terminated by the kernel. No research process, and no child
   it managed to start, can outlive the trusted parent or the request. This
   composes with ADR-0003's existing kill/dispose paths; it does not replace the
   in-process handle-closing and attempt-consumption semantics, which remain.

The boundary is created **before** labels are materialized and before the
evaluator endpoint exists, exactly as ADR-0003 requires for the process itself.
The confinement is per-launch (a fresh capability SID / principal and a fresh
job per research process) and is torn down with the process.

## What this ADR deliberately does NOT change

- ADR-0003's topology, `ResearchProgramRef-v1` contract, sealed-frame/label
  isolation, IPC schema, attempt lifecycle, request/program binding, lifecycle
  timing (including the 15 s readiness deadlines) and the real-activation guard
  are unchanged. This ADR is additive: an outer wrapper around the same launch.
- The 15 s readiness deadlines are not weakened. Any confinement setup cost must
  fit before the ready handshake or be measured and justified in a later
  revision; the checkpoint scaffold performs no setup and adds no latency.
- The CPython audit-hook controls remain as **defense in depth**, not as the
  boundary. Removing them is out of scope.

## Implementation status and the disabled-activation guard

This ADR is accompanied by a **disabled scaffold**, not an activation:

- `src/genesis/protected_isolation.py` defines the confinement policy as data
  (`ResearchProcessConfinement`) and a planner (`plan_confinement`) that emits
  the exact OS mechanism above as an inspectable, testable descriptor. Its
  applicator (`apply_confinement`) is **fail-closed**: it refuses to run unless
  an approval token that no code can currently supply is presented, so real
  OS confinement cannot be activated by this change.
- `launch_trusted_protected_evaluator` still raises for any non-test launch
  (`local_checkpoint_test_only` must be True). The test-only launch path is
  behaviourally unchanged (no confinement is applied, no timing changes), so
  the synthetic checkpoint and its retained tests are unaffected.
- Real activation therefore remains **disabled**: turning it on requires (a)
  operator approval of this ADR, (b) implementing the AppContainer/Job-Object
  primitives behind `apply_confinement`, and (c) a fresh independent hostile
  re-audit.

## Explicit non-decisions

This ADR grants no adapter GO, shadow-research GO, protected-campaign GO or
live-money GO. It approves no model, calibration, strategy, tier/expiry rule or
profitability claim, and changes no objective, odds range, staking tier, risk
percentage, quota interpretation or hold-to-settlement rule. It does not
reinterpret any historical record.

## Approval requested

The operator must explicitly approve **this exact ADR version and SHA-256**
before any OS-confinement code is activated or real protected activation is
enabled. Approval must be recorded in a separate versioned `DECISIONS/` note
citing the draft hash, approver, approval date and scope, after which the
approved content is immutable. A material change to the confinement properties,
the principal model or the teardown guarantee requires a new proposed version
and approval.
