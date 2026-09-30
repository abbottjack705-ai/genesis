# F44_ASSESSMENT — I/O failure during raw-evidence publication (expands HA-007)

**Verdict: SAFE, NOT A c8dfafd VIOLATION, NOT CERTIFICATION-BLOCKING. Diagnostic fidelity is lost and the
reconciled outcome is mislabelled. The additive `RAW_PUBLISH_FAILED` semantics are a hardening for a
later ADR (an authority revision), not a patch to `cfcff3d`. F-44 is not implemented here.**

## 1. The gap

c8dfafd §15 has no row for "a valid, secret-clean response whose immutable raw-evidence publication fails
for a reason other than an immutability or identity conflict" (disk full, permission denied, antivirus
lock, network share gone). F-32 covers only a publication the frozen store *refuses* (`ImmutableConflict`,
`RegistryConflict`), F-05 covers transport errors before any response, F-35 covers an orphaned
reservation after a crash. The implementer names this F-44 (`adapters/evidence/S7/SUMMARY.md`, section
"F-44 (not taken as authority)") and did not invent a taxonomy code for it. That restraint is correct:
§15 says every detail code maps to exactly one frozen `ReasonCode` (FM-00), so a new code is an authority
change.

## 2. What the candidate does (read from `cfcff3d`, then exercised)

Code path (`adapters/src/genesis_adapters/oddspapi/raw_capture.py:230-238`,
`acquisition.py:680-692`):

1. The body and every header name/value are scanned first (§7.6). Only a clean, inspectable body reaches
   the publish step, so nothing that follows can persist secret-bearing bytes.
2. `EvidenceStore.publish(...)` raises `OSError`. `RawCapture.store` catches only
   `(ImmutableConflict, RegistryConflict, ValueError)`, so the `OSError` propagates out of
   `AcquisitionRunner._complete`, `acquire`, `AdapterRuntime.acquire` and, in live mode, `cli.cmd_run`,
   where the sanitizing `sys.excepthook` prints only the class name and the process exits 1.
3. The frozen `immutable_write` removes its `*.pending` temp on any `BaseException`; a hard kill between
   the temp write and the link can leave one (clean bytes only, see step 1).
4. Durable state: `acq_planned`, `acq_quota_decided{Tq}`, `acq_sent{T0}` and the Genesis debit. No
   `acq_completed` row.
5. On restart `reconcile_after_restart` writes `acq_reconciled{ORPHANED_RESERVATION, MAY_HAVE_BEEN_SENT,
   quota_row_found=true}` and a `MISSING / MISSING_EVIDENCE (ORPHANED_RESERVATION)` coverage entry. The
   same plan item is answered `REFUSED/ORPHANED_RESERVATION` and is never re-sent under its `request_id`;
   a retry is a new attempt (`attempt+1`) with its own `request_id` and its own debit.

Exercised by the crash matrix (`attacks/a02_a03_crash_matrix.py`), which reaches exactly this durable
state by killing the process at the same point: **C07a** (temp written, link not done, plus a planted stray
`*.pending` temp) and **C07b** (object linked, observation not written), and **C08a** (before the
`completed` row). Results: `TEST_RESULTS.md` §A3.

## 3. Assessment against c8dfafd

| Requirement | Met? | Why |
| --- | --- | --- |
| §11.1 strict order, "each step durable before the next" | yes | `completed` is never written before the raw publish is durable, so no row claims evidence that does not exist |
| §14.2 "Any failure after the debit … Debit stands. No refunds" | yes | the ledger row is untouched |
| §14.4 / F-35 orphan: "not re-sent under the same ID" | yes | restart reconciles the orphan and refuses the same plan item |
| A-2 doctrine: a possibly-sent request never causes an automatic resend under an old debit | yes | only an explicit new attempt, with a new debit, can send again |
| §7.6 credential precedence | yes | publication is after the scan; the only bytes that can remain (a stray temp) passed the scan |
| D13 "no usable observation … writes a coverage/exclusion record" | yes (after restart) | coverage `MISSING (ORPHANED_RESERVATION)` is written by reconciliation; no observation or PIT record exists |
| D13 "retains whatever bytes were received" | not achievable | the store that would retain them is the thing that failed; no requirement is broken by an impossibility |
| §15 row for this failure | none exists | the candidate did not invent one (correct) |

## 4. What is lost (diagnostic fidelity)

- `T1`, `http_status`, the allowlisted response headers, `content_encoding` and `byte_length` of a
  response that **was** received are not durable anywhere.
- The provider usage header (`x-requests-used`, deviation 11) of that response is lost, so the F-37
  `QUOTA_DIVERGENCE` comparison cannot run for it (the next successful response reports the cumulative
  count, so divergence is still caught later).
- The reconciled label says `ORPHANED_RESERVATION / MAY_HAVE_BEEN_SENT`, although the process knew, before
  it died, that the request was received and answered. An auditor cannot distinguish this case from a
  crash before the response.
- No durable halt is written for a plain `OSError`. A restarted runner, while the store is still failing
  (disk still full), will debit and send again on the next planned window and fail again. The frozen
  daily cap (7) bounds the waste; nothing unsafe is persisted.

## 5. Recommended additive semantics (for a later ADR; do NOT implement in `cfcff3d`)

1. New `AdapterFailure.RAW_PUBLISH_FAILED` → frozen `ReasonCode.MISSING_EVIDENCE` (FM-00 stays total),
   coverage `MISSING`, and a new §15 row F-44.
2. In `_complete`, on any `OSError` from `capture.store`: append `acq_completed{outcome: RESPONSE, T1,
   http_status, headers (allowlisted, already scanned), content_encoding, byte_length,
   raw_observation_id: null, failure: RAW_PUBLISH_FAILED}` and `acq_halted{RAW_PUBLISH_FAILED}` before
   re-raising (both writes are to other files; if they also fail the current crash semantics remain).
3. Replay rule: a `completed` row with `failure = RAW_PUBLISH_FAILED` is terminal (never normalized,
   never a retry input for the same ID); a retry is `attempt+1` as today.
4. Tests (RED first): OSError injected into `EvidenceStore.publish` → the two rows, the coverage entry,
   no raw observation, no PIT record, restart does not reconcile it as an orphan, `sends == 1`, and the
   halt blocks the next attempt until an operator reset.

This is an authority revision (new taxonomy row + code), so it belongs in an ADR under
`adapters/DECISIONS/` written by the human owner, not in a certification remediation.
