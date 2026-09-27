# T6 authority memo: F-A (reopens F-1/E3) — research imports become fail-closed

Date: 2026-09-27 (Europe/London)

Base: HEAD `0df2297425efee134c6fdc903146952b5eb20075` (the F-1/E3 teardown fix),
not rewritten. The finding is **F-A** of the independent E11 hostile audit
(`C:\Users\abbot\a8\evidence\E11\E11_AUDIT_REPORT.md`), which E11 classified as a
CONFIRMED HIGH enforcement weakness that reopens F-1/E3. This memo classifies and
describes the remediation. It grants no GO and creates no approval, strategy,
model, tier or TTL. Real protected campaigns remain disabled.

Classification scale (as in T2–T6):

- **A**: a correction the audit requires, with no change to an approved ADR,
  historical identity or record meaning.
- **B**: a new durable fact or schema added beside unchanged history.
- **C**: would need a new ADR version and operator approval.

This repair is **A**. It changes only the *policy direction* of an existing
control (import gating) from a denylist to a fail-closed allowlist, and extends
existing defense-in-depth lists. It adds no schema, changes no record meaning,
and does not alter the ADR-0003 boundary contract (topology, program identity,
handle/path/environment boundary, attempt lifecycle, real-campaign guard) — it
makes the runtime meet that contract.

## Finding (restated precisely)

E11 confirmed that the worker's control over what research code may import was a
**denylist** (`_CONTROL_MODULES`), and its forbidden-sink enforcement a fixed set
of audit events. Both are enumerations, and the set of stdlib extension modules
that can create a process, load native code or open the network is open-ended.
Two escapes were demonstrated end-to-end inside the real worker:

- `import sqlite3` → `Connection.enable_load_extension(True)` +
  `load_extension(...)` reaches the SQLite native-extension loader (arbitrary
  native code); its audit events were not in the deny set.
- `import _tkinter` → a Tcl interpreter whose `exec` command spawns OS processes
  and raises **no** Python audit event at all.

Neither is teardown-specific: both fire during the nominal research callback, so
the F-1 teardown framing was a subset of the real class. The F-1 regression was
GREEN because it asserted named vectors (`os.system`, `os.startfile`, `_winapi`),
not the class.

## Invariant

Research-controlled code must not be able, in any callback/lifecycle phase, to
obtain or invoke a capability that can create/control an OS process, load
arbitrary native code, access the network, escape the permitted data surface,
mutate the enforcement mechanism, or otherwise cross the protected-evaluation
trust boundary — **whether or not CPython emits an audit event** for that
operation.

## Is a Python-level audit hook / static scan a sufficient boundary? (No.)

CPython documents audit hooks as unsuitable for sandboxing hostile Python code,
and that is correct: a determined program with arbitrary execution can generally
defeat any in-process control. This remediation therefore does **not** claim the
Python-level controls are a sandbox. The actual trust boundary in Genesis is, and
remains, the one in ADR-0003:

1. **Process/address-space separation** — research runs in a fresh, label-free
   `python -I -S` subprocess; the trusted evaluator (a separate process) alone
   holds labels and never runs research code.
2. **No `FutureOutcomeLabel` ever enters the worker** — `require_clean` fails
   closed on any label object, checked before use; results are reconstructed from
   bytes by the parent/evaluator.
3. **(Deferred, per ADR-0003) OS-level least-privilege isolation** — a real
   protected activation must add enforceable identity/ACL/container controls
   (e.g. a restricted token / job object / seccomp-style jail) so the worker
   cannot reach the process table, arbitrary filesystem, or the network at the
   OS level. ADR-0003 explicitly defers this to an approved deployment, and real
   activation stays disabled (`launch_trusted_protected_evaluator` refuses unless
   `local_checkpoint_test_only=True`).

The Python-level import allowlist and runtime hook are **fail-closed
defense-in-depth** layered on (1)–(2); they are not a substitute for (3). The
smallest architecture-consistent change that closes the demonstrated class
without redesigning the process model or contradicting ADR-0003's deferral of OS
controls is to make the import policy fail closed. Implementing OS-level jailing
now would exceed this finding and pre-empt the deferred, approval-gated control;
it is recorded here as the required control before any real activation.

## Construction (`src/genesis/protected_research_worker.py` only)

