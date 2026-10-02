# F44_ASSESSMENT — raw-publication I/O failure, reassessed for the b22263e re-audit

**Classification: REQUIRED BEFORE G2** (not required for V0.5 fixture-only certification), **conditional**
on the b22263e re-audit confirming the three safety conditions in §3. If any of them fails on b22263e,
F-44 becomes **REQUIRED NOW** and the failure is a finding of its own.

**Not implemented.** This package changes no candidate code.

**Basis for this reassessment.**

- The architecture authority c8dfafd (`V05_ADAPTER_ARCHITECTURE.md` r3, blob `30c4ca7…`), read in full.
- The cfcff3d behaviour as recorded by the 37b86fb audit (`F44_ASSESSMENT.md`, crash matrix C07a/C07b/C08a).
- **b22263e was not available** (RA-000), so nothing here is a statement about b22263e's code. Probe
  `reaudit/probes/p23_f44_protective_halts.py` and crash-matrix cases C07a/C07b/C08a decide it once the
  candidate is reachable.

## 1. The gap

c8dfafd §15 has no row for this case: a secret-clean, inspectable response whose raw-evidence publication
fails for an ordinary I/O reason. Examples are a full disk, a permission error, an antivirus lock, or a
vanished share. F-32 covers a publication the frozen store refuses (`ImmutableConflict`); F-05 covers a
transport failure before any response; F-35 covers an orphaned reservation after a crash. §15 requires every
detail code to map to exactly one frozen `ReasonCode` (FM-00), so adding F-44 is an authority change
(an ADR), not a patch.

## 2. What the 37b86fb assessment established, and what it missed

It established, on cfcff3d:

- the secret scan runs before the publish, so no secret-bearing byte can be persisted;
- no `completed` row is written before a durable raw publish;
- restart reconciles the attempt as `ORPHANED_RESERVATION` / `MAY_HAVE_BEEN_SENT`, never re-sends under the
  same `request_id`, and the Genesis debit stands.

It called the residual "diagnostic only". **That misses one consequence.** c8dfafd §11.1 fixes this order:

```text
transport → T1 → secret scan → raw EvidenceStore.publish → acquisition(completed)
          → skew check / status-code / strict JSON / closed envelope schema → …
```

Several **protective reactions** depend only on the HTTP status and headers of a received response, and
§11.1 places all of them *after* the raw publish:

| Reaction | Authority | Effect if the raw publish raises `OSError` first |
| --- | --- | --- |
| 401/403: circuit open for all roles indefinitely, capability `BLOCKED`, human G1 re-check | §14.3, F-08, G-04 | not recorded; after restart the attempt is an orphan with no status, so the runner sends again with a key the provider rejected |
| 429: circuit for the role until the next UTC day; two 429s open all roles | §14.3, F-09 | not recorded; the runner keeps sending into the rate limit |
| `Date` skew: all sends suspended until the next UTC day and a clean `Date` check | §6.1, §14.6 rule 5, F-12 | not recorded; sends continue while the skew bound that W1–W4 rely on is known to be broken |
| Provider usage above the Genesis debit: halt all live acquisition | §14.2, F-37 | not compared for that response; the next good response's cumulative count may catch it later |

The `SECRET_ECHO` halt is **not** affected. The scan runs before the publish, and a hit writes quarantine
metadata, never raw evidence. If that metadata write also fails, nothing is persisted, so secrecy holds.

Contrast with a **crash** after `completed`. There, §14.4 resume re-enters the flow with the status and
headers already durable in the `completed` row, so a correct resume restores the protective reaction. The
`OSError` case differs because no `completed` row exists: the status is lost before it becomes durable.

## 3. Safety conditions that must hold on b22263e (re-audit checks)

| # | Condition (c8dfafd) | Decided by |
| --- | --- | --- |
| S1 | Secret scan of the wire body, decoded body and every header precedes any durable write (§7.6, D15) | a06, SEC-01…05, crash C06 |
| S2 | No `completed` row and no observation before the raw object and its observation are durable (§11.1) | crash C07a, C07b, C08a |
| S3 | After restart, an attempt without `completed` is reconciled `ORPHANED_RESERVATION`. It is never re-sent under its `request_id`, its debit stands, and a retry is `attempt+1` with its own debit (§14.4, F-35, A-2) | crash C02–C08 (0 sends, 0 `reserve()` after restart) |
| S4 | **(new)** A protective reaction to a received response survives a raw-publish `OSError` | p23 F1 (control F0 first) |

