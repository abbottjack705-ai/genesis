# T1 final diff and policy review

Date: 2026-09-24
Pre-fix base: `27dd525c1fd7d531c4833c4bf7e44204a9345f19`

## Scope review

The production change is confined to:

- `src/genesis/registry.py`: fresh durable strategy heads and global ordered
  coordinator acquisition;
- `src/genesis/risk.py`: trusted-output dependence, current portfolio checks,
  durable strategy/PAPER-mode gates and proof-bound release replay;
- `src/genesis/execution.py`: fenced strategy/mode/risk/market/refresh
  recertification at pending and sent;
- `src/genesis/release_proof.py`: exact synthetic PAPER release proofs and the
  separate legacy-v2 audit-settlement-only proof.

No source/sport/venue adapter, provider call, network client, credential,
strategy formula, calibration, tier cutoff, expiry TTL, protected campaign,
shadow-research path or live-money path was added.

## Authority and identity review

`git diff --quiet` returned 0 for Project Laws, Project Genesis,
decision/risk policy, `DECISIONS/` and `config/`. No frozen authority or
approved policy file changed.

Historical identity owners are byte-identical to the S5 base:

| File | S5 Git blob | T1 Git blob before commit |
|---|---|---|
| `src/genesis/decision.py` | `58487969f2690a3290db72b37d93c34ac91f1a4e` | `58487969f2690a3290db72b37d93c34ac91f1a4e` |
| `src/genesis/selection.py` | `67402fae070d0853bd77e82db44bdd5933b61fde` | `67402fae070d0853bd77e82db44bdd5933b61fde` |

Thus candidate-v1/v2/v3 constructors and qualification-record identity
semantics are unchanged. The v2 compatibility repair uses new, separate
`offline-paper-legacy-release-proof-v1` and
`risk-reservation-legacy-release-v1` schemas. It binds the exact existing v2
qualification row hash and contains no `decision_output_hash`; it is accepted
only for an already consumed, sent/matched, terminal synthetic PAPER order.

## Concurrency and fail-closed review

- All JSONL coordinator paths, including the primary append target, are now
  acquired in one case-normalized global order. This prevents risk-release /
  order-send lock inversion while retaining every lock through fsync and the
  checked append.
- Missing, swapped or partial strategy/mode/release authority owners fail
  closed. A caller boolean, timestamp, terminal enum or correlation omission
  is not authority.
- Current capacity includes every factual open exposure and the exact current
  reservation once. Existing over-limit exposure is retained; it blocks a new
  action rather than being rewritten.
- A release row creates capacity only while its exact proof still validates
  against the complete current order/fill/settlement heads. Late fills or
  incompatible lineage restore UNKNOWN/full charge on replay.

## Retained-test review

A zero-context assertion-removal scan found only two removed assertion lines:

1. the S1 restart assertion was re-emitted with the proof-bearing action time
   after constructing the exact release owner, and its intent remains unchanged;
2. the registry replay assertion changed only from private stale cache
   `_latest[...]` to public fresh `current_head(...)`, retaining the exact
   expected `EXPLORATION` value.

Every terminal fixture edit and its original invariant is documented in
`RETAINED_S1_RECONCILIATION.md`, `RETAINED_TERMINAL_RECONCILIATION.md`,
`RETAINED_POST_T1_RECONCILIATION.md` and
`RETAINED_STRATEGY_HEAD_RECONCILIATION.md`. The rejected first attempt,
pre-change blobs, exact patches and transcripts remain in this evidence
directory. No assertion was deleted, inverted, bypassed or weakened to make
the suite green.

Raw `.txt` transcripts and preserved `.patch` artifacts intentionally retain
their exact source whitespace. The repository's new `.gitattributes` rule
disables only the trailing-space diagnostic for those two formats under
`remediation_evidence/T1/`; code and authored Markdown remain under the normal
strict whitespace check.

## Final diff result

`git diff --check` exited 0. Git printed only the repository's expected
LF-to-CRLF working-copy notices. The retained 196-test gate and full 266-test
gate prove no known R0–R10 or S1–S5 regression was lost. B4/B5/B6/B8 were not
implemented and remain HOLD.
