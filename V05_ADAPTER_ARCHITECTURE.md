# V0.5 read-only adapter architecture — slice 1 implementation handoff

| Field | Value |
| --- | --- |
| Status | **DESIGN — implementation-ready, not implemented.** No production code accompanies this document. |
| Baseline (immutable) | tag `v0.4-foundation-freeze` → commit `2278e2a68083f7ac58d796b1ed9c43d50020b6b0` (docs-only child of certified executable baseline `4f11606615c7650f3bd74c7ccf5d2fb7a5a753c5`) |
| Branch | `v0.5-adapters` (at `2278e2a` when this was written) |
| Date | 2026-09-28 |
| Scope | First read-only source adapter + first sport adapter + first market subset, as an additive layer on the frozen foundation |
| Operating mode | Offline / paper only. No betting, no order path, no strategy activation, no model or selection logic |
| Audience | The implementing model (Section 18 is the copy-paste prompt) and the reviewing human/auditor |

Everything in this document is a design decision unless it is marked **FACT**
with a source. Where the repository already settles something, this document
cites it rather than re-deciding it. Where it does not, this document makes one
recommendation and records it in Section 17.

---

## 1. Current-state findings

### 1.1 Baseline verification (performed 2026-09-28)

| Check | Result |
| --- | --- |
| Repository | `https://github.com/abbottjack705-ai/genesis.git`, clone `C:\Users\abbot\fz\g` (`core.autocrlf=false`) |
| `git rev-parse v0.4-foundation-freeze^{commit}` | `2278e2a68083f7ac58d796b1ed9c43d50020b6b0` (annotated tag object `a5ca3c96…`, identical on `origin`) |
| Branch/HEAD | `v0.5-adapters` → `2278e2a`, tracking `origin/v0.5-adapters`, clean |
| Relationship | `4f11606` is an ancestor of `2278e2a`; `v0.5-adapters` == tag == freeze commit; no adapter commits yet |
| Frozen tree IDs at `4f11606` and `2278e2a` | identical: `src 51cb635b…`, `tests e90b2981…`, `config abd22db0…`, `tools a0e3411e…`, `DECISIONS cc97ec6f…`, `v04_pack 3c3c1c27…` |
| Runtime | Python 3.12.10, stdlib-only project (`requirements.lock` empty; `pyproject.toml` `dependencies = []`) |
| Default discovery | `python -m unittest discover -s tests -t . -v` — 493 tests, 492 pass, 1 skip (platform symlink case) at the freeze |

`V04_FOUNDATION_FREEZE.md` says the adapter branch is "cut from `4f11606`". It was
actually cut from `2278e2a`, a documentation-only child with byte-identical
executable trees. That is equivalent for every purpose in this document.

**Can adapter development proceed additively? Yes.** Every capability that slice 1
needs is either already provided by a frozen public interface (evidence store,
source contracts, PIT store, capability registry, quota ledger, verified cache,
coverage ledger, audit logger, canonical helpers) or can be built beside the
foundation in a new package without editing any frozen file. Section 16 lists
the three foundation interface *extensions* that later slices will need; none is
required for slice 1.

### 1.2 Frozen foundation components the adapter layer consumes

| Frozen component | What it already guarantees | How slice 1 uses it |
| --- | --- | --- |
| `genesis.time` (`parse_utc`, `iso_utc`) | Aware UTC only; naive and non-UTC offsets fail closed (`time.py:17-30`) | Every timestamp enters and leaves through these two functions |
| `genesis.repro` (`canonical_json`, `sha256_bytes`, `immutable_write`, `tree_digest`) | One deterministic JSON encoding; content-addressed, write-once publication (`repro.py:17-93`) | Hashing, identities, immutable run reports, code identity |
| `genesis.registry.AppendOnlyJsonl`, `RegistryConflict` | Hash-chained JSONL; cross-process verified read/check/append/fsync; exact-JSON rows; single-name files (`registry.py:123-322`) | Acquisition ledger, identity registry |
| `genesis.provenance` (`SourceContract`, `SourceContractRegistry`, `AvailabilityClass`, `ProvenanceRef`) | Append-only immutable source contracts; decision-usable availability classes | Raw (`prospective_captured`) and normalized (`derived`) contracts |
| `genesis.evidence.EvidenceStore` | Content-addressed raw objects + contract-validated, append-only observations whose ID covers retrieval/ready times (`evidence.py:110-324`) | Raw provider bytes; normalized snapshot documents |
| `genesis.pit` (`SourceCapabilityRegistry`, `BitemporalRecord`, `PITStore`) | Bitemporal admissibility (`available/retrieved/ready ≤ T`, validity, supersession) and capability-at-T gating (`pit.py:134-278`) | PIT index rows for events, book-markets and listing scopes |
| `genesis.feature_manifest` (`SourceInputBindingStore`, `FeatureInputManifestStore`) | One-to-one approved source↔contract binding; exact decision inputs verified against observation bytes and the unique PIT head (`feature_manifest.py:58-303`) | Bootstrap binding; slice-1 compatibility test proves adapter output is consumable unchanged |
| `genesis.quota` (`QuotaPolicy`, `QuotaLedger`, `VerifiedCacheStore`, `CacheReference`) | Approved Interpretation A for OddsPapi (250/220/30/7), atomic daily/monthly/reserve accounting, content-addressed cache proof re-verified on replay (`quota.py:39-1229`) | Every billable provider call and every cache hit |
| `genesis.coverage` (`CoverageLedger`, `CoverageEntry`, `CoverageStatus`) | Append-only coverage/exclusion telemetry; non-available entries need reason codes | Per-event coverage outcome |
| `genesis.reasons.ReasonCode` | Stable coarse reason taxonomy | Coarse mapping target for adapter failure codes |
| `genesis.logging` (`JsonlAuditLogger`, `LogEvent`) | Structured append-only operational events with key redaction | Telemetry events |
| `genesis.canonical` (`stable_id`, `Event`, `Participant`, `MarketSnapshot`, `MarketSide`) | Minimal frozen canonical schemas | ID minting helper; projection targets for downstream consumers |

### 1.3 Findings that shape the design

- **F1 — The quota authority is hard-bound to OddsPapi.** `QuotaPolicy.require_operational`
  refuses any active policy whose `provider_id` is not `"oddspapi"` or whose
  numbers are not exactly `(250, 220, 30, 7)` (`quota.py:170-187`; active config
  `config/oddspapi_quota_policy_v2.json`, approval `D-REM-001`). A different
  first provider could not be quota-governed operationally without a foundation
  interface extension.
- **F2 — Decision inputs are read from exact observation bytes by dict-only JSON
  paths.** `FeatureInputManifestStore.verify_for_pack` requires the PIT row's
  `payload_hash` to equal the observation's `artifact_hash`, requires that row to be
  the *unique* as-of head of its `(entity_id, source_id)` scope, and reads features
  with `field_id` `"$.a.b.c"` split on `.` over dict keys only (`feature_manifest.py:261-292`).
  Normalized documents must therefore be JSON objects keyed by dot-free IDs (no
  lists on any feature path), and each PIT scope must have unique `valid_from` values.
- **F3 — Contract, parser version and PIT source are locked together.** An observation's
  `parser_version` must equal its contract's (`evidence.py:139-147`) and
  `SourceInputBindingStore` is one-to-one between `source_id` and `source_contract_id`
  (`feature_manifest.py:79-93`). A normalizer version bump is therefore a new
  contract *and* a new PIT source. That is desirable: old and new projections can
  never compete for the same PIT head.
- **F4 — PIT ordering compares timestamp strings.** `PITStore.as_of_query` sorts on
  `record.valid_from` as a string (`pit.py:262`). Every PIT timestamp must be written
  through `iso_utc` (fixed-width microsecond `…Z` form) so lexical order equals
  chronological order.
- **F5 — Every append/read re-verifies the whole log.** `AppendOnlyJsonl` reads and
  hash-verifies every row on each transaction and read (`registry.py:143-157, 195-270`);
  `PITStore` replays its log on every query. Log size must be bounded by
  entity-stable partitioning (Section 7.3).
- **F6 — Stdlib only.** `requirements.lock` is empty and pinned by digest in
  `config/defaults.json` (`config.py:load_config`). Adding a third-party package would
  change a frozen pin. Transport uses `urllib.request`; property tests use seeded
  `random`, not Hypothesis.
- **F7 — Adapter code must not live inside the `genesis` package.** The protected
  research worker integrity-checks *every loaded `genesis.*` module* and exposes a
  narrow `genesis` import allowlist to research code (`protected_research_worker.py:217-259`).
  A sibling top-level package keeps adapter code outside that scope entirely,
  unreachable by research code, and lets the gate "`src/genesis` tree ID unchanged"
  be checked mechanically.
- **F8 — Writer-declared times are a carried residual.** Quota/ingestion/lifecycle
  times are declared by the writer; a writer could future-date a quota window
  (`V04_FOUNDATION_FREEZE.md`, residual "Declared-time quota"). The adapter layer
  must stamp every time it writes from a clock it does not let callers control.
- **F9 — Cache bytes are permanent.** Every persisted `quota_verified_cache_hit` is
  re-resolved against `VerifiedCacheStore` bytes whenever the ledger replays
  (`quota.py:755-776`). Cache objects can never be garbage-collected.
- **F10 — `ReasonCode` is frozen and coarse.** Adapter-level failure codes are a new
  adapter-local enum, mapped to the nearest `ReasonCode` wherever a frozen
  component (the coverage ledger) needs one.
- **F11 — Non-UTC timestamps fail closed.** `parse_utc` rejects non-zero offsets
  (`time.py:28`) and `SOURCE_AVAILABILITY.md` rule 2 requires the same. A provider
  timestamp with a non-UTC offset is treated as schema drift and rejected, not converted.
- **F12 — Frozen canonical types exist but are minimal.** `genesis.canonical.Event`,
  `Participant` and `MarketSnapshot` carry no market-family, bookmaker or
  provider-identity structure. The adapter defines richer records and provides tested
  projections *into* the frozen types, instead of editing them.
- **F13 — Test discovery.** The default command discovers any `test*.py` under
  `tests/`, including sub-packages. Adapter tests go in `tests/adapters/`. The live
  smoke runner is a package CLI module, not a `test*.py` file.
- **F14 — OddsPapi facts (public docs, 2026-09; re-verify before operational use).**
  Host `https://api.oddspapi.io`; `apiKey` is a query parameter; free tier 250
  requests/month; "1 request = 1 call to a billable endpoint, regardless of the
  response"; `/v4/historical-odds` is not metered and `/v4/account` stays reachable
  after exhaustion (whether it is metered is unclear, so it is treated as metered); exhaustion returns HTTP 429 "Request limit
  exceeded"; per-endpoint cooldowns of 1000–2000 ms; `/v4/odds-by-tournaments`
  takes one `bookmaker` and a comma-separated `tournamentIds` list; payloads carry
  numeric `participant1Id/participant2Id`, `tournamentId`, `seasonId`, `statusId`
  (0 not started, 1 live, 2 finished, 3 cancelled), `startTime`, `updatedAt`, and
  per-outcome `price`, `active`, `changedAt` (µs precision, `+00:00`), `limit`;
  market `101` is "Full Time Result" (`1x2`, period `fulltime`, outcomes 101 "1",
  102 "X", 103 "2"); lines are separate market IDs carrying a `handicap` value;
  standard (non-player) markets file quotes under the synthetic player key `"0"`.
- **F15 — `GENESIS_AUTONOMOUS_PRODUCTION_SPEC.md` does not exist** in the repository
  or on this machine's user folders. It was not used. Its absence changes nothing
  below; if it exists elsewhere, reconcile it before slice 2.
- **F16 — No real source is active.** `SOURCE_AVAILABILITY.md`: "No external source is
  currently active." `PROJECT_STATE.md` and `HANDOFF.md`: adapters remain NO-GO until
  separately authorized; the freeze grants no external-API or credential GO. This
  design authorizes nothing. The live smoke (Section 12.6) is operator-invoked only.

---

## 2. Authoritative constraints

| # | Constraint | Source |
| --- | --- | --- |
| C1 | Baseline `v0.4-foundation-freeze` / `2278e2a` is immutable; no amend/rebase/rewrite at or before `4f11606` | `V04_FOUNDATION_FREEZE.md` |
| C2 | Offline/paper only; no live order path; `ACTIVATION_ENABLED` stays a guard | `V04_FOUNDATION_FREEZE.md`, `PROJECT_LAWS_v0.4.md` |
| C3 | Sport/source adapters may not submit orders, change risk caps, write the ledger, bypass PASS/gates, read protected labels, or change execution mode | `PROJECT_GENESIS_v0.4.md` §21 |
| C4 | A market is not "supported" merely because an API returns it; capabilities are separate facts; unknown → PASS | `PROJECT_GENESIS_v0.4.md` §23, `capabilities.py` |
| C5 | Source capability (status, PIT reliability, revision, coverage, quota, schema, entitlement) must be explicitly READY; unknown fails closed | `SOURCE_AVAILABILITY.md` rule 7, `pit.py:43-44` |
| C6 | A value is decision-usable only when available **and** ready by decision time; retrieval, publisher, parse-ready and decision times are separate | `SOURCE_AVAILABILITY.md` rules 1, 3 |
| C7 | Raw bytes are evidence; parsed projections are derived artifacts carrying raw hash and parser version | `SOURCE_AVAILABILITY.md` rule 4 |
| C8 | Corrections add records; they never replace | `SOURCE_AVAILABILITY.md` rule 5, `PROJECT_GENESIS_v0.4.md` §12-13 |
| C9 | Decision/model code reads through controlled `as_of_query`/`feature_view` only | `SOURCE_AVAILABILITY.md` rule 6 |
| C10 | OddsPapi: one legitimate allowance, ≤7 billable current-data calls/day, ≤220/month normal, ≥30 reserve; no key rotation; exhaustion blocks odds-dependent decisions; provider error → fail closed or verified fresh cache only | `PROJECT_LAWS_v0.4.md`, `ODDSPAPI_BUDGET_DRAFT.yaml`, `quota.py` |
| C11 | Provider terms must be re-verified before operational reliance; fees/limits are not project law | `PROJECT_GENESIS_v0.4.md` §25, §41 |
| C12 | Pre-profit cost ≤ £10/month; no mandatory paid dependency | `RUNTIME_AND_COST_TARGET_v0.4.md` |
| C13 | Any missing field, schema mismatch, timeout, unknown state, ambiguous identity or corruption → PASS/block, never qualification | `PROJECT_GENESIS_v0.4.md` §6.6 |
| C14 | LLMs do not set probabilities, stakes or override gates; research code holds no credentials | `PROJECT_GENESIS_v0.4.md` §14, §32 |
| C15 | Coding agents may autonomously build "adapters under fixed core contracts" but may not weaken PIT rules, evidence immutability, fail-closed PASS, or protected-invariant tests | `PROJECT_GENESIS_v0.4.md` §38 |
| C16 | Stdlib only; any dependency needs an exact version and documented reason | `requirements.lock`, `ASSUMPTIONS.md` |
| C17 | Trusted clock required before quota authority is extended to live provider calls | `ASSUMPTIONS.md`, freeze residuals |
| C18 | Strategy decision contracts pin `sport_adapter_version` | `registry.py:559-612` |

---

## 3. Adapter architecture

### 3.1 Layers

```text
                     operator CLI (bootstrap, live smoke, reports)       tests (FakeTransport)
                                        |                                       |
                                        v                                       v
+----------------------------------------------------------------------------------------+
| IngestionCoordinator (genesis_adapters.ingestion)                                      |
|  owns: run lock, clock stamps, plan execution order, persistence ordering, crash       |
|  recovery, breaker state, telemetry emission. Contains no provider or sport knowledge. |
+-----------+----------------------+-------------------------+---------------------------+
            |                      |                         |
            v                      v                         v
+-------------------+   +----------------------+   +------------------------------------+
| Acquisition       |   | SourceAdapter        |   | SportAdapter                       |
| (provider-neutral)|   | (one per provider)   |   | (one per sport x provider mapping) |
|  transport        |   |  endpoint catalog:   |   |  sport semantics (families,        |
|  rate gate        |   |   paths, params,     |   |   outcome codes, invariants)       |
|  quota gate       |<--|   costs, cooldowns,  |   |  provider->sport mapping tables    |
|  (QuotaLedger +   |   |   TTLs, auth place-  |   |  catalog drift checks              |
|   VerifiedCache)  |   |   ment, size caps    |   |  pure normalize(): provider-native |
|  acquisition      |   |  request building +  |   |   records -> canonical records +   |
|  ledger           |   |   redaction + hash   |   |   rejections                       |
+-------------------+   |  HTTP/error classes  |   +------------------------------------+
                        |  pure parse(): bytes |                    |
                        |   -> provider-native |                    v
                        |   records            |   +------------------------------------+
                        +----------------------+   | Canonical layer                    |
                                                    |  records + NormalizedSnapshot doc  |
                                                    |  (closed schema, canonical JSON)   |
                                                    |  projections to genesis.canonical  |
                                                    +------------------------------------+
                                                                     |
                                                                     v
+----------------------------------------------------------------------------------------+
| Evidence/ingestion boundary (genesis_adapters.evidence)                                |
|  raw EvidenceStore (prospective_captured) -> normalized EvidenceStore (derived)       |
|  -> PITStore rows (events, book-markets, listing scopes) -> CoverageLedger            |
|  provenance verifier; CanonicalReader (read-only as-of API)                            |
+----------------------------------------------------------------------------------------+
            | frozen foundation interfaces only (genesis.*), never modified
```

### 3.2 Responsibilities and prohibitions

**Source adapter** (`genesis_adapters.sources.<provider>`; slice 1: `oddspapi`)

- Owns: the endpoint catalog (paths, allowed/required params, metering, billable
  units, cooldown, cache TTL, max body size, retry policy, payload kind);
  deterministic request construction and the provider request hash; credential
  *placement* (which query parameter) but never the credential value;
  pagination rule (slice 1: none, and a pagination marker in a payload is drift);
  classification of HTTP status/transport errors into failure codes; pure parsing
  of raw bytes into typed provider-native records with provider IDs and provider
  timestamps preserved verbatim; per-field schema checks and drift detection.
- Declares, but does not execute, rate limits and quota costs. The provider-neutral
  acquisition layer executes them so a second provider reuses the mechanics.
- Must not contain: sport semantics, market-family meaning, canonical IDs,
  probabilities (model, implied or fair), betting decisions, staking, risk,
  ranking, or any read of the PIT store.

**Provider-neutral acquisition** (`genesis_adapters.acquisition`)

- Owns: the only network code (`transport.py`), cooldown enforcement, the quota
  gate over the frozen `QuotaLedger` + `VerifiedCacheStore`, the append-only
  acquisition ledger, credential lookup from the environment, the circuit breaker, and
  raw capture (status, allowlisted headers, exact body bytes, stamped times).
- Must not contain: parsing beyond size/encoding/status envelope checks.

**Sport adapter** (`genesis_adapters.sports.<sport>`; slice 1: `soccer`)

- Owns: sport semantics independent of provider (`semantics.py`: market families,
  outcome codes, selection invariants, price/overround sanity bounds, status
  meaning); a provider mapping table per provider (`oddspapi_map.py`: market/outcome
  ID ↔ family/outcome code, status ID ↔ event status, competition allowlist with
  expected catalog facts); catalog drift checks; the pure `normalize()` function.
- Must not contain: network or file IO, clock reads, strategy logic, candidate
  generation, model features, probabilities other than the explicitly-named raw
  implied probability (Section 4.8), or anything that ranks, filters for value, or
  recommends.

**Canonical layer** (`genesis_adapters.canonical`)

- Owns: canonical record dataclasses, the closed `NormalizedSnapshot` document
  schema and its validator, deterministic ID minting, and projections into
  `genesis.canonical` types.

**Evidence/ingestion boundary** (`genesis_adapters.evidence`)

- Owns: storage layout and partitioning; writing raw bytes and normalized documents
  through the frozen `EvidenceStore`; writing PIT index rows through the frozen
  `PITStore`; coverage entries through the frozen `CoverageLedger`; a provenance
  verifier that walks PIT row → normalized observation → document → raw
  observation → raw bytes and fails closed on any mismatch; and `CanonicalReader`,
  the read-only as-of API.
