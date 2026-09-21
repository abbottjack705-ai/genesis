# R9 — Independently isolated protected evaluation

Status: **GREEN / LOCAL CHECKPOINT ONLY**

## Red-before basis

The hostile probe ran in a detached worktree at `d486297`. It recovered the raw label
both directly and from inside the strategy callback, proved the callback ran in the
label-owner PID, and let two processes consume a one-attempt budget. See
`RED_BEFORE.md` and the retained R0 F13 evidence.

## Closed invariants

- Research receives sealed `DecisionFrame` objects only. Their exact IDs and content
  hashes form a deterministic `frame_manifest_hash`.
- Research creates a content-addressed frozen prediction artifact keyed to frame IDs and
  bound to campaign, dataset, strategy ID/digest, and exact frame manifest.
- Labels exist only in a separately spawned trusted evaluator process. The returned
  research client contains no label object, label path, label handle, or process argument
  retaining label material.
- IPC accepts and emits bounded canonical JSON bytes using `send_bytes`/`recv_bytes`; it
  never unpickles a research payload. Unknown/raw IPC operations return a fixed generic
  error and cannot query labels.
- No arbitrary strategy callback executes in the label-owning process. The client-side
  callback receives only sealed frames; the evaluator accepts only a frozen artifact.
- Campaigns are append-only registered and bound to an existing registered experiment,
  dataset version, evaluator digest, and exact sealed frame manifest.
- Attempt reservation occurs inside the trusted evaluator before research generation or
  artifact evaluation. Campaign/family count, budget check, deterministic attempt ID,
  and append share one R1 transaction.
- Research failure, artifact mismatch, suppression, evaluator failure, and evaluator
  crash do not refund an attempt. Counts replay exactly after restart.
- Two evaluator processes racing the final slot produce one certificate and one
  deterministic rejection.
- Missing, extra, substituted, or wrong-manifest frames reject after reservation. Tiny
  fixed campaigns suppress under registered policy; arbitrary caller slices do not exist.
- Only a controlled certificate or fixed generic error crosses IPC. A label-dependent
  internal exception exposes no label value, traceback, cause, or context.
- The old callback implementation is renamed as an explicitly unsafe synthetic-only
  harness. It requires opt-in and rejects registered V2 campaigns.
- Real protected-campaign activation remains disabled until an independent boundary
  review; only `local_checkpoint_test_only=True` can launch this offline test boundary.

## Matrix evidence

- T-F13-001..002: client/object/IPC introspection finds no label material; strategy runs
  outside the evaluator process and cannot execute there.
- T-F13-003..005: suppression, research/evaluation failure, and post-reservation crash
  all consume durable attempts.
- T-F13-006..008: campaign/experiment registration, evaluator digest, and fixed campaign
  frame set are enforced before label evaluation or by controlled suppression.
- T-F13-009: label-dependent exception returns only a generic error with no traceback,
  cause, context, or label-derived detail.
- T-F13-010..011: restart preserves monotonic campaign/family counts and the final-slot
  inter-process race admits exactly one reservation.
- T-F13-012: missing, extra, and substituted frame manifests reject and consume attempts.

## Verification

- Targeted R9 suite: **11/11 green**.
- Full suite: **107/107 green**.
- Compileall: **green**.
- Diff check: **green**.

## Scope check

No cloud service, label vault path, external provider, network integration, sport model,
credential, strategy promotion, autonomous protected campaign, or live path was added.
