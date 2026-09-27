# F-1/E3 worker lifecycle context dossier

Read-only implementation analysis of `9b32c6f6db3844adedeb903ff0d44884df2f75ae`.
This document records contracts and ordering, not a finding, reproducer, or fix.
Line references below refer to that pre-fix implementation. `W` means
`src/genesis/protected_research_worker.py`; `P` means `src/genesis/protected.py`.

## Authority and intended invariant

- Project laws require immutable evidence and research-independent protected
  holdouts/attempt budgets (`v04_pack/Genesis_v0.4_Implementation_Pack/03_PROJECT_LAWS_v0.4.md:L34-L43`).
- The project specification assigns protected evaluation to a trusted boundary
  research cannot modify (`01_PROJECT_GENESIS_v0.4.md:L795-L812`, in the same pack).
- ADR-0003 is approved exactly by the separate approval record
  (`DECISIONS/ADR-0003-v1-approval-2026-09-22.md:L7-L18`), despite the original
  immutable proposal retaining its draft status header. It requires separate
  trusted label/evaluator and label-free research processes; research readiness
  precedes label materialization and evaluator IPC creation
  (`DECISIONS/ADR-0003-s5-protected-process-boundary.md:L14-L33`).
- The ADR binds exact module bytes and a top-level function to the request,
  requires malformed probabilities/exceptions to fail generically, and limits
  IPC to frozen artifacts/errors without research output corrupting the protocol
  (ADR-0003:L76-L110, L112-L145).
- The retained remediation interpretation is: certificates depend only on
  hashed program bytes plus trusted runtime, with no reachable raw label
  (`T5_RESUME_HANDOFF.md:L139-L169`). One worker remains bound to one digest;
  ordinary class/module attribute assignments are not all audit events, so the
  runtime hook supplements rather than replaces state checks
  (`T5_RESUME_HANDOFF.md:L303-L347`).

The lifecycle invariant to test is consequently broader than entry-point
identity: any execution/state attributable to research must stay within the
research restrictions until the worker has finished consuming that state and
established integrity for publication and reuse. Whether the present
implementation establishes this implication is an open question, not an
assumption supplied by this dossier.

## Lifecycle table

The meta-path origin guard persists once installed. “Hook off” means its
closure state is dormant; restricted builtins in research function globals and
the static source audit still exist.

