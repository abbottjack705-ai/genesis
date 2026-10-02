# MUTATION_REVIEW — implementer's mutation claim, the claimed-equivalent survivor, remediation mutants

**Status: NOT VERIFIED.** The candidate b22263e, its mutation tooling and the mutant list are unreachable
(RA-000). The claimed-equivalent survivor **cannot be examined**, so it is **not accepted as equivalent**.

This document fixes four things:

- the standard any equivalence claim must meet;
- the remediation-area mutants that must be killed;
- the policy on timeouts;
- an independent, self-tested tool (`reaudit/mutate_sites.py`) that mutates exactly the remediation diff.

## 1. The claim under review

> 128 mutants; 127 killed; 1 claimed equivalent. One sleep-contaminated R3 timeout was independently rerun
> and killed in 91 seconds.

| Element | Status | Why it matters |
| --- | --- | --- |
| 128 / 127 / 1 | NOT VERIFIED | The counts mean nothing without the mutant list and where it sits relative to the remediation diff `cfcff3d..b22263e`. 128 mutants over the slice is small next to a 690-test suite. The question is whether every *changed predicate* carries one (§4). |
| "1 equivalent" | NOT ACCEPTED | §2 standard not demonstrated to this auditor. |
| "R3 timeout … rerun … killed in 91 s" | NOT ACCEPTED as evidence of test quality without the rerun's failing-test names | See §3. "Sleep-contaminated" also signals real waits in a test or in production code near the R3 (reset-authority) surface. The driver flags every production `sleep()` call for review (R04). |

## 2. Standard for accepting "equivalent"

A survivor is equivalent only if **no valid input**, in **any reachable state**, produces a different
**observable** effect. For this codebase "observable" is not only a return value. It includes:

1. every **durable byte**: ledger rows, evidence objects, quarantine metadata, PIT records, coverage
   entries, the canonical request file;
2. the **order** of durable writes (crash windows, §11.1 "each step durable before the next");
3. **time**: what is compared with what at equality. Boundary instants include `Tq`, `T0`, `T1`, `T3`,
   `valid_to`, the deadline, W1–W4 edges, `S − prematch_guard_seconds` and `T_inv`;
4. **exceptions**: class, chained context, and whether a process-control exception still reaches top level;
5. **restart behaviour**: what a fresh runtime does with the state the mutant left;
6. **number of sends and debits**.

An equivalence argument must therefore cover:

- (a) a proof over the input domain, including equality and ±1 µs at every time comparison;
- (b) the crash points on either side of the mutated line;
- (c) the restart path.

"No test fails" is not an argument. A survivor on a time or boundary comparison is presumed **not**
equivalent: an equality input can almost always be constructed with a fixed clock.

**The decision rule this auditor will apply when the survivor is visible:**

1. Write the narrowest input that would distinguish it. That is a test against the original; it must pass.
2. Run that input on the mutant.
3. Equivalence is accepted only if a reasoned search of (a)–(c) finds no such input, written down with the
   mutated line, the operator and the argument.

## 3. Timeouts are not kills (demonstrated)

`reaudit/selftest/selftest_mutate_sites.py` (transcript `evidence/selftest_mutate_sites.txt`) builds a
polling loop of the deadline kind:

```python
while True:
    t = clock()
    if t >= deadline:
        return t
```

The mutant `>=` → `>`, with a clock that stalls exactly at the deadline, does not fail an assertion. It
**hangs** (`D011 TIMEOUT`). A campaign that scores that as "killed by timeout" reports a test that asserts
nothing about the equality case. The suite never checked that the loop exits at `t == deadline`; it only
failed to finish.

For a clock, deadline, guard or sleep site, a timeout-kill shows only that something changed. It does not
show that the property is tested.

**Policy for this re-audit:**

- a mutant on a time, deadline, guard, retry or sleep site counts as **killed** only if a **named test
  fails with an assertion** within the timeout;
- `TIMEOUT` is reported separately and requires a new assertion-based test;
- `KILLED_IMPORT` (non-zero exit with no failing test named) is a weak kill and is listed.

The R3 rerun "killed in 91 seconds" must show the failing test name and assertion to count.

