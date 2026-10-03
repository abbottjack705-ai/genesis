# Remediation handoff (for the implementer; the auditor changed nothing)

Audited: code `4ed66de4e2f3161464b9205583b3ee7a97133904` (tip `435cdba…`, evidence only). Verdict: **REMEDIATION
REQUIRED** (two MEDIUM, three LOW, five INFO). Every item has a deterministic reproduction in `probes/` and a transcript
in `evidence/`. **Do not weaken a test, edit the architecture, or touch the six frozen trees to make an item pass.**
Keep each fix inside `adapters/`, minimal, and write the stated regression RED first against `4ed66de`.

What must stay byte-for-byte (verified closed here): the strict-decoder bounds and their exact edges, the total
`derive()` boundary and its terminal row semantics, the `parse_http_date` totality and CLOCK_SKEW mapping, the hidden
environment for the single-threaded production context, the absolute monotonic deadline on every socket phase, and all
R1–R5 closures (§7 of the report).

## Required before G2R / G3 (blocking)

### R6-A `RA6-001` MEDIUM — settle every rejection verdict, not only the newest attempt's

`settle_last()` (acquisition.py:967) settles the newest *planned* attempt. R6's `acq_derivation_rejected` is the first
verdict that can be written for an **older** attempt (the first G2R `resume()` derives every G2 capture in ledger
order), so a crash or an I/O error between the row and `settle(aid)` loses the REJECTED coverage entry for ever, silently
(`probes/a01_settle_gap.py`: CONTROL held, ATTACK lost).

Minimal requirement: at restart (`reconcile_after_restart` or `resume`) settle every attempt whose latest verdict row is
`acq_derivation_rejected` and whose deterministic coverage entry id is absent; or make `settle_last` consider every
attempt with a verdict newer than its last settlement. Regression: crash at `after_derivation_rejected` for the newest
and for a non-newest attempt, plus a failing coverage append; after restart exactly one REJECTED entry per row (today
no test crashes at that checkpoint at all, RA6-009).

### R6-B `RA6-002` MEDIUM — a QUOTA_DIVERGENCE response must not become usable at the next start

F-37 says "Observation / head: none; halt" (evidence "acquisition + headers"). Today the halt is durable but
`completed.failure` stays `None`, so `successful_capture()` is true and the next `resume()` (every G2R start) derives the
response into usable OPEN documents while the halt is still in force; the uninterrupted process never does
(`probes/q01_quota_divergence_restart.py`). Inherited for `reported > debited`; R6's RA5-011 extends it to every
unreadable header.

Minimal requirement (pick one, record it): (a) put the divergence into the response's own verdict before the completed
row is written (the HA-04 mechanism), so `successful_capture()` is false in every run order; or (b) a terminal row that
`successful_capture` honours; or (c) an ADR amending F-37 to keep the response usable — then the uninterrupted run must
derive it too. Regression: identical PIT/document sets for the uninterrupted and the restarted run for each usage form.

## Required before the corresponding gate, lower priority

| Finding | Do | Regression |
| --- | --- | --- |
| `RA6-003` LOW | Stop mutating `os.environ` in `tls_context()`: build `SSLContext(PROTOCOL_TLS_CLIENT)`, load `ssl.get_default_verify_paths().openssl_cafile/openssl_capath` (compiled-in, environment-free) and, on Windows, the system stores; set `check_hostname`, `CERT_REQUIRED`, `keylog_filename=None`, and pin `minimum_version = TLSv1_2` explicitly. If the mutation stays, serialise it with a module lock and use `pop(name, None)` | `probes/t02_tls_env_race.py`: zero trusting contexts, zero exceptions, `os.environ` untouched; t01 still all held; 127 system CAs still present |
| `RA6-004` LOW | Bound name resolution by the remaining time (resolver thread joined with the deadline and abandoned; or resolve outside the attempt and connect to the resolved addresses with SNI/hostname verification unchanged) | `probes/r02_dns_stall.py` (isolated namespace): `send()` returns by deadline + ε |
| `RA6-005` LOW | Detect a derivation-source change at start (stored `acq_normalized.derivation_version` ≠ running) and refuse explicitly (not `EVIDENCE_CONFLICT`), or implement §13.3; document "new derivation source ⇒ new runtime root" in the runbook | `probes/v01_versioning_replay.py` part C: explicit refusal, no tamper-class halt |

## Recommended, no gate dependency

`RA6-006` scope the terminal rejection to its `derivation_version` (or ADR why not); `RA6-007` tighten replay of
`acq_derivation_rejected` (role ODDS, RESPONSE/200, raw id, derivation failure codes only, `derivation_version` text);
`RA6-008` judge every `Date` occurrence or document first-wins; `RA6-009` add the crash test at
`after_derivation_rejected`; `RA6-010` frozen-foundation T6 race test under load → foundation owners, not this slice.

## Certification still owed outside the code

`WINDOWS SYMLINK CERTIFICATION: OPEN` — `WINDOWS_GAPS.md` W1–W15 against the final remediated commit.