- Must not: overwrite, delete, compact or "heal" any stored object, row or file.

**Ingestion coordinator** (`genesis_adapters.ingestion`)

- Owns orchestration only: plan validation, the single-runner lock, stamping every
  time from the acquisition clock, the ordering of side effects, crash recovery,
  breaker decisions, and telemetry/run reports. It contains no provider- or
  sport-specific branches; it dispatches through registries of adapters.

### 3.3 One acquisition attempt, end to end

1. **Plan check.** Validate the plan against the endpoint catalog, the polling
   policy and the static budget (Section 9.4). An invalid plan aborts before any IO.
2. **Run lock.** Acquire the provider's single-runner lock (SQLite `BEGIN IMMEDIATE`
   held for the run; released automatically on process death).
3. **Clock gate.** `clock.now()`; refuse to run if any durable timestamp in the quota
   ledger or the current acquisition partition is later than `now + 120 s`
   (`CLOCK_DURABLE_AHEAD`).
4. **Breaker gate.** Replay breaker state from the acquisition ledger; an open breaker
   records `CIRCUIT_OPEN` and skips the attempt.
5. **Credential gate** (metered or credentialed endpoints): the secret must be present,
   otherwise `CREDENTIAL_MISSING`. This is checked *before* quota reservation so a
   misconfiguration never spends budget.
6. **Cooldown.** Wait until `last_call(endpoint) + cooldown_ms` has passed, using the
   injected sleeper.
7. **Attempt intent.** Stamp `quota_occurred_at`, derive `attempt_id` (Section 8.2),
   append `attempt_started` to the acquisition ledger.
8. **Quota/cache decision.** Look up the newest cache entry for the request hash in the
   acquisition ledger index; call `QuotaLedger.request(request_id=attempt_id,
   occurred_at=quota_occurred_at, billable_units=spec.billable_units,
   cache=CacheReference|None, provider_request_hash=…)`.
   - `verified_cache_hit` → append `attempt_finished(outcome=CACHE_HIT)`. **No new raw
     observation, no new normalized document, no PIT row.** The information is still
     as of the original capture.
   - any blocked reason → `attempt_finished(outcome=QUOTA_BLOCKED)`; stop the window.
   - `billable_call_reserved` → continue.
9. **HTTP.** Stamp `request_started_at`; transport sends the request (credential
   injected only here); stamp `received_at` after the full body is read (or
   `failed_at` on transport failure).
10. **Raw capture.** For every HTTP response (including error statuses), publish the
    exact body bytes to the raw `EvidenceStore` (`retrieved_at = first_seen_at =
    parse_ready_at = received_at`); then append `attempt_finished` with status, the
    header allowlist, body hash/length, `raw_observation_id` and latency. Transport
    failures append `attempt_finished` with the failure code and no raw observation.
    The one exception is `PayloadKind.ACCOUNT`: its body is parsed in memory into
    `AccountStatus` and discarded (Section 7.2).
11. **Clock witness.** Compare the HTTP `Date` header with `received_at`. If they
    disagree by more than 120 s → `CLOCK_DISAGREEMENT`: no ingestion, breaker opens
    until operator reset. Raw bytes stay preserved.
12. **Cache publish.** Only for HTTP 200 with a structurally valid envelope: publish
    the bytes to `VerifiedCacheStore` (`captured_at = received_at`, `expires_at =
    received_at + ttl`) and append `attempt_cached` with the `cache_entry_id`.
13. **Parse.** `source.parse(request, capture)` → typed provider payload or a
    response-level failure (`ingestion_rejected`).
14. **Ingestion intent.** Append `ingestion_started` pinning `normalizer_version`,
    `catalog_digest`, `identity_registry_head` and the metadata raw observations used.
15. **Normalize.** `sport.normalize(payload, ctx)` is a pure function: canonical
    records plus rejections.
16. **Identity append.** Append new identity mappings, `event_seen` changes and
    conflicts to the identity registry (idempotent).
17. **Normalized publish.** Stamp `derived_at`; publish the canonical document bytes to
    the normalized `EvidenceStore` (`retrieved_at = first_seen_at = received_at`,
    `parse_ready_at = derived_at`).
18. **PIT index.** For each event, book-market and listing scope in the document, stamp
    `indexed_at` and append one `BitemporalRecord` to its partition's `PITStore`.
19. **Coverage.** Append one coverage entry per event.
20. **Commit.** Append `ingestion_committed` (document hash and observation, PIT row
    count and digest, rejection digest, counts). Emit telemetry.

### 3.4 Change classification (every change this design proposes)

| Change | Class | Justification |
| --- | --- | --- |
| New top-level package `src/genesis_adapters/**` | ADDITIVE POST-FREEZE | Sibling of `genesis`; `src/genesis` tree ID stays identical |
| New tests `tests/adapters/**` (sub-package, fixtures, goldens) | ADDITIVE POST-FREEZE | New files only; no existing test file edited |
| Append one `.gitattributes` rule (`tests/adapters/fixtures/** -text`) | ADDITIVE POST-FREEZE | Append-only; existing lines byte-identical; pins golden fixture bytes on `autocrlf=true` checkouts |
| New `DECISIONS/ADR-0005-v05-read-only-adapter-boundary.md` (PROPOSED) | ADDITIVE POST-FREEZE | New file; existing ADRs untouched; approval is a separate human note |
| New `remediation_evidence/V05/slice1/**` | ADDITIVE POST-FREEZE | Evidence convention of T1–T6 |
| Additive sections in root docs (`PROJECT_STATE.md`, `ARCHITECTURE.md`, `HANDOFF.md`, `TEST_EVIDENCE.md`, `DATA_DICTIONARY.md`, `SOURCE_AVAILABILITY.md`) | ADDITIVE POST-FREEZE | Root docs are outside the frozen trees; existing text is kept |
| New source contracts, capability rows, source input binding, market capability rows (runtime data, via operator CLI) | ADDITIVE POST-FREEZE | Written through frozen public APIs into runtime stores; not code |
| Consume `QuotaLedger`/`VerifiedCacheStore` with the active D-REM-001 policy | ADDITIVE POST-FREEZE | Exactly the purpose the frozen authority was built for |
| Adapter-local failure codes mapped to `ReasonCode` | ADDITIVE POST-FREEZE | No enum change |
| Adapter clock (`SystemUtcClock` + durable-ahead + HTTP-Date witness) | ADDITIVE POST-FREEZE | Closes the declared-time residual *for adapter-written times* without touching `quota.py` |
| Generalize `QuotaPolicy.require_operational` beyond OddsPapi | FOUNDATION INTERFACE EXTENSION — **deferred, not slice 1** | Needed only for a second provider (E-1, Section 16.3) |
| Trusted-clock guard inside `QuotaLedger.request` | FOUNDATION INTERFACE EXTENSION — **deferred, recommended before multi-writer/cloud** | E-2, Section 16.3 |
| Incremental/indexed `AppendOnlyJsonl`/`PITStore` reads | FOUNDATION INTERFACE EXTENSION — **deferred** | E-3, performance only |
| Accept non-UTC provider timestamps by converting them | FOUNDATION SEMANTIC CHANGE — **rejected** | Contradicts `parse_utc` and `SOURCE_AVAILABILITY.md` rule 2 |
| Add adapter codes to `ReasonCode`; relax `EvidenceStore` contract checks; change quota numbers; enable any live path | FOUNDATION SEMANTIC CHANGE — **rejected** | Not needed and not permitted |

---

## 4. Canonical schemas and interfaces

These are the exact shapes to implement. Bodies are intentionally omitted; field
lists, types, invariants and signatures are normative.

### 4.1 Conventions (apply to every record)

- `@dataclass(frozen=True)`; validate in `__post_init__`; raise `ValueError`
  subclasses defined in `genesis_adapters.errors` (`SchemaError`, `IdentityError`,
  `ClockError`, `ConfigError`). The foundation's `RegistryConflict` propagates unchanged.
- Timestamps are `str` and must satisfy `value == iso_utc(value)` (canonical
  microsecond `…Z`). `datetime` objects never appear in records.
- Decimals are `str` produced by the functions in Section 4.8, never `float`.
- Digests are lowercase 64-hex; validate like `feature_manifest._digest` (length,
  hex, lowercase).
- Collections are `tuple`s in canonical sort order; serialized dict keys match
  `^[a-z][a-z0-9_]{0,63}$` **except** provider-ref values, which are values, not keys.
- `to_dict()` returns builtin JSON types only (passes `AppendOnlyJsonl`'s exact-JSON
  check); bytes are produced only by `genesis.repro.canonical_json`.
- Forbidden anywhere in canonical records, document keys or telemetry field names:
  `probability` (except the exact name `implied_probability_raw`), `fair`, `edge`,
  `ev`, `expected_value`, `stake`, `kelly`, `recommend`, `confidence`, `tier`,
  `qualif`, `bet_`, `pick`. A test enforces this list.

### 4.2 Versions and constants (`genesis_adapters/__init__.py`, `versions.py`)

```python
ADAPTER_FRAMEWORK_VERSION = "genesis-adapters-v0.5.0"
ODDSPAPI_SOURCE_ADAPTER_VERSION = "oddspapi-source-v1"
SOCCER_ODDSPAPI_NORMALIZER_VERSION = "soccer-oddspapi-normalizer-v1"   # == normalized contract parser_version
                                                                        # == future StrategyDecisionContract.sport_adapter_version
NORMALIZED_SNAPSHOT_SCHEMA = "normalized-snapshot-v1"
ACQUISITION_LEDGER_SCHEMA = "acquisition-ledger-v1"
IDENTITY_REGISTRY_SCHEMA = "identity-registry-v1"
ID_DOMAIN = "genesis-adapters-id-v1"

RAW_CONTRACT_ID = "contract.oddspapi.v4.raw.v1"
NORMALIZED_CONTRACT_ID = "contract.oddspapi.soccer.normalized.v1"
NORMALIZED_PIT_SOURCE_ID = "pit.oddspapi.soccer.normalized.v1"
PROVIDER_ID = "oddspapi"                      # must equal QuotaPolicy.provider_id
CLOCK_SKEW_TOLERANCE_SECONDS = 120
```

### 4.3 Failure and rejection codes (`errors.py`)

```python
class FailureCode(StrEnum):          # REQUEST / RESPONSE scope; no canonical output at all
    CONFIG_INVALID = "CONFIG_INVALID"
    CREDENTIAL_MISSING = "CREDENTIAL_MISSING"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    CLOCK_REGRESSION = "CLOCK_REGRESSION"
    CLOCK_DURABLE_AHEAD = "CLOCK_DURABLE_AHEAD"
    CLOCK_DISAGREEMENT = "CLOCK_DISAGREEMENT"
    QUOTA_BLOCKED = "QUOTA_BLOCKED"
    TRANSPORT_DNS = "TRANSPORT_DNS"
    TRANSPORT_CONNECT = "TRANSPORT_CONNECT"
    TRANSPORT_TLS = "TRANSPORT_TLS"
    TRANSPORT_TIMEOUT = "TRANSPORT_TIMEOUT"
    TRANSPORT_RESET = "TRANSPORT_RESET"
    TRANSPORT_OTHER = "TRANSPORT_OTHER"
    HTTP_AUTH = "HTTP_AUTH"                          # 401, 403
    HTTP_RATE_LIMITED = "HTTP_RATE_LIMITED"          # 429
    HTTP_NOT_FOUND = "HTTP_NOT_FOUND"                # 404
    HTTP_CLIENT = "HTTP_CLIENT"                      # other 4xx
    HTTP_SERVER = "HTTP_SERVER"                      # 5xx
    HTTP_UNEXPECTED = "HTTP_UNEXPECTED"              # 1xx, 3xx (redirects are never followed), 2xx other than 200
    PAYLOAD_EMPTY = "PAYLOAD_EMPTY"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    PAYLOAD_TRUNCATED = "PAYLOAD_TRUNCATED"          # Content-Length mismatch / early EOF
    CONTENT_TYPE_INVALID = "CONTENT_TYPE_INVALID"
    CONTENT_ENCODING_UNSUPPORTED = "CONTENT_ENCODING_UNSUPPORTED"
    JSON_MALFORMED = "JSON_MALFORMED"
    JSON_DUPLICATE_KEY = "JSON_DUPLICATE_KEY"
    JSON_NONFINITE_NUMBER = "JSON_NONFINITE_NUMBER"
    JSON_DEPTH_EXCEEDED = "JSON_DEPTH_EXCEEDED"
    SCHEMA_ROOT_INVALID = "SCHEMA_ROOT_INVALID"      # unknown schema/version at the root
    CATALOG_UNAVAILABLE = "CATALOG_UNAVAILABLE"      # required metadata pin missing
    ATTEMPT_OUTCOME_UNKNOWN = "ATTEMPT_OUTCOME_UNKNOWN"  # crash between reservation and capture
    INGESTION_CONFLICT = "INGESTION_CONFLICT"        # ImmutableConflict / RegistryConflict on write

class RejectionCode(StrEnum):        # ITEM scope; the item gets QUARANTINED status or is excluded
    ELEMENT_SCHEMA_VIOLATION = "ELEMENT_SCHEMA_VIOLATION"
    QUOTE_SCHEMA_DRIFT = "QUOTE_SCHEMA_DRIFT"
    BOOK_SCHEMA_DRIFT = "BOOK_SCHEMA_DRIFT"
    UNKNOWN_SPORT = "UNKNOWN_SPORT"
    UNKNOWN_COMPETITION = "UNKNOWN_COMPETITION"
    COMPETITION_CATALOG_DRIFT = "COMPETITION_CATALOG_DRIFT"
    UNKNOWN_PARTICIPANT = "UNKNOWN_PARTICIPANT"
    PARTICIPANT_IDENTITY_AMBIGUOUS = "PARTICIPANT_IDENTITY_AMBIGUOUS"
    DUPLICATE_EVENT_IN_PAYLOAD = "DUPLICATE_EVENT_IN_PAYLOAD"
    EVENT_IDENTITY_CONFLICT = "EVENT_IDENTITY_CONFLICT"      # natural-key collision / changed provider ID
    EVENT_IDENTITY_MUTATION = "EVENT_IDENTITY_MUTATION"      # known ID now names a different match
    EVENT_NOT_PREMATCH = "EVENT_NOT_PREMATCH"                # status live/finished
    EVENT_CANCELLED = "EVENT_CANCELLED"
    EVENT_PAST_KICKOFF = "EVENT_PAST_KICKOFF"
    UNKNOWN_EVENT_STATUS = "UNKNOWN_EVENT_STATUS"
    CONFLICTING_STATUS = "CONFLICTING_STATUS"
    MARKET_CATALOG_DRIFT = "MARKET_CATALOG_DRIFT"
    MARKET_OUT_OF_SLICE = "MARKET_OUT_OF_SLICE"              # counted in `excluded`, not a rejection row
    UNKNOWN_BOOKMAKER = "UNKNOWN_BOOKMAKER"
    EXCHANGE_DATA_UNSUPPORTED = "EXCHANGE_DATA_UNSUPPORTED"
    PLAYER_PROP_UNSUPPORTED = "PLAYER_PROP_UNSUPPORTED"
    INCOMPLETE_MARKET = "INCOMPLETE_MARKET"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    QUOTE_INVALID_PRICE = "QUOTE_INVALID_PRICE"
    INCOHERENT_PRICES = "INCOHERENT_PRICES"
    TIMESTAMP_INVALID = "TIMESTAMP_INVALID"
    TIMESTAMP_NOT_UTC = "TIMESTAMP_NOT_UTC"
    TIMESTAMP_IMPLAUSIBLE = "TIMESTAMP_IMPLAUSIBLE"
    PROVIDER_TIMESTAMP_FUTURE = "PROVIDER_TIMESTAMP_FUTURE"

class ItemScope(StrEnum):
    RESPONSE = "response"; COMPETITION = "competition"; EVENT = "event"
    BOOK_MARKET = "book_market"; QUOTE = "quote"; CATALOG = "catalog"

REASON_CODE_MAP: Mapping[str, genesis.reasons.ReasonCode]   # total over both enums; tested
# e.g. *_SCHEMA_* / JSON_* / PAYLOAD_* -> SCHEMA_REJECTED; *_IDENTITY_* / DUPLICATE_* -> AMBIGUOUS_IDENTITY;
# UNKNOWN_COMPETITION/UNKNOWN_SPORT -> UNKNOWN_SOURCE; MARKET_* -> UNSUPPORTED_MARKET;
# INCOMPLETE_MARKET -> MISSING_EVIDENCE; PROVIDER_TIMESTAMP_FUTURE/TIMESTAMP_* -> SOURCE_CONTRACT_VIOLATION;
# EXCHANGE_*/PLAYER_* -> NOT_IMPLEMENTED; CATALOG drift -> CONFIGURATION_MISMATCH;
# INGESTION_CONFLICT -> ARTIFACT_TAMPERED; transport/HTTP/quota/clock/breaker -> NOT_READY_AT_DECISION
```

### 4.4 Clock (`clock.py`)

```python
class AcquisitionClock(Protocol):
    def now(self) -> str: ...        # iso_utc; strictly increasing within the process

class SystemUtcClock:                 # production default (mirrors risk.py action_clock default)
    def __init__(self, *, floor: str | None = None) -> None: ...
    def now(self) -> str: ...
    # If the system time <= last issued: if the gap is < 1 ms, wait (<= 5 ms total) for
    # a strictly later value; otherwise raise ClockRegression. Never fabricates a time.

def require_not_ahead(now: str, durable_latest: Iterable[str], *, tolerance_s: int) -> None: ...
    # raises ClockDurableAhead if any durable stamp > now + tolerance

@dataclass(frozen=True)
class ClockWitness:
    provider_http_date: str | None    # parsed RFC 7231 Date header -> iso_utc, or None
    skew_seconds: int | None          # received_at - http_date, rounded toward zero
    disagreement: bool                # abs(skew) > tolerance
```

Test clocks (`SteppingClock`, `FrozenListClock`) live only in `tests/adapters/support.py`.

### 4.5 Acquisition contracts (`acquisition/contracts.py`)

