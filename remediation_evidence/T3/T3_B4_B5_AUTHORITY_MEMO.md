# T3 / B4+B5 authority and implementation memo

Date: 2026-09-25 (Europe/London)

Sealed base: commit `4214f38886d5046f76a3fa8002889f02a701187f`,
tree `31f00dabaaf320835f8aaf7d041ab5c75bc1b83c`.

Scope: B4 and B5 only. B8 remains separate. No protected campaign, research,
adapter, shadow or live GO is authorized.

## Exact failures

### B4 cached executable substitution

`protected_research_worker._resolve_program()` currently calls
`importlib.import_module(program.module)`, then hashes the current path. A
persistent worker can therefore receive a new correct file hash after the file
changes while `import_module()` returns the old `sys.modules` object. The
certificate carries the new program digest but the old callback computes it.
The original probe obtains Brier `0.01` before and after replacing the source
with a constant-0.5 program; the second exact expected result is `0.25`.

### B5 incomplete reachable-state inspection

`_contains_label()` stops after depth five, treats functions/modules/types as
safe without inspecting state, handles only built-in containers, and returns
false for arbitrary objects. A module-global `SimpleNamespace` containing raw
`FutureOutcomeLabel` instances is therefore accepted, read by the callback,
and certified with Brier `0` while `raw_labels_exposed` remains false.

The exact original RED transcript is `ORIGINAL_B4_B5_RED_T2.txt`.

## Authority reconciliation and classification

Approved ADR-0003 v1, SHA-256
`0fd4c63deb7a8431c41d7869163ccf79ce0295b63b585c8e4c3a0695f1dafaad`,
already requires all of the following:

- `module_artifact_hash` is the hash of the actual resolved module bytes;
- the worker resolves only below an allowed root and executes the exact
  top-level stateless function;
- changed code/reference and label-bearing globals fail generically;
- no raw `FutureOutcomeLabel` is reachable from program global state;
- process/PID, launch topology, sealed frames, IPC, attempt consumption,
  output suppression and real-campaign disablement remain intact.

Classification: **A — already-authorized implementation repair**. No new ADR
or human decision is required. The repair makes the existing approved contract
true without changing `ResearchProgramRef-v1`, `program_digest`, campaign,
certificate, frame, attempt, process topology, IPC or activation semantics.

A class-C decision would be required if closure needed a new program-reference
preimage, per-call launcher/evaluator topology, a different handle/path
boundary, changed attempt lifecycle, or real protected activation. None is
proposed. If the implementation below proves insufficient without one of those
changes, T3 must stop before making that change.

## Smallest compliant construction

1. Resolve the program module deterministically as a `.py` module or package
   `__init__.py` below exactly one declared import root, without importing the
   target module and without consulting a target object in `sys.modules`.
   Ambiguous origins, non-files, outside-root origins and unsupported forms
   fail closed.
2. Read the resolved bytes once, hash those exact bytes, and compare them to
   `module_artifact_hash` before any target import-time code runs. Compile and
   execute those same in-memory bytes in a fresh, unregistered module namespace
   for each request. The callable can therefore never be a cached object from
   different bytes, and a path mutation after the read cannot change the bytes
   actually compiled.
3. Resolve and validate the exact function as before, then run a cycle-safe,
   no-depth-cutoff capability audit over the function's reachable global state
   and function attributes. Inspect mappings, keys/values, deep collections,
   transparent object dictionaries, real slots, referenced local functions,
   and custom imported holders. Reject raw labels and unsupported/opaque state;
   do not equate “not yet inspected” with label-free. For trusted code modules,
   inspect the statically referenced capability attributes and reject dynamic
   reflection that defeats the closed audit.
4. Preserve the generic error response. Because validation happens after the
   evaluator's durable reservation in `ProtectedEvaluationClient.run()`, every
   B4/B5 rejection remains a consumed, nonrefundable attempt.

This is an executable-integrity and capability-validation repair inside the
existing research process. It is not a claim that Python graph inspection is
an operating-system security boundary; ADR-0003's real-campaign guard remains.

## Expected files

- `src/genesis/protected_research_worker.py`: verified-byte loader and strict
  reachable-state validator.
- `tests/test_astra_t3_protected_integrity.py`: independent B4/B5 hostile,
  positive, replay and attempt tests.
- `ARCHITECTURE.md`, `PROJECT_STATE.md`, `TEST_EVIDENCE.md`, `HANDOFF.md` and
  `remediation_evidence/T3`: truthful checkpoint evidence.

No ADR, `ResearchProgramRef`, campaign, evaluator, quota, risk, candidate,
settlement or policy implementation is expected to change.

## RED to GREEN matrix

| Invariant | Sealed-T2 RED | Required GREEN |
|---|---|---|
| Changed bytes execute exactly | new digest, old cached Brier `0.01` | new digest executes new bytes, Brier `0.25` |
| Cache/origin isolation | target comes from `sys.modules` | target always comes from verified in-memory bytes; ambiguous/outside origin rejects |
| Verify/load mutation | disk hash and cached code can diverge | bytes hashed are exactly bytes compiled; later path mutation cannot substitute code |
| Same/stale reference | cached target can mask changed disk | identical bytes repeat; stale ref after mutation fails generically |
| Object-held labels | `SimpleNamespace.labels` certifies | object dictionaries and slots reveal label and reject |
| Imported/function-held labels | functions/modules skipped | custom imported holders and function attributes reject |
| Deep/cyclic state | depth >5 treated safe | arbitrary depth is checked; cycles terminate; safe cycles work |
| Opaque global state | unknown objects treated safe | unsupported/uninspectable reachable state fails closed |
| Legal program | old simple signal program works | valid label-free repeated program remains valid in distinct research PID |
| Failure lifecycle | bypass yields certificate | rejection generic, consumes attempt, restart cannot refund |
| Retained protections | must not regress | sealed frames, exact request, PID/IPC, output suppression, attempt quota, crash/restart and activation guard all green |

## Untouched invariants

- ADR-0003 and its approval note remain byte-for-byte immutable.
- `ResearchProgramRef-v1` fields, hash preimage and every historical program
  digest retain their exact meaning.
- Research remains a distinct label-free process started before label
  materialization and evaluator IPC; evaluator still executes no callback.
- Campaign/frame/certificate/frozen-prediction identities, durable attempt
  reservation/completion, generic errors, suppression and quotas are unchanged.
- Real protected activation remains disabled; no model, strategy, adapter,
  shadow research, protected campaign or live-money path is approved.
- Project objective, odds/stake/risk law, quota Interpretation A,
  hold-to-settlement and offline/PAPER status are unchanged.
