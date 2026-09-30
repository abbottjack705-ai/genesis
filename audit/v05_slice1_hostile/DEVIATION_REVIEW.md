# DEVIATION_REVIEW — the 24 documented deviations of `adapters/evidence/S7/SUMMARY.md` at `cfcff3d`

Source text: `git show cfcff3d:adapters/evidence/S7/SUMMARY.md`, section "Deviations and interpretations"
(items 1–24). Every classification below was checked against the **code** at `cfcff3d` and, where a
behaviour is claimed, against an auditor attack (`attacks/`, results in `TEST_RESULTS.md`). The SUMMARY
text itself is treated as untrusted.

Classes (as required by the handoff): **CONFORMING INTERPRETATION** · **STRICTER BUT SAFE** ·
**AUTHORITY AMBIGUITY** (the authority is silent or self-contradictory; the candidate's reading is recorded
and, where it matters, turned into a finding) · **UNAUTHORIZED SEMANTIC CHANGE** · **DEFECT**.

## Summary

| # | Deviation (short) | Class | Finding |
| --- | --- | --- | --- |
| 1 | RED drafted before the RED run, held outside the repo | CONFORMING INTERPRETATION | — |
| 2 | Boundability: examples vs formulas | STRICTER BUT SAFE | — |
| 3 | Extra policy fields | STRICTER BUT SAFE | — |
| 4 | META cache publish only after all content checks | STRICTER BUT SAFE | — |
| 5 | `send_state` on reconciliation; `ORPHANED` retry input | CONFORMING INTERPRETATION | — |
| 6 | `bookmakerIsActive` allowlist | CONFORMING INTERPRETATION | — |
| 7 | ODDS `startTime` optional; `price` nullable | CONFORMING INTERPRETATION | — |
| 8 | Two stricter reader refusals | STRICTER BUT SAFE | closes HA-002 |
| 9 | Expected scope computed as of `Tq` at normalization | CONFORMING INTERPRETATION | closes HA-012 |
| 10 | `complete_hint` always `True` | AUTHORITY AMBIGUITY (safe direction) | — |
| 11 | Provisional `x-requests-used` as a UTC-month count | CONFORMING INTERPRETATION (provisional, A12) | — |
| 12 | Gate bounds in `oddspapi_gate_limits.json` | AUTHORITY AMBIGUITY | HA-015 (LOW) |
| 13 | CLI location; extra `reset`; separate `approve-ready` | CONFORMING INTERPRETATION for the split; **UNAUTHORIZED SEMANTIC CHANGE** for the undocumented operator-chosen times; AUTHORITY AMBIGUITY for `reset` | HA-013 (MEDIUM), HA-014 (LOW) |
| 14 | G2 mode is raw capture only | CONFORMING INTERPRETATION | — |
| 15 | One `LIVE_SEND` gate | CONFORMING INTERPRETATION (G2R `plan_digest` not checked: see HA-015) | HA-015 (LOW) |
| 16 | Guard-zone skips; simulated-`lstat` symlink test | CONFORMING INTERPRETATION for the zone skip; the symlink branch is a certification gap | HA-004 |
| 17 | Transport read cap / premature close / completion | CONFORMING INTERPRETATION | — |
| 18 | `T0 < T1` on a coarse clock | CONFORMING INTERPRETATION | closes HA-008 |
| 19 | Strict credential file (CRLF, hard link, same file) | STRICTER BUT SAFE | — |
| 20 | Loopback end-to-end CLI run with an injected test CA | AUTHORITY AMBIGUITY (test seam in the live CLI) | HA-006 |
| 21 | G-03 exercised in a scratch registry | CONFORMING INTERPRETATION | — |
| 22 | Hardening tests added after `S7/RED.txt` | CONFORMING INTERPRETATION (RED for those is by mutation) | — |
| 23 | `S7/FROZEN.txt` wall time includes a host pause | CONFORMING INTERPRETATION (independently re-run) | — |
| 24 | Committed test `server.key` | AUTHORITY AMBIGUITY | HA-006 |

No deviation is classified DEFECT in itself; the one UNAUTHORIZED SEMANTIC CHANGE (inside item 13, not
documented by the implementer) is HA-013.

## Item by item