```python
class PayloadKind(StrEnum):
    ODDS_LISTING = "odds_listing"                 # PIT-indexed decision data
    CATALOG_TOURNAMENTS = "catalog_tournaments"
    CATALOG_PARTICIPANTS = "catalog_participants"
    CATALOG_MARKETS = "catalog_markets"
    CATALOG_BOOKMAKERS = "catalog_bookmakers"
    ACCOUNT = "account"                           # never persisted raw (may contain personal data)

@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int                 # 1 for every metered endpoint (each attempt is charged)
    backoff_seconds: tuple[int, ...]  # len == max_attempts - 1; deterministic, no jitter
    retry_on: frozenset[FailureCode]  # subset of transport/5xx codes

@dataclass(frozen=True)
class EndpointSpec:
    endpoint_id: str                  # "oddspapi.v4.odds_by_tournaments"
    path: str                         # "/v4/odds-by-tournaments"
    payload_kind: PayloadKind
    metered: bool                     # True unless documented free AND operator-verified
    billable_units: int               # 1 if metered else 0 (QuotaLedger rejects 0 units; unmetered calls bypass it)
    cooldown_ms: int
    cache_ttl_seconds: int            # 0 = never cached
    max_response_bytes: int
    required_params: frozenset[str]
    allowed_params: frozenset[str]
    fixed_params: tuple[tuple[str, str], ...]   # e.g. (("oddsFormat","decimal"),("language","en"))
    retry: RetryPolicy
    terms_verified: bool              # False until an operator records verification
    # invariant: metered == (billable_units > 0); metered => retry.max_attempts == 1;
    # "apiKey" never appears in required/allowed/fixed params

@dataclass(frozen=True)
class ProviderRequest:
    provider_id: str
    endpoint_id: str
    method: str                       # "GET" only
    host: str                         # "api.oddspapi.io"
    path: str
    params: tuple[tuple[str, str], ...]   # sorted by key; credential excluded
    redacted_uri: str                 # "https://api.oddspapi.io/v4/...?a=1&b=2" (urlencode, quote_via=quote)
    request_hash: str                 # sha256(canonical_json({"domain":"genesis-adapters.provider-request",
                                      #   "version":1,"provider_id","endpoint_id","method","host","path","params"}))
    credential_param: str | None      # "apiKey"; value supplied only inside the transport

class Secret:                          # holds the API key; __repr__/__str__ -> "Secret(<redacted>)";
    def reveal(self) -> str: ...      # not a dataclass; not JSON-serializable; never logged

class CredentialProvider(Protocol):
    def get(self, provider_id: str) -> Secret | None: ...
# production: EnvironmentCredentialProvider reads GENESIS_ODDSPAPI_API_KEY; tests: static fake

@dataclass(frozen=True)
class HttpCapture:
    request: ProviderRequest
    request_started_at: str
    received_at: str
    http_status: int
    headers: tuple[tuple[str, str], ...]   # lower-cased allowlist: content-type, content-length,
                                           # content-encoding, date, retry-after; sorted
    body: bytes
    body_sha256: str
    body_length: int
    # invariant: received_at >= request_started_at; body_sha256 == sha256(body)

@dataclass(frozen=True)
class TransportFailure:
    request: ProviderRequest
    request_started_at: str
    failed_at: str
    code: FailureCode                 # TRANSPORT_* only
    detail: str                       # fixed adapter vocabulary; never exception text, never a URL

class LiveNetworkPermit:               # capability token; only cli/ constructs it after env checks
    def __init__(self, *, confirmation: str) -> None: ...
    # raises ConfigError unless confirmation == "read-only-live" AND os.environ.get("GENESIS_ADAPTER_LIVE") == "1"

class HttpTransport(Protocol):
    def send(self, request: ProviderRequest, *, secret: Secret | None,
             timeout_s: float, max_bytes: int, clock: AcquisitionClock) -> HttpCapture | TransportFailure: ...

class UrllibTransport:                  # the ONLY module that imports urllib/http/ssl/socket
    def __init__(self, permit: LiveNetworkPermit) -> None: ...
    # TLS verification on (default context); redirects refused (3xx -> HTTP_UNEXPECTED);
    # proxies disabled (ProxyHandler({})); Accept: application/json; Accept-Encoding: identity;
    # host must equal request.host; body read in chunks to max_bytes+1; socket timeout 20 s,
    # total deadline 60 s; urllib exceptions are mapped to TransportFailure without their text.

class AttemptOutcome(StrEnum):
    CACHE_HIT = "cache_hit"; QUOTA_BLOCKED = "quota_blocked"; CAPTURED = "captured"
    TRANSPORT_FAILED = "transport_failed"; SKIPPED = "skipped"      # breaker/credential/clock
    OUTCOME_UNKNOWN = "outcome_unknown"                               # recovery only

@dataclass(frozen=True)
class QuotaCharge:
    quota_request_id: str
    reason: str                       # QuotaDecision.reason verbatim
    allowed: bool
    billable_units: int
    daily_used: int
    monthly_used: int
    normal_monthly_used: int
    reserve_monthly_used: int
    cache_entry_id: str | None
```

### 4.6 Source adapter protocol and OddsPapi provider-native records

```python
class SourceAdapter(Protocol):
    provider_id: str
    version: str
    def endpoints(self) -> Mapping[str, EndpointSpec]: ...
    def build_request(self, endpoint_id: str, params: Mapping[str, str]) -> ProviderRequest: ...  # pure
    def classify_http(self, capture: HttpCapture) -> FailureCode | None: ...                       # None == 200 OK envelope
    def parse(self, capture: HttpCapture) -> ParsedPayload | ParseFailure: ...                     # pure

@dataclass(frozen=True)
class ParseFailure:
    code: FailureCode
    detail: str

@dataclass(frozen=True)
class DriftNote:
    path: str                         # e.g. "fixture.newField", "quote.mainLine"
    count: int

@dataclass(frozen=True)
class ElementIssue:                    # an array element that could not be typed
    index: int
    code: RejectionCode
    provider_ref: tuple[tuple[str, str], ...]   # whatever IDs were readable, as strings
    detail: str

# ---- OddsPapi (sources/oddspapi/records.py). Provider IDs kept as strings of the exact JSON text. ----
# Parse never drops an attributable element: type/timestamp/price problems are recorded as
# ElementIssue on the owning fixture (provider_ref names the book/market/outcome) and the
# affected field is None; the sport adapter turns every issue into a quarantine.
@dataclass(frozen=True)
class OPQuote:                          # bookmakerOdds[b].markets[m].outcomes[o].players[p]
    market_id: str; outcome_id: str; player_key: str
    price_text: str | None             # exact decimal text of the JSON number (Section 4.8); None iff an issue was recorded
    active: bool | None                # None iff an issue was recorded
    changed_at: str | None             # iso_utc; None iff an issue was recorded
    limit_text: str | None
    bookmaker_outcome_id: str | None
    exchange_meta_empty: bool
    unknown_fields: tuple[str, ...]

@dataclass(frozen=True)
class OPBookMarket:
    market_id: str
    bookmaker_market_id: str | None
    quotes: tuple[OPQuote, ...]        # sorted (outcome_id, player_key)

@dataclass(frozen=True)
class OPBook:
    bookmaker_slug: str
    is_active: bool
    bookmaker_fixture_id: str | None
    markets: tuple[OPBookMarket, ...]  # sorted market_id
    unknown_fields: tuple[str, ...]

@dataclass(frozen=True)
class OPFixture:
    fixture_id: str; sport_id: str; tournament_id: str; season_id: str
    participant1_id: str; participant2_id: str; status_id: str
    has_odds: bool
    start_time: str                    # iso_utc
    true_start_time: str | None
    true_end_time: str | None
    updated_at: str | None
    books: tuple[OPBook, ...]          # sorted slug
    unknown_fields: tuple[str, ...]
    issues: tuple[ElementIssue, ...]   # timestamp/type problems inside this fixture

@dataclass(frozen=True)
class OddsListingPayload:
    endpoint_id: str
    fixtures: tuple[OPFixture, ...]    # sorted fixture_id; duplicates kept (sport adapter rejects them)
    element_issues: tuple[ElementIssue, ...]
    drift: tuple[DriftNote, ...]

@dataclass(frozen=True)
class TournamentCatalog:   entries: Mapping[str, tuple[str, str, str]]   # id -> (slug, name, category_name)
@dataclass(frozen=True)
class ParticipantCatalog:  entries: Mapping[str, str]                    # id -> name (display only)
@dataclass(frozen=True)
class MarketCatalog:       entries: Mapping[str, "OPMarketDef"]
@dataclass(frozen=True)
class OPMarketDef:
    market_id: str; market_name: str; market_type: str; period: str; handicap_text: str
    sport_id: str; player_prop: bool; outcomes: tuple[tuple[str, str], ...]   # (outcome_id, outcome_name)
@dataclass(frozen=True)
class BookmakerCatalog:    slugs: frozenset[str]

ParsedPayload = OddsListingPayload | TournamentCatalog | ParticipantCatalog | MarketCatalog | BookmakerCatalog | AccountStatus
@dataclass(frozen=True)
class AccountStatus:       request_limit: int; request_count: int     # everything else discarded
```

Closed-schema policy for OddsPapi (parse level):

| Object | Required keys (type) | Known optional keys | Unknown keys |
| --- | --- | --- | --- |
| Root (odds listing) | JSON array | — | a non-array root → `SCHEMA_ROOT_INVALID` |
| Fixture | `fixtureId` (str), `participant1Id`/`participant2Id` (int), `sportId`/`tournamentId`/`seasonId`/`statusId` (int), `startTime` (str), `bookmakerOdds` (object) | `hasOdds`, `trueStartTime`, `trueEndTime`, `updatedAt`, `statusName`, `participant1Name`, `participant2Name`, `sportName`, `tournamentName` | recorded as `DriftNote`, tolerated |
| Book (`bookmakerOdds[slug]`) | `bookmakerIsActive` (bool), `markets` (object) | `bookmakerFixtureId`, `fixturePath` | `BOOK_SCHEMA_DRIFT` → that book's book-markets quarantined |
| Book-market (`markets[id]`) | `outcomes` (object) | `bookmakerMarketId` | `BOOK_SCHEMA_DRIFT` |
| Quote (`players[key]`) | `price` (number), `active` (bool), `changedAt` (str) | `betslip`, `bookmakerOutcomeId`, `limit`, `playerName`, `exchangeMeta` | `QUOTE_SCHEMA_DRIFT` → book-market quarantined |

Price-adjacent objects are closed because an unknown field there can change what a
price means (for example a new suspension flag). Fixture-level additions are
tolerated and reported because they cannot silently change a price's meaning.
`bool` is never accepted where `int` is required (`type(x) is int`).

### 4.7 Canonical records (`canonical/records.py`)

```python
class Sport(StrEnum): SOCCER = "soccer"
class BookmakerKind(StrEnum): SPORTSBOOK = "sportsbook"; EXCHANGE = "exchange"
class EventStatus(StrEnum):
    SCHEDULED = "scheduled"; LIVE = "live"; FINISHED = "finished"
    CANCELLED_OR_POSTPONED = "cancelled_or_postponed"      # OddsPapi statusId 3 does not distinguish
class BookMarketStatus(StrEnum):
    OPEN = "open"                        # every selection has an ACTIVE quote
    PARTIALLY_SUSPENDED = "partially_suspended"
    SUSPENDED = "suspended"              # no ACTIVE quote
    BOOK_INACTIVE = "book_inactive"      # bookmakerIsActive == false; no quotes emitted
    QUARANTINED = "quarantined"          # untrustworthy; no quotes emitted
class QuoteState(StrEnum): ACTIVE = "active"; SUSPENDED = "suspended"
class QuoteSide(StrEnum): BACK = "back"   # LAY reserved for exchange support (not slice 1)
class OutcomeCode(StrEnum):
    PARTICIPANT1_WIN = "p1"; DRAW = "draw"; PARTICIPANT2_WIN = "p2"

@dataclass(frozen=True)
class ProviderRef:                        # provider-native identity; values are exact provider text
    provider_id: str
    kind: str                             # "tournament" | "season" | "participant" | "fixture" | "market" | "outcome" | "bookmaker"
    native_id: str

@dataclass(frozen=True)
class CanonicalCompetition:
    competition_id: str; sport: Sport
    provider_ref: ProviderRef
    name: str; category: str              # from the pinned tournament catalog; must match the allowlist

@dataclass(frozen=True)
class CanonicalParticipant:
    participant_id: str; sport: Sport
    provider_ref: ProviderRef
    display_name: str | None              # display only; never identity

@dataclass(frozen=True)
class CanonicalEvent:
    event_id: str; sport: Sport
    competition_id: str; season_id: str
    participant1_id: str; participant2_id: str      # "1"/"home" role as the provider orders them
    scheduled_start_at: str                          # provider startTime as asserted at received_at
    status: EventStatus
    provider_updated_at: str | None
    provider_true_start_at: str | None
    provider_true_end_at: str | None
    venue_neutral: None                              # unknown in slice 1; never guessed
    provider_refs: tuple[ProviderRef, ...]           # fixture, tournament, season, participant x2
    quarantined: bool
    rejection_codes: tuple[RejectionCode, ...]
    # invariants: participant1_id != participant2_id; quarantined == bool(rejection_codes)

@dataclass(frozen=True)
class CanonicalSelection:
    selection_id: str; market_id: str
    outcome_code: OutcomeCode
    participant_id: str | None             # set for p1/p2, None for draw

@dataclass(frozen=True)
class CanonicalMarket:
    market_id: str; event_id: str
    family: str                            # "soccer.full_time_result_1x2"
    period: str                            # "provider_fulltime" (settlement semantics unverified)
    line: str | None                       # canonical decimal text; None for 1X2
    selections: tuple[CanonicalSelection, ...]   # sorted outcome_code

@dataclass(frozen=True)
class CanonicalBookmaker:
    bookmaker_id: str; key: str            # curated provider-independent key, e.g. "pinnacle"
    kind: BookmakerKind
    provider_refs: tuple[ProviderRef, ...]

@dataclass(frozen=True)
class Quote:
    selection_id: str
    side: QuoteSide
    state: QuoteState
    raw_price_text: str                    # exact provider text
    decimal_odds: str | None               # canonical decimal; None unless state == ACTIVE
    implied_probability_raw: str | None    # 1/decimal_odds, includes margin; None unless ACTIVE
    provider_changed_at: str               # provider "last price change"; informational
    provider_limit_text: str | None        # provider "limit"; unit/currency unknown; informational
    provider_clock_ahead: bool             # changed_at in (received_at, received_at + tolerance]
    provider_stale_flag: bool              # changed_at < received_at - 7 days; informational only
    provider_refs: tuple[ProviderRef, ...] # market, outcome (+ bookmaker_outcome_id as a ProviderRef kind "bookmaker_outcome")

@dataclass(frozen=True)
class BookMarketObservation:
    book_market_id: str; market_id: str; event_id: str; bookmaker_id: str
    family: str; period: str; line: str | None
    status: BookMarketStatus
    book_is_active: bool
    quotes: tuple[Quote, ...]              # empty iff status in {QUARANTINED, BOOK_INACTIVE}
    overround: str | None                  # sum(implied) - 1; only when status == OPEN
    provider_market_changed_at: str | None # max quote changed_at
    provider_refs: tuple[ProviderRef, ...] # bookmaker slug, bookmaker fixture/market IDs, market ID
    rejection_codes: tuple[RejectionCode, ...]

@dataclass(frozen=True)
class ListingScope:
    scope_id: str
    endpoint_id: str; bookmaker_id: str; competition_id: str; season_id: str
    event_ids: tuple[str, ...]             # every event of this (competition, season) in the response
    book_market_ids: tuple[str, ...]       # every book-market (any status) of this bookmaker in scope

@dataclass(frozen=True)
class ItemRejection:
    scope: ItemScope; code: RejectionCode
    entity_id: str | None
    provider_ref: tuple[tuple[str, str], ...]
    detail: str                            # adapter vocabulary only; never provider free text
```

### 4.8 Odds, lines and derived arithmetic (exact rules)

- **Raw quoted odds.** Decode JSON with `parse_float=decimal.Decimal` and
  `parse_int=int`. `raw_price_text = format(Decimal(value), "f")` for a `Decimal` or `int`
  price. Reject (`QUOTE_INVALID_PRICE`) if the literal used exponent notation, the value is not finite,
  the value is ≤ 1.0, the value is > 1000, or it has more than 4 decimal places. The
  request always pins `oddsFormat=decimal`; any other format is out of scope.
- **Canonical decimal odds.** `decimal_odds = format(Decimal(raw_price_text).normalize(), "f")`
  (e.g. `"2.10"` → `"2.1"`, `"10"` → `"10"`). Present only for `ACTIVE` quotes.
- **Implied probability (raw).** Under `decimal.localcontext(prec=28)`:
  `(Decimal(1) / Decimal(decimal_odds)).quantize(Decimal("1E-10"), rounding=ROUND_HALF_EVEN)`,
  rendered with `format(…, "f")`. It includes the bookmaker margin. It is **not** a fair
  probability, not a model probability, and not an input to any adapter decision other
  than the coherence check below.
- **Overround.** Only when the book-market is `OPEN`:
  `sum(implied_probability_raw) - 1`, quantized as above. Coherence rule for
  `soccer.full_time_result_1x2`: overround in `[0, 0.30]`, otherwise
  `INCOHERENT_PRICES` → quarantine. (A single bookmaker quoting a negative 1X2 margin
  indicates a torn or stale update, not an opportunity.)
- **Lines.** `line` is canonical decimal text (`format(Decimal(x).normalize(), "f")`) and
  part of market identity (Section 8). Slice 1 has no line markets; `line` is `None`.
- **Back/lay.** Every slice-1 quote is `side = BACK` from a `SPORTSBOOK`. Exchange quotes
  (`LAY`, available size, commission) are reserved and rejected in slice 1
  (`EXCHANGE_DATA_UNSUPPORTED` whenever `exchangeMeta` is non-empty).
- **What the adapter never produces:** fair/de-vigged probability, model probability,
  EV, edge, price-sanity class, odds-profile class, stake, or any ranking.

### 4.9 Normalized snapshot document (the PIT payload) — closed schema v1

One document per ingested odds-listing capture. It is written as `canonical_json(doc)` bytes and
published to the normalized `EvidenceStore`. Every dict key below is literal; `<…>`
marks an ID-keyed map. Validation rejects any other key at any level.

```text
{
  "domain": "genesis-adapters.normalized-snapshot",
  "schema_version": "normalized-snapshot-v1",
  "provider_id": "oddspapi",
  "sport": "soccer",
  "normalizer_version": "soccer-oddspapi-normalizer-v1",
  "source_adapter_version": "oddspapi-source-v1",
  "catalog_digest": <sha256 of canonical_json(pinned sport mapping tables + semantics constants)>,
  "pins": {
    "identity_registry_head": <record_hash of the last identity row read, or 64 zeros>,
    "metadata": {"bookmakers": <raw obs id>, "markets": <raw obs id>,
                 "participants": <raw obs id>, "tournaments": <raw obs id>}
  },
  "raw": {"attempt_id": str, "artifact_hash": <sha256>, "byte_length": int,
          "contract_id": "contract.oddspapi.v4.raw.v1", "observation_id": <sha256>},
  "request": {"endpoint_id": str, "provider_request_hash": <sha256>, "redacted_uri": str,
              "scope": {"bookmaker_ids": [..], "competition_ids": [..],
                        "provider_bookmakers": [..], "provider_tournament_ids": [..]}},
  "times": {"request_started_at": iso, "received_at": iso, "provider_http_date": iso|null},
  "competitions": {<competition_id>: {"category": str, "name": str,
                   "provider_tournament_id": str, "season_ids": [..]}},
  "participants": {<participant_id>: {"display_name": str|null, "provider_participant_id": str}},
  "events": {<event_id>: {
      "competition_id", "season_id", "participant1_id", "participant2_id",
      "scheduled_start_at", "status", "provider_updated_at", "provider_true_start_at",
      "provider_true_end_at", "venue_neutral": null, "quarantined": bool,
      "rejection_codes": [..], "book_market_ids": [..],
      "provider_refs": {"fixture_id", "participant1_id", "participant2_id", "season_id", "tournament_id"}}},
  "book_markets": {<book_market_id>: {
      "market_id", "event_id", "bookmaker_id", "family", "period", "line": null,
      "status", "book_is_active": bool, "overround": str|null,
      "provider_market_changed_at": iso|null, "rejection_codes": [..],
      "selections": {<selection_id>: {"outcome_code", "participant_id": str|null}},
      "quotes": {<selection_id>: {"side", "state", "raw_price_text", "decimal_odds",
                  "implied_probability_raw", "provider_changed_at", "provider_limit_text",
                  "provider_clock_ahead", "provider_stale_flag",
                  "provider_refs": {"bookmaker_outcome_id": str|null, "market_id", "outcome_id", "player_key"}}},
      "provider_refs": {"bookmaker_fixture_id": str|null, "bookmaker_market_id": str|null,
                        "bookmaker_slug", "market_id"}}},
  "scopes": {<scope_id>: {"endpoint_id", "bookmaker_id", "competition_id", "season_id",
             "event_ids": [..], "book_market_ids": [..]}},
  "rejections": [{"scope", "code", "entity_id": str|null, "provider_ref": {..}, "detail"}],
  "excluded": {"markets_out_of_slice": {<provider market id>: count}, "competitions_out_of_scope": {<provider tournament id>: count}},
  "drift": [{"path", "count"}]
}
```

Rules:

- The document contains **no** Genesis time other than `times.*` (which come from the
  raw capture). `derived_at` and `indexed_at` live only in the observation and PIT rows,
  so re-deriving the same inputs yields byte-identical documents.
- Lists are sorted: ID lists lexicographically; `rejections` by
  `(scope, code, entity_id or "", canonical_json(provider_ref))`; `drift` by `path`.
- Feature paths are dict-only, for example
  `$.book_markets.<gbm_…>.quotes.<gsel_…>.decimal_odds`, which satisfies F2.
