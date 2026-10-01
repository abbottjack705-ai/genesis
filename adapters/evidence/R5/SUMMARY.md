# V0.5 slice-1 hostile-audit remediation R5 - operator times and security resets

| | |
| --- | --- |
| Failed candidate (unchanged) | `cfcff3dbb285eaa48a6cfc1eceedb91e27662c81` |
| Base of this commit | R4 `2e1fb27cfe9f8eb41000b24e8d5108822757c8cd` |
| Architecture authority | `c8dfafdff3be611fa6255a03ed361bc46d7ad8fe` (`V05_ADAPTER_ARCHITECTURE.md` r3) |
| Controlling audit | `C:\Users\abbot\a8\v05_prep\audit_oracle\hostile_audit_cfcff3d\` (manifest 10/10 OK; never written to) |
| Parallel audit (read-only) | `C:\Users\abbot\ha\audit\audit\v05_slice1_hostile\` (37b86fb): HA-013 (MEDIUM), HA-014 (LOW) - here P:HA-013, P:HA-014 |
| Commit | the commit that adds this file, on `v05-slice1-impl` on top of R4 (not amended; not pushed) |

Everything is under `adapters/`; the six frozen trees are unchanged. No credential, no provider or network contact,
no gate record outside throwaway test roots, no G2, no READY capability outside throwaway test registries.

## Method

1. `RED.txt` - the R5 tests (`test_v05_r5_operator.py`) and the updated `test_v05_authority.py` against the
   **unmodified R4 production code**: 25 tests, failures=7, errors=3 (approve keeps a back-dated `granted_at`;
   approve-ready uses the operator's `--at`; no `anchor_unknown`; resets clear SECRET_ECHO / AUTH_REJECTED without a
   new G1). Two tests were added after this capture to cover mutants (the approval clock's floor; a G3 granted
   before / at / after the trusted reading); they run in `GREEN.txt` and `MUTATION.txt`.
2. The production changes below, then `GREEN.txt`, `MUTATION.txt`, `FROZEN.txt` + `FROZEN_COMPARE.txt`,
   `COMPILE.txt`, `DIFFCHECK.txt`, `TREES.txt`, `GUARDS.txt`; `HASHES.sha256` covers them.

## Finding by finding

### P:HA-013 (MEDIUM) - no operator-chosen time can make READY or a gate retroactively valid

Authority: design 16.2 (`granted_at` from the trusted clock), 16.4 (during G2R market-book sources are UNKNOWN),
16.5 (`SourceCapability(..., READY, recorded_at=now)`), 13.1 / 13.2 (history at an earlier cutoff never changes).

- `cli.py approve`: `granted_at` is the trusted clock's reading at approval (`SystemUtcClock`, floored at the
  ledger's latest `granted_at`; a clock behind it refuses). A record file that states a `granted_at` more than
  `clock_skew_max_seconds` from that reading, or one that is not a time, is refused; a stated time within the bound
  is overwritten by the reading.
- `cli.py approve-ready`: the `--at` option is gone. The G3 record is checked at the trusted clock's reading, which
  is floored at the source's latest capability row, and the READY row is recorded at that reading. A capture made
  before the approval is therefore not usable at any cutoff before it - tested before / just before / at / after
  the approval cutoff, and with a G3 granted after / at / before the reading.
- `cli.py run --mode G2R` (the only G2R entry point) first registers the running source `UNKNOWN` with
  `point_in_time_reliability = "unverified"` when it has no capability row yet (`capability.anchor_unknown`, via the
  existing `register_downgrade`), so the frozen registry's monotonic `recorded_at` refuses any later READY row
  dated before the recurring capture began. The fixture pipeline is not G2R and registers nothing.

### P:HA-014 (LOW) - a reset never clears a security halt without the re-approval the design requires

Authority: design 7.6 ("for SECRET_ECHO ... a human must rotate the key (re-G1)"), 14.3 (401/403: "a human must
re-approve (G1 re-check)"). `cli.py reset` refuses (nothing written) while any `SECRET_ECHO` halt in the
acquisition ledger lacks a G1 record granted after it for a key that **no G1 granted at or before the halt
named** - no send records which G1 authorized it, and a gate is valid only from its `granted_at`, so the echoed key
is among those; re-approving any of them is not a rotation (fail closed) - or while any `AUTH_REJECTED` circuit
lacks a G1 record granted after it. Every such halt in the ledger is checked; one that was resolved stays resolved,
as gate records are only ever added. Other halts reset as before; a `CLOCK_SKEW` suspension is never cleared by a
reset (R3).

## Test changes (disclosed)

- New `test_v05_r5_operator.py`. Its trusted clock is the real `SystemUtcClock` class with every check intact,
  reading a fixed wall time, so the cases are deterministic on any day.
- `test_v05_authority.py`: G-03 approves READY without a time argument after a G3 granted a minute before the real
  clock (the old case passed an operator time); the AUTH_REJECTED reset case grants the re-approval G1 the design
  requires before resetting.

## Results

- `GREEN.txt`: complete adapter suite - Ran 690, OK, skipped=1 (`test_f04_a_link_is_refused`: no symlink privilege;
  real-symlink certification stays OPEN, see R1).
- `FROZEN.txt` / `FROZEN_COMPARE.txt`: frozen V0.4 suite - Ran 493, OK, skipped=1 - IDENTICAL to the recorded baseline.
- `TREES.txt`, `GUARDS.txt`: the six tree SHAs at HEAD, no frozen path changed or dirty, freeze and module-provenance
  guards PASS. `COMPILE.txt`, `DIFFCHECK.txt`: clean.
- `MUTATION.txt`: 17 distinct mutants over 2 files (`cli.py` 16, `capability.py` 1): 17 KILLED, none survived. (Each
  mutant appears twice: once as it runs, once in the per-file summary.)
- `A13_ADAPTED.txt`: the parallel audit's `attacks/a13_ready_backdate.py`, run from a scratch copy with one disclosed
  adaptation (R4 made the derivation verifier a required argument): 5 checks, 4 PASS, 1 FAIL. PASS: the handoff's
  HA-014 acceptance check (a SECRET_ECHO reset is refused without a rotated-key G1), the back-dated `granted_at`,
  READY at an operator time, and the consequence check (a cutoff between capture and approval is not usable).
  FAIL by construction: "a G2R-style capture leaves an UNKNOWN row" - the attack captures through the offline fixture
  pipeline, which is not a G2R run and registers no capability rows; R5 registers UNKNOWN at the start of
  `cli.py run --mode G2R`, where design 16.4 and the handoff place it (covered by
  `test_p013_a_g2r_cli_start_anchors_the_running_source_unknown_once`). This is a remediation-side run, not an audit
  verdict.
- Evidence secret sweep: `oracle_secret_sweep.py adapters/evidence/R5` - 166 sentinel forms, unexpected=0.
