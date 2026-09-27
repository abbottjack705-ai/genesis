# T6 authority memo: F-1/E3, the research boundary holds through trusted teardown

Date: 2026-09-27 (Europe/London)

Base: HEAD `9b32c6f6db3844adedeb903ff0d44884df2f75ae` (C-1), not rewritten. The
finding is F-1/E3 of the T5 independent verification report and its handoff
`GENESIS_V04_T5_REMEDIATION_HANDOFF_F1_F4.md`. The read-only lifecycle context
that framed the repair is `remediation_evidence/T6/F1_E3/audit-context/DOSSIER.md`.
This memo classifies and describes one construction. It grants no GO and creates
no approval, strategy, model, tier or TTL.

Classification scale (as in T2–T5):

- **A**: a correction the audit requires, with no change to an approved ADR,
  historical identity or record meaning.
- **B**: a new durable fact or schema added beside unchanged history.
- **C**: would need a new ADR version and operator approval.

This repair is **A**. It changes only *when* the runtime audit hook enforces its
existing denials; it adds no schema, changes no record meaning, and does not
alter the ADR-0003 boundary contract — it makes the runtime meet that contract.

## Finding (restated precisely)

The protected worker runs research (untrusted) code with the runtime audit hook
armed. When the callback returns, the worker enters trusted housekeeping — the
post-execution interpreter-state scan (`_InterpreterBaseline.require_clean`),
result conversion (`FrozenPredictionArtifact.create`), serialization
(`artifact.to_dict` → `canonical_json`) and request cleanup
(`restore_request_scope`) — and the hook goes dormant (`state["mode"] = None`,
returning immediately). The broken assumption was:

> "The research function returned, therefore no research-controlled code can
> execute anymore."

That is false in CPython. Research code can arrange to regain control *after*
the callback returns and *during* the dormant trusted phases, through:

- a `__del__`/finalizer or a generator `close`/`finally` run when garbage
  collection reclaims research objects (GC runs inside `require_clean` and
  `restore_request_scope`);
- a dunder method (`__hash__`, `startswith`, `__str__`) invoked when the scan
  hashes a research-controlled `__file__`, or when result conversion stringifies
  a research-returned value;
- a trusted callable rebound by research (`json.JSONEncoder.encode`,
  `FrozenPredictionArtifact.to_dict`) that trusted serialization then calls.

While the hook was dormant, that re-entrant code reached a forbidden sink
unprotected. The later identity/module scan does not save us: a transient
finalizer performs the side effect and leaves no suspicious binding behind.

Separately, the armed hook's deny list did not cover **all** process creation.
On Windows, `_winapi.CreateProcess` and `os.startfile` reach a new process
through primitives the deny set omitted; `_winapi.CreateProcess` raises no audit
event at all, so no hook can see the call.

`37c7ba5` was a genuine but **separate** fix: it cached path-containment to keep
the scan under the fixed research timeout. It changed neither *when* protection
is active nor whether research can re-enter during teardown, so it did not close
F-1. That is why 430 tests could pass while F-1 remained open: those tests
demonstrated the reliability of the mechanism they exercised, not the
impossibility of research-controlled execution during the unprotected teardown
boundary.

## Invariant

There must never be a period in which research-controlled Python execution
remains possible while enforcement of forbidden operations is withdrawn.

CPython cannot prevent a finalizer, dunder method or GC-driven callback from
*running* during teardown. The sound way to satisfy the invariant is therefore
not to try to stop that code from running, but to guarantee that **whenever it
runs, the operations that would breach the boundary stay refused** — i.e. the
denial of forbidden operations has no dormant state to exploit.

## Construction (`src/genesis/protected_research_worker.py`)

Two coordinated changes, both inside the worker; no other module changes.