1. **Fail-closed import allowlist.** `_RESEARCH_IMPORT_ALLOWLIST` is the only set
   of stdlib roots research may import (`__future__` plus vetted pure-computation
   and data modules, and `os`/`pathlib`/`io` whose only boundary-relevant sinks —
   process creation — are refused by the always-on runtime hook). The `genesis`
   package (never `genesis.protected_research_worker`) is additionally allowed as
   trusted runtime and is deep-audited by `_audit_capability`. `_import_allowed`
   is the single source of truth, enforced at the two layers that gate research's
   own imports: the static program audit (`_audit_program_code`) and the guarded
   `__import__` (`_guarded_import`). Any module not on the allowlist — including
   every native/extension module and any future one — fails closed by omission.

2. **Pre-load the allowlist.** `_preload_research_allowlist()` imports the
   allowlisted modules once in the trusted worker before any research runs, so a
   research `import` of one is a cache hit that triggers no further (possibly
   denied) transitive import during research mode.

3. **Defense-in-depth (belt-and-suspenders, not the boundary).**
   - `_CONTROL_MODULES` gains `sqlite3`, `_sqlite3`, `tkinter`, `_tkinter`,
     `socket`, `ssl`; the runtime audit hook refuses these import events in every
     phase regardless of the allowlist.
   - `forbidden_events` gains `sqlite3.load_extension` and
     `sqlite3.enable_load_extension`.
   - `_FORBIDDEN_PROGRAM_NAMES` gains `sqlite3`, `subprocess`, `socket`,
     `load_extension`, `enable_load_extension`, so these cannot be reached as a
     name/string through a trusted module attribute (e.g. `genesis.protected`).

No other module changed. Reflection/compile/exec/import gating stays mode-gated;
the always-on forbidden sinks and the F-1 two-tier phase design are unchanged and
now cover the SQLite extension events too.

## Why this closes the class (not two vectors)

The policy is positive (default-deny): a module becomes reachable only by being
vetted onto the allowlist, so an unenumerated capability — the exact fail-open
condition E11 exploited — now fails closed. The adversarial regression proves
this at the class level (below), and the self-review confirmed that a sink
reached through an *allowed* module (`os.system`, `os.startfile`) or through a
trusted `genesis` attribute (`subprocess`), an obfuscated Tcl `exec`, and a
spread of unlisted capability and benign modules (`platform`, `antigravity`,
`pty`, `ctypes.util`, `pydoc`, `pip`, `venv`, `base64`, `hashlib`, …) all fail
closed.

### Residual, documented, out of scope for this finding

- **Filesystem surface.** `os`/`pathlib`/`io`/`open` remain available, so research
  can read/write within the worker's own (label-free) filesystem surface. This is
  the existing, tested design (`hostile_parent_probe` proves no label is reachable
  via env/fs because none is present). Filesystem jailing is part of the deferred
  OS-level controls (ADR-0003), not this pass.
- **Bounded DoS.** `time.sleep` / pathological `re` are bounded by the existing
  research timeout; they cross no trust boundary. The 15 s readiness timeouts are
  unchanged (E11 classified them as fail-closed availability, not a weakness).

## Tests

`tests/test_astra_t6_fa_capability_allowlist.py` (new, adversarial, invariant-
level): asserts the SQLite and Tcl capabilities fail closed; that a broad set of
capability modules fails closed; that an **unenumerated benign** module also
fails closed (proving default-deny, not a denylist); and that allowlisted compute
modules still certify. RED against the pre-fix worker (15 failures — the
unenumerated modules certified), GREEN after. The pre-existing F-1 teardown suite
and the S5/T3/T5 protected suites continue to pass.

## Evidence (outside the repo, `C:\Users\abbot\a8\evidence\E11\`)

- `E11_AUDIT_REPORT.md`, `E11_worker_probe.py`, `E11_TRANSCRIPT.txt` — the finding.
- `FA_RED_prefix.txt` — new suite RED on the pre-fix worker (15 failures).
- `FA_GREEN_postfix.txt` — new suite GREEN after the fix.
- `FA_SELFREVIEW.txt`, `FA_selfreview_probe.py` — third-route adversarial review.
- `FA_PROTECTED_SET.txt`, `FA_FULL_SUITE.txt` — regression and full-discovery runs.

## Status

F-A is repaired and verified on this checkpoint. This memo does not declare the
T6 candidate final or the foundation cleared, and does not declare E11 satisfied;
that remains for a fresh independent hostile re-audit.