**1. RED timing.** §18: "Each test is written first and shown RED … against the stage's starting commit".
Holding drafted production code outside the repository during the RED run keeps the RED transcript a run
of the previous stage's tree, which is what §18 asks. Process only; the RED transcripts are implementer
artefacts and were not relied on (the audit's independent kill evidence is `attacks/a15_mutation.py`).
→ CONFORMING INTERPRETATION.

**2. Boundability: examples vs formulas (§20.1).** Two genuine inconsistencies in the authority: (a) the
reopen example "UTC-calendar-month allowance below 250" versus B1 `min(7 × U_W, 250 × M_W)`, which gives
217 for a 31-day UTC month because the frozen daily cap applies before the budget-class branch, reserve
included (`src/genesis/quota.py:1134`); (b) the UTC-aligned-day fallback example `U = 2` versus the formal
`W⁺` count 3. The code (`oddspapi/boundability.py:117-128`) requires **both** the formula and the stricter
UTC-month example (`formula_ok and example_ok`) and uses the formal `W⁺` geometry, so it refuses whenever
either reading refuses. §14.6 W1–W4 remain the normative send rule and are untouched. (The SUMMARY's
wording "follows the formulas" understates what the code does; the code is the stricter union.)
The implementation prompt (§23) says "If it is internally inconsistent … STOP and report the exact
conflict"; the implementer reported it and continued with the stricter union instead of stopping. Because
the evaluator only assists the G1 human check and refuses whenever either reading refuses, no authority
decision was pre-empted; recorded here, not raised as a finding. → STRICTER BUT SAFE.

**3. Extra policy fields** (`header_value_max_chars`, `read_chunk_bytes`, `max_decompression_ratio`,
`secret_fragment_min_chars_floor/_divisor`, `declared_bookmakers_max`). §12.1 forbids literal bounds
(FRZ-10) and §9.2 puts every policy field inside `policy_digest` → `derivation_version`. The policy file
carries `classification: PROVISIONAL_SLICE1_POLICY` and `policy_version`; `SlicePolicy` has no defaults.
Each extra field only names a bound the code needs; none relaxes a §12.1 value (the fragment formula is
`max(8, ceil(n/3))` exactly). → STRICTER BUT SAFE.

**4. META cache publish only after skew, content-type, strict JSON and closed-envelope checks**
(`acquisition.py:749-753`). §11.1 draws the publish before those checks. Publishing later can only
withhold a cache entry, never create one, so a rejected response can never answer a later request for 0
units; the frozen `VerifiedCacheStore` semantics are unchanged. → STRICTER BUT SAFE.

**5. `send_state` on `reconciled`; `ORPHANED` retry input.** §9.3 lists `reconciled{outcome}`; the extra
`send_state` (`NOT_SENT` / `MAY_HAVE_BEEN_SENT`, derived from whether `acq_sent` was durable) and
`quota_row_found` are validated on replay (`acquisition.py:328-337`, a contradiction is a ledger
invariant error). Treating a reconciled orphan as a retry input with no status seen matches §14.3
("NO_RESPONSE (no HTTP status received)") and §14.2 "Retry: new attempt, new `request_id`, debited
again"; the retry limit still applies. Crash matrix C01–C08 confirm no resend under the old ID.
→ CONFORMING INTERPRETATION.

**6. `bookmakerIsActive` allowlist.** The field lives in `oddspapi_v4_status_map.json` under
`bookmaker_status` (typed `(field, bool, value)` rows), and that file is one of the five `CONFIG_FILES`
whose digests enter `derivation_version` (`config.py:26-32`, `status_map_digest`). `true` → ACTIVE,
`false` → the bookmaker's books SUSPENDED (no `selections`), anything else → BLOCKED. §10 rule 1
("Anything not listed is UNKNOWN … BLOCKED") and §10.1 (the bookmaker block is a closed semantic
structure) require exactly an allowlist here; the design's list of levels was not exhaustive for a field
it did not know about. Probed by `a08` (false / wrongly typed / missing; no probe leaves a price).
→ CONFORMING INTERPRETATION.

**7. ODDS `startTime` optional; `price` nullable.** §8.3 defines the fixture join for exactly the case
where the ODDS response lacks kickoff data (absent → join, or BLOCKED `EVENT_METADATA_STALE`), and §6.3
forbids OPEN without `S`. §10 rule 5 makes "an ACTIVE outcome with a missing, zero or ≤ 1.0 price" a
CONTRADICTORY_STATUS, which presupposes that a missing/null price can be represented instead of being
schema drift. `a08` probes: `startTime` absent with no join → BLOCKED `EVENT_METADATA_STALE`, never OPEN;
null price on an ACTIVE outcome → BLOCKED `CONTRADICTORY_STATUS`. → CONFORMING INTERPRETATION.

**8. Two stricter adapter-only reader refusals.** (a) `STALE` when a record newer than the head
(`valid_from` later) was already available, retrieved and ready at `D` but is no longer admissible
(`reader.py:197-213`); (b) the head's artifact must have exactly one observation under the contract. §12.3
says the reader "adds adapter-only refusals on top, and never removes a verifier refusal". Both only
refuse. Determinism in `D`: (a) reads only PIT rows with `available_at, retrieved_at, ready_at ≤ D`, so it
is a function of the history visible at `D` under the §6.3 quiescence rule; (b) can flip a past "usable"
to a refusal only if a second observation of the same normalized artifact appears later, which the
emitter never produces (it reuses the existing observation) and which would itself be tampering - the
direction is fail-closed. (a) is precisely the HA-002 refusal; `a04` confirms the frozen verifier
**accepts** the older record in `[valid_to_new, valid_to_old)` while the reader returns `STALE`.
→ STRICTER BUT SAFE; closes HA-002.

**9. Expected scope as of `Tq`, computed at normalization and on resume.** §12.4 says "Before sending …
the runner computes the expected scope … at `Tq`". The candidate computes the same set later, from the
append-only PIT log with `admissible_at(Tq)` (`scope.py:76-114`) and pins it by hash in the `normalized`
row. Equivalence holds because every record appended after `Tq` carries `ready_at = T3 > Tq` (trusted,
monotonic clock; the single-writer constraint of §3.2/A9), so `admissible_at(Tq)` excludes it; on a
resume the recomputation gives the same bytes (idempotent `immutable_write`). The computation does **not**
consult the capability registry, so tombstones are produced while the source is UNKNOWN (G2R) - which is
what AC-4 needs (`a10` HA-012 probe). → CONFORMING INTERPRETATION; closes HA-012. (Residual, INFO: the
equivalence relies on one writer; a second concurrent runner is FR-2 territory.)

**10. `complete_hint` always `True`.** §15 F-15 recognises partiality from "a provider completeness flag,
or a required list missing for part of the scope". No completeness flag is known before G2 (A2), so only
the second signal can be used. A silently partial provider response without either signal would yield
ABSENT tombstones - which **reduce** usability (a tombstone never supplies a price), so the error direction
is safe; G2 must confirm whether the provider paginates or truncates. → AUTHORITY AMBIGUITY (safe
direction), carried to G2.

**11. `x-requests-used` read as a UTC-month count.** §21 A12 explicitly defers usage headers to G2; F-37
halts when reported > debited (`acquisition.py:709-711`). If the real header counts a shorter window the
check can miss a divergence; if a longer one it false-halts (safe). → CONFORMING INTERPRETATION
(provisional, G2).

**12. Gate bounds in `adapters/config/oddspapi_gate_limits.json`.** FRZ-10 forbids literals, so moving
§16.3/§16.4's "≤ 5 requests", "≤ 72 h" and "≤ 35 days" out of code is reasonable. But the file is not one
of the digest-pinned `CONFIG_FILES`, not in `derivation_version`, not checked by F-31, and `--config` lets
the operator point every CLI command at any directory: an edited file silently widens design constants
with no digest change anywhere. → AUTHORITY AMBIGUITY → **HA-015 (LOW)**: pin the file's SHA-256 in code
the way `frozen_genesis_modules.json` is pinned in `verify.py`.

**13. CLI location, `reset`, `approve-ready`.** (a) `cli.py` at package level instead of `oddspapi/`:
cosmetic. (b) READY written by a separate interactive `approve-ready` that requires a G3 record, an
interactive TTY and the typed phrase (`cli.py:167-200`), so the command that appends gate records never
touches the capability registry: consistent with §16.5/§16.6. (c) **Not documented:** `approve-ready`
stamps the READY row with the operator's `--at` value, and `approve` stores `granted_at` exactly as written
in the record file, while §16.5 says `recorded_at=now` and §16.2 says `granted_at (trusted clock)`; combined
with the absence of the §16.4 G2R `UNKNOWN` row, a READY row can be dated before the approval and before
the captures it makes consumable (demonstrated by `a13`). → UNAUTHORIZED SEMANTIC CHANGE → **HA-013
(MEDIUM)**. (d) `reset` (writer of the ledger's `acq_operator_reset`) is not in the design's command list;
it is operator-only and interactive, but it clears every durable halt, including `SECRET_ECHO` and
`AUTH_REJECTED`, without checking that a newer G1 with a different credential fingerprint exists (§7.6:
"a human must rotate the key (re-G1)"). → AUTHORITY AMBIGUITY → **HA-014 (LOW)**.

**14. G2 mode is raw capture only.** §16.3 "Output (raw only; no normalization emitted operationally)".
`cmd_run` calls `rt.runner.acquire` in G2 mode. → CONFORMING INTERPRETATION.

**15. One named `LIVE_SEND` gate** (`authority.py:193-219`): attestation, G1 valid at `Tq` with the loaded
key's fingerprint, then G2 (pinned hash, call budget since `valid_from`, window) or G2R (`derivation_version`,
`policy_digest`). Matches G-01/G-02 and the §16.6 list ("derivation_version, request hashes, credential
fingerprint"). The G2R record's `plan_digest` is recorded but never compared with the plan being run
(`cmd_run --plan` is a free list of requests). §16.6 does not list `plan_digest` among the checked pins, so
this is not a violation; the frozen ledger still bounds spend. → CONFORMING INTERPRETATION, with the
`plan_digest` note folded into **HA-015 (LOW)**.

**16. Skips.** Tests needing the real clock outside the 23:57–00:02 UTC guard zone skip inside it
(environmental, deterministic). The real-symlink credential branch skips on accounts without the symlink
privilege and is otherwise covered by a simulated `lstat`: a security boundary certified by simulation
only. `a11` could not create a symlink on this account either (see TEST_RESULTS §A11). → CONFORMING
INTERPRETATION for the zone skip; the symlink branch stays **HA-004** until one privileged run.

**17. HTTPS transport read cap / premature close / completion** (`transport_http.py:73-83, 177-211`).
Reading at most `max_response_bytes + 1` makes an oversize body detectable (F-06) without unbounded
reads; an early close before `Content-Length` is a truncation (F-06); stopping when `http.client` reports
completion avoids touching a closed socket. → CONFORMING INTERPRETATION.

**18. `T0 < T1` on a coarse clock** (`transport_http.py:112-128`). HA-008's three conditions: bounded by
the drift budget (`give_up = monotonic + wall_monotonic_drift_max_ms`), no literal sleep (the tick is
`time.get_clock_info("time").resolution`; the oracle's X-08 found no numeric sleep/timeout literal), and T1
read after the last body byte (after the read loop and `close`). A clock that never moves is returned as
read and the runner halts `CLOCK_FAULT` (`acquisition.py:671-676`); `SystemUtcClock` raises
`WALL_CLOCK_JUMP` first. `a07` confirms all four behaviours. → CONFORMING INTERPRETATION; closes HA-008.

**19. Strict credential file.** One line ended by a single LF or nothing (CRLF refused), exactly one
hard-link name, bytes read from the very file that was checked (`credential.py:90-117`). §7.5 "anything
else is refused" permits the strict reading; every refusal is a `CredentialProblem` whose only content is
an `AdapterFailure` code (no path, no content). `a11` confirms on NTFS with real ACLs and a real hard link.
→ STRICTER BUT SAFE.

**20. Loopback end-to-end CLI run.** The test itself contacts only 127.0.0.1 (the suite's audit hook
refuses anything else). But to make it possible, the **production** `run` command accepts `--connect
<loopback>` and `--ca-file`, so the live transport can be made to trust only an injected CA - and the
repository ships a private key for a certificate naming `api.oddspapi.io` under that CA (`a12`). §7.6 says
TLS "uses the system trust store"; §19 S7 says the self-signed CA is "injected for tests". The seam is
limited to loopback and requires the operator to type both flags, so no remote party can use it.
→ AUTHORITY AMBIGUITY → **HA-006** (LOW, confirmed).

**21. G-03 in a scratch registry.** The only READY row ever written is in a throwaway scratch registry
inside a test. → CONFORMING INTERPRETATION.

**22. Hardening tests added after `S7/RED.txt`.** They have no RED transcript; the implementer offers
mutation evidence instead. The audit's own mutants (`a15`) are the independent substitute.
→ CONFORMING INTERPRETATION.

**23. `S7/FROZEN.txt` wall time.** Not relied on; the frozen suite was re-run independently at `cfcff3d`
on Windows: 493 tests, OK (skipped=1), matching the S0 Windows baseline. → CONFORMING INTERPRETATION.

**24. Committed `adapter_tests/fixtures/tls/server.key`.** Test-only and unreachable from the pinned
production host path, but it matches a certificate for the real provider host, it ships in `git archive`
(no `export-ignore`), and secret scanners flag it. → AUTHORITY AMBIGUITY → **HA-006** (LOW).