1. **Two-tier hook policy.** `_install_runtime_audit_hook` now splits its policy:

   - **Forbidden sinks** — operations with an external or irreversible effect,
     or that grant new native/execution capability, or that would subvert
     enforcement itself: `os.system`, `os.startfile`, `os.kill`,
     `os.posix_spawn`, `os.fork`, `os.forkpty`, the `os.exec*`/`os.spawn*`
     prefixes, `subprocess.Popen`, `socket.__new__`, the `ctypes.*` prefix,
     `sys.addaudithook`, `sys.setprofile`, `sys.settrace`, `builtins.breakpoint`.
     These are refused in **every** phase, independent of `mode` — including
     while `mode` is `None` during trusted housekeeping. Trusted worker code
     never performs any of them after the hook is installed, so keeping them
     refused costs trusted activity nothing while closing the boundary by
     construction.
   - **Reflection / compile / exec / import gating** — `gc.get_objects`,
     `gc.get_referents`, `gc.get_referrers`, `code.__new__`, `function.__new__`,
     `pickle.find_class`, `sys._getframe`, `sys._current_frames`, plus the
     `exec`/`compile`/`import`/`object.__getattr__` checks — remain gated on an
     active research `mode`, because trusted worker activity legitimately does
     these (importing at startup, compiling and exec-ing the hashed program, and
     calling `gc.get_objects` during its own scan).

2. **Refuse importing native process/OS modules.** `_winapi.CreateProcess` and
   `_posixsubprocess.fork_exec` create processes through primitives that raise no
   audit event, so no runtime hook can see the call. The only sound defense is to
   refuse the import. `_winapi`, `_posixsubprocess`, `nt`, `_socket`, `msvcrt`
   and `winreg` are added to `_CONTROL_MODULES`, so the static program audit
   (`_audit_program_code`), the runtime import event and the guarded
   `__import__` all refuse them. `os.startfile` is additionally a forbidden sink
   (defense in depth for the call site).

### Why this is complete for the demonstrated class

The reproducer (`a8/evidence/F1_PROBE.py`, unchanged from the RED run) exercises
14 vectors: direct calls, str-subclass indirection through `__hash__`/
`startswith`, GC and teardown finalizers, generator close, rebinding of stdlib
and Genesis classes and of a trusted module function, prediction-value dispatch,
and the two Windows armed primitives. Pre-fix, 12 escaped
(`denied_operation_ran: true`). Post-fix, `ESCAPED []` — every vector's forbidden
operation is refused. The finalizer vectors still return a certificate because
the blocked-operation exception raised inside `__del__`/`finally` is ignored by
CPython; the security property (no forbidden operation) holds regardless.

### Residual, out of scope for this finding

Non-sink reflection primitives (`gc.get_referents`, `sys._getframe`) remain
gated on `mode`, so a teardown-phase finalizer could still *read* live objects.
This does not breach the boundary: no raw label ever enters the worker
(`require_clean` fails closed on `FutureOutcomeLabel`, checked before use), and
the parent/evaluator reconstruct results from bytes. The finding, the reproducer
and this repair concern the forbidden *sinks* (external effect / new
capability), which are now refused in every phase.

## Tests

`tests/test_astra_t6_f1_teardown_enforcement.py` (new, adversarial) creates
research-controlled finalizers, a generator `finally`, a scan-time `__hash__`, a
result-conversion `__str__`, and a rebound trusted serializer that each attempt
to spawn a process specifically during the post-research transition, plus the
Windows `os.startfile` sink and the `_winapi` import. The security assertion is
structural and observable: the marker file a spawned process would create must
never exist. Pre-fix these go RED (marker present / import allowed); post-fix all
pass. The pre-existing `test_runtime_audit_layer_blocks_process_creation_during_research`
(direct-callback case) continues to pass.

## Evidence (outside the repo, `C:\Users\abbot\a8\evidence\`)

- `F1_PROBE.py`, `F1_PROBE_RED.txt` — reproducer and its pre-fix RED transcript.
- `F1_PROBE_GREEN.txt` — same reproducer, post-fix: `ESCAPED []`.
- `F1_TEARDOWN_RED.txt`, `F1_TEARDOWN_GREEN.txt` — the new regression suite RED
  (pre-fix, hook stashed) then GREEN (post-fix).
- `F1_TEARDOWN_FULL_SUITE.txt` — full `python -m unittest` run.
- `F1_STATIC_GATES.txt` — `git diff --check`, changed-file list, `compileall`.

## Status

F-1/E3 is repaired and verified on this checkpoint. This memo does not declare
the T6 candidate final or the foundation cleared; that remains for the
independent hostile audit.