- `competitions` includes only allowlisted competitions present in the response;
  out-of-scope competitions are counted under `excluded`.

### 4.10 Sport adapter protocol (`sports/base.py`)

```python
@dataclass(frozen=True)
class CatalogPins:
    tournaments: tuple[str, TournamentCatalog]     # (raw observation id, parsed catalog)
    participants: tuple[str, ParticipantCatalog]
    markets: tuple[str, MarketCatalog]
    bookmakers: tuple[str, BookmakerCatalog]

@dataclass(frozen=True)
class IdentitySnapshot:
    head: str                                      # 64 zeros if empty
    events: Mapping[str, "EventSeen"]              # event_id -> last seen natural key
    natural_index: Mapping[tuple[str, str, str], tuple[str, ...]]   # (competition, p1, p2) -> event_ids
    conflicted_event_ids: frozenset[str]

@dataclass(frozen=True)
class NormalizationContext:
    raw_observation_id: str; raw_artifact_hash: str; raw_byte_length: int
    attempt_id: str
    request: ProviderRequest
    request_started_at: str; received_at: str; provider_http_date: str | None
    requested_bookmaker_slugs: tuple[str, ...]
    requested_tournament_ids: tuple[str, ...]
    catalogs: CatalogPins
    identity: IdentitySnapshot
    policy: "NormalizationPolicy"                  # Appendix B.3 constants (versioned)

@dataclass(frozen=True)
class IdentityAppend:                              # rows the coordinator appends after normalization
    kind: str                                      # "identity_mapping" | "event_seen" | "identity_conflict"
    body: Mapping[str, object]

@dataclass(frozen=True)
class NormalizationResult:
    document: Mapping[str, object]                 # validated closed-schema v1 dict
    document_bytes: bytes                          # canonical_json(document)
    events: tuple[CanonicalEvent, ...]
    book_markets: tuple[BookMarketObservation, ...]
    scopes: tuple[ListingScope, ...]
    rejections: tuple[ItemRejection, ...]
    identity_appends: tuple[IdentityAppend, ...]

class SportAdapter(Protocol):
    sport: Sport
    provider_id: str
    version: str                                   # == normalized contract parser_version
    def catalog_digest(self) -> str: ...
    def normalize(self, payload: OddsListingPayload, ctx: NormalizationContext) -> NormalizationResult: ...
    # pure: no IO, no clock, no randomness, no global state; same inputs -> same bytes
```

### 4.11 Evidence, ingestion and reader interfaces

```python
@dataclass(frozen=True)
class RawEvidenceRef:
    contract_id: str; observation_id: str; artifact_hash: str; byte_length: int; received_at: str

@dataclass(frozen=True)
class NormalizedEvidenceRef:
    contract_id: str; observation_id: str; artifact_hash: str
    received_at: str; derived_at: str; raw: RawEvidenceRef

@dataclass(frozen=True)
class PitRowRef:
    pit_source_id: str; partition: str; record_id: str; record_hash: str
    entity_id: str; indexed_at: str

@dataclass(frozen=True)
class ProvenanceChain:                              # returned by every reader call
    pit_row: PitRowRef
    normalized: NormalizedEvidenceRef
    raw: RawEvidenceRef
    attempt_id: str; provider_request_hash: str

@dataclass(frozen=True)
class IngestionResult:
    attempt_id: str
    outcome: AttemptOutcome
    failure: FailureCode | None
    raw: RawEvidenceRef | None
    normalized: NormalizedEvidenceRef | None
    pit_rows_written: int
    events: int; book_markets_by_status: Mapping[str, int]
    rejections_by_code: Mapping[str, int]
    # invariant: failure is not None => normalized is None and pit_rows_written == 0

class Unavailable(StrEnum):
    NO_OBSERVATION = "no_observation"
    CAPABILITY_NOT_READY = "capability_not_ready"          # PITStore raised SourceUnavailable
    ABSENT_FROM_LATEST_LISTING = "absent_from_latest_listing"
    STALE = "stale"
    PROVENANCE_BROKEN = "provenance_broken"                 # any hash/ID/contract mismatch

@dataclass(frozen=True)
class BookMarketView:                    # returned for ANY verified current head, whatever its status
    observation: BookMarketObservation
    event: CanonicalEvent
    received_at: str; request_started_at: str
    provenance: ProvenanceChain
    def usable_quotes(self) -> tuple[Quote, ...]: ...
    # ACTIVE quotes only, and only when observation.status == OPEN and not event.quarantined;
    # otherwise (). Callers that need prices must use this, never observation.quotes directly.

class CanonicalReader:                              # read-only; the only supported way to read adapter output
    def book_market_as_of(self, *, book_market_id: str, event_id: str, as_of: str,
                          max_age_seconds: int | None = None) -> BookMarketView | Unavailable: ...
    def event_as_of(self, *, event_id: str, as_of: str) -> tuple[CanonicalEvent, ProvenanceChain] | Unavailable: ...
    def verify_chain(self, chain: ProvenanceChain) -> None: ...        # raises ProvenanceError

class IngestionCoordinator:
    def __init__(self, *, layout: "StorageLayout", source: SourceAdapter,
                 sports: Mapping[tuple[str, str], SportAdapter],       # (provider_id, sport) -> adapter
                 transport: HttpTransport, credentials: CredentialProvider,
                 quota: QuotaLedger, cache: VerifiedCacheStore,
                 clock: AcquisitionClock, sleeper: Callable[[float], None],
                 telemetry: "Telemetry",
                 checkpoint_hook: Callable[[str], None] | None = None) -> None: ...
    # checkpoint_hook is called with the step name ("raw_published", "cache_published",
    # "ingestion_started", "identity_appended", "document_published", "pit_row:<n>",
    # "coverage_appended") after each side effect; production passes None; tests inject
    # faults through it (Section 12.4 #9). It can only raise, never alter data.
    def recover(self) -> tuple[IngestionResult, ...]: ...              # Section 6.5; always run first
    def run_window(self, plan: "AcquisitionPlan", window_id: str) -> "RunReport": ...

@dataclass(frozen=True)
class RunReport:                                    # immutable JSON at runs/<run_id>.json
    run_id: str; provider_id: str; started_at: str; finished_at: str
    plan_digest: str; code_digest: str               # tree_digest(src/genesis_adapters)
    adapter_versions: Mapping[str, str]
    metrics: Mapping[str, int | str]                 # Section 13 names
    attempts: tuple[str, ...]                        # attempt IDs
```

### 4.12 Projections into frozen foundation types (`canonical/projection.py`)

```python
def to_foundation_participant(p: CanonicalParticipant, prov: ProvenanceRef) -> genesis.canonical.Participant
    # participant_id, sport, canonical_name = display_name or participant_id, source_refs=(prov,),
    # identity_confidence = "provider_id_mapped"
def to_foundation_event(e: CanonicalEvent, prov: ProvenanceRef) -> genesis.canonical.Event
    # event_id, sport, scheduled_start=scheduled_start_at, participant_ids=(p1, p2),
    # source_refs=(prov,), venue=None, competition_id=e.competition_id
def to_foundation_market_snapshots(bm: BookMarketObservation, n: NormalizedEvidenceRef,
                                   prov: ProvenanceRef) -> tuple[genesis.canonical.MarketSnapshot, ...]
    # one per ACTIVE quote only; snapshot_id = mint("pit", "snapshot", bm.book_market_id, q.selection_id, n.observation_id)
    # market_type=family, observed_at=received_at=n.received_at, parse_ready_at=n.derived_at,
    # side=MarketSide.BACK, odds_decimal=q.decimal_odds, available_size=None, status="open"
def provenance_ref(n: NormalizedEvidenceRef, *, evidence_span: str | None) -> genesis.provenance.ProvenanceRef
    # artifact_hash=n.artifact_hash, contract_id, source_uri, retrieved_at=n.received_at,
    # parse_ready_at=n.derived_at, availability_class=DERIVED, parser_version, observation_id=n.observation_id
```

---

## 5. PIT and provenance model

### 5.1 Timestamps (none of these is collapsed into another)

| Name | Written by | Taken | Stored in | PIT role |
| --- | --- | --- | --- | --- |
| `planned_at` | Genesis clock | plan built | acquisition ledger `run_started` | none |
| `quota_occurred_at` | Genesis clock | just before `QuotaLedger.request` | quota ledger `occurred_at`; `attempt_started` | daily/monthly quota windows |
| `request_started_at` | Genesis clock | immediately before the HTTP send | `attempt_finished`; document `times` | **freshness bound**: the provider state is no older than this, minus unknown provider lag |
| `provider_http_date` | provider server | HTTP `Date` header | `attempt_finished`; document `times` | clock witness only |
| `received_at` | Genesis clock | after the last body byte is read | raw observation `retrieved_at`/`first_seen_at`/`parse_ready_at`; normalized observation `retrieved_at`/`first_seen_at`; document `times`; PIT `available_at`, `retrieved_at`, `valid_from` | **observation time**: when Genesis possessed the information |
| `raw_persisted_at` | Genesis clock | after raw `EvidenceStore.publish` returns | `attempt_finished` | audit only |
| `derived_at` | Genesis clock | immediately before the normalized publish | normalized observation `parse_ready_at` (not in the document bytes) | normalized record usable from here |
| `indexed_at` | Genesis clock | immediately before each PIT append | PIT `ready_at` | admissibility of that row |
| `scheduled_start_at` | provider `startTime` | as asserted at `received_at` | document event | event-time semantics; pre-match gate |
| `provider_updated_at` | provider `updatedAt` | — | document event | informational; future-check |
| `provider_changed_at` | provider `changedAt` | — | document quote | informational; future-check; stale flag |
| `provider_market_changed_at` | derived | max of quote `changedAt` | document book-market | informational ("market last update") |
| `provider_true_start_at` / `_end_at` | provider | — | document event | status consistency only |

Ordering invariant (asserted on every ingestion):
`quota_occurred_at ≤ request_started_at ≤ received_at ≤ raw_persisted_at ≤ derived_at ≤ indexed_at`.

### 5.2 Admissibility at decision time T

A book-market (or event) observation is admissible at T iff **all** hold:

1. the PIT row satisfies `BitemporalRecord.admissible_at(T)`
   (`available_at = received_at ≤ T`, `retrieved_at ≤ T`, `ready_at = indexed_at ≤ T`,
   `valid_from = received_at ≤ T`);
2. the normalized observation's `retrieved_at ≤ T` and `parse_ready_at = derived_at ≤ T`;
3. `SourceCapabilityRegistry.require_ready_at(NORMALIZED_PIT_SOURCE_ID, T)` passes;
4. every input pinned by the document (raw capture, metadata captures, identity head)
   was received/recorded at or before `derived_at` (true by construction; verified by
   `verify_chain`).

Availability uses `received_at` (the later, conservative bound). Freshness uses
`request_started_at` (the earlier, conservative bound):
`age(T) = T − request_started_at`.

### 5.3 Reconstructing "what was legitimately available at T"

`CanonicalReader.book_market_as_of(bm, event, T)`:

1. Resolve the partition `(competition_id, season_id)` for `event` from the identity
   registry, using only rows recorded at or before T.
2. `rows = PITStore(partition).as_of_query(bm, T, source_id=NORMALIZED_PIT_SOURCE_ID)`
   (the frozen query enforces capability readiness and admissibility). The head is the
   unique row with maximum `valid_from`. Two heads with the same `valid_from` →
   `PITViolation` → `PROVENANCE_BROKEN`. None → `NO_OBSERVATION`.
3. Head of the listing scope `scope_id(endpoint, bookmaker, competition, season)` at T,
   likewise. If `scope_head.valid_from > bm_head.valid_from`, a later listing of the same
   scope omitted this book-market → `ABSENT_FROM_LATEST_LISTING`. This check is what
   stops a suspended or pulled market from falling back to an older price.
4. Load the normalized observation whose `artifact_hash == head.payload_hash` and
   `parse_ready_at ≤ T` (earliest such if re-derivation created several); verify the bytes,
   the closed schema, `times.received_at == head.valid_from`, the raw observation and raw
   bytes, and the contracts. Any mismatch → `PROVENANCE_BROKEN`.
5. If `max_age_seconds` is set and `T − request_started_at > max_age_seconds` → `STALE`.
6. Return the view. A suspended, book-inactive or quarantined head is returned as a view
   whose `usable_quotes()` is empty. The status is information, and the caller must not
   look past it to an older head.

Guarantee: the answer for any T is a function only of rows whose `ready_at ≤ T`. Later
ingestion can add rows with `valid_from > T` but cannot change the answer at T. A
property test asserts this (Section 12.3).

Downstream decision code that uses the frozen `FeatureInputManifest` must list both the
book-market row and its listing-scope row as required inputs and require them to have
equal `payload_hash`. That is the manifest-level expression of step 3. It is
guidance for the later decision slice; slice 1 proves it with a compatibility test.

### 5.4 Rules

- **Immutable raw snapshots.** Raw bytes are stored exactly as received (no decoding,
  pretty-printing or re-encoding) in a content-addressed `EvidenceStore`. The raw
  observation ID covers `retrieved_at`, so a byte-identical response received later is a
  *second observation of the same content*: evidence that the provider still asserted it.
- **Deterministic IDs/digests.** See Section 8.2. Documents are pure functions of pinned
  inputs; the document hash is their digest.
- **Duplicate responses.** Identical bytes → one object, two observations, two documents
  (they differ in `times`), two sets of PIT rows. A cache hit is *not* a response and
  produces nothing.
- **Corrections.** A provider correction (new kickoff time, repriced outcome) is simply a
  later observation with a later `valid_from`. Nothing earlier is edited. An event whose
  `scheduled_start_at` changes keeps its `event_id`, and the identity registry records an
  `event_seen` change row.
- **Late-arriving data.** Data received now about the past (an old `changedAt`, an
  old `updatedAt`) is admissible only from its `received_at`/`indexed_at`. Provider
  timestamps never back-date availability.
- **Partial payloads.** A truncated or undecodable body fails the whole response.
  A valid body with missing items yields item-level quarantines (missing outcome →
  `INCOMPLETE_MARKET`). Missing book-markets are handled by the scope rule in 5.3.3.
- **Retries.** Each attempt has its own ID and quota charge. A retried success is a
  separate observation; failed attempts produce no observation.
- **Stale data.** The adapter flags (`provider_stale_flag`) but does not decide. The
  reader enforces caller-supplied `max_age_seconds` from `request_started_at`. Aging
  heads are the expected result of an outage; consumers then PASS.
- **Conflicting source data.** Within one payload, a duplicate fixture or quote is
  quarantined on every copy (duplicate JSON keys are already fatal at decode time).
  Across providers (later slices) nothing is merged; each provider is its own PIT
  source and reconciliation is a separate, later component.
- **Timezone normalization.** Provider timestamps must carry an explicit UTC designator
  (`Z` or `+00:00`); they pass through `parse_utc` and are re-emitted with `iso_utc`.
  Naive → `TIMESTAMP_INVALID`; non-UTC offset → `TIMESTAMP_NOT_UTC`. Local time zones
  are never consulted; polling windows are UTC.
- **Source clocks ahead of local time.** A provider timestamp in
  `(received_at, received_at + 120 s]` is kept and flagged `provider_clock_ahead`. Beyond
  that → `PROVIDER_TIMESTAMP_FUTURE`: the quote's book-market is quarantined (for
  `updatedAt`, the event is quarantined). An HTTP `Date` more than 120 s from
  `received_at` in either direction → `CLOCK_DISAGREEMENT` for the whole response.
- **Implausible times.** Any provider timestamp before `2000-01-01T00:00:00Z`, or a
  `startTime` more than 400 days after `received_at` → `TIMESTAMP_IMPLAUSIBLE`.
- **Provider timestamp regressions across observations** (a `changedAt` older than a
  previously observed one for the same quote) are recorded as `anomaly` rows and
  telemetry, not quarantines, because they cannot cause PIT leakage: availability never
  uses provider times. See Section 17, R7.

### 5.5 Trusted clock (closes the declared-time residual for adapter writes)

- Adapter code never accepts a timestamp from its caller for any value it persists.
  Every stamp in 5.1 comes from the injected `AcquisitionClock`; production uses
  `SystemUtcClock`.
- Monotonic: the clock never issues a time ≤ one it already issued (`ClockRegression`).
- Durable-ahead gate at run start (3.3 step 3) detects a future-dated ledger (manual
  tampering, or a previous run on a wrong clock) and refuses to run.
- External witness: the HTTP `Date` header on every response (3.3 step 11).
- Residual (documented, not fixed here): the frozen `QuotaLedger` still accepts any
  writer's `occurred_at`. Slice 1 is the only OddsPapi writer, so the risk is
  controlled operationally. Extension E-2 (Section 16.3) moves the guard into the authority.

---

## 6. Failure semantics

### 6.1 Principles

1. An untrustworthy acquisition produces **no usable canonical observation**. Nothing
   is guessed, substituted, defaulted, carried forward or down-graded to "unknown but usable".
2. Raw bytes of any HTTP response are preserved, even on failure, because they are the
   evidence that the failure happened.
3. A failure that concerns an identifiable, in-scope entity is written as a
   `QUARANTINED` head for that entity, so no reader falls back to an older observation.
4. Metered calls are charged by the provider regardless of outcome (F14). Genesis
   reserves the unit before the call and never auto-retries a metered call.
5. Every failure is recorded with a stable code in the acquisition ledger and the
   document or coverage ledger, and is counted in telemetry.

### 6.2 Request- and response-level failures

"Charged" = a Genesis quota unit was reserved. "Raw" = response bytes stored. "Breaker" =
effect on further calls.

| Condition | Code | Charged | Raw | Cache | Canonical/PIT | Retry | Breaker |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Missing API key | `CREDENTIAL_MISSING` | no | no | no | none | no | window |
| Breaker open | `CIRCUIT_OPEN` | no | no | no | none | no | — |
| Clock went backwards | `CLOCK_REGRESSION` | no | no | no | none | no | operator reset |
| Durable stamp ahead of clock | `CLOCK_DURABLE_AHEAD` | no | no | no | none | no | operator reset |
| Quota ledger blocks (daily/monthly/reserve/time-regression/provider mismatch) | `QUOTA_BLOCKED` (+ ledger reason) | no | no | no | none | no | window (quota) |
| DNS failure | `TRANSPORT_DNS` | yes | no | no | none | metered: no; unmetered: per policy | 2 consecutive → window |
| Connect refused/unreachable | `TRANSPORT_CONNECT` | yes | no | no | none | as above | as above |
| TLS failure | `TRANSPORT_TLS` | yes | no | no | none | no | operator reset (possible interception) |
| Timeout (socket 20 s / total 60 s) | `TRANSPORT_TIMEOUT` | yes | no | no | none | as above | as above |
| Connection reset / early EOF | `TRANSPORT_RESET` / `PAYLOAD_TRUNCATED` | yes | partial bytes not stored | no | none | as above | as above |
| HTTP 401/403 | `HTTP_AUTH` | yes | yes | no | none | no | operator reset |
| HTTP 429 | `HTTP_RATE_LIMITED` | yes | yes | no | none | no | until next UTC day; run quota reconciliation |
| HTTP 404 | `HTTP_NOT_FOUND` | yes | yes | no | none | no | window (endpoint/config problem) |
| Other 4xx | `HTTP_CLIENT` | yes | yes | no | none | no | window |
| 5xx | `HTTP_SERVER` | yes | yes | no | none | as transport | 2 consecutive → window |
| 3xx (redirects never followed), 1xx, non-200 2xx | `HTTP_UNEXPECTED` | yes | yes | no | none | no | operator reset |
| Wrong/absent `Content-Type` (not `application/json`) | `CONTENT_TYPE_INVALID` | yes | yes | no | none | no | window |
| `Content-Encoding` other than identity | `CONTENT_ENCODING_UNSUPPORTED` | yes | yes | no | none | no | window |
| Empty body | `PAYLOAD_EMPTY` | yes | yes | no | none | no | window |
| Body > endpoint cap | `PAYLOAD_TOO_LARGE` | yes | no (not read past cap) | no | none | no | window |
| HTTP `Date` disagrees > 120 s | `CLOCK_DISAGREEMENT` | yes | yes | no | none | no | operator reset |
| Malformed JSON / BOM / invalid UTF-8 | `JSON_MALFORMED` | yes | yes | no | none | no | window |
| Duplicate JSON key | `JSON_DUPLICATE_KEY` | yes | yes | no | none | no | window |
| NaN/Infinity | `JSON_NONFINITE_NUMBER` | yes | yes | no | none | no | window |
| Nesting > 64 | `JSON_DEPTH_EXCEEDED` | yes | yes | no | none | no | window |
| Root not the expected type (unknown schema/version) | `SCHEMA_ROOT_INVALID` | yes | yes | no | none | no | operator reset (drift) |
| Required metadata pin unavailable (no tournaments/participants/markets/bookmakers capture received before ingestion) | `CATALOG_UNAVAILABLE` | yes | yes | yes | none; terminal for this capture (`ingestion_rejected`). The planner prevents it by scheduling metadata first | — | window |
| Provider outage (repeated transport/5xx) | the per-attempt codes + breaker | yes | as above | no | none | no | window; next window retries naturally |
| Crash between reservation and capture | `ATTEMPT_OUTCOME_UNKNOWN` | yes | unknown | no | none | new attempt ID only in a later window | — |
| Write conflict (`ImmutableConflict`/`RegistryConflict`) | `INGESTION_CONFLICT` | — | — | — | none beyond what was committed | no | operator reset (tampering suspected) |

