# ADR-0003 v1: S5 label-free research process boundary

Date drafted: 2026-09-22

Status: **PROPOSED — NOT APPROVED; no S5 production implementation authority**

Scope: Astra A8, offline/local-checkpoint protected-evaluation plumbing only.
This record is the exact protected-control change proposed under Project
Genesis §38 and the approved Astra remediation plan. It does not authorize a
real protected campaign or any research, adapter, shadow, or live GO.

## Decision and authority boundary

1. The process that loads or retains `FutureOutcomeLabel` objects is trusted.
   It may start the trusted evaluator, but it must never execute a research
   callback. The evaluator remains a separate trusted process which alone
   combines frozen predictions with raw labels.
2. Every research callback used by the registered protected API executes in a
   freshly spawned, label-free operating-system process. The process receives
   only the exact sealed decision frames, a versioned research-program
   reference, a dedicated label-free working directory and its own bounded
   research IPC streams. It receives no label object, label value, label path,
   label-store handle, evaluator IPC endpoint, shared memory, parent closure or
   caller callback object.
3. The research process is created and reports ready before the evaluator IPC
   endpoint is created and before labels are materialized by the launcher.
   The required start method is a fresh interpreter, not `fork`; parent memory
   is never inherited. Deliberate retention of labels by the trusted parent is
   therefore part of the acceptance test, not a caller-cleanup convention.
4. Existing `protected-campaign-v2`, sealed-frame, frozen-prediction,
   certificate and durable-attempt meanings remain unchanged. This ADR adds a
   process boundary and a program-reference contract; it does not reinterpret
   historical records or create a campaign.

## Research-process launch contract

The local checkpoint implementation launches an absolute, repository-owned
worker entry point with the current Python executable in isolated mode. It
uses no shell. It supplies a fixed minimal environment, a dedicated research
working directory, stdin/stdout research pipes, closed standard error and no
other inheritable handles. `close_fds` (or the platform-equivalent explicit
handle allowlist) is mandatory. The environment contains only operating-system
bootstrap keys required to start Python plus `PYTHONUTF8=1`,
`PYTHONIOENCODING=utf-8`, and temporary-directory values pointing inside the
dedicated research directory. User/project credentials, label paths,
`PYTHONPATH`, parent task state and arbitrary parent environment variables are
not copied.

The dedicated research directory and explicitly allowed program import roots
must be resolved absolute paths. They must not equal, contain, or be contained
by any trusted label root declared to the launcher. The launch payload has a
closed schema and contains exactly:

```text
schema_version = "protected-research-launch-v1"
sealed_frame_manifest and exact sealed DecisionFrame values
allowed_program_import_roots
max_ipc_bytes
```

It contains no labels or trusted evaluator path/connection. Import roots are a
code capability only; they must not be used as label stores. The worker checks
the sealed frame manifest before becoming ready. Its ready response contains
only the boundary schema, research PID, frame-manifest hash and names of the
capability classes received; it returns no environment values or filesystem
contents. The trusted parent verifies the response and retains it as local
boundary evidence.

For the synthetic checkpoint, labels are in trusted memory and any synthetic
label directory is disjoint and undisclosed. This proves the required process
and address-space/dataflow boundary; it is not a claim that a same-user local
process is an operating-system security principal. Real protected activation
remains disabled until a later approved deployment supplies enforceable
least-privilege identity/ACL/container controls for any real label store.

## `ResearchProgramRef-v1`

Research is selected by a closed, data-only program reference. The registered
protected API must reject Python callable objects, lambdas, closures and
callable instances; it never serializes a callback from the trusted parent.
The unsigned reference has exactly:

```text
domain = "genesis.protected-research-program.v1"
schema_version = "research-program-ref-v1"
module
qualname
module_artifact_hash
```

`module` and `qualname` are nonempty import identifiers; `<locals>` and magic
attribute traversal are forbidden. `module_artifact_hash` is lowercase SHA-256
of the actual resolved module bytes. `program_digest` is lowercase SHA-256 of
`canonical_json` of the unsigned reference and must equal the
`EvaluationRequest.strategy_digest`. The serialized reference contains the
five unsigned fields plus `program_digest`; unknown, missing or malformed
fields fail closed.