| Phase | Executing code and protection | Mutable state consumed / research influence | Validation ordering |
|---|---|---|---|
| Process initialization | Parent starts absolute worker using Python `-I -S`, dedicated cwd, minimal environment, closed extra handles (P:L936-L947, L999-L1022). | Sealed launch data, declared code roots; parent callbacks/label objects are not transferred. | Parent checks launch ready schema/PID/capabilities (P:L1035-L1086). |
| Trusted imports and IPC setup | Worker imports stdlib/Genesis, duplicates stdout IPC, redirects ordinary stdout to devnull (W:L5-L37, L891-L896). Hook not installed. | Trusted module objects, private stream objects, interpreter state. | Happens before research source resolution/execution. |
| Launch validation/readiness | `_recv`, `_sealed_from_dict`, schema/root checks, ready `_send` (W:L898-L939). | Parsed JSON, frame/fact values, provenance, sealed manifest. | Reconstructed `SealedFrameSet` validates before ready. Parent creates labels and evaluator only afterward (P:L1428-L1464). |
| Origin guard/baseline/hook | Insert guard; snapshot; install permanent hook (W:L941-L945). Hook initially off. | Snapshot holds module objects, binding identities, copied builtins/environment/path state, decimal/random state (W:L403-L423). | Guard itself is included in baseline. No research has executed yet. |
| Request entry and identity | `_recv`, closed schema/nonce parsing, request/reference construction, digest binding, poison check (W:L946-L978). Hook off. | Request JSON, worker digest/poison latch, sealed frames and baseline reused. | Same-digest and poison checks precede source execution. Parent reserves attempt before request (P:L1270-L1285). |
| Resolve/compile/static audit | Exact unique root resolution, read/hash bytes, compile, recursive code audit, fresh module with restricted builtins (W:L536-L555, L830-L852). Hook off. | Filesystem source bytes, compile machinery, baseline builtins. Source is research supplied. | Hash/static audit precede module execution; source bytes read once are those compiled. |
| Research module execution | `audit_enter_module(code)`, exact `exec`, `finally audit_leave()` (W:L853-L857). Hook on for module execution. | Program globals, imported trusted modules/classes/functions and nested mutable objects. | Source audited before execution; integrity scan follows hook exit. |
| Post-module verification/capability resolution | `require_clean`, qualname/signature checks, recursive `_audit_function` (W:L858-L888). Hook off. | Module/reachable globals, descriptors, function metadata; imported functions/types use trusted-origin exemptions (W:L574-L655). | `gc.unfreeze`/`gc.collect` precede inspection (W:L448-L449). Capability audit precedes main callback calls. |
| Research callbacks | Hook on around all callbacks and predictions-dict comprehension (W:L980-L985). | Same sealed frame objects, callback globals, imported state; arbitrary callback return objects retained as dict values. | No return-type normalization in comprehension; later artifact creation performs conversion. |
| Research exit | `finally audit_leave`, `del callback` (W:L986-L988). Hook off. | Return objects remain in `predictions`; research module/global cycles may remain reachable. | Post-callback scan has not yet run. |
| Post-callback integrity | `baseline.require_clean(program_path)` (W:L989). Hook off. | GC objects, module bindings, selected runtime state; research return objects remain live. | GC collection runs first; scan then compares identities/state. Current program origin is allowed (W:L457-L478). |
| Prediction/artifact construction | `FrozenPredictionArtifact.create` (W:L990-L994; P:L178-L210). Hook off. | Iterates predictions and calls `str(probability)`, `Decimal`, `format`, sorting, then canonical hashing and dataclass checks. | Probability normalization/validation and output hash happen after the preceding scan. |
| Serialization/encoding | `artifact.to_dict`, `_send` -> `canonical_json` -> `json.dumps(...).encode('utf-8')` (W:L995-L1003, L40-L45; P:L157-L175; `src/genesis/repro.py:L17-L29`). Hook off. | Trusted serializer module/classes/functions and stream objects retained from startup; their transitive state is shared in the interpreter. | Size bound follows encoding. No additional integrity scan occurs between artifact creation and write. |
| IPC and parent consumption | Write/flush artifact/error. Parent validates nonce, exact response/PID, artifact/hash/membership and sends artifact to evaluator (W:L995-L1012; P:L1286-L1314). | Byte-only response crosses process boundary. Separate parent/evaluator reconstruct data. | Parent/evaluator validate before consuming labels (P:L834-L880); worker cleanup is after send. |
| Cleanup/finalization | `state.clear`, restore request scope, `require_clean(None)` in finally (W:L1013-L1020). Hook off. | Removes newly loaded modules/submodule bindings, clears decimal flags, restores random state (W:L506-L523); GC runs again. Local `predictions`/artifact references are not explicitly cleared here. | Cleanup/integrity failure sets poison after the reply may already have been consumed. |
| Worker reuse/restart/shutdown | Loop retains baseline/digest/poison and process (W:L944-L976). Shutdown sends closed and returns (W:L952-L954); normal interpreter exit at W:L1023-L1024. Parent closes or kills process (P:L1323-L1340). | Interpreter/module state and surviving references reused for same digest; new identity needs fresh client. | Poison checked before subsequent research. No in-client worker replacement; fresh client preserves pre-label ordering (P:L1260-L1269). |

## Function contract notes and unenforced assumptions

### `_install_runtime_audit_hook` (W:L195-L294)