"Window" = no further calls to that provider for the rest of the current polling window.
"Operator reset" = no calls until an `operator_reset` row (CLI, approval reference required).
Quota reconciliation after a 429: when `/v4/account` is invoked (live smoke or
`reconcile-quota` CLI), `provider.request_count > ledger monthly_used` →
`quota_reconciled(drift=true)` and the breaker opens until operator reset (someone else is
spending the allowance).

### 6.3 Item-level failures (inside a valid response)

| Condition | Code | Effect |
| --- | --- | --- |
| Array element without readable `fixtureId`/`tournamentId`/`seasonId` | `ELEMENT_SCHEMA_VIOLATION` | unattributed rejection; no entity |
| Other required fixture field missing/mistyped | `ELEMENT_SCHEMA_VIOLATION` | event + all its book-markets `QUARANTINED` |
| `sportId` ≠ requested sport | `UNKNOWN_SPORT` | event quarantined if attributable, else unattributed |
| Tournament not allowlisted | — | counted in `excluded.competitions_out_of_scope`; no entity |
| Allowlisted tournament whose catalog entry differs (name/category/slug) or is missing | `COMPETITION_CATALOG_DRIFT` | every event of that competition quarantined |
| Participant ID absent from the pinned participant catalog | `UNKNOWN_PARTICIPANT` | event quarantined |
| `participant1Id == participant2Id` | `PARTICIPANT_IDENTITY_AMBIGUOUS` | event quarantined |
| Same `fixtureId` twice in one payload | `DUPLICATE_EVENT_IN_PAYLOAD` | every copy quarantined |
| Two fixtures in one payload with the same natural key | `DUPLICATE_EVENT_IN_PAYLOAD` | both quarantined + conflict row |
| New `fixtureId` colliding with a known event's natural key (changed provider event ID) | `EVENT_IDENTITY_CONFLICT` | both events quarantined in this and every later document; conflict row |
| Known `fixtureId` whose competition/participants changed | `EVENT_IDENTITY_MUTATION` | event quarantined; conflict row |
| `statusId` 1 or 2 | `EVENT_NOT_PREMATCH` | event observation written with status; no book-market entries (scope rule makes old prices absent) |
| `statusId` 3 | `EVENT_CANCELLED` | event observation with `cancelled_or_postponed`; no book-market entries |
| Unknown `statusId` | `UNKNOWN_EVENT_STATUS` | event quarantined |
| `statusId` 0 but `startTime ≤ received_at` | `EVENT_PAST_KICKOFF` | event quarantined |
| `statusId` 0 but `trueStartTime`/`trueEndTime` set | `CONFLICTING_STATUS` | event quarantined |
| Market ID not in slice-1 mapping | — | counted in `excluded.markets_out_of_slice` |
| Slice market whose pinned catalog definition differs (name/type/period/handicap/outcomes/sport/playerProp) | `MARKET_CATALOG_DRIFT` | every book-market of that family quarantined |
| Bookmaker slug not in the curated table, or not requested | `UNKNOWN_BOOKMAKER` | book's book-markets quarantined |
| `bookmakerIsActive == false` | — | status `BOOK_INACTIVE`, no quotes |
| Unknown key in book/book-market object | `BOOK_SCHEMA_DRIFT` | book-markets quarantined |
| Unknown key in quote object | `QUOTE_SCHEMA_DRIFT` | book-market quarantined |
| Non-empty `exchangeMeta` | `EXCHANGE_DATA_UNSUPPORTED` | book-market quarantined |
| Player key other than `"0"` | `PLAYER_PROP_UNSUPPORTED` | book-market quarantined |
| Outcome ID not in the mapping | `UNKNOWN_OUTCOME` | book-market quarantined |
| Expected outcome missing | `INCOMPLETE_MARKET` | book-market quarantined |
| Invalid price (Section 4.8) | `QUOTE_INVALID_PRICE` | book-market quarantined |
| Overround outside `[0, 0.30]` | `INCOHERENT_PRICES` | book-market quarantined |
| Naive / non-UTC / unparseable timestamp | `TIMESTAMP_INVALID` / `TIMESTAMP_NOT_UTC` | owning entity quarantined |
| Provider time > `received_at + 120 s` | `PROVIDER_TIMESTAMP_FUTURE` | owning entity quarantined |
| Implausible time | `TIMESTAMP_IMPLAUSIBLE` | owning entity quarantined |
| `active == false` on some/all outcomes | — | `PARTIALLY_SUSPENDED` / `SUSPENDED`; `decimal_odds = null` for inactive quotes |
| Fixture-level unknown key | — | `drift` note; not a rejection |

### 6.4 Circuit breaker

State is derived by replaying `breaker_opened` / `operator_reset` rows and window
boundaries from the acquisition ledger; nothing is held only in memory.
Scopes: `WINDOW` (closes at the next planned window), `DAY` (closes at the next UTC
midnight), `OPERATOR` (closes only on `operator_reset` with an approval reference).

### 6.5 Crash recovery (idempotent, never blind)

At run start, the coordinator replays the current and previous acquisition partitions:

- `attempt_started` without `attempt_finished` → append
  `attempt_finished(outcome=OUTCOME_UNKNOWN, failure=ATTEMPT_OUTCOME_UNKNOWN)`. The quota
  unit stays spent. The same `attempt_id` is never reused; a later window may plan the
  request again under a new attempt number.
- `attempt_finished(CAPTURED)` with a raw observation but no `ingestion_committed` /
  `ingestion_rejected` → re-run ingestion using the pins in `ingestion_started` (or pin
  afresh if that row is absent). The document bytes are identical. If an observation of
  that document already exists it is reused. PIT rows whose `record_id` already exists in
  the partition log are skipped; missing ones are appended with a **new** `indexed_at`
  (truthful: they became queryable only now). Then commit.
- Identity appends are idempotent by construction (exact-duplicate rows are not re-appended).

---

## 7. Raw evidence vs canonical data; storage design

### 7.1 What is persisted, where

`<runtime_root>` is operator-configured. Default is `<repo>/runtime/`, which is already in
`.gitignore`. Tests use `scratch_directory()`.

```text
<runtime_root>/adapters/v1/
  shared/
    source-contracts.jsonl              SourceContractRegistry (raw + normalized contracts)
    source-capabilities.jsonl           SourceCapabilityRegistry (operator-written only)
    source-input-bindings.jsonl         SourceInputBindingStore (operator-written only)
  providers/oddspapi/
    run.lock.sqlite3                    single-runner lock
    quota/quota-ledger.jsonl            frozen QuotaLedger (active D-REM-001 policy)
    cache/                              frozen VerifiedCacheStore root (objects/, cache-authority.jsonl)
    acquisition/<YYYY-MM>.jsonl         AcquisitionLedger partitions (UTC month of attempt)
    raw/                                frozen EvidenceStore root for raw provider bytes
    telemetry/<YYYY-MM>.jsonl           JsonlAuditLogger events
    runs/<run_id>.json                  immutable RunReports
  sports/soccer/oddspapi/
    normalized/                         frozen EvidenceStore root for NormalizedSnapshot documents
    identity/registry.jsonl             IdentityRegistry
    pit/<competition_id>/<season_id>.jsonl      PITStore partitions (entity-stable keys)
    coverage/<competition_id>/<season_id>.jsonl CoverageLedger partitions
    coverage/_unattributed/<YYYY-MM>.jsonl      rejections with no attributable partition
```

### 7.2 Must persist vs may derive later

| Must persist (evidence/authority) | May be derived later (never persisted as authority) |
| --- | --- |
| Exact raw response bytes of every HTTP response (except `/v4/account`, see below) | Parsed provider records (`parse()` is pure over raw bytes) |
| Raw observation (contract, redacted URI, received time) | Canonical dataclass objects (from the document) |
| Acquisition ledger rows (attempts, quota charges, capture metadata, ingestion intent/commit, breaker, anomalies) | Foundation projections (`Event`, `MarketSnapshot`) |
| Quota ledger rows and cache objects/authority (frozen, permanent: F9) | Telemetry aggregates and dashboards |
| Normalized documents (bytes + observation) | Re-derivations under a *new* normalizer version, which are new contracts and new PIT sources, never replacements |
| PIT rows, identity registry rows, coverage rows | |
| Run reports | |

`/v4/account` responses may contain personal data. Only `request_limit` and
`request_count` are extracted into a `quota_reconciled` row; the body is not stored.
This is the single documented exception to "store raw".

Why normalized documents are persisted rather than always re-derived: decision-time
admissibility needs a durable, hash-bound observation with its own `parse_ready_at`
(C6/C7, F2). A document re-derived later would be admissible only from its later
derivation time, so it could not reproduce what Genesis knew at the original time.

### 7.3 Growth and partitioning (keeps F5 bounded without weakening audit)

- Each odds call writes 2 evidence observations (raw + document) and about
  `2 × fixtures + scopes` PIT rows. Nothing is written per quote.
- PIT and coverage logs are partitioned by `(competition_id, season_id)`. Both keys are
  **entity-stable**: a fixture's competition and provider season never change without an
  identity conflict. Time-based partitioning is forbidden because it would let the
  frozen manifest verifier accept a head from an older partition while a newer row exists
  in another (it checks head uniqueness within one store only).
- Rough size: about 24k PIT rows per competition-season per bookmaker at 3 polls/day.
  Every append re-verifies at most one season.
- Acquisition ledger and telemetry are month-partitioned. They are operational
  histories, not PIT scopes. Replays read only the current and previous month
  (the cache TTL is at most 30 days).
- Raw storage ≈ 0.1–0.5 MB per odds response. It is duplicated once in the cache store,
  which is mandatory under F9. Order of magnitude: under 100 MB/month at slice-1 volumes.
  Content addressing deduplicates identical bodies. No compression, compaction or
  deletion: bytes must stay exact.
- If the append cost ever exceeds the budget in Section 15 (G11), the remedy is
  extension E-3, not deleting or rewriting logs.

### 7.4 Contracts, capability and binding (runtime data written by the operator CLI)

| Record | Values |
| --- | --- |
| Raw `SourceContract` | `contract.oddspapi.v4.raw.v1`, provider `oddspapi`, source_type `provider_http_response`, uri_pattern `https://api.oddspapi.io/v4/*`, `PROSPECTIVE_CAPTURED`, precision `microseconds`, rule `available_at=received_at`, parser_version `raw-capture-v1`, licensing note `OddsPapi API; terms reverification required; no redistribution`, `supports_prospective_capture=True` |
| Normalized `SourceContract` | `contract.oddspapi.soccer.normalized.v1`, provider `oddspapi`, source_type `normalized_odds_snapshot`, uri_pattern `genesis-derived://oddspapi/soccer/v1/*`, `DERIVED`, precision `microseconds`, rule `available_at=received_at; ready_at=indexed_at`, parser_version `soccer-oddspapi-normalizer-v1`, same licensing note |
| Normalized source URI | `genesis-derived://oddspapi/soccer/v1/<raw_observation_id>` |
| `SourceInputBinding` | `pit.oddspapi.soccer.normalized.v1` ↔ `contract.oddspapi.soccer.normalized.v1`, provider `oddspapi`, approval reference supplied by the operator |
| `SourceCapability` (initial) | source `pit.oddspapi.soccer.normalized.v1`, `operational_status=BLOCKED`, `point_in_time_reliability="unverified"`; promoted to READY **only** by the operator after slice-1 acceptance and a reviewed live smoke (the adapter never self-promotes) |
| `MarketCapability` | not written in slice 1; `market_supported_by_data_adapter` may be set by the operator after acceptance; settlement/liquidity/model/venue remain `None` |

---

## 8. Event and market identity rules

### 8.1 Three kinds of identifier

| Kind | Example | Authority |
| --- | --- | --- |
| Provider-native ID | OddsPapi `fixtureId "id1000001761301153"`, `participant1Id 35`, `tournamentId 17`, market `101`, outcome `102`, bookmaker `"pinnacle"` | The provider; stored verbatim as strings in `ProviderRef` |
| Genesis canonical ID | `gevt_…`, `gpart_…`, `gmkt_…` | Deterministic minting (8.2) plus the identity registry |
| Mapping record | `identity_mapping` row: `(domain, provider_id, native_id) → canonical_id, method, first_seen_at, first_seen_raw_observation_id` | Identity registry, append-only |

Display names are never identity. They are stored as observed attributes only.

### 8.2 Deterministic minting (`ids.py`)

`mint(kind, *parts) = genesis.canonical.stable_id(PREFIX[kind], ID_DOMAIN, kind, *parts)`.
Every part must be a non-empty printable-ASCII string of at most 128 characters without
`|`, otherwise `IdentityError`. The output is `<prefix>_<24 hex>` and satisfies the document key regex.

| Canonical ID | Formula | Prefix |
| --- | --- | --- |
| competition | `mint("competition", sport, provider_id, tournament_id)` | `gcomp` |
| season | `mint("season", competition_id, provider_id, season_id)` | `gseas` |
| participant | `mint("participant", sport, provider_id, participant_id)` | `gpart` |
| event | `mint("event", sport, provider_id, fixture_id)` | `gevt` |
| bookmaker | `mint("bookmaker", curated_key)` (provider-independent) | `gbook` |
| market | `mint("market", event_id, family, period, line or "none")` | `gmkt` |
| selection | `mint("selection", market_id, outcome_code)` | `gsel` |
| book-market | `mint("book_market", market_id, bookmaker_id)` | `gbm` |
| listing scope | `mint("scope", endpoint_id, bookmaker_id, competition_id, season_id)` | `gscope` |
| PIT row | `mint("pit", pit_source_id, entity_id, raw_observation_id)` | `gpit` |
| coverage entry | `mint("coverage", document_artifact_hash, event_id)` | `gcov` |
| run | `mint("run", provider_id, started_at, plan_digest)` | `grun` |
| attempt (= quota request ID) | `mint("attempt", run_id, window_id, provider_request_hash, str(attempt_no))` | `gatt` |

Canonical participant, competition and event IDs are anchored to the **first provider
that introduced them** (slice 1: OddsPapi). A second provider maps *onto* existing
canonical IDs through mapping rows. It never re-mints them. Slice 1 implements only
`method="deterministic_mint"`.

### 8.3 Rules by case

- **Same event, multiple bookmakers.** One `event_id` and `market_id`, and one
  `book_market_id` per bookmaker. A bookmaker's absence is inferred per listing scope.
- **Same event, multiple providers (later).** A second provider's fixture maps to an
  existing `event_id` only through a mapping row with method `exact_shared_id`
  (both providers expose the same upstream ID) or `operator_confirmed` (approval
  reference). Automatic fuzzy matching is not permitted to create mappings; it may only
  *propose* them. Until mapped, the second provider's events are distinct entities.
- **Team/player aliases.** Identity comes from provider IDs. Aliases (name variants) are
  display data; cross-provider participant mapping follows the same rule as events.
- **Rescheduled events.** Same `fixtureId` → same `event_id`; `scheduled_start_at` changes
  in the next observation; the registry appends `event_seen`. Old observations keep the
  old time.
- **Abandoned/postponed/cancelled.** `statusId 3` → `cancelled_or_postponed`. The provider
  does not distinguish these, so neither does Genesis. A replayed match that the provider
  lists under a new `fixtureId` within ±7 days of the original kickoff is an identity
  conflict (fail closed), not an automatic continuation.
- **Neutral venue.** Unknown in slice 1 (`venue_neutral: null`). Outcome codes are
  defined relative to participant order (`p1`/`p2`), never "home/away", so neutral venues
  cannot mislabel a selection.
- **Competitions with similar names.** Identity is the provider tournament ID.
  The allowlist pins `(id, name, category)` and each must match the pinned catalog
  (for example "Premier League" under category "England", not another country's league
  of the same name). The slug is recorded, not compared.
- **Player name collisions.** Player markets are out of slice 1. Later rule: player
  identity = provider player ID plus team plus provider participant catalog, never name.
- **Market naming differences.** A market's meaning is the provider catalog definition
  (`marketId`, `marketType`, `period`, `handicap`, `outcomes`, `sportId`, `playerProp`) matched
  field-by-field against the pinned mapping. Names are compared only as a drift signal.
- **Alternate lines.** Line is part of `market_id`. OddsPapi encodes lines as distinct
  market IDs carrying `handicap`. The mapping table must enumerate each supported
  `(marketId → family, line)`. Main vs alternate classification is unknown until verified
  and is not inferred.
- **Bookmaker-specific selections.** `bookmakerOutcomeId`/`bookmakerMarketId` are provider
  references only. Selection identity comes from the canonical outcome code.
- **Sportsbook vs exchange.** Bookmaker kind comes from the curated table. Exchange
  back/lay, size and commission are separate future fields. Exchange quotes are rejected in slice 1.

### 8.4 Natural-key conflict rule

The natural key is `(competition_id, participant1_id, participant2_id)`. A fixture is in
conflict if another `event_id` with the same natural key has a last-seen
`scheduled_start_at` within ±7 days. Detection uses the pinned `IdentitySnapshot`, so it
is deterministic. The first detection appends `identity_conflict`. Both events stay
quarantined in every later document until a future slice implements operator
resolution. Slice 1 provides no resolution path, which is deliberately conservative.

---

## 9. Cost, quota and cache strategy

### 9.1 Endpoint catalog v1 (`sources/oddspapi/endpoints.py`)

All values are **planning assumptions from public docs** (`terms_verified=False`) until
the operator records verification.

| endpoint_id | Path | Metered | Units | Cooldown | Cache TTL | Max bytes | Params (fixed) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `oddspapi.v4.odds_by_tournaments` | `/v4/odds-by-tournaments` | yes | 1 | 2000 ms | 15 min | 16 MiB | `bookmaker`, `tournamentIds` (≤5 IDs); fixed `oddsFormat=decimal` |
| `oddspapi.v4.tournaments` | `/v4/tournaments` | yes | 1 | 1000 ms | 7 d | 4 MiB | `sportId`; fixed `language=en` |
| `oddspapi.v4.participants` | `/v4/participants` | yes | 1 | 1000 ms | 7 d | 32 MiB | `sportId`; fixed `language=en` |
| `oddspapi.v4.markets` | `/v4/markets` | yes | 1 | 1000 ms | 30 d | 8 MiB | fixed `language=en` |
| `oddspapi.v4.bookmakers` | `/v4/bookmakers` | yes | 1 | 1000 ms | 30 d | 4 MiB | none |
| `oddspapi.v4.account` | `/v4/account` | **yes (conservative)** | 1 | 1000 ms | none | 64 KiB | none; used only by live smoke / `reconcile-quota` |

Excluded in slice 1: `/v4/fixtures`, `/v4/fixture`, `/v4/odds`, `/v4/historical-odds`,
`/v4/settlements` and `/v4/scores` (settlements and scores are future labels, forbidden in
decision paths), and the WebSocket API.

