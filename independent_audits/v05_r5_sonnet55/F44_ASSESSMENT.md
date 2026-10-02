# F-44 — ordinary immutable raw-publication I/O failure (independent assessment)

Audited commit `b22263e582386f04e5b7939e511757940ffdfbe0` (code `9f846d8abcd7383d6acae78294f0aefaba08e630`),
authority `c8dfafdff3be611fa6255a03ed361bc46d7ad8fe`. Reproduced by `probes/p95_f44.py` (output in
`evidence/p95_f44.txt`). Nothing here proposes or makes a change to the candidate.

## What F-44 is

A valid, scanned, 200-class response whose raw-evidence publication (`EvidenceStore.publish` under the raw
contract) fails for a reason that is **not** an immutability/identity conflict — for example `ENOSPC`, a
permission error, or a sharing violation. Architecture §15 has no row for it: F-32 covers only
`ImmutableConflict` / identity conflicts (`QUARANTINED / ARTIFACT_TAMPERED`, halt), and F-05..F-10 assume the
bytes *can* be stored.

## Observed behaviour (independent reproduction)

Injection: `EvidenceStore.publish` raises `OSError(ENOSPC)` for the raw contract only.

| Observation | Result |
| --- | --- |
| Exception from `acquire()` | `OSError: [Errno 28]` propagates (not swallowed, not converted) |
| Durable acquisition rows after the failure | `acq_planned`, `acq_quota_decided`, `acq_sent` — **no** `acq_completed` |
| Coverage rows in the failing process | none |
| Sends | 1 (the request was sent; a 200 body was in memory) |
| Genesis debit | stands (1 unit) |
| After restart + `resume()` | `acq_reconciled` (`ORPHANED_RESERVATION`, `MAY_HAVE_BEEN_SENT`) and one coverage entry `MISSING / ORPHANED_RESERVATION` |
| Re-send under the same plan item | refused (`REFUSED / ORPHANED_RESERVATION`), transport call count stays 1 |
| PIT rows / normalized documents | none |
| Any secret exposure | none (the body was scanned in memory only; nothing was persisted) |

## Is the current behaviour safe?

**Yes.** It is fail-closed on every axis the architecture cares about: no usable observation is created, nothing is
re-sent under the old debit (§14.4), the debit is not refunded (§14.2), nothing partial becomes visible
(`pending_work` lists an open attempt until restart reconciles it), and no credential-bearing byte is persisted
(§7.6). The restart path is the existing F-35 orphan path.

## Does it satisfy c8dfafd?

**Substantively yes after restart, not literally in the failing process.** D13 says *every* failure path "writes a
coverage/exclusion record". In the process that observes the I/O error nothing is recorded; the record is produced
only by the *next* start (`reconcile_after_restart`). §11.1 orders `raw publish → acquisition(completed, …)`, so on
an exception between the two the design leaves no hook for a durable verdict. The classification of the end state
(`MISSING / MISSING_EVIDENCE`-equivalent via `ORPHANED_RESERVATION`) is acceptable under §15 F-35, but it is the
**wrong cause**: the evidence says "may have been sent, outcome unknown" when the truth is "a response was received
and could not be stored".

## What diagnostic durability is lost

All of the following are known in memory and then discarded, never durably recorded:

* that a response **was received** (HTTP status, `T1`, byte length, scan verdict);
* the **provider-reported usage header** — so F-37 / `QUOTA_DIVERGENCE` detection (design §14.2) is skipped for that
  response, even though the provider has metered it;
* the cause (class/errno of the I/O error) — nothing in the ledger distinguishes disk-full from a crash.

The retry policy also cannot tell "received but unstorable" from "never answered": both are `ORPHANED` and become
retryable once under a fresh debit, i.e. a persistent disk fault burns one more unit per retry without ever recording
why.

## Does it need the proposed additive `RAW_PUBLISH_FAILED` / `MISSING_EVIDENCE` taxonomy before G2?

* **G2 (≤5 attended requests, raw capture only): not required.** An operator is present, the call budget is tiny, and
  the orphan path leaves the system safe. The gap should be *recorded* as an accepted residual in the G2 record.
* **G2R / G3 (unattended recurring capture): recommended before.** Without it, an unattended disk-full or permission
  fault silently converts into an orphan, hides provider usage evidence, and cannot be told apart from a crash in the
  AC-2 failure review. This is a diagnostic-durability defect, not a safety defect.
* It should be implemented **together with** the broader totality remediation in `RA5-001`: both are "the runner
  receives a response and then cannot finish" and should share one durable `completed{failure=…}` verdict recorded
  *before* any further step, using the existing HA-04 mechanism (`verdict_effects` / `settle`).

## Classification (kept separate from implementation defects)

`F-44` is an **architecture taxonomy gap**, not an implementation defect against c8dfafd: the code does exactly what
the authority describes for an unmodelled failure (propagate, orphan, never re-send). Severity **INFO**
(finding `RA5-017`), with the G2R/G3 recommendation above.