Inputs are trusted resolved roots. Captured policy includes control module names,
denied audit events, trusted root, and mutable mode/allowed-exec state. The hook
returns immediately while mode is `None` (L250-L252); module/callback entry arm it
and `leave` disables it (L282-L294). Calls to compile/exec are permitted for
trusted origins; current exact module code is additionally allowed. The caller
assumes no research-attributable execution needs hook restrictions after `leave`.
An explicit check establishing that all surviving references/deferred work are
inert at `leave`: **nothing found**. Reachability through supported programs
requires a separate reproducer.

### `_InterpreterBaseline` (W:L398-L523)

The constructor holds baseline module objects and each binding's `id`, not a
recursive immutable graph (L405-L410). `require_clean` first unfreezes/collects
GC, then scans live objects for raw labels and foreign research source origins,
checks retained module/binding identity and selected runtime values (L448-L504).
Volatile warning registries and legitimate added submodule bindings are exempt.
Imported trusted classes/functions and nested mutable objects retain their
binding identity when changed internally; a general recursive content
comparison in this baseline: **nothing found**. `restore_request_scope` removes
new modules and newly added submodule bindings, clears decimal flags and resets
captured random state (L506-L523). It does not claim to restore arbitrary nested
state. Whether supported research can retain executable influence in such state
requires testing.

### `_resolve_program` (W:L830-L888)

Reads exact hashed bytes, audits all code objects before exec, enables hook only
around exec, then scans and validates target/signature/global capabilities.
Imported trusted functions are origin-checked and have function attributes
audited; their implementation globals are not recursively traversed
(W:L581-L595). Imported trusted types are export/origin verified and return
without research-type member traversal (W:L624-L655). This is an intentional
trusted-runtime assumption, not proof that their mutable state cannot be
influenced. Exceptions unwind through `_main` generic error/cleanup paths.

### `_main` and `FrozenPredictionArtifact.create` (W:L891-L1024; P:L178-L210)

Callbacks receive sealed frame objects and return values retained across the
hook exit and integrity scan. `create` subsequently invokes Python string
conversion on each value (P:L184-L188). Its annotation is not an exact runtime
type gate. The assumption that return-value consumption cannot invoke
research-attributable behaviour outside the hook has no explicit enforcement
at that boundary: **nothing found**. Success/error messages are sent before
request cleanup; the cleanup poison latch can affect later requests but cannot
retract an already emitted message (W:L995-L1020).

## Existing test contracts and open questions

- Lifecycle tests explicitly require same-program reuse and fresh-client success
  for a different identity (`tests/test_astra_t5_worker_lifecycle.py:L26-L94`).
  Its runtime-hook case exercises `os.system` inside the direct callback only
  (L95-L115). This establishes that phase, not the later conversion/cleanup
  phases.
- T3 tests cover exact-byte selection, reachable label-bearing globals and
  retained repeat success (`tests/test_astra_t3_protected_integrity.py:L51-L172`,
  L174-L366). T5 closure tests cover unbound imports/dynamic code, label stashes,
  cross-program state, decimal state and IPC forgery
  (`tests/test_astra_t5_protected_closure.py:L82-L327`).
- The scan-cost change intentionally preserves acceptance semantics by resolving
  each distinct source once per scan and caching containment only for canonical
  paths (`W:L420-L430`, L450-L466;
  `remediation_evidence/T5/T5_AUTHORITY_MEMO.md:L60-L83`). It assumes no research
  execution during a scan; GC before scanning and later state consumption need
  separate lifecycle examination.
- Can a permitted program retain mutable trusted-runtime state that executes
  after `audit_leave`, including through a returned object, serializer, finalizer
  or other deferred work? No verdict here; supported end-to-end reproducer needed.
- Can cleanup cause executable state changes before its final scan, or preserve
  influence into same-digest reuse? No verdict here; inspect all exceptional paths
  and run repeat-request tests.
- Parent/evaluator byte reconstruction bounds label exposure, but does it make
  worker-side state influence harmless to execution identity and authenticated
  publication? Parent checks data, not a proof of worker execution provenance.
- An independent F-1/E3 audit report was not found among tracked Markdown files
  examined for this bounded context task. Historical finding reconstruction is
  delegated separately; this dossier does not substitute inference for that
  missing original report.