### 9.2 Quota integration (frozen authority, unchanged)

- Operational runs construct `QuotaLedger(<quota path>,
  policy=load_quota_policy("config/oddspapi_quota_policy_v2.json"), cache_store=<the
  provider's VerifiedCacheStore>)`. `load_quota_policy` (default `require_active=True`) and the
  ledger constructor both enforce D-REM-001 (250/220/30/7). Do **not** use
  `QuotaLedger.from_active_config`: it attaches no cache store, and a ledger with
  cache-hit history then fails replay (`quota.py:582-588, 755-757`). Tests use
  `QuotaPolicy.test_fixture(QuotaInterpretation.A, provider_monthly_allowance=250,
  normal_monthly_budget=220, reserve_units=30, daily_billable_budget=7)` with
  `allow_test_policy=True` and a cache store.
- One ledger file per provider allowance for the whole deployment. The adapter is the
  only OddsPapi caller.
- `request_id` = `attempt_id` (deterministic). `occurred_at` = the stamped `quota_occurred_at`.
- The adapter only uses `BudgetClass.NORMAL`. Reserve use requires an operator-granted
  `QuotaReserveAuthorization` and an explicit CLI flag. The coordinator never escalates.
- Exhaustion (any blocked reason) → no call → no new observation → downstream decisions
  see aging heads and PASS (`BLOCK_NEW_ODDS_DEPENDENT_DECISIONS`).

### 9.3 Cache identity and semantics

- Cache key = `f"{endpoint_id}:{provider_request_hash}"`. The request hash covers the
  host, path and sorted params (credential excluded), so any scope change is a
  different entry.
- Entries are published only for HTTP 200 with a valid envelope (`captured_at =
  received_at`, `expires_at = received_at + ttl`), bound to the active policy digest.
- Lookup: the acquisition ledger's `attempt_cached` rows are the index (newest entry for
  the hash within the current and previous partitions). The frozen ledger decides
  validity at `occurred_at`. The adapter never trusts its own index alone.
- A cache hit costs 0 units and creates no observation (5.4). For catalog endpoints the
  hit's bytes (original raw observation) remain the metadata pin. For odds endpoints a
  hit means the capture was already ingested. This is duplicate-request suppression.
- Invalidation: `VerifiedCacheStore.invalidate` is used only by the operator CLI (for example
  after detected drift). There is no automatic invalidation.

### 9.4 Polling policy v1 (UTC; `ingestion/plan.py`)

| Window | Time | Billable requests |
| --- | --- | --- |
| `W1 global_morning_inventory` | 07:30 | odds-by-tournaments(pinnacle; 17,8); Mondays also tournaments(sportId=10) + participants(sportId=10); on the 1st also markets + bookmakers |
| `W2 europe_midday` | 12:30 | odds-by-tournaments(pinnacle; 17,8) |
| `W3 europe_pre_event` | 17:30 | odds-by-tournaments(pinnacle; 17,8) |
| `W4 flexible_retry_or_targeted_refresh` | 20:30 | at most 1 request: a participants refresh if the previous windows recorded `UNKNOWN_PARTICIPANT`, or the odds request if W3 failed; otherwise nothing |

Static checks at plan build (fail closed, `CONFIG_INVALID`):

- the worst-case day (a Monday that is the 1st: 3 odds + 4 metadata = 7, plus a W4
  request) must not exceed 7. The planner resolves this by letting W4 run only if the
  ledger's `daily_used ≤ 6` at W4 time. The ledger remains the hard stop.
- the projected month (`30 × 3 odds + 4.4 × 2 weekly + 2 monthly + 30 × W4 upper bound`)
  must be ≤ 220 − 10 headroom. With the W4 bound this is 90 + 9 + 2 + 30 = 131 ✓.
- the plan never references an excluded endpoint, a reserve budget or a non-allowlisted tournament.
- an odds request is planned only if all four metadata catalogs already have a captured
  pin or are scheduled earlier in the same window; otherwise the metadata requests are
  inserted first (bootstrap day) or the odds request is dropped (`CONFIG_INVALID` recorded).

Expected typical use: about 100 billable calls/month (about 45% of the normal budget),
leaving headroom for later sports under the same allowance.

### 9.5 Backoff, retry, duplicate suppression, observability of cost

- Metered endpoints: `max_attempts=1`. The next scheduled window is the retry.
- Unmetered endpoints (none in slice 1 until the operator verifies one): up to 3 attempts
  with a deterministic `(2, 4)` second backoff, only for `TRANSPORT_*` and `HTTP_SERVER`.
- 429: no retry; `DAY` breaker (6.2).
- Duplicate suppression: the cache (9.3), plus the run lock (one runner per provider),
  plus deterministic attempt IDs (a replayed attempt ID with a different fingerprint is
  refused by the frozen ledger).
- Cost is visible in every `attempt_finished` (`QuotaCharge`), in run reports, and in
  telemetry (`quota_daily_used/remaining`, `quota_monthly_used/remaining`,
  `billable_units_consumed`, `provider_reported_request_count`).

---

## 10. First vertical slice

### 10.1 Source evaluation (including The Odds API, independently)

| Criterion | OddsPapi (oddspapi.io) | The Odds API (the-odds-api.com) |
| --- | --- | --- |
| Project intent | Named in `PROJECT_LAWS_v0.4.md`, `RUNTIME_AND_COST_TARGET_v0.4.md`, `ODDSPAPI_BUDGET_DRAFT.yaml`, D-REM-001 | Not named anywhere in the repository |
| Frozen quota authority | **Works unchanged** (`require_operational` binds `oddspapi`) | **Cannot be quota-governed operationally** without extension E-1 |
| Free allowance | 250 requests/month (matches the approved assumption) | 500 credits/month; odds cost = markets × regions |
| Metering transparency | No usage headers; free `/v4/account` counters (metering status unverified); every call charged regardless of status | `x-requests-remaining/used/last` headers on every response; empty responses free |
| Timestamp/provenance quality | Per-outcome `changedAt` (µs), fixture `updatedAt`, `startTime`, `trueStartTime/EndTime` | Per-bookmaker and per-market `last_update`, `commence_time` |
| Identity | Numeric participant/tournament/season IDs, fixture IDs, market/outcome catalogs | Event ID plus **team names only** (identity would need a curated alias table) |
| Authentication | `apiKey` query parameter | `apiKey` query parameter |
| Documentation | Adequate; some fields/rate limits under-specified | Good, stable, widely used |
| Market richness | 350+ bookmakers incl. exchanges; many markets; lines as catalog IDs | h2h/spreads/totals/outrights by region; fewer bookmakers per call |
| Normalization complexity | Moderate (nested maps keyed by IDs) | Low (flat lists) |
| Breadth per call | `odds-by-tournaments`: 1 bookmaker × many tournaments; `/odds`: all bookmakers × 1 fixture | 1 sport × N bookmakers per region-market credit |
| Deterministic testability | Good (ID-keyed, catalog-driven) | Good |
| Template value | High: ID-based identity + catalog drift checks generalize | Medium: name-based identity is the harder, less reusable path |

**Recommendation: OddsPapi first.** The deciding factors are the frozen quota authority
(F1) and ID-based identity. The Odds API is technically attractive: better metering
transparency, free inventory endpoints, cheaper broad h2h coverage. It is recommended as
the **second** source, for cross-provider validation and as a fallback. That requires extension
E-1 and a separately approved quota policy for its allowance.

### 10.2 Sport evaluation

| Sport | For | Against (for slice 1) |
| --- | --- | --- |
| **Football (soccer)** | Blueprint §22.2 says develop early; largest daily coverage; 1X2 is simple and well-defined; OddsPapi IDs and catalog cover it; leagues have no neutral venues or extra time | Draw outcome (three-way) is slightly richer than two-way; this is a *good* template test |
| Horse racing | High long-term value (§22.1) | Hoofs/Race Shape/Betfair semantics unverified; non-runners, going, declarations and dead heats make identity and settlement hard; poor first template |
| Tennis | Good early candidate (§22.3) | Player identity and retirement/walkover semantics; better as slice 2+ |
| Basketball/baseball | Later sports (§22.4) | Out of blueprint order |

### 10.3 Slice-1 decision

| Item | Choice |
| --- | --- |
| Source | OddsPapi API v4 (read-only) |
| Sport | Soccer |
| Competitions | England Premier League (`tournamentId 17`) and Spain LaLiga (`tournamentId 8`), requested together in one `odds-by-tournaments` call. Pinned expectations (slug/name/category) are recorded from the first reviewed live `tournaments` capture; until then the fixture catalog carries the documented examples and the competition check fails closed |
| Bookmaker | `pinnacle` (curated key `pinnacle`, kind `SPORTSBOOK`): documented example, sharp reference. This is a data choice, not a venue or betting choice |
| Market | `soccer.full_time_result_1x2`: OddsPapi market `101` "Full Time Result", `marketType 1x2`, `period fulltime`, `handicap 0`, `playerProp false`, `sportId 10`; outcomes `101→p1`, `102→draw`, `103→p2` |
| Status | Pre-match only (`statusId 0`, `startTime > received_at`) |
| Why two leagues | Proves multi-competition batching, partitioning and competition identity at zero extra quota cost |

**Intentionally excluded from slice 1:** every other market (BTTS 104, totals,
handicaps/lines, player props), exchanges and lay prices, additional bookmakers
(the design supports N, but slice 1 requests 1), in-play/live odds, `/v4/odds` per-fixture
multi-book depth, historical odds and backfill (`historical_reconstructed`),
settlements/scores/results (future labels), WebSocket streaming, cross-provider
mapping, identity-conflict resolution, any decision, candidate, strategy, model,
price-sanity or risk integration, cloud scheduling (windows are executed by an
operator or cron-like runner; no deployment).

Recommended slice 2: add the totals 2.5 line market (validates line identity) and the
`/v4/odds` per-fixture multi-bookmaker endpoint (validates N-bookmaker scopes).

---

## 11. Exact repository/file structure

Target: no module over about 400 lines. Every `.py` and `.json` file is LF.

