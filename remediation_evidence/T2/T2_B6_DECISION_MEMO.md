# T2 / B6 authority decision memo

Date: 2026-09-24 (Europe/London)

Sealed base: commit `d130c21668b769c371cfa4a4a75c3f382af1af71`,
tree `15253d9c3b8e474509e05d43f10db04b7b949b4a`.

Scope: B6 only. This memo neither changes ADR-0002 nor approves a strategy,
model, tier rule, expiry rule, adapter, protected campaign, shadow-research
campaign, or live-money path.

## Exact construction failure

ADR-0002's approved `StrategyOutputRuleBinding-v1` preimage contains the
nonempty `human_approval_reference` field. Production computes:

`B = SHA256(canonical_json(StrategyOutputRuleBinding-v1 containing R))`.

The current validator additionally constrains `R` to be the raw SHA-256
content hash of this exact separate note:

`{domain=genesis.strategy-output-approval.v1,
schema_version=strategy-output-approval-v1, binding_hash=B, approved_by,
approved_at, scope=PAPER}`.

Consequently `R = SHA256(canonical_json(note containing B))` while `B`
already depends on `R`. The original hostile probe proves an ordinary
sequential construction fails: its pre-approval binding is
`64d8935e55f58e11c1b9d4644e4cf7dda8b0bd82d0a987527678bebf6595b842`,
the resulting approval hash is
`6ad9b663645b4dc90bc2fbd75d005c0a45c42b8aa81645fd9c8a0b69c257bd67`,
and placing that reference in the binding changes the final binding hash to
`8b5afa9cab3a0178144ae44d7566fc6f004026f59d9f2877aecd484848f56324`.
The real validator rejects it. See `ORIGINAL_B6_RED_T1.txt`.

## Governing authority and classification

ADR-0002 v1, approved at SHA-256
`7e851df9898f3a257a87b602bc1a7f6011ebae1397d42c17b8727c84e554ae00`,
requires a nonempty operator-owned human approval reference in the unchanged
binding preimage and a separately approved exact binding. It does not require
that reference to equal the content hash of a note that contains the final
binding hash. It also requires closed, versioned schemas, immutable history,
fail-closed resolution, and preservation of all v1/v2/v3 identities.

Classification: **B — compatible versioned schema/interface evolution**,
implementing the already-authorized approval boundary without altering the
approved binding contract. No new ADR or human decision is required for this
plumbing repair. Every real strategy binding still requires a separate actual
human grant; this repair supplies no such grant.

A class-C decision would be required to remove the approval reference from
the binding preimage, change any binding/candidate/output hash algorithm,
reinterpret an existing reference, accept caller self-approval, or change
economic/operational policy. None of those actions is proposed.

## Smallest acyclic construction

Preserve the historical raw-64-hex `strategy-output-approval-v1` file-note
path and its byte/content-hash meaning unchanged. Add a disjoint versioned
reference namespace:

`strategy-output-approval-v2:<reservation-record-hash>`.

An operator-owned append-only approval ledger performs three explicit acts:

1. `strategy_output_approval_reference_reserved` records a closed
   `strategy-output-approval-reference-v2` request with an operator request
   ID, reserving operator identity, canonical time, and `scope=PAPER`. Its
   hash-chained record hash becomes the stable reference suffix.
2. The unchanged binding v1 body includes that stable reference and is then
   hashed by the existing `rule_binding_hash()` algorithm.
3. After human review of the final exact binding, a closed
   `strategy-output-approval-v2` grant binds that reference to the final
   binding hash, approver, approval time, and `scope=PAPER`. A closed revocation
   event can revoke the exact reference/binding pair.

Resolution accepts exactly one valid reservation and one matching grant,
rejects unknown, malformed, conflicting, tampered, future-dated, wrong-scope,
wrong-binding, or revoked history, and runs under the ledger lock whenever it
can authorize qualification, risk, pending submission, or send. Exact replay
is idempotent; conflicting concurrent publication fails closed. The ledger
record hashes provide immutable integrity without placing the final binding
hash into the reference's own preimage.

## Expected production surface

- `src/genesis/decision_output.py`: versioned approval ledger, strict replay,
  legacy-v1/new-v2 dispatch in the real validator.
- `src/genesis/selection.py`: own the approval ledger and include it in
  qualification proof locking.
- `src/genesis/risk.py`: include approval authority in risk approval and
  consumption locking.
- `src/genesis/execution.py`: include approval authority in intent,
  recertification, pending and send locking.
- `tests/test_astra_t2_b6_approval.py`: independent hostile/positive,
  replay/restart/concurrency and historical-identity tests.
- state/evidence documents and `remediation_evidence/T2` only.

No ADR content, candidate identity implementation, output/binding preimage,
stake/odds/risk/quota law, or protected-process implementation is changed.

## RED to GREEN matrix

| Invariant | Sealed-T1 RED | Required GREEN |
|---|---|---|
| Ordinary separate approval is constructible | Original Astra B6 assertion fails | Reserve -> bind -> grant -> real unmodified validator accepts |
| Exact authority | No acyclic production owner | Missing/wrong/tampered/future/wrong-scope grant rejects |
| Binding lineage | Cycle prevents positive proof | Wrong-binding and reference substitution reject |
| Revocation | No constructible approved lineage | Exact revocation blocks all later authorization |
| Replay/restart | Synthetic overrides only | Exact reserve/grant replay is stable across fresh store instances |
| Concurrency | No genuine publication path | Same request/grant is idempotent; conflicting grants serialize/fail closed |
| Operational boundary | No real authority exists | Absence of a real strategy grant/resolver/rules remains blocked |
| Historical identity | Current meanings frozen | Golden v1/v2/v3 candidate and binding/output hashes remain identical |
| Cross-store stability | Approval ledger absent from fences | Qualification/risk/order reads lock the approval ledger through append |

## Invariants that remain untouched

- `StrategyOutputRuleBinding-v1` fields and `rule_binding_hash()` bytes.
- `DecisionOutput-v1`, `candidate-v1`, `candidate-v2`, `candidate-v3`, and
  qualification identity meanings and all persisted historical hashes.
- one candidate hash / one intent; one risk approval / one consumption.
- PAPER-only scope, no automatic retry on UNKNOWN, hold-to-settlement,
  existing odds/stake/risk percentages, quota Interpretation A, and safety,
  kill, refresh, expiry, strategy-withdrawal and current-market checks.
- fail-closed operational qualification until separately approved exact
  strategy-specific model, calibration, tier and expiry authorities exist.
- no adapter, shadow-research, protected-campaign, or live-money GO.