If **S1**, **S2** or **S3** fails, F-44 is **REQUIRED NOW**. Each of those failures could persist secret
bytes, claim evidence that does not exist, or resend under an old debit.

If only **S4** fails, the classification stays **REQUIRED BEFORE G2**, recorded as a confirmed MEDIUM
finding. The reason: fixture mode (Stages 0–7) never receives a real 401, 429 or skewed `Date`, and G1 only
stores a credential; the first exposure is the first live request at G2.

## 4. Why REQUIRED BEFORE G2, and not "later ADR" or "now"

**Not required now.** Under S1–S3 nothing unsafe is persisted, nothing is re-sent under an old debit, and
no usable observation can appear. Stages 0–7 are fixture-only (§3.1 "Network: None until G1/G2"). G1 stores
a credential and sends nothing. No V0.5 certification property depends on F-44.

**Required before G2, for three reasons.**

1. **G2 is the first live exposure.** It is also when the provider's real 401/403/429/`Date` behaviour is
   first observed (§16.3: "`Date` header presence", "quota/usage headers", "per-role metering evidence").
   Without F-44, an I/O failure during G2 can:
   - lose the one response that evidences the provider's metering or status behaviour;
   - label the attempt identically to a crash before any response;
   - consume one of G2's ≤ 5 pinned calls (`max_calls` = list length).

   The G2 schema verification report must account for every call, and a replacement needs a new
   human-approved G2 record.
2. **The loss of protective reactions in §2 is live-only, and G2 is where it starts to matter.** A 401/403
   that never opens the circuit lets a restarted runner keep presenting a rejected (possibly revoked or
   compromised) key. §14.3 requires a human G1 re-check before any further send. The frozen daily cap of 7
   bounds the count but not the principle.
3. **No durable halt is written for a plain `OSError`.** Under G2R scheduling, a store that stays broken
   (a full disk) makes every window debit, send and lose its evidence. That repeats until an operator reads
   the exit status, consuming the 220-unit normal budget with zero retained evidence, against the intent of
   D13 and AC-7.

## 5. Minimal additive semantics (for a human-written ADR under `adapters/DECISIONS/`; not implemented)

1. A new `AdapterFailure.RAW_PUBLISH_FAILED` maps to the frozen `ReasonCode.MISSING_EVIDENCE`, with
   coverage `MISSING`, plus a new §15 row F-44. FM-00 stays total.
2. **Protective decisions before the publish.** Derive, from the already-scanned status and allowlisted
   headers, the protective reaction the response will require (circuit 401/403/429, skew suspension, usage
   divergence). Append it durably **before** `EvidenceStore.publish`. Each reaction needs only the status
   line and headers, which §7.6 has already scanned.
3. On any `OSError` from the raw publish:
   - append `acq_completed{outcome: RESPONSE, T1, http_status, allowlisted headers, content_encoding,
     byte_length, raw_observation_id: null, failure: RAW_PUBLISH_FAILED}`;
   - append `acq_halted{RAW_PUBLISH_FAILED}`;
   - then re-raise.

   Both rows go to files other than the evidence store. If those writes fail too, today's crash semantics
   (S3) still apply.
4. Replay rule: a `completed` row carrying `failure = RAW_PUBLISH_FAILED` is terminal. It is never
   normalized and never a retry input under the same ID. A retry is `attempt+1`. The halt blocks further
   sends until an operator reset, which should require the store to pass `EvidenceStore.verify_manifest()`
   first.

## 6. Required regression (RED on the current semantics, GREEN after the ADR)

- `OSError(ENOSPC)` injected into the raw `EvidenceStore.publish` for responses 401, 403, 429, a skewed
  `Date`, and `x-requests-used` above the debit. After restart: 0 sends (p23 F1). There must also be:
  - one `completed{failure: RAW_PUBLISH_FAILED}` row and one `acq_halted` row;
  - no raw observation and no PIT record;
  - coverage `MISSING (RAW_PUBLISH_FAILED)`;
  - restart does not reconcile the attempt as an orphan.
- The same injection for a clean 200: `sends == 1` in total, the halt blocks the next window, and an
  operator reset is refused while `verify_manifest()` fails.
- Unchanged: crash matrix C02–C08, C07a/C07b/C08a (S2/S3) and SEC-01…05 (S1).