```text
src/genesis_adapters/                      NEW top-level package (sibling of src/genesis; F7)
  __init__.py                              version constants re-export only
  versions.py                              Section 4.2 constants
  errors.py                                FailureCode, RejectionCode, ItemScope, exception types, REASON_CODE_MAP
  clock.py                                 AcquisitionClock, SystemUtcClock, require_not_ahead, ClockWitness
  jsonstrict.py                            decode_strict(): exact Decimal numbers, dup-key/NaN/depth/size/BOM rejection
  ids.py                                   mint(), PREFIX table, key regex validation
  acquisition/
    __init__.py
    contracts.py                           EndpointSpec, RetryPolicy, ProviderRequest, Secret, CredentialProvider,
                                           HttpCapture, TransportFailure, AttemptOutcome, QuotaCharge, LiveNetworkPermit
    transport.py                           HttpTransport protocol, UrllibTransport (ONLY network module)
    credentials.py                         EnvironmentCredentialProvider (GENESIS_<PROVIDER>_API_KEY)
    ratelimit.py                           per-endpoint cooldown gate (clock + injectable sleeper)
    quota_gate.py                          wraps frozen QuotaLedger + VerifiedCacheStore; cache index lookup
    ledger.py                              AcquisitionLedger (month partitions over AppendOnlyJsonl); row builders/replay
    breaker.py                             breaker state replay + decisions
    runlock.py                             SQLite single-runner lock
  sources/
    __init__.py
    base.py                                SourceAdapter protocol, ParseFailure, DriftNote, ElementIssue
    oddspapi/
      __init__.py
      endpoints.py                         endpoint catalog v1 (Section 9.1)
      request.py                           build_request, redaction, request hash
      classify.py                          HTTP/envelope -> FailureCode
      records.py                           OP* provider-native dataclasses, catalogs, AccountStatus
      parse_odds.py                        odds-by-tournaments parser (closed-schema policy, 4.6)
      parse_catalogs.py                    tournaments/participants/markets/bookmakers/account parsers
      adapter.py                           OddsPapiSource implementing SourceAdapter
  sports/
    __init__.py
    base.py                                SportAdapter protocol, CatalogPins, IdentitySnapshot, NormalizationContext,
                                           NormalizationResult, IdentityAppend, NormalizationPolicy
    soccer/
      __init__.py
      semantics.py                         families, outcome codes, selection invariants, price/overround bounds
      oddspapi_map.py                      market/outcome/status maps, competition allowlist, curated bookmakers
      normalize.py                         pure normalize() for OddsPapi odds listings
      adapter.py                           SoccerOddsPapiAdapter implementing SportAdapter
  canonical/
    __init__.py
    records.py                             Section 4.7 records and enums
    document.py                            NormalizedSnapshot builder + closed-schema validator (4.9)
    odds.py                                Section 4.8 decimal/implied/overround functions
    projection.py                          Section 4.12 projections to genesis.canonical
  identity/
    __init__.py
    registry.py                            IdentityRegistry (AppendOnlyJsonl) + snapshot at head
  evidence/
    __init__.py
    layout.py                              StorageLayout (Section 7.1) and partition keys
    source_contracts.py                    exact SourceContract constants for raw/normalized
    writers.py                             raw capture publish, normalized publish, PIT row builder/appender, coverage
    provenance.py                          verify_chain(); ProvenanceError
    reader.py                              CanonicalReader (Section 5.3)
  ingestion/
    __init__.py
    plan.py                                PollingPolicy v1, AcquisitionPlan, static budget checks, plan digest
    coordinator.py                         IngestionCoordinator (Section 3.3, 6.5)
    results.py                             IngestionResult, RunReport, metric names
  telemetry.py                             counters + JsonlAuditLogger emission (write-only)
  cli/
    __init__.py
    __main__.py                            `python -m genesis_adapters.cli <command>` dispatcher
    bootstrap.py                           register contracts, binding (--approval-reference), capability BLOCKED
    capability.py                          promote/demote capability (--approval-reference, --evidence run report)
    run_window.py                          execute one polling window (live; requires permit)
    live_smoke.py                          explicit capped live smoke (Section 12.6)
    reconcile_quota.py                     /v4/account reconciliation (charged conservatively)
    operator_reset.py                      breaker reset (--approval-reference)
    verify_freeze.py                       frozen-foundation gate (Section 15, G1)
    report.py                              read-only usage/run summaries

tests/adapters/                            NEW test sub-package (discovered by default)
  __init__.py
  support.py                               FakeTransport, SteppingClock, FakeCredentials, fixture loaders, store builders
  fixtures/oddspapi/                       synthetic provider-shaped payloads (bytes pinned; -text)
    odds_ok_epl_laliga_pinnacle.json
    odds_suspended_partial.json            odds_missing_outcome.json        odds_unknown_participant.json
    odds_duplicate_fixture.json            odds_natural_key_collision.json  odds_future_changed_at.json
    odds_clock_ahead_within_tolerance.json odds_non_utc_timestamp.json      odds_naive_timestamp.json
    odds_quote_unknown_field.json          odds_fixture_unknown_field.json  odds_exchange_meta.json
    odds_player_prop.json                  odds_live_status.json            odds_cancelled.json
    odds_past_kickoff.json                 odds_conflicting_status.json     odds_negative_overround.json
    odds_invalid_price.json                odds_book_inactive.json          odds_unknown_bookmaker.json
    odds_out_of_scope_tournament.json      odds_empty_array.json            odds_root_object.json
    odds_truncated.bin                     odds_duplicate_key.bin           odds_nan.bin
    odds_bom.bin                           odds_rescheduled_a.json          odds_rescheduled_b.json
    odds_absent_second_listing.json        cat_tournaments.json             cat_tournaments_drift.json
    cat_participants.json                  cat_markets.json                 cat_markets_drift_101.json
    cat_bookmakers.json                    account.json
  fixtures/expected/
    normalized_ok.json                     exact expected document bytes (canonical_json)
    normalized_ok.sha256                   expected document digest
    <case>.rejections.json                 expected rejection lists per negative fixture
  test_adapters_boundaries.py              import/AST boundary, forbidden names, no network outside transport
  test_adapters_jsonstrict.py
  test_adapters_clock.py
  test_adapters_ids.py
  test_adapters_odds_arithmetic.py
  test_adapters_request.py                 request building, redaction, hash stability, credential never in URI/hash
  test_adapters_transport_fake.py          UrllibTransport refuses without permit; sanitization; redirect refusal (local stub)
  test_adapters_oddspapi_parse.py
  test_adapters_oddspapi_catalogs.py
  test_adapters_soccer_normalize.py        item-level cases (Section 6.3)
  test_adapters_golden.py                  payload -> exact expected document bytes
  test_adapters_document_schema.py
  test_adapters_identity_registry.py
  test_adapters_evidence_binding.py        raw/normalized publish, PIT rows, provenance chain, tamper
  test_adapters_reader_pit.py              as-of semantics, scope absence, stale, capability gating
  test_adapters_quota_cache.py             frozen QuotaLedger/VerifiedCacheStore integration
  test_adapters_coordinator.py             mocked-provider integration, failures, breaker, recovery
  test_adapters_properties.py              seeded property/invariant tests (Section 12.3)
  test_adapters_foundation_compat.py       frozen FeatureInputManifest/PITStore/projection compatibility
  test_adapters_cli_guards.py              live smoke/run_window refuse without explicit env/permit; offline only
  test_adapters_telemetry.py

DECISIONS/ADR-0005-v05-read-only-adapter-boundary.md   NEW, status PROPOSED (human approval note separate)
remediation_evidence/V05/slice1/<stage>/                NEW RED/GREEN transcripts, decisions log, gate outputs
.gitattributes                                          APPEND ONLY: `tests/adapters/fixtures/** -text`
```

**Existing modules consumed (read-only, public API only):** `genesis.time`, `genesis.repro`,
`genesis.registry` (`AppendOnlyJsonl`, `RegistryConflict`), `genesis.provenance`,
`genesis.evidence` (`EvidenceStore`), `genesis.pit`, `genesis.feature_manifest`
(`SourceInputBindingStore`; `FeatureInputManifestStore` in the compatibility test only),
`genesis.quota`, `genesis.coverage`, `genesis.reasons`, `genesis.logging`,
`genesis.canonical`, and (compatibility test only) `genesis.evidence_pack`.

**Forbidden imports in `genesis_adapters` (enforced by test):** `genesis.risk`,
`genesis.execution`, `genesis.selection`, `genesis.selection_evaluation`,
`genesis.policy`, `genesis.decision`, `genesis.decision_output`, `genesis.ledger`,
`genesis.accounting`, `genesis.release_proof`, `genesis.owner_binding`,
`genesis.composition`, `genesis.protected*`, `genesis.evaluation`, `genesis.labels`,
`genesis.candidate_runs`, `genesis.capabilities` (market capability is operator data,
written in a later slice), and any third-party package. `urllib`, `http`, `socket` and `ssl`
may be imported only in `acquisition/transport.py`. Private foundation attributes
(`_replay`, `_verify_bytes`, `_records`, `_validate_contract`, …) must not be used; only the
public methods and the public `log.records()` may be.

---

## 12. Test strategy

All tests are stdlib `unittest`, use `tests._support.scratch_directory()` for file-backed
stores, never touch the network, and finish the whole adapter sub-suite in under 90 s.

### 12.1 Unit tests

- **jsonstrict:** exact decimal text preserved (`5.010`, `1.649`); exponent literal
  rejected; duplicate key, NaN/Infinity, BOM, invalid UTF-8, depth 65, size cap+1 all
  rejected with the right `FailureCode`; `true` is not accepted as an int.
- **clock:** strict monotonicity; regression raises; sub-millisecond equality waits then
  succeeds; durable-ahead boundary exactly at `+120 s` passes and `+120 s + 1 µs` fails; HTTP
  Date parsing (RFC 7231 only) and skew rounding.
- **ids:** every formula in 8.2; `|`/empty/non-ASCII/over-long parts rejected; prefixes;
  key regex; no two kinds share a prefix.
- **odds arithmetic:** 4.8 rules at the boundaries (1.0, 1.0001, 1000, 1000.0001, 4 vs 5 dp);
  implied/overround quantization; `ROUND_HALF_EVEN` cases.
- **request:** param sorting, fixed params, unknown or missing param → `CONFIG_INVALID`;
  `apiKey` can never be supplied as a param; redacted URI golden strings; request-hash
  golden values; changing any scope element changes the hash.
- **parsing:** each closed-schema rule in 4.6; drift notes; element issues; catalogs.
- **timestamps:** `Z`, `+00:00`, milli/micro precision → the same `iso_utc`; non-UTC and
  naive rejected; implausible bounds.
- **normalization cases:** one test per row of Section 6.3 using the named fixtures;
  every negative case asserts the quarantined status, empty quotes, the exact codes, and
  that no ACTIVE quote exists for the affected entity.
- **errors:** `REASON_CODE_MAP` is total over both enums and maps only to existing `ReasonCode` members.

### 12.2 Golden fixtures

- The fixtures are **synthetic**, hand-authored to the documented OddsPapi v4 shapes (F14).
  Real provider payloads are never committed, because redistribution terms are unverified.
- `test_adapters_golden.py`: for `odds_ok_epl_laliga_pinnacle.json` with the catalog fixtures
  pinned, `normalize()` must produce bytes equal to `fixtures/expected/normalized_ok.json`,
  and `sha256` must equal `normalized_ok.sha256`. The expected file is produced once by the
  implementation, reviewed by hand against this document (every field), and committed. From
  then on it only changes with a normalizer version bump.
- The golden content must cover: 3 EPL + 2 LaLiga fixtures; one fixture with market 104
  (excluded, counted); one partially suspended market; one bookmaker-inactive case; one
  quote within the clock-ahead tolerance; the two-season case (one fixture whose `seasonId`
  differs); participant display names from the catalog.
- Golden fixture bytes are pinned: `.gitattributes` `-text`, and a test asserts each fixture's
  SHA-256 against a committed `fixtures/MANIFEST.sha256`.

### 12.3 Property and invariant tests (seeded `random.Random(20260928 + n)`, ≥200 cases each)

1. **Determinism:** the same raw bytes and pins, normalized twice in separate processes
   (spawn) → identical document bytes.
2. **Order invariance:** permuting the fixture array order and the object key order in
   the raw JSON changes the raw hash but leaves `events`, `book_markets`, `scopes`,
   `rejections`, `excluded` and `competitions` byte-identical.
3. **ID determinism/injectivity:** random provider IDs → stable IDs; distinct inputs →
   distinct IDs within and across kinds; minting is independent of call order.
4. **PIT monotonicity:** a random sequence of 3–12 observations of overlapping entities
   (strictly increasing received times, random suspensions and absences) is ingested; for
   random T the reader equals a brute-force oracle (latest admissible, with the scope
   absence rule); the answer at every earlier T is byte-identical before and after
   ingesting later observations.
5. **No future leakage:** for every T, every returned provenance has
   `received_at ≤ T`, `derived_at ≤ T`, `indexed_at ≤ T`.
6. **Immutability:** random single-byte tampering of any stored raw object, normalized
   object, observation JSON or JSONL row → reader returns `PROVENANCE_BROKEN` or the
   frozen store raises; it never returns a view.
7. **Provenance preservation:** every canonical book-market reachable through the reader
   verifies back to the raw bytes, and its quotes' `raw_price_text` equals the raw JSON literal.
8. **Fail-closed mutation:** random mutations of the golden payload (drop a required key,
   change a type, future-date a timestamp, add an unknown quote key, duplicate a fixture,
   corrupt a price) never yield an `ACTIVE` quote for the mutated entity.
9. **Cache/PIT separation:** interleaving cache hits with fresh captures never changes
   PIT heads on a hit.

### 12.4 Integration tests (mocked provider, real file-backed frozen stores)

`FakeTransport` returns scripted `HttpCapture`/`TransportFailure` values keyed by request
hash and call order, and records every call. Scenarios:

1. Full W1 on a Monday the 1st: 4 metadata + 1 odds; stores, ledger rows, PIT rows,
   coverage, telemetry and run report all consistent; quota `daily_used == 5`.
2. Repeat within the TTL: 0 HTTP calls, `verified_cache_hit` rows, no new observations or PIT rows.
3. Quota: the 8th billable request in a day is blocked by the frozen ledger before
   `FakeTransport.send` is called; normal budget exhaustion at 220; reserve never used.
4. Transport timeout on a metered call: charged, no retry, `WINDOW` breaker after the second.
5. 429: `DAY` breaker; next-day run proceeds.
6. 401: `OPERATOR` breaker; `operator_reset` clears it.
7. 3xx: `HTTP_UNEXPECTED`, `OPERATOR` breaker, no follow.
8. HTTP Date skew 121 s: raw stored, no document, `OPERATOR` breaker.
9. Crash injection (an exception raised after each numbered step 10–19 of 3.3, via an injected
   hook in the test only): rerun completes; exactly one document observation, no duplicate
   PIT `record_id`, all PIT rows present, identity rows not duplicated, counts equal to a crash-free run.
10. Crash between quota reservation and HTTP (step 8→9): `OUTCOME_UNKNOWN`; unit stays spent;
    no reuse of the attempt ID.
11. Clock regression mid-run and future-dated ledger at start → refusal before any quota write.
12. Credential missing → no quota reservation, `CREDENTIAL_MISSING`.
13. Source/sport composition: the coordinator dispatches by `(provider, sport)`; an
    unregistered sport or a plan naming an unknown endpoint fails at plan validation with zero IO.
14. Credential hygiene: after scenarios 1–12 with the fake key `TEST-KEY-9f2c…`, a scan of
    every file under the runtime root and every log line finds no occurrence of the key.
15. Absence: `odds_absent_second_listing.json` after `odds_ok…` → the reader returns
    `ABSENT_FROM_LATEST_LISTING` for the dropped book-market at T after the second listing,
    and the original view at T between them.
16. Reschedule: `odds_rescheduled_a` then `_b` → same `event_id`, new `scheduled_start_at` head,
    one `event_seen` change row, no conflict.
17. Collision: `odds_natural_key_collision.json` after `odds_ok…` → both events quarantined now
    and in a later clean listing; one conflict row.

### 12.5 Foundation compatibility tests (prove "no frozen change needed")

- Build a synthetic `FeatureInputManifest` whose required inputs are one book-market PIT
  row and its scope row. Build a `ResearchEvidence` over the normalized observation and an
  `EvidencePack` (test-only), then call the **frozen** `FeatureInputManifestStore.verify_for_pack`
  unchanged. It must pass, and fail when the capability is BLOCKED, when the cutoff is before
  `indexed_at`, or when a later row exists.
- `PITStore.as_of_query` over adapter partitions honors capability gating
  (`SourceUnavailable` when BLOCKED/absent).
- Projections construct valid frozen `Event`, `Participant` and `MarketSnapshot` objects
  (their own `__post_init__` validation passes) for every ACTIVE quote in the golden document.
- The coverage ledger accepts every adapter coverage entry.

### 12.6 Live smoke (explicit, read-only, never discovered)

- Module: `python -m genesis_adapters.cli live_smoke --confirm-read-only-live
  --runtime-root <dir> [--max-billable 4]`.
- Refuses unless **all** hold: env `GENESIS_ADAPTER_LIVE=1`; env `GENESIS_ODDSPAPI_API_KEY`
  present; `--confirm-read-only-live`; `--max-billable` ≤ 5; the active quota policy loads via
  `load_quota_policy` (D-REM-001, Section 9.2); the ledger shows `daily_used + max_billable ≤ 7`;
  `verify_freeze` passes.
- Requests, in order: markets, tournaments(10), participants(10), odds-by-tournaments(pinnacle;
  17,8) = 4 billable. With `--with-account`, it also calls `/v4/account` (+1, conservative) and
  reconciles provider `request_count` against the ledger.
- Success is **structural only**: all 200s; no response-level failure; catalog drift checks
  pass (or the run reports `CATALOG_DRIFT` for human review, with no code change); the
  document validates; the clock witness is OK; zero credential occurrences on disk. Zero
  fixtures (off-season) → `INCONCLUSIVE`, not failure. It never asserts specific odds, fixtures or counts.
- Output: a run report path and a human summary. The captured raw bytes remain in the
  runtime evidence store for the operator's schema review. They are never copied into `tests/`.
- A guard test (`test_adapters_cli_guards.py`) proves the refusals offline with `FakeTransport`.
  No test constructs `UrllibTransport` with a real permit.

---

## 13. Observability

Telemetry is write-only. No normalization, identity, PIT, reader or decision code imports
`telemetry.py` or reads telemetry files (import-boundary test). Metrics are counters in the
`RunReport` and per-attempt `LogEvent`s (`component="genesis_adapters.oddspapi"`,
`mode="offline_research"`), emitted through the frozen `JsonlAuditLogger` (which redacts
`api_key`/`token`/… keys).

| Metric | Definition |
| --- | --- |
| `requests_attempted` | attempts that reached the quota decision |
| `requests_succeeded` | captures with HTTP 200 and valid envelope |
| `requests_failed.<FailureCode>` | per code |
| `requests_skipped.<reason>` | breaker/credential/clock skips |
| `cache_hits` | `verified_cache_hit` decisions |
| `quota_blocked.<ledger reason>` | per blocked reason |
| `retries` | attempts with `attempt_no > 1` |
| `billable_units_consumed` | sum of charged units in the run |
| `quota_daily_used`, `quota_daily_remaining`, `quota_monthly_used`, `quota_monthly_remaining`, `quota_reserve_used` | from the frozen ledger after the run |
| `provider_reported_request_count`, `provider_request_limit`, `quota_drift` | from reconciliation, when run |
| `raw_snapshots_captured`, `raw_bytes_captured` | raw observations published |
| `normalized_documents_published` | |
| `canonical_events_produced`, `events_quarantined` | |
| `book_markets_produced.<status>` | per `BookMarketStatus` |
| `quotes_active` | |
| `observations_rejected.<RejectionCode>` | item rejections per code |
| `stale_flags` | quotes with `provider_stale_flag` |
| `clock_ahead_flags`, `clock_skew_ms_max` | |
| `unknown_mappings.<domain>` | unknown participant/competition/bookmaker/outcome |
| `schema_drift.<path>` | drift notes and schema-drift rejections |
| `identity_conflicts` | new conflict rows |
| `pit_rows_written`, `coverage_rows_written` | |
| `latency_ms_max.<endpoint>`, `latency_ms_sum.<endpoint>` | request_started_at → received_at |
| `ingestion_ms_max` | received_at → commit |
| `breaker_opened.<scope>` | |

Alert conditions for later deployment (documented; not implemented in slice 1): any
`OPERATOR` breaker; `quota_monthly_remaining < 40`; `schema_drift` > 0 at a price-adjacent
path; the golden live smoke is not green within 14 days before capability READY.

---

## 14. Implementation sequence (for Sonnet 5.5)

Each stage: write the tests first and record RED (import/assertion failures, zero errors
from unrelated causes), implement until GREEN, run the stage gate, save transcripts under
`remediation_evidence/V05/slice1/S<n>/`, then commit on `v0.5-adapters`.

| Stage | Build | GREEN acceptance condition |
| --- | --- | --- |
| **S0 Baseline & scaffolding** | `verify_freeze` CLI; `ADR-0005` (PROPOSED); `.gitattributes` append; empty package skeleton; `tests/adapters/__init__.py`, `support.py`; `test_adapters_boundaries.py` | `python -m genesis_adapters.cli verify_freeze --tag v0.4-foundation-freeze` OK; boundary tests green; full discovery still 493 foundation tests green plus the new ones |
| **S1 Primitives** | `versions`, `errors`, `clock`, `jsonstrict`, `ids`, `canonical/odds.py` | Unit tests 12.1 (jsonstrict, clock, ids, odds, errors) green |
| **S2 Canonical contracts** | `canonical/records.py`, `document.py` (builder + closed validator), `projection.py` | Record invariants, document schema tests, projection-validity tests (with a hand-built document) green |
| **S3 Evidence & PIT binding** | `evidence/layout.py`, `source_contracts.py`, `writers.py`, `provenance.py`, `reader.py`; `identity/registry.py` | Evidence binding, identity registry and reader tests with hand-built documents green, including tamper and capability gating; the 12.5 compatibility test with a hand-built document green |
| **S4 Acquisition mechanics** | `acquisition/*` (contracts, transport with permit, credentials, ratelimit, quota_gate, ledger, breaker, runlock) | Transport guard/sanitization tests, quota/cache tests against the frozen ledger, ledger replay and breaker tests green; no real socket opened (assert via FakeTransport-only construction) |
| **S5 OddsPapi source adapter** | `sources/base.py`, `sources/oddspapi/*`; all synthetic fixtures | Request/redaction/hash goldens, parse and catalog tests, HTTP classification tests green |
| **S6 Soccer sport adapter** | `sports/base.py`, `sports/soccer/*` | Every Section 6.3 case test green; golden document produced, reviewed field-by-field against Sections 4.7–4.9 and 8, committed with its digest; golden test green |
| **S7 Ingestion coordinator** | `ingestion/plan.py`, `coordinator.py`, `results.py`, `telemetry.py` | Integration scenarios 12.4 (1–17) green; crash-recovery exactness proven |
| **S8 Invariants** | `test_adapters_properties.py` | All 9 properties green three times consecutively with identical outcomes |
| **S9 Foundation compatibility** | `test_adapters_foundation_compat.py` over golden output | 12.5 green using the unchanged frozen `verify_for_pack` |
| **S10 Operator CLI & live smoke** | `cli/*` | Guard tests green offline; `bootstrap` writes contracts/binding/BLOCKED capability into a scratch root in tests; live smoke **not run** by the implementer unless the user supplies credentials and says so |
| **S11 Docs & handoff** | additive sections in root docs; `remediation_evidence/V05/slice1/GREEN_FINAL.md`; handoff for independent review | Section 15 gate fully green and recorded |

---

## 15. Slice-1 acceptance criteria (hard gate)

Slice 1 is complete only when **every** item holds and its evidence is recorded in
`remediation_evidence/V05/slice1/GREEN_FINAL.md`:

- **G1 Frozen foundation unchanged.** `verify_freeze` passes:
  (a) `git rev-parse HEAD:src/genesis` == `git rev-parse v0.4-foundation-freeze:src/genesis`;
  (b) the `config`, `tools` and `v04_pack` tree IDs are identical to the tag;
  (c) every path under `tests/` and `DECISIONS/` that exists at the tag is byte-identical
  (additions only: `tests/adapters/**`, `DECISIONS/ADR-0005-*`);
  (d) `git diff --name-status --diff-filter=DMRTC v0.4-foundation-freeze HEAD` lists only
  allowlisted root docs and `.gitattributes`, and the tag's `.gitattributes` bytes are a
  prefix of HEAD's; (e) `requirements.lock`, `pyproject.toml`, `config/defaults.json` and
  `config/oddspapi_quota_policy_v2.json` are unchanged.
- **G2 Default suite green.** `python -m unittest discover -s tests -t . -v`: all tests pass,
  with 0 failures and 0 errors; the only skips are pre-existing platform skips (one on this Windows host);
  the foundation's 493 tests are all present and pass.
- **G3 Hygiene.** `python -m compileall -q src tests` and `git diff --check` are clean;
  all new files are LF; no file over about 400 lines without a recorded reason.
- **G4 Determinism.** The adapter sub-suite
  (`python -m unittest discover -s tests/adapters -t . -v`) passes 3 consecutive runs; the
  golden document digest is identical across runs and processes.
- **G5 Raw evidence immutable and identity-bound.** Tamper/overwrite tests green; every
  raw capture has an observation under `contract.oddspapi.v4.raw.v1`; the credential never
  appears in any persisted byte (scan test).
- **G6 Canonical output bound to provenance.** Every reader result carries a
  `ProvenanceChain` that `verify_chain` validates down to raw bytes; the golden test green.
- **G7 PIT explicit and correct.** Section 5.1 ordering asserted on every ingestion;
  property tests 4–5 green; frozen `verify_for_pack` compatibility green.
- **G8 Failures produce no usable observation.** Every row of 6.2 and 6.3 has a test;
  mutation property 8 green.
- **G9 Quota/cost deterministic.** Scenarios 12.4 #2, #3, #10 green; every metered call
  goes through the frozen `QuotaLedger`; ledger `verify()` passes after all scenarios; cache
  hits create no observation.
- **G10 Slice subset normalized correctly.** EPL + LaLiga, pinnacle, FT 1X2 golden
  document matches the reviewed expectation; all excluded features are counted, not dropped.
- **G11 Performance.** Ingesting the golden payload (5 fixtures) into fresh partitions takes
  under 5 s. A synthetic 40-fixture listing into partitions pre-filled with 20k PIT rows
  takes under 120 s on the development host (recorded, not asserted in tests).
- **G12 Boundaries.** Import-boundary, forbidden-name and network-isolation tests green;
  `genesis_adapters` is not importable from the protected research worker. It is not
  allowlisted, so no change is needed. A test parses `src/genesis/protected_research_worker.py`
  with `ast` (without importing it) and asserts that `genesis_adapters` is neither in
  `_RESEARCH_IMPORT_ALLOWLIST` nor matched by `_RESEARCH_GENESIS_ALLOWLIST`.
- **G13 Governance.** The adapter never writes a READY capability or a market capability;
  bootstrap writes BLOCKED only; ADR-0005 is PROPOSED with no fabricated approval.
- **G14 Live smoke (optional).** If and only if the user supplies credentials and
  explicitly asks: the live smoke runs with ≤ 4 (≤ 5 with account) billable calls, reports
  structural success or a precise drift report, and its run report is saved. Live smoke is
  never required for G1–G13.

---

## 16. Frozen foundation boundaries

### 16.1 Do not modify (normal slice-1 work)

- Everything under `src/genesis/` (all 36 modules, including `__init__.py`), tree `51cb635b…`.
- Every file that exists under `tests/` at the tag, including `tests/__init__.py`,
  `tests/_support.py`, `tests/protected_*` and all `test_*.py`. Adapter tests may *import*
  `tests._support`.
- `config/defaults.json`, `config/oddspapi_quota_policy_v2.json` (including the
  D-REM-001 numbers and digest).
- `tools/genesis_audit_package.py`.
- `DECISIONS/ADR-0001…0004` and their approval notes.
- `v04_pack/**`.
- `requirements.lock`, `pyproject.toml`, `.gitignore`.
- Existing `.gitattributes` lines (append only).
- `remediation_evidence/**` at the tag (T1–T6 byte evidence and hash manifests).
- History: no amend, rebase, force-push, tag move, or rewrite at or before `2278e2a`.

### 16.2 Behaviour that must not change even indirectly

No monkey-patching of `genesis.*` at runtime. No subclassing of frozen stores to alter
validation (subclassing for test fixtures follows the existing `tests/_support.py` pattern
only, and only in tests). No writes to frozen stores except through their public methods.
No new `ReasonCode` members. No change in live activation state.

### 16.3 Foundation interface extensions (identified, justified, **not** for slice 1)

| ID | Extension | Why additive implementation is impossible | Smallest proposal | When |
| --- | --- | --- | --- | --- |
| E-1 | Provider-generic operational quota policy | `require_operational` hard-codes provider `oddspapi` and `(250,220,30,7)` (`quota.py:179-187`); an adapter-owned parallel ledger would bypass the certified authority | Replace the hard-coded check with an approved-policy registry mapping `provider_id → exact approved numbers + approval reference`, keeping OddsPapi's D-REM-001 entry byte-identical in meaning; RED/GREEN + hostile review | Before any second provider (for example The Odds API) is used operationally |
| E-2 | Trusted-clock guard inside `QuotaLedger.request` | The ledger accepts any caller's `occurred_at`; the adapter can only police its own writes | Optional injected `clock` in `QuotaLedger.__init__`; reject `occurred_at > clock() + tolerance` with a new blocked reason `quota_event_time_ahead` | Before more than one writer or any cloud deployment |
| E-3 | Incremental verification / indexed reads for `AppendOnlyJsonl`/`PITStore` | Whole-log verification per append is inside the frozen class | Cached verified prefix (size + last hash + inode) re-verified only past the cached offset, with the same failure semantics; `PITStore` entity index | Only if G11 budgets are exceeded in real operation |

Each extension is a new remediation tranche with RED/GREEN evidence and an
independent hostile audit, per `V04_FOUNDATION_FREEZE.md`.

---

## 17. Risks and open questions (with recommendations)

| # | Question/risk | Recommendation |
| --- | --- | --- |
| R1 | OddsPapi terms (250/month, per-call charging, cooldowns, whether `/v4/account` is free) are from public docs and unverified | The operator verifies before capability READY; until then the catalog keeps `terms_verified=False` and treats `/v4/account` as metered. No code change is needed when verified: bump the endpoint catalog to v2 |
| R2 | Payload shapes may differ from the documented examples | The live smoke's first capture is reviewed against the closed-schema table; differences go through RED/GREEN parser changes plus new synthetic fixtures; drift fails closed meanwhile |
| R3 | Redistribution/licensing of provider data | Commit only synthetic fixtures; runtime evidence stays out of Git (`runtime/` is ignored). Recommend the operator confirm OddsPapi's terms before any data leaves the machine |
| R4 | Tournament IDs 17/8 and their names/categories are from documentation examples | Pin them from the first reviewed `tournaments` capture; the competition check fails closed until the pinned expectation matches |
| R5 | "Full Time Result" settlement semantics (regular time only?) are not verified | Irrelevant to data capture; `MarketCapability.market_settlement_rules_known` stays `None`; verify before any strategy uses the market |
| R6 | `changedAt` means "last price change", not "last confirmed" | Freshness always comes from `request_started_at`; `changedAt` is informational |
| R7 | Cross-observation provider timestamp regressions are flagged, not quarantined | Acceptable because availability never uses provider times; revisit if anomalies are observed |
| R8 | Single reference bookmaker | Deliberate for slice 1; N-bookmaker support is designed in (scopes per bookmaker); slice 2 adds `/v4/odds` multi-book depth |
| R9 | Identity conflicts have no resolution path | Conservative by design; slice 2+ adds operator-approved resolution rows |
| R10 | Partition growth with many bookmakers | Measured by G11; extension E-3 if needed; never time-partition PIT |
| R11 | `gzip` responses would fail (`identity` requested) | The live smoke reveals whether this happens; if so, a v2 transport stores the *received* bytes as raw evidence and the decoded bytes as a second, derived, hash-bound artifact |
| R12 | The host clock is the root of time trust | NTP-synced hosts only; the HTTP Date witness catches drift over 120 s; E-2 before multi-writer |
| R13 | The E11 containment residuals (non-English `icacls`, single host) | Unrelated to adapters: the adapter runs in its own process and never in the research worker |
| R14 | `GENESIS_AUTONOMOUS_PRODUCTION_SPEC.md` not found | Nothing depends on it; reconcile before slice 2 if it surfaces |
| R15 | The LAY price-sanity residual | Untouched: slice 1 produces BACK sportsbook quotes only and no price-sanity inputs |

No question here blocks slice 1. The only human inputs slice 1 needs are the ones
the repository already reserves for humans: the ADR-0005 approval note, the source-input
binding approval reference, capability promotion to READY, and (optionally) credentials
plus explicit permission for the live smoke.

---

## 18. Copy-paste implementation prompt for Sonnet 5.5

```text
ROLE
You are implementing Project Genesis v0.5 slice 1: the first READ-ONLY source/sport
adapter layer. You are an implementer, not a designer. The architecture is final and
lives in V05_ADAPTER_ARCHITECTURE.md at the repository root. Implement it exactly.

REPOSITORY
- Work in the Genesis repository on branch `v0.5-adapters`.
- Baseline: tag `v0.4-foundation-freeze` = commit 2278e2a68083f7ac58d796b1ed9c43d50020b6b0.
  Verify first: `git rev-parse v0.4-foundation-freeze^{commit}` must print that SHA, and
  `git merge-base --is-ancestor 4f11606 HEAD` must succeed. If not, STOP and report.
- Python 3.12, stdlib only. Default tests:
  `python -m unittest discover -s tests -t . -v` (about 10 minutes; 493 foundation tests, 1 platform skip).

READ FIRST (in this order, completely)
1. V05_ADAPTER_ARCHITECTURE.md (all sections; Sections 3-16 and Appendices A-B are normative).
2. V04_FOUNDATION_FREEZE.md, SOURCE_AVAILABILITY.md, DATA_DICTIONARY.md.
3. The frozen modules you will call: src/genesis/{time,repro,registry,provenance,evidence,
   pit,feature_manifest,quota,coverage,reasons,logging,canonical}.py, and tests/_support.py.

HARD RULES (violating any of these fails the task)
1. Never modify, delete, rename or reformat any file that exists at the tag under src/genesis,
   tests, config, tools, DECISIONS, v04_pack, remediation_evidence, or requirements.lock,
   pyproject.toml, .gitignore. `.gitattributes` is append-only (one line:
   `tests/adapters/fixtures/** -text`). Never rewrite history, amend, force-push, or move tags.
2. All new code goes in src/genesis_adapters/ (a NEW top-level package, NOT under src/genesis/).
   All new tests go in tests/adapters/. Follow Section 11's file tree exactly.
3. Read-only, offline, paper-only. No betting logic, no probabilities other than
   `implied_probability_raw`, no fair odds, EV, edge, stake, ranking, tiers, recommendations,
   candidates, strategies or models. No imports from genesis.risk/execution/selection/policy/
   decision/decision_output/ledger/accounting/release_proof/owner_binding/composition/
   protected*/evaluation/labels/candidate_runs/selection_evaluation/capabilities.