## 4. Remediation-area mutants that must be killed (assertion-based)

These are generated mechanically by `mutate_sites.py` over the lines changed in `cfcff3d..b22263e`
(comparison swaps, and↔or, `not` removal, `if`/`while` negation, `return` True↔False, `raise` deletion,
guard-call deletion). The following **must** appear among them, and each must be killed by a named test:

| Area (request) | Mutant (at the remediated line) | Must be killed by |
| --- | --- | --- |
| Deadline comparison (CB-2) | `now < deadline` → `<=`; `>= deadline` → `>`; T0 read moved before connect; timeout clamp `max(0, remaining)` with no refusal | BND-04 at equality and +1 µs at connect, write, read-head and read-body (p20 D1–D4 shape) |
| Deadline binding | `deadline = Tq + timeout` → `T0 + timeout` / `now + timeout` | runner-level check that `deadline_at == Tq + request_timeout_seconds` (p20 D5) |
| Restart refusal state (CB-3) | the terminal-state check for REJECTED / QUARANTINED / HALTED attempts in `resume()` negated or deleted; status/skew/content-type re-check on resume deleted | crash after `completed` for each rejection class, carrying a **valid** odds body (p21 R1–R4) |
| READY time source (CO-4) | trusted clock replaced by a record or argument value; floor check `recorded_at >= granted_at` negated | p25 A2–A5, a13 |
| Reset authorization (CO-5) | `fingerprint_new != fingerprint_halted` → `==`; `g1.granted_at > halt_at` → `>=`, `<`; the G1 lookup deleted | p25 R1–R6 (both halt kinds) |
| Completeness / ABSENT (CO-2) | a per-tournament completeness check negated or deleted; the ABSENT emission guard inverted | p24 T1 **and** T2 (both directions; an over-correction must be killed too) |
| Derivation verification | byte-equality `==` → `!=`; `derivation_kind` dispatch default changed from failure to pass; the INVALIDATION ledger-prefix check deleted | INV-03, EV-03, PIT-09 |
| Invalidation recovery (CB-5) | the pending-invalidation completion in `resume()` deleted; the head test `R is target` inverted | p22 I1–I5 |
| PIT recovery (CB-4) | resume reuse lookup "exactly one observation" `== 1` → `>= 1`; `record_id` key changed to the observation | PIT-08, crash C09–C13 |
| Credential paths (CB-1) | each secret-scan call before a durable write deleted; a detection form removed | SEC-01…05, REQ-04, TX-01, a06 |
| Gate limits (CO-3/CO-7) | the pinned-digest comparison of the limits file negated; the G2R `plan_digest` comparison deleted | p25 L1–L2, a14 |

## 5. Independent tool

`reaudit/mutate_sites.py` refuses a dirty or wrong checkout. It mutates **only lines changed by the
remediation**, restores the file byte-for-byte after every run, and classifies each mutant as `KILLED`,
`KILLED_IMPORT`, `SURVIVED`, `TIMEOUT` or `INVALID`, with the failing test names.

The self-test passes 7/7 expectations:

| Mutant | Result |
| --- | --- |
| deadline `<` → `<=` | KILLED |
| all eight reset-authority mutants | KILLED |
| polling `>=` → `>` | **TIMEOUT** |
| an equivalent site | **SURVIVED** (correctly) |

The self-test also shows that unchanged lines are untouched and the checkout is restored.

Command (step 5 of `run_all.sh`; run alone on the host, it takes hours):

```text
python reaudit/mutate_sites.py --repo <clean b22263e clone> --base cfcff3dbb285eaa48a6cfc1eceedb91e27662c81 \
  --head b22263e --paths adapters/src \
  --test-cmd "python -B -m unittest discover -s adapters/adapter_tests -t adapters" --timeout 1800 \
  --out mutants.json
```

Acceptance for GREEN:

- every mutant in §4 is present and `KILLED` (assertion-based);
- every `SURVIVED` mutant has a §2 equivalence argument accepted by the auditor;
- no `TIMEOUT` mutant remains without a new assertion-based test;
- the implementer's claimed-equivalent survivor is re-derived and either killed by a new test or accepted
  under §2.