The worker resolves the module only below one declared import root, verifies
the actual module bytes, and resolves an exact top-level Python function. The
function must have one frame argument, no closure, defaults, bound instance or
raw `FutureOutcomeLabel` instance reachable from its module globals. The
worker invokes it once for each sealed frame and creates the existing exact
`FrozenPredictionArtifact`. A missing/mismatched module, changed code,
different program digest, malformed probability, reflection-discovered raw
label instance or exception produces only the fixed generic failure.

This contract binds executable test research to the request without approving
the research logic. It defines no model, calibration, strategy, tier rule,
expiry rule or profitability claim.

## IPC and attempt lifecycle

Research IPC is canonical JSON with a hard byte bound and closed operations:

```text
predict: request + ResearchProgramRef-v1
shutdown
```

The worker may return only `ready`, an exact frozen-prediction artifact tagged
with its own PID, `closed`, or the fixed generic research failure. It has no
label-query/evaluator operation. The worker's original stdout IPC handle is
kept private by the worker; callback stdout/stderr is discarded so callback
output cannot become a side channel or corrupt the protocol.

`ProtectedEvaluationClient.run()` first validates that it received a
`ResearchProgramRef-v1`, then reserves the durable attempt, asks the research
worker to produce the artifact and forwards only that artifact to the trusted
evaluator. It does not invoke the program. The trusted evaluator continues to
execute no research callback. It verifies exact request, strategy digest,
frame manifest and complete prediction membership before reading labels and
returns only the controlled certificate or fixed error.

A research exception, timeout, malformed IPC, process death or artifact
mismatch after reservation consumes the attempt. The parent asks the evaluator
to record `research_failure`; failure or uncertainty while doing so never
refunds or reuses the reserved attempt. Restart reads the same durable attempt
history. Evaluator crash semantics, campaign/family limits, suppression and
nonrefundable attempts remain unchanged. Shutdown terminates both children
without transferring labels between them.

The existing explicit `submit()` of an already frozen prediction artifact may
remain for adversarial/exact-binding tests; it supplies no callback and does
not weaken label isolation. The named legacy in-process harness remains
synthetic-only and unavailable to registered v2 campaigns.

## Required RED and acceptance evidence

Before implementation, `tests/test_astra_s5_process.py` must fail with invariant
assertions (not import/setup failures) on clean `166f923` and the immediately
preceding S4 green commit. It must deliberately retain a sentinel raw label and
label-path value in trusted-parent globals/environment while invoking hostile
research, reproducing that the old callback runs in that address space.

Green acceptance requires all of the following:

- research PID differs from both trusted parent and evaluator PID, and the
  actual successful callback response is tagged with that research PID;
- retained parent labels are not visible through callback globals/closures,
  sealed frames, launch serialization, IPC, environment, working directory,
  handles or disclosed paths; research and trusted label roots are disjoint;
- the research worker starts before the evaluator endpoint exists and its
  recorded capability names contain no label/evaluator capability;
- direct callables/closures are rejected without executing in the parent;
- exact valid importable research succeeds, while changed code/reference,
  label-bearing globals, malformed IPC, timeout and crash fail generically;
- failure/crash after reservation remains nonrefundable across restart and
  concurrent clients cannot exceed campaign/family attempts;
- evaluator receives no callback, exact sealed-frame/prediction binding and
  suppression remain, and the real-campaign guard still rejects activation;
- retained R0–R10 and S1–S4 suites, full `unittest discover`, and `compileall`
  pass with exact evidence and a clean independently reviewable commit.

## Explicit non-decisions

This ADR changes no objective, odds range, staking tier, stake/risk percentage,
quota Interpretation A, hold-to-settlement rule, candidate identity, model,
calibration, strategy-specific tier/expiry authority or PAPER/offline status.
It grants no adapter GO, shadow-research GO, protected-campaign GO or live-money
GO. A fresh hostile re-audit and separate checkpoint approval remain required.

## Approval requested

The operator must explicitly approve **this exact ADR version and SHA-256**
before S5 production code is changed. Approval must be recorded in a separate
versioned `DECISIONS/` note citing the draft hash, approver, approval date and
scope. The approved content then remains immutable. A material change to the
topology, program identity, handle/path/environment boundary, attempt behavior
or real-campaign guard requires a new proposed version and approval.