4. No network in tests. Only acquisition/transport.py may import urllib/http/socket/ssl, and
   UrllibTransport requires a LiveNetworkPermit that only cli/ constructs after env checks.
   Do NOT run the live smoke or any live request unless the user explicitly provides
   credentials and tells you to.
5. No third-party packages. Property tests use seeded `random`, not Hypothesis.
6. Fail closed everywhere (Section 6). Never guess, default, substitute, or carry forward data.
   Never self-promote a source capability to READY; bootstrap writes BLOCKED only.
7. Use only public APIs of frozen modules (plus the public `log.records()` of AppendOnlyJsonl).
   No monkey-patching of genesis.* at runtime. No new ReasonCode members.
8. Every persisted timestamp comes from the injected AcquisitionClock and is written via
   genesis.time.iso_utc. Never accept a caller-supplied time for anything you persist.
9. The API key never appears in any persisted byte, log, exception message, URI, cache key,
   or request hash. Test this (Section 12.4 #14).
10. Write every file with LF line endings (the Write/Edit tools do this; do NOT use
    Path.write_text without newline="\n" on Windows). Golden fixture bytes are pinned by SHA-256.
11. Never fabricate human approvals (ADR-0005 stays PROPOSED; approval references in tests
    are clearly synthetic, e.g. "synthetic-test-only-...").

METHOD
- Follow Section 14 stages S0 through S11 in order. For each stage: write tests first, run them,
  save the RED transcript; implement; run to GREEN; save the GREEN transcript under
  remediation_evidence/V05/slice1/S<n>/ (write transcripts with LF, include the exact command,
  timestamp, and summary line); then commit on v0.5-adapters with a message
  `feat(v0.5/S<n>): <summary>` (docs/evidence stages: `docs(v0.5/S<n>): ...`).
- Run the FULL default discovery at the end of S0, S3, S7 and S11 (it is slow; that is expected).
- If the document is ambiguous, choose the more fail-closed interpretation that keeps the
  frozen foundation untouched, record it in remediation_evidence/V05/slice1/DECISIONS_LOG.md
  (what, why, section reference), and continue. Do not ask routine questions.
- STOP and report (do not work around it) only if: a frozen file would have to change; a frozen
  public API cannot do what the document says; a test in the foundation suite fails; or
  anything would require network, credentials, or a live call.
- Do not push to origin. Leave commits local on v0.5-adapters for review.

DEFINITION OF DONE
All gate items G1-G13 of Section 15 green and recorded in
remediation_evidence/V05/slice1/GREEN_FINAL.md, with:
- verify_freeze output;
- full default discovery summary (total/pass/skip/fail/error) and adapter sub-suite x3;
- compileall and `git diff --check` clean;
- golden document digest and the field-by-field review notes;
- a list of every file added;
- a list of every DECISIONS_LOG entry;
- the commit list (`git log --oneline v0.4-foundation-freeze..HEAD`).
Update the root docs (PROJECT_STATE.md, ARCHITECTURE.md, HANDOFF.md, TEST_EVIDENCE.md,
DATA_DICTIONARY.md, SOURCE_AVAILABILITY.md) with ADDITIVE v0.5 slice-1 sections that state clearly:
implemented and proven vs. assumed; the capability remains BLOCKED; no live call was made
(unless the user authorized the live smoke, in which case record its report); and that an
independent hostile review is required before any capability promotion.

FINAL REPORT (your last message)
1. Stage table S0-S11: status, commit SHA, tests added, RED->GREEN counts.
2. Gate table G1-G14 with evidence paths.
3. Deviations from the document (should be none) and every DECISIONS_LOG entry.
4. Known limitations and anything a hostile reviewer should attack first.
```

---

## Appendix A — Frozen API calls used (exact)

```python
# evidence
SourceContractRegistry(path).register(SourceContract(...)) / .get(contract_id)
EvidenceStore(root, contracts=registry).publish(payload, contract_id=, source_uri=, provider=,
    source_type=, retrieved_at=, parse_ready_at=, parser_version=, content_type=,
    licensing_note=, availability_class=, publisher_timestamp=None, valid_from=None,
    valid_to=None, upstream_version=None, first_seen_at=)
EvidenceStore.get_bytes(artifact_hash) / .get_observation(observation_id) / .get_observations(artifact_hash) / .verify_manifest()
# PIT
SourceCapabilityRegistry(path).register(SourceCapability(...)) / .require_ready_at(source_id, T)
PITStore(path, capabilities=registry).append(BitemporalRecord(...)) / .as_of_query(entity_id, T, source_id=)
PITStore.log.records()        # public; used to check existing record_ids during recovery
SourceInputBindingStore(path).register(source_id=, source_contract_id=, provider=, approval_reference=)
# quota/cache
QuotaLedger(path, policy=load_quota_policy(policy_path), cache_store=store)   # operational (NOT from_active_config: no cache store)
QuotaLedger(path, policy=QuotaPolicy.test_fixture(...), allow_test_policy=True, cache_store=store)  # tests
QuotaLedger.request(request_id=, occurred_at=, billable_units=, cache=CacheReference|None, provider_request_hash=)
QuotaLedger.usage(occurred_at) / .verify() / .log.records()
VerifiedCacheStore(root).publish(payload, cache_key=, provider_request_hash=, provider_id=,
    quota_policy_digest=, captured_at=, expires_at=) -> CacheReference
VerifiedCacheStore.get(cache_entry_id) ; .object_path(artifact_hash).read_bytes() (after get() verified it)
# telemetry/coverage/helpers
CoverageLedger(path).append(CoverageEntry(...))
JsonlAuditLogger(path).emit(LogEvent(...))
genesis.canonical.stable_id(prefix, *parts); genesis.time.parse_utc/iso_utc;
genesis.repro.canonical_json/sha256_bytes/immutable_write/tree_digest
```

## Appendix B — Exact row schemas, policy constants and mapping tables

### B.1 Acquisition ledger (`acquisition-ledger-v1`)

The `AcquisitionLedger` wraps one `AppendOnlyJsonl` per UTC month of `recorded_at`
(`acquisition/<YYYY-MM>.jsonl`) and passes its own replay as the frozen `reader=` hook,
so a row it could not replay is never appended. Every row has `record_type`,
`schema_version = "acquisition-ledger-v1"` and `recorded_at` (clock stamp at append).
Replay refuses unknown `record_type`/`schema_version`, missing or extra keys, an
`attempt_finished` without `attempt_started`, a second `attempt_finished`, and
`ingestion_committed` without `ingestion_started`.

| record_type | Keys (besides the three common keys) |
| --- | --- |
| `run_started` | `run_id`, `provider_id`, `window_id`, `plan_digest`, `code_digest`, `adapter_versions` (`{framework, source, sports: {sport: version}}`) |
| `attempt_started` | `attempt_id`, `run_id`, `window_id`, `attempt_no`, `endpoint_id`, `provider_request_hash`, `redacted_uri`, `quota_occurred_at`, `billable_units_requested` |
| `attempt_finished` | `attempt_id`, `outcome`, `failure_code`, `quota` (QuotaCharge fields or null when skipped before the ledger), `request_started_at`, `received_at`, `failed_at`, `http_status`, `headers` (`[[name, value], …]`), `body_sha256`, `body_length`, `raw_observation_id`, `raw_persisted_at`, `provider_http_date`, `clock_skew_seconds`, `latency_ms` (inapplicable values are `null`) |
| `attempt_cached` | `attempt_id`, `cache_entry_id`, `cache_key`, `provider_request_hash`, `captured_at`, `expires_at` |
| `ingestion_started` | `attempt_id`, `raw_observation_id`, `normalizer_version`, `catalog_digest`, `identity_registry_head`, `metadata_pins` (`{bookmakers, markets, participants, tournaments}` raw observation IDs) |
| `ingestion_rejected` | `attempt_id`, `raw_observation_id`, `failure_code` |
| `ingestion_committed` | `attempt_id`, `raw_observation_id`, `document_artifact_hash`, `document_observation_id`, `derived_at`, `pit_row_count`, `pit_record_ids_digest` (sha256 of canonical_json(sorted record IDs)), `coverage_row_count`, `rejections_digest`, `counts` (`{events, book_markets_by_status, rejections_by_code}`) |
| `breaker_opened` | `provider_id`, `scope` (`window`/`day`/`operator`), `reason_code`, `window_id` |
| `operator_reset` | `provider_id`, `approval_reference`, `reason` |
| `quota_reconciled` | `provider_request_limit`, `provider_request_count`, `ledger_monthly_used`, `drift` |
| `anomaly` | `kind` (slice 1: `provider_timestamp_regression`), `attempt_id`, `entity_id`, `detail` |
| `run_finished` | `run_id`, `report_path`, `report_sha256` |

### B.2 Identity registry (`identity-registry-v1`)

One `AppendOnlyJsonl` per (provider, sport). Every row has `record_type`,
`schema_version = "identity-registry-v1"` and `recorded_at`. A row whose content (all keys
except `recorded_at`) already exists is not re-appended (idempotence). An
`identity_mapping` for an existing `(domain, provider_id, native_id)` with a different
`canonical_id` is a `RegistryConflict`.

| record_type | Keys |
| --- | --- |
| `identity_mapping` | `domain` (`competition`/`season`/`participant`/`event`/`bookmaker`), `provider_id`, `native_id`, `canonical_id`, `method` (`deterministic_mint`), `first_seen_at` (capture `received_at`), `first_seen_raw_observation_id` |
| `event_seen` | `event_id`, `competition_id`, `season_id`, `participant1_id`, `participant2_id`, `scheduled_start_at`, `observed_at` (capture `received_at`), `raw_observation_id`; appended only when the event is new or any of the first five values or `scheduled_start_at` differs from its last `event_seen` |
| `identity_conflict` | `conflict_id` (sha256 of canonical_json of the other keys), `kind` (`natural_key_collision`/`duplicate_in_payload`/`identity_mutation`), `event_ids` (sorted), `natural_key` (`[competition_id, participant1_id, participant2_id]`), `detected_at` (capture `received_at`), `raw_observation_id` |

`IdentitySnapshot` at head `H` = replay of the log prefix ending at the row whose
`record_hash == H` (all zeros = empty). The reader's partition lookup at time T uses the
latest `event_seen` for the event with `recorded_at ≤ T`.

### B.3 `NormalizationPolicy` v1 (constants in `sports/soccer/semantics.py`)

| Name | Value |
| --- | --- |
| `clock_skew_tolerance_seconds` | `120` |
| `stale_flag_after_seconds` | `604800` (7 days) |
| `min_plausible_timestamp` | `"2000-01-01T00:00:00.000000Z"` |
| `max_start_horizon_days` | `400` |
| `natural_key_window_days` | `7` |
| `odds_min_exclusive` / `odds_max_inclusive` / `odds_max_decimal_places` | `"1"` / `"1000"` / `4` |
| `overround_bounds["soccer.full_time_result_1x2"]` | `("0", "0.30")` inclusive |
| `implied_quantum` | `"1E-10"`, `ROUND_HALF_EVEN`, context precision 28 |

### B.4 Soccer ↔ OddsPapi mapping table v1 (`sports/soccer/oddspapi_map.py`)

| Item | Value |
| --- | --- |
| Sport | provider `sportId "10"` ↔ `soccer` |
| Family | `soccer.full_time_result_1x2`, period `provider_fulltime`, line `None` ↔ provider market `"101"` |
| Expected catalog definition of `"101"` | `marketName "Full Time Result"`, `marketType "1x2"`, `period "fulltime"`, `handicap "0"`, `sportId "10"`, `playerProp false`, outcomes `[("101","1"), ("102","X"), ("103","2")]` |
| Outcome map | `"101" → p1` (participant1), `"102" → draw`, `"103" → p2` (participant2); all three required |
| Status map | `"0" → scheduled`, `"1" → live`, `"2" → finished`, `"3" → cancelled_or_postponed`; anything else → `UNKNOWN_EVENT_STATUS` |
| Competition allowlist | `"17"`: name `"Premier League"`, category `"England"`; `"8"`: name `"LaLiga"`, category `"Spain"`. **Provisional:** the name for 17 is documented, while the category values and LaLiga's name are expectations to confirm from the first reviewed live `tournaments` capture. A mismatch fails closed (`COMPETITION_CATALOG_DRIFT`); correcting an expectation is a mapping change and bumps the normalizer version (new contract and PIT source) |
| Curated bookmakers | `"pinnacle"` → key `pinnacle`, kind `SPORTSBOOK` |
| Requested per call (slice 1) | `bookmaker=pinnacle`, `tournamentIds=17,8`, `oddsFormat=decimal` |

`catalog_digest` = sha256 of `canonical_json` of B.3 and B.4 (as a dict with sorted keys,
Decimal values as strings) plus the normalizer version.

## Appendix C — Sources consulted

Repository (at `2278e2a`): `V04_FOUNDATION_FREEZE.md`, `PROJECT_STATE.md`, `ARCHITECTURE.md`,
`HANDOFF.md`, `ASSUMPTIONS.md`, `DATA_DICTIONARY.md`, `SOURCE_AVAILABILITY.md`,
`V04_MIGRATION_PLAN.md`, `V03_TO_V04_GAP_ANALYSIS.md`, `TEST_EVIDENCE.md`,
`v04_pack/…/01_PROJECT_GENESIS_v0.4.md`, `02_AUDIT_RECONCILIATION_v0.4.md` §2.20,
`03_PROJECT_LAWS_v0.4.md`, `05_DECISION_AND_RISK_POLICY_v0.4.md`,
`06_RUNTIME_AND_COST_TARGET_v0.4.md`, `08_ODDSPAPI_BUDGET_DRAFT.yaml`,
`remediation_evidence/R8/R8_CHECKPOINT.md` (D-REM-001), `config/*.json`, `pyproject.toml`,
`requirements.lock`, `.gitattributes`, `.gitignore`, and the `src/genesis` modules and tests
cited inline.

External (public documentation, 2026-09-28; must be re-verified before operational use):
[OddsPapi docs overview](https://oddspapi.io/en/docs),
[OddsPapi methods](https://oddspapi.io/en/docs/methods),
[OddsPapi requests & quota](https://oddspapi.io/en/docs/requests-and-quota),
[OddsPapi odds-by-tournaments](https://oddspapi.io/en/docs/get-odds-by-tournament),
[OddsPapi fixtures](https://oddspapi.io/en/docs/get-fixtures),
[OddsPapi tournaments](https://oddspapi.io/en/docs/get-tournaments),
[OddsPapi participants](https://oddspapi.io/en/docs/get-participants),
[OddsPapi markets](https://oddspapi.io/en/docs/get-markets),
[OddsPapi free tier blog](https://oddspapi.io/blog/free-sports-data-api/),
[The Odds API v4 docs](https://the-odds-api.com/liveapi/guides/v4/).
