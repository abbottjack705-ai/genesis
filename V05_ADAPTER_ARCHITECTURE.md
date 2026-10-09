# V0.5 adapter architecture — slice 1 implementation authority

| Field | Value |
| --- | --- |
| Status | **FINAL DESIGN AUTHORITY for V0.5 slice 1** (design only; no production adapter code exists) |
| Frozen foundation | tag `v0.4-foundation-freeze` → commit `2278e2a68083f7ac58d796b1ed9c43d50020b6b0` (documentation-only over certified executable baseline `4f11606615c7650f3bd74c7ccf5d2fb7a5a753c5`) |
| Authority order | frozen repository → Prep B (frozen requirements matrix) → Prep A (provider dossier) → Prep C (cost / vertical slice) → earlier architecture draft |
| Scope of this document | freeze interpretation, slice-1 scope, file layout, interfaces and immutable schemas, identity, time/PIT, evidence flow, credential and request hashing, quota/cache/polling, failure semantics, approval gates, tests, staged plan, no-touch list, residuals, implementation prompt |
| What it grants | Permission to implement Stages 0–7 (§19) against deterministic fixtures, with no credential and no network access to OddsPapi. It grants **no** credential storage, live request, READY capability, strategy, shadow research, protected campaign, live-order or canary authority. Those are gated in §16. |
| Revision | **r3.** r2 (`117c98a`) closed the ten findings (A1–A10) of the independent pre-implementation hostile review of r1 (`cff1ede`). The short closure review of r2 marked eight CLOSED and A4/A6 partially closed. r3 closes A4 (debit-to-receipt boundary edge: §14.6, §20.1) and A6 (process-control exception semantics: §7.7). §24 maps every finding to the sections it changed. |

### Inputs and how they were used

- **Frozen repository.** I read it directly at `2278e2a`: `pit.py`, `time.py`, `quota.py`,
  `evidence.py`, `feature_manifest.py`, `provenance.py`, `coverage.py`,
  `capabilities.py`, `canonical.py`, `logging.py`, `registry.py`,
  `SOURCE_AVAILABILITY.md`, `DATA_DICTIONARY.md`, `ASSUMPTIONS.md`,
  `V04_FOUNDATION_FREEZE.md`, and the v0.4 pack laws and blueprint. Every rule below that
  relies on a frozen behaviour cites the file it comes from.
- **Prep A, Prep B and Prep C.** I used the conclusions as stated in the task brief. Where
  Prep B's numbered questions were named (Q1/Q3 timestamps, Q2 corrections, Q4 market
  representation, Q5 cache and staleness, Q9 network authority), this document uses
  those numbers. The rest are indexed by topic in §22.
- **Earlier draft `V05_ADAPTER_ARCHITECTURE.md`.** No file of that name existed in the
  repository (any branch or tag) or in the connected Drive when this authority was written.
  I rebuilt this document from the frozen repository and Prep A/B/C. It **replaces**
  any earlier draft of the same name. If that draft turns up later, any content it holds
  that conflicts with this document has no authority.

---

## 1. Decision summary

| # | Decision | Resolution (section) |
| --- | --- | --- |
| D1 | Post-freeze code location | All V0.5 code, tests, config and evidence live under the new top-level tree `adapters/`. The six frozen trees (`src`, `tests`, `config`, `tools`, `DECISIONS`, `v04_pack`) keep their recorded tree SHAs at **every** V0.5 commit, and a guard test enforces this. No file is added under a frozen tree. (§2, §4) |
| D2 | Slice-1 scope | OddsPapi v4 pre-game REST → soccer → Premier League + LaLiga → 1X2 (full time) + exactly-identified total goals O/U 2.5 (full time) → up to 3 declared **fixed-odds sportsbook** acquisition bookmakers → prospective raw capture → decision-consumable PIT observations for PAPER-mode consumers only. Narrowed: exchanges, historical/backfill endpoints and in-play are excluded (§3). |
| D3 | Canonical request / secrets | The canonical request is structured JSON built from an endpoint spec. It holds no field that can carry the credential. The credential is injected only inside the HTTP transport, after hashing and logging. `provider_request_hash = sha256(canonical_json(request))`. (§7) |
| D4 | Timestamps / PIT (Q1, Q3) | Every PIT-relevant time comes from one trusted clock. `available_at = retrieved_at = valid_from = response_received_at (T1)`. `ready_at = T3` (after normalized evidence is durable). Provider times are provenance only and never decide availability. Non-UTC and naive provider timestamps are rejected, following `SOURCE_AVAILABILITY.md` rule 2. (§6) |
| D5 | Corrections (Q2) | Nothing is mutated. A newer observation supersedes by `valid_from`. A tombstone head (SUSPENDED/ABSENT/BLOCKED/INVALIDATED) blocks older prices. An invalidation is an append-only record whose head takes effect only from its own admissible time, even against a still-current price (§13.2). Any derivation change yields a new source (contract + PIT `source_id` + capability). `superseded_by`/`superseded_at` are always `None`. (§13) |
| D6 | Market representation (Q4) | An adapter-owned immutable `MarketBookDocument` per (event, market, bookmaker). The frozen `MarketSnapshot` has no consumer in `src` and is **not** modified or emitted. (§9) |
| D7 | Identity | IDs are deterministic, domain-separated SHA-256 values over provider-native IDs. Competitions, bookmakers, markets and outcomes come from pinned, human-reviewed maps. Display names never establish identity. (§8) |
| D8 | Provider status | Explicit allowlists typed on (field, JSON type, value). Unknown, mistyped or contradictory values produce a BLOCKED head with no price. (§10) |
| D9 | Cache/staleness (Q5) | An OPEN price is usable only in `[T1, min(T1 + price_ttl_seconds, kickoff − prematch_guard_seconds))`. Both are **versioned provisional slice-1 policy parameters, not Genesis architectural law** (§12.1). No carry-forward. Odds responses are never cached. A verified cache hit (metadata only) never creates an observation. Cache objects referenced by quota-ledger rows are retained forever. (§12) |
| D10 | Quota | The frozen `QuotaLedger` and `config/oddspapi_quota_policy_v2.json` are reused unchanged. **Provider metering** (what OddsPapi documents or reports) and the **Genesis debit** (what Genesis conservatively charges its own budget) are separate fields. Every attempt debits `genesis_units_debited ≥ 1` NORMAL units before sending. There are no refunds. The adapter never builds or uses reserve authority. (§14) |
| D11 | Network authority (Q9) | Gates G0 → G1 (credential storage) → G2 (a fixed list of first live requests) → G2R (recurring capture) → G3 (capability READY). Each gate is a human approval record, not code. (§16) |
| D12 | Raw vs normalized evidence | Raw response bytes are PROSPECTIVE_CAPTURED evidence and are never decision inputs. One normalized DERIVED document per book is the decision-consumable input. It embeds the raw hash and observation ID and re-derives byte-identically. It satisfies the frozen `FeatureInputManifestStore.verify_for_pack` without change. (§11) |
| D13 | Failure default | Every failure path produces **no usable observation**, retains whatever bytes were received (except secret-bearing bytes), and writes a coverage/exclusion record. (§15) |
| D14 | Foundation reopen | **None required for slice 1.** A reopen is triggered only if actual provider terms cannot be safely bounded by the frozen `(250, 220, 30, 7)` authority (§20). The UTC boundary guard (§14.6) keeps each provider receipt in the same UTC day and month as its debit. |
| D15 | Credential precedence | **Credential safety dominates raw-response retention.** Secret-bearing bytes never enter durable evidence. A body that cannot be fully inspected before storage is not stored. (§7.6) |
| D16 | Runtime provenance | At adapter-suite and runner startup, every loaded `genesis.*` module must resolve to the frozen source file with the frozen blob identity (FRZ-09, §2.4). This supplements the tree-SHA guard. |
| D17 | Closed provider schemas | Every provider structure carrying status, price, line, identity or market semantics is validated against a closed schema. An unknown field there gives `BLOCKED / SCHEMA_DRIFT` with no usable observation. (§10.1) |
| D18 | Scope of success | Successful ingestion, even at READY, does **not** authorize PAPER qualification, strategy readiness or live execution. Those need their own frozen authorities (strategy approval, `MarketCapability` flags, qualification, risk). |

---

## 2. Freeze semantics (authoritative interpretation) — D1

### 2.1 What "frozen" means

1. **History is immutable.** No commit at or before `2278e2a` (tag) or `4f11606`
   (certified baseline) is amended, rebased, force-pushed or rewritten.
2. **Tree identity is invariant on the V0.5 line.** At every commit on the V0.5 branch
   (and any successor), each frozen top-level tree must have exactly the recorded
   object ID:

   | Path | Tree SHA (must equal at every V0.5 commit) |
   | --- | --- |
   | `src` | `51cb635bc42b993815b6c02a23c4c3ceb7d98476` |
   | `tests` | `e90b298180068fec03ba7e2fa81957082e7fb3ce` |
   | `config` | `abd22db01ff482a8da84634ee740ba382b68c804` |
   | `tools` | `a0e3411edb4e068fd4708050516cb6870834e7ac` |
   | `DECISIONS` | `cc97ec6f841f1e3fbe6dbb57c9cb6e1ac24fdb64` |
   | `v04_pack` | `3c3c1c27d80ed6f10c32ac6605a5f438b2e7de12` |

   A tree SHA covers every path inside it, so **adding** a file under `src/genesis/` or
   `tests/` changes the frozen tree and is a foundation change, not an "additive
   adapter". This settles the apparent conflict: additive adapter code cannot live under
   a frozen tree. It lives in a new sibling tree.
3. **Semantics are invariant.** V0.5 code may import and call the public API of
   `genesis.*`. It must not monkeypatch, subclass-override authority methods, write to a
   frozen authority's files except through that authority's public methods, or call
   private (`_`-prefixed) members. §18 FRZ-05 enforces this statically.
4. **Frozen data files are read, never edited.** `config/oddspapi_quota_policy_v2.json`
   (SHA-256 `aa7c13c8…a559`, `policy_digest 3cdf9e3e…a0f9`) is loaded through
   `genesis.quota.load_quota_policy`. It is never copied into `adapters/config/` with
   edits.
5. **Top-level documentation files are not frozen trees.** They (this file,
   `HANDOFF.md`, `PROJECT_STATE.md`, …) may receive **additive** V0.5 status updates.
   `remediation_evidence/**` is historical evidence and is never modified. New evidence
   goes under `adapters/evidence/`.
6. **Branch base.** Implementation branches start from the tag commit `2278e2a`. Its
   executable trees are identical to `4f11606`, which is what `V04_FOUNDATION_FREEZE.md`
   allows ("branch cut from the frozen commit"). The freeze guard compares against the
   SHAs above, not against a commit, so it holds on either base.

### 2.2 The V0.5 root

`adapters/` is the single root for V0.5 work: package `genesis_adapters`, tests package
`adapter_tests`, adapter config, V0.5 ADRs, and V0.5 checkpoint evidence. §4 has the layout. No
separate repository or worktree is needed. The tree-SHA guard already gives a mechanical
boundary that an auditor can check in one command:

```text
for t in src tests config tools DECISIONS v04_pack; do git rev-parse HEAD:$t; done
git diff --name-status 2278e2a HEAD -- src tests config tools DECISIONS v04_pack   # must be empty
```

### 2.3 How V0.5 is run without touching the frozen suite

- Frozen suite (unchanged command, unchanged meaning):
  `python -m unittest discover -s tests -t . -v`
- Adapter suite:
  `python -m unittest discover -s adapters/adapter_tests -t adapters -v`
  (`adapter_tests/__init__.py` puts `src` and `adapters/src` on `sys.path`, the same way
  `tests/__init__.py` does for `src`.)
- Static: `python -m compileall -q src tests adapters/src adapters/adapter_tests` and
  `git diff --check`.

Runtime state (evidence stores, ledgers, caches) is never committed. It defaults to
`runtime/adapters/oddspapi/`, which the existing `.gitignore` rule `runtime/` already
covers, so `.gitignore` is not edited. Byte-exact fixtures are protected by a **nested**
`adapters/.gitattributes` (`adapter_tests/fixtures/** -text`). The top-level
`.gitattributes` is not edited.

### 2.4 Runtime module-provenance guard (FRZ-09) — closes A7

Tree SHAs prove what is **committed**. They do not prove what Python **loaded**. A
`PYTHONPATH` entry, a `.pth` file, a competing `genesis/` package or a stale or foreign
bytecode file could make the adapter run against a different foundation. The guard
closes that gap. It runs:

- in `adapter_tests/__init__.py`, before any test module imports `genesis`, and again in
  a final suite-level test once all modules are loaded;
- at every runner/CLI startup, after `genesis_adapters` and all its `genesis.*`
  dependencies are imported and before any store is opened.

**Pinned manifest.** `adapters/config/frozen_genesis_modules.json` lists every
`src/genesis/**/*.py` path in the frozen `src` tree. For each it holds the Git blob SHA-1
(from `git ls-tree -r 51cb635…`) and the SHA-256 of the blob bytes. The manifest's own
SHA-256 is pinned in `verify.py`. At Stage 0 the manifest is generated from the frozen
tree with Git, and FRZ-09 checks it against `git ls-tree` whenever Git is available.

**Checks, all fail-closed (`ModuleProvenanceError`, runner halts):**

1. `importlib.util.find_spec("genesis").origin` resolves (after `os.path.realpath`) to
   exactly `<repo>/src/genesis/__init__.py`. `genesis.__path__` has exactly one entry,
   `<repo>/src/genesis`.
2. For every `sys.modules` key equal to `genesis` or starting with `genesis.`:
   - `__file__` realpath lies under `<repo>/src/genesis/` and names a manifest entry;
   - `__spec__.loader` is a plain `importlib.machinery.SourceFileLoader` (no zip, custom
     or namespace loader);
   - the file's current bytes hash to the manifest's blob SHA-1 (`"blob <len>\0" + bytes`)
     **and** SHA-256.
3. No other `sys.path` entry, in any position, contains `genesis/__init__.py`,
   `genesis.py` or a `genesis` namespace directory. A lower-precedence competing copy is
   still refused, because precedence can change between processes.
4. No `.pth` file in `site.getsitepackages()` / `site.getusersitepackages()` references
   the repo, `src` or any path holding a `genesis` package, unless it points exactly at
   `<repo>/src` and that path is already listed in the run's recorded environment.
5. `genesis_adapters` itself resolves to `<repo>/adapters/src/genesis_adapters`
   (same shadowing checks, against the working tree rather than a frozen manifest).
6. Bytecode: the live runner starts with `-B` and `PYTHONPYCACHEPREFIX` pointing at a
   fresh per-run temporary directory, so no pre-existing `.pyc` can be loaded in place of
   verified source. The adapter suite does the same through its documented command.

The guard records its verdict (module list, realpaths, hashes, `sys.path`,
`sys.flags`) in the run record. FRZ-09 attacks it in subprocesses with: a shadow
`genesis` package prepended through `PYTHONPATH`; a `.pth` file in a temporary site
directory; a competing `genesis` on a lower-precedence path; a modified copy of one
frozen module; and a planted stale `.pyc`. Every case must fail closed.

---

## 3. Slice-1 scope — D2

### 3.1 In scope (final)

| Dimension | Slice 1 |
| --- | --- |
| Provider | OddsPapi (`provider_id = "oddspapi"`), API v4, pre-game REST only |
| Sport | Soccer |
| Competitions | Premier League, LaLiga. Exactly two provider tournament IDs pinned in `oddspapi_v4_identity_map.json` |
| Markets | `SOCCER_1X2_FT` (home/draw/away, regular time incl. stoppage). `SOCCER_TOTAL_GOALS_OU_FT` at line exactly `2.5` (over/under, regular time) |
| Bookmakers | 1–3 declared **fixed-odds sportsbooks** (acquisition policy only; the canonical schema has no count limit) |
| Price side | Bookmaker back price (decimal odds). No size, no lay |
| Timing | Pre-match only: capture accepted only when `T1 < scheduled_start − prematch_guard_seconds` (provisional policy parameter, §12.1) |
| Evidence | Prospective raw capture plus deterministic normalized derivation. No historical/backfill endpoint |
| Downstream | Output ends at decision-consumable PIT observations, structured evidence and buildable `FeatureInputManifest-v1` bodies. Consumers are PAPER-mode only. No candidate generation, model, strategy, risk or order code is in slice 1. Successful ingestion, including a READY source, does **not** authorize PAPER qualification, strategy readiness or live execution (D18) |
| Network | None until G1/G2 (§16). Stages 0–7 are fixture-only |

### 3.2 Narrowings relative to Prep C, and why each is required

| Narrowing | Architectural property that would otherwise be unsafe or untestable |
| --- | --- |
| **Exchanges excluded** from the declared bookmaker set (e.g. an exchange listed by OddsPapi) | Exchange prices have back/lay sides and liquidity. The frozen `LAY price-sanity` residual (`policy.py`/`selection.py`) is open, and the slice-1 book has no size or side vocabulary. Admitting exchanges would create LAY-shaped data with no verified consumer. |
| **Full-time regular-time markets only** | "O/U 2.5" without a period is ambiguous (first half, extra time). Exact identification requires `period = FT_REGULAR` to be explicit in the pinned market map. A market whose period is not provably regular time is excluded. |
| **No historical endpoints** | Historical provider snapshots are HISTORICAL_RECONSTRUCTED. Their PIT reliability is unverified (Prep A). Slice 1 proves only prospective capture. |
| **Single process, single writer** | The trusted-clock mitigation (§6.1) and the quota ledger's writer-declared time residual are safe only while the adapter runner is the sole writer of its quota ledger. |
| **Data-only terminus** | No strategy is approved. Emitting candidates would imply readiness that the `MarketCapability` flags (`market_supported_by_model`, …) deny. |

The rest of Prep C's slice is adopted unchanged: two competitions, both market families,
up to three bookmakers, PAPER only, and the budget envelope.

---

## 4. File and package layout

```text
adapters/
  README.md                         pointer to this document + exact run commands
  .gitattributes                    adapter_tests/fixtures/** -text
  DECISIONS/                        V0.5 ADRs (ADR-A001 = this document's acceptance record)
  config/
    oddspapi_v4_endpoints.json      endpoint specs (§7.2); every entry "verified_live": false until G2
    oddspapi_slice1_policy.json     policy constants (§12.1, §14); digest-pinned
    oddspapi_v4_identity_map.json   competitions + declared bookmakers (§8)
    oddspapi_v4_market_map.json     provider market/outcome → family/line/period/selection (§8.5)
    oddspapi_v4_status_map.json     status allowlists (§10)
    oddspapi_v4_response_schemas.json closed provider schemas (§10.1)
    frozen_genesis_modules.json     frozen module blob/hash manifest (§2.4)
  src/genesis_adapters/
    __init__.py
    errors.py            AdapterFailure enum + mapping to frozen genesis.reasons.ReasonCode
    ids.py               gid(), native-ID canonicalization
    jsonstrict.py        strict JSON: duplicate keys, NaN/Infinity, Decimal floats, size cap, UTF-8
    schema.py            closed-schema validator (§10.1)
    provenance_guard.py  runtime module-provenance guard (§2.4)
    clock.py             TrustedClock protocol, SystemUtcClock, ClockFault
    secrets.py           Secret (unserializable), scan_for_secret(); CredentialSource (Stage 7)
    config.py            load + digest adapter config; derivation_version()
    oddspapi/
      __init__.py
      endpoints.py       EndpointSpec, CanonicalRequest, build_request(), provider_request_hash()
      quota_gate.py      QuotaGate over frozen QuotaLedger + VerifiedCacheStore
      transport.py       Transport protocol, TransportRequest, TransportResult (no network)
      transport_http.py  Stage 7 only: HTTPS transport, credential injection, no redirects
      acquisition.py     AcquisitionLedger + AcquisitionRunner (reserve → send → capture)
      raw_capture.py     raw SourceContract, secret scan, skew check, EvidenceStore publish
      maps.py            identity/market/status maps + validation
      identity_registry.py append-only fixture/participant binding registry
      parser.py          PURE: raw bytes + ParseContext → ParsedResponse
      normalize.py       PURE: ParsedResponse → MarketBookDocument bytes (+ tombstones)
      emit.py            normalized evidence, structured evidence, PIT records, coverage
      reader.py          MarketBookReader: as-of consumer (fail-closed)
      manifest.py        FeatureInputManifest-v1 body builder
      verify.py          derivation re-verification, runtime secret scan, freeze guard
      scheduler.py       deterministic window plan, budget projection, conditional refresh
      authority.py       AdapterAuthorityLedger (gate records) + gate checks
      cli.py             Stage 7: run / verify / plan; `approve` is operator-only (§16.6)
  adapter_tests/
    __init__.py          sys.path setup (src, adapters/src)
    support.py           FixedClock, FakeTransport, scratch roots, fixture loader (TEST-ONLY)
    fixtures/oddspapi/v4/*.json   doc-derived synthetic payloads + FIXTURES.sha256
    test_v05_*.py        one module per §18 area
  evidence/S0 … S7/      RED/GREEN transcripts per stage (mirrors remediation_evidence style)
```

Runtime layout under `GENESIS_ADAPTER_ROOT` (default `runtime/adapters/oddspapi`):

```text
evidence/           frozen EvidenceStore root (raw + normalized observations)
structured/         frozen StructuredEvidenceStore root
contracts.jsonl     frozen SourceContractRegistry
capabilities.jsonl  frozen SourceCapabilityRegistry
bindings.jsonl      frozen SourceInputBindingStore
pit.jsonl           frozen PITStore log
manifests/          frozen FeatureInputManifestStore root
quota/ledger.jsonl  frozen QuotaLedger
quota/cache/        frozen VerifiedCacheStore root
coverage.jsonl      frozen CoverageLedger / ExclusionLedger
requests/<hash>.json      canonical request bytes (content-addressed by provider_request_hash)
acquisition.jsonl   adapter AcquisitionLedger (AppendOnlyJsonl)
identity.jsonl      adapter IdentityRegistry (AppendOnlyJsonl)
scopes/<hash>.json  expected-scope artifacts (§12.4)
authority.jsonl     adapter AdapterAuthorityLedger (operator-owned)
```

Credentials are **never** under this root or the repository (§7.5).

---

## 5. Frozen APIs reused, and frozen facts this design depends on

| Frozen API | How slice 1 uses it | Frozen behaviour relied on |
| --- | --- | --- |
| `genesis.time.parse_utc`, `iso_utc` | All timestamp validation | Rejects naive and non-UTC offsets (`time.py`) |
| `genesis.provenance.SourceContract`, `SourceContractRegistry`, `AvailabilityClass` | Raw contract (PROSPECTIVE_CAPTURED), normalized contract (DERIVED) | Contract immutability. `uri_pattern` is an `fnmatch` pattern. FUTURE_LABEL/UNKNOWN are not decision-usable |
| `genesis.evidence.EvidenceStore` | Raw and normalized artifacts plus observations | `first_seen_at ≤ retrieved_at ≤ parse_ready_at`. Content-addressed, immutable. `observation_id` = hash of observation fields |
| `genesis.evidence.StructuredEvidenceStore`, `genesis.canonical.ResearchEvidence`, `ProvenanceRef` | One `ResearchEvidence` per OPEN book | Manifests require ≥1 structured-evidence hash whose `source_ref.observation_id` is a required input |
| `genesis.pit.SourceCapabilityRegistry`, `SourceCapability`, `OperationalStatus` | Capability timeline per derivation source | `require_ready_at` uses the latest row at decision time. `is_ready` also needs `point_in_time_reliability ∉ {unknown, unverified}` |
| `genesis.pit.PITStore`, `BitemporalRecord` | One PIT record per book observation | Append-only, one record per `record_id`, no retroactive field update. `as_of_query` raises `PITViolation` when the top two admissible records share `valid_from` |
| `genesis.feature_manifest.SourceInputBindingStore`, `FeatureInputManifestStore`, `identity_transform_hash` | Manifest bodies for PAPER consumers | 1:1 contract↔source binding. `payload_hash == observation.artifact_hash`. Unique as-of head by max `valid_from`. `field_id` is walked as a **dict-only** path in the exact bytes |
| `genesis.evidence_pack.EvidencePack` | End-to-end verification test only | `source_artifact_hashes` must equal the set of required-input artifact hashes |
| `genesis.quota.QuotaLedger`, `load_quota_policy`, `VerifiedCacheStore`, `CacheReference` | Quota reservation for every attempt. Metadata cache | Active policy must be exactly `(250, 220, 30, 7)` for `oddspapi`. Rejects time regression. Cache hits are 0 units only with a verified exact-request entry |
| `genesis.coverage.CoverageLedger`, `ExclusionLedger`, `CoverageStatus` | Every exclusion and failure | Non-AVAILABLE entries need a frozen `ReasonCode` |
| `genesis.capabilities.MarketCapabilityRegistry` | G3 registers `market_supported_by_data_adapter = True` only | Any other required flag not `True` keeps the market not ready |
| `genesis.registry.AppendOnlyJsonl` | Adapter-owned ledgers | Hash-chained, verified-before-append, single-name files |

Frozen observations that shape this design. None of them requires a reopen:

- `MarketSnapshot` (`canonical.py`) is declared and documented but **consumed nowhere**
  in `src`. It has no bookmaker, line or status vocabulary. Slice 1 neither emits nor
  modifies it.
- `BitemporalRecord.superseded_by/superseded_at` can only be set when a record is first
  appended. The append-only store has no update path, so retroactive supersession is
  impossible by construction. Slice 1 always writes them as `None`.
- `genesis.logging._redact` masks keys by name (`api_key`, `token`, `secret`, …). It
  does **not** mask `apiKey`/`apikey` or secrets inside URL strings. Slice 1 never relies
  on it: secrets cannot reach any log by construction (§7). The gap is recorded in §20 as
  a deferred foundation hygiene item.
- `QuotaLedger.request` accepts writer-declared `occurred_at`. §6.1 bounds that on the
  adapter path.

---

## 6. Trusted clock and timestamp/PIT rules — D4 (resolves Q1, Q3)

### 6.1 Trusted clock

- `clock.TrustedClock` protocol: `now() -> str` (canonical `iso_utc`, microseconds, `Z`).
- `clock.SystemUtcClock` (the only production clock):
  - reads `time.time_ns()` for wall time and `time.monotonic_ns()` for drift;
  - at construction records `(wall0, mono0)`. Each `now()` checks
    `|(wall − wall0) − (mono − mono0)| ≤ wall_monotonic_drift_max_ms`, otherwise raises `ClockFault`
    (a wall-clock jump);
  - never returns a value earlier than its last value (`ClockFault` on regression);
  - at runner start, checks the value against the durable heads it will extend: the last
    `occurred_at` in the quota ledger and the last time in `acquisition.jsonl`. It must be
    ≥ both, otherwise `ClockFault`.
- **Live mode only** (Stage 7+, after G2): at runner start, record an OS time-sync
  attestation (Linux `timedatectl show -p NTPSynchronized --value` = `yes`; Windows: healthy only
  when `w32tm /query /status` exits 0, Leap Indicator is exactly `0`, Stratum is 1 through 15 inclusive
  (RFC 5905 primary and secondary strata; 0, 16 and 17-255 fail closed), and Source is present and is
  neither `Local CMOS Clock` nor `Free-running System Clock`).
  Missing, repeated or unparseable required fields fail closed (`synchronized: false`). A line
  with a label containing any non-ASCII character or ASCII control character (including NUL and DEL)
  makes the entire attestation unhealthy, even for unrelated fields. Labels are checked before any
  case folding or normalization: the supported live authorization format is the certified English,
  printable-ASCII `w32tm` label format. For valid ASCII labels, a line whose label, ignoring spaces
  and punctuation, begins with a required label is an attempt at it and is valid only when its label
  is exactly that label with a value;
  any other attempt fails closed, while lines that merely contain these words are ignored. A
  Stratum note that passes the strict note grammar fails closed if its comparison form (ASCII case
  folded, every non-alphanumeric character removed) contains `notsynchronized`, `notsynchronised`,
  `unsynchronized`, `unsynchronised` or `unspecified`, so hyphens, spacing, punctuation and
  parentheses cannot hide the phrase. The grammar itself is unchanged. The Windows rule was corrected under WC7-003 (ratified by the project owner): the earlier
  "source ≠ `Local CMOS Clock`" rule admitted an unsynchronized host. The owner later narrowed Stratum to 1-15 (RFC 5905 defines 16 as
  unsynchronized and 17-255 as reserved; the parser still reads any 0-255 value). Last Successful Sync Time
  is recorded as evidence and is not gated, because no maximum age is approved. Without a
  healthy attestation there is no live acquisition.
- **Independent cross-check per response:** the HTTP `Date` header `Hd` (provider-controlled,
  1 s precision) must satisfy `|Hd − T1| ≤ clock_skew_max_seconds`. Otherwise the whole response is
  quarantined (`CLOCK_SKEW`). In live mode a missing or unparseable `Date` header also
  quarantines.
- `FixedClock` exists **only** in `adapter_tests/support.py`. The live runner refuses any
  clock that is not a `SystemUtcClock` instance (test CLK-02).
- Parsers and normalizers are pure and never read a clock. Every time they use is passed
  in from the acquisition record.

This closes the freeze residual "writer-declared quota/ingestion timestamps" **for the
adapter path**. The adapter never accepts a caller-supplied time for quota, acquisition,
evidence or PIT fields. The frozen `QuotaLedger` still *accepts* declared times from any
writer. Binding a trusted clock inside the foundation is deferred (§20 FR-2) and is not
needed while the adapter runner is the ledger's only writer.

### 6.2 Timestamp definitions

| Name | Symbol | Source | Persisted in | Meaning |
| --- | --- | --- | --- | --- |
| quota reservation time | `Tq` | trusted clock | quota ledger `occurred_at`. Acquisition row | When one quota unit was reserved for this attempt |
| request_started_at | `T0` | trusted clock | acquisition row. Normalized doc | Immediately before the first request byte is written. `T0 ≥ Tq` |
| response_received_at (= retrieved_at) | `T1` | trusted clock | acquisition row. Raw and normalized `retrieved_at` and `first_seen_at`. PIT `available_at`, `retrieved_at`, `valid_from`. Normalized doc | After the last body byte is read. `T1 > T0` |
| provider Date header | `Hd` | response header | acquisition row | Skew cross-check only (§6.1) |
| provider/source timestamps | `Tp` | payload fields (per fixture/outcome, per the verified endpoint schema) | normalized doc (`provider_timestamps`). Normalized `publisher_timestamp` and PIT `published_at` = max `Tp` over the book's outcomes, or `None` | **Provenance only.** Never used for freshness or ordering. The one consumption rule it takes part in is parity with the frozen verifier: a head whose `published_at > D` is not usable at `D` (§12.3) |
| first_seen_at | — | = `T1` | raw and normalized observations | The earliest trusted time Genesis held *this observation*. Every retrieval is its own observation, so slice 1 never back-dates availability to an earlier retrieval of identical bytes |
| raw parse_ready_at | — | = `T1` | raw observation | Raw bytes can be parsed on receipt. Raw is never a decision input |
| parse_ready_at (normalized) | `T2` | trusted clock | normalized observation. `ResearchEvidence.ready_at` | After the whole response has been parsed and validated, before the first normalized publish. Shared by all books of one response |
| PIT ready_at | `T3` | trusted clock | PIT `ready_at` | After every normalized observation and structured-evidence object of the response is durably published, before the PIT appends. Shared by the response |
| available_at | — | = `T1` | PIT | The earliest time the value was available **to Genesis**. It is never earlier than `T1` for prospective capture |
| valid_from | — | = `T1`. = `T_inv` for an invalidation head (§13.2) | PIT. Normalized observation | Head ordering key. Latest `valid_from` wins |
| valid_to | — | OPEN: `min(T1 + price_ttl_seconds, S − prematch_guard_seconds)`. Every non-OPEN head: `None` | PIT. Normalized observation. `ResearchEvidence.freshness_expires_at` (OPEN) | End of decision usability. Tombstones never expire (§12.2) |
| event scheduled start | `S` | payload (same response, or the joined fixtures snapshot, §8.3) | normalized doc `scheduled_start_as_known` | Kickoff *as known at `T1`*. Not part of identity |
| decision cutoff | `D` | trusted clock of the consuming decision runner | `FeatureInputManifest.evidence_cutoff_ts` | The single as-of point for every admissibility check |

### 6.3 Invariants (validated on write and on replay)

```text
Tq ≤ T0 < T1 ≤ T2 ≤ T3
available_at = retrieved_at = first_seen_at = valid_from = T1        (response-derived heads)
OPEN only if T1 < S − prematch_guard_seconds; then T1 < valid_to ≤ S − prematch_guard_seconds
every Tp ≤ T1 + provider_future_tolerance_seconds
usable at D only if the record is the unique admissible head at D (§12.3) and
    T3 ≤ D and T1 ≤ D and (published_at is None or published_at ≤ D)
    and (valid_to is None or D < valid_to) and D < S − prematch_guard_seconds
```

All named durations above are fields of the versioned slice-1 policy (§12.1). They are
never written as literals in code.

`D ≥ T3` alone does not make visibility deterministic. A record can have `ready_at ≤ D`
and still be committed after the decision runner read the log. Rule: **acquisition and
decision phases are serialized.** The decision runner takes `D` only after it acquires the
acquisition-quiescence lock (the `acquisition.jsonl` coordinator plus an adapter run lock).
The frozen `verify_for_pack` unique-head check would detect any late record with
`ready_at ≤ D`, so a violation fails closed; it can never silently change a replay.

### 6.4 Provider timestamp anomalies (no normalization of offsets)

`SOURCE_AVAILABILITY.md` rule 2 ("naive timestamps, non-UTC timestamps … fail closed") is
frozen authority. Slice 1 therefore **rejects** rather than normalizes:

| Anomaly | Result |
| --- | --- |
| naive (no offset) | book → BLOCKED `TIMESTAMP_NAIVE` |
| explicit non-zero offset (e.g. `+01:00`) | book → BLOCKED `TIMESTAMP_NON_UTC` |
| unparseable / wrong JSON type | book → BLOCKED `TIMESTAMP_INVALID` |
| `Tp > T1 + provider_future_tolerance_seconds` | book → BLOCKED `TIMESTAMP_FUTURE` |
| `S` missing/invalid | event → BLOCKED `EVENT_START_INVALID` |
| `S ≤ T1` while status says pre-match | event → BLOCKED `CONTRADICTORY_STATUS` |
| `|Hd − T1| > clock_skew_max_seconds` or `Hd` missing (live) | response quarantined `CLOCK_SKEW` |
| `T1 ≤ T0` or quota time regression | `ClockFault`: runner halts |

If the G2 live capture shows OddsPapi emitting offsets, normalization needs a new ADR.
It is *not* silently allowed.

---

## 7. Canonical request identity and credential handling — D3

### 7.1 Principle

The credential and the canonical request never share a data structure. The request is
built as data from a pinned endpoint spec. The credential exists only as a `Secret`, held
by the transport. The transport adds the credential to the outgoing wire request at send
time. That happens after the canonical request has been hashed, persisted and logged.

### 7.2 Endpoint spec (`adapters/config/oddspapi_v4_endpoints.json`)

Each entry: `role` (`META_SPORTS`, `META_TOURNAMENTS`, `META_BOOKMAKERS`, `META_MARKETS`,
`FIXTURES`, `ODDS`), `method` (`GET`), `scheme` (`https`), `host` (lowercase, pinned),
`path` (exact, no trailing slash), `params` (each: `name`, `type` `int|str|date|csv_set`,
`required`, `set_valued`, `allowed_values?`), `credential_param` (the single name
used for the key, e.g. `apiKey`), `cacheable` (`true` for `META_*` only; `ODDS` is
always `false`), `cache_ttl_seconds`, `response_schema_id`, `doc_reference`,
`verified_live` (`false` until G2).

Metering fields. These describe the **provider**, never Genesis's budget (A3, §14.2):

- `provider_metering`: `PER_REQUEST` | `FIXED_WEIGHT` | `NON_METERED` | `VARIABLE` |
  `UNKNOWN`. Taken from Prep A / the reverified terms, and confirmed at G2 where the
  provider reports usage.
- `provider_request_weight`: integer ≥ 1 for `PER_REQUEST` (=1) and `FIXED_WEIGHT`;
  `0` for `NON_METERED`; `null` for `VARIABLE`/`UNKNOWN`.
- `provider_documented_billable`: `true` | `false` | `null` (not documented).
- `genesis_debit_units`: the **Genesis** budget units debited per attempt. It must satisfy
  `genesis_debit_units ≥ max(1, provider_request_weight or 1)`. A role with
  `provider_metering = VARIABLE` has no pre-send bound and is **not usable** in slice 1
  (§20 FR-1).

Paths and parameter names come from Prep A's reading of the OddsPapi v4 documentation
(base host and per-role paths such as sports, tournaments, bookmakers, markets, fixtures,
and odds by tournament). They are **provisional**. G2 verifies each one against a live
response before any recurring capture.

### 7.3 Canonical request

```json
{
  "domain": "genesis.adapters.oddspapi.request.v1",
  "provider_id": "oddspapi",
  "api_version": "v4",
  "role": "ODDS",
  "method": "GET",
  "scheme": "https",
  "host": "<pinned lowercase host>",
  "path": "<pinned path>",
  "query": [["<name>", "<canonical value>"], ...],
  "headers": [["accept", "application/json"], ["accept-encoding", "identity"]],
  "body": null
}
```

Canonicalization rules:

1. Parameters come only from typed arguments validated against the spec. Unknown names are
   rejected.
2. Any parameter whose name case-folds to the spec's `credential_param`, or to any of
   `{apikey, api_key, key, token, access_token, secret}`, is **rejected at build time**. It
   is never dropped silently.
3. Values render deterministically: `int` as a base-10 string with no sign or leading
   zeros; `str` as NFC-normalized, matching `^[A-Za-z0-9_.:-]{1,64}$`; `date` as
   `YYYY-MM-DD`; `csv_set` as sorted, de-duplicated, comma-joined (only where
   `set_valued: true`, e.g. the bookmaker filter).
4. `query` is sorted by `(name, value)`. `headers` is the fixed allowlist above,
   lowercase names, sorted.
5. `provider_request_hash = sha256(canonical_json(request))` (frozen
   `genesis.repro.canonical_json`: sorted keys, compact separators, UTF-8, trailing LF).
6. The canonical bytes are written immutably to `requests/<provider_request_hash>.json`.
   The file is content-addressed, so its name is its own integrity check.
7. `source_uri` for raw evidence is `oddspapi-request:sha256:<provider_request_hash>`. The
   raw contract's `uri_pattern` is `oddspapi-request:sha256:*`. No URL string is ever
   persisted.

Identity uses:

- Quota: `provider_request_hash` is passed to `QuotaLedger.request(...,
  provider_request_hash=h)`. It is part of the frozen request fingerprint.
- Cache: `cache_key = "oddspapi:v4:" + role + ":" + h`. `VerifiedCacheStore` binds
  `provider_request_hash = h`.
- Quota `request_id = "oddspapi-attempt:" + sha256(canonical_json({"domain":
  "genesis.adapters.oddspapi.attempt.v1", "provider_request_hash": h, "window_id": w,
  "attempt": n}))`. It is deterministic per planned attempt, so a crash-restart cannot
  mint a second reservation for the same attempt (§14.4).

### 7.4 `Secret`

- `Secret.__repr__`/`__str__` return `Secret(<fingerprint>)`, where fingerprint =
  first 12 hex of `sha256(b"genesis.adapters.credential-fp.v1\0" + key)`.
- Serialization and copying are blocked: `__reduce__`, `__getstate__`, `__copy__` and
  `__deepcopy__` raise. `canonical_json` fails on it because it is not a JSON type.
- `Secret.reveal_for_transport(token)` returns the value only when called with the
  transport module's private capability token (plain Python, not a security boundary). A
  static test (FRZ-06) proves no other module calls it.

### 7.5 Storage (after G1 only)

- File path given by `GENESIS_ODDSPAPI_CREDENTIAL_FILE`. It must lie outside the repository
  worktree and outside `GENESIS_ADAPTER_ROOT`. POSIX mode must be `0600` and owned by the
  runner user. On Windows, the ACL must grant only the runner user. The file holds one line
  with the key. Anything else is refused.
- The fingerprint recorded in the G1 approval must match the loaded key, otherwise the
  runner refuses.
- No environment variable ever holds the key itself.

### 7.6 Precedence rule and pre-persistence secret detection (closes A5)

> **Credential safety dominates raw-response retention. Secret-bearing bytes must never
> enter durable evidence.** Where this rule conflicts with "retain raw bytes"
> (§11, §15), this rule wins. A response that cannot be fully inspected before durable
> storage is **not** persisted as raw evidence.

**Transport hygiene**

- Redirects are **disabled**. A 3xx is `PROVIDER_ERROR`, never followed, because a
  redirect could carry the key to another host. The host is pinned. TLS verification uses
  the system trust store and is never disabled.
- The keyed URL is built inside `transport_http.send` only. It is held in one local
  variable and never assigned to an attribute, closure, log record, exception argument or
  return value.

**What is scanned.** The detector `secrets.scan_for_secret(data, secret)` runs over every
byte sequence **before** it can be written anywhere durable (evidence, ledgers, cache,
quarantine, logs, run records):

1. the response body — after content decoding (§7.6 "content-encoded bodies"), and also
   the undecoded wire body;
2. every response header **name and value**, before the header allowlist is applied;
3. any exception text or `repr` that code might want to record. In practice nothing
   records it (§7.7), but the scanner still guards the sanitized record;
4. canonical request bytes, as an assertion: by construction they can't contain the key.
   A hit is a programming error and halts;
5. at stage end and at G3, every file under `GENESIS_ADAPTER_ROOT`
   (`verify.scan_runtime_for_secret`).

**Forms detected** (key `k`, length `n`; comparisons are ASCII-case-insensitive for
text forms):

| Form | Detection |
| --- | --- |
| Raw UTF-8/ASCII | `k` |
| URL/query encodings | percent-encoded (upper- and lower-case hex), `+`-for-space form, double-encoded (`%25XX`), and `apiKey=`-style `name=value` fragments |
| JSON string escapes | `\uXXXX` escaping of every character and of mixed characters; escaped `/` |
| UTF-16 LE/BE (with or without BOM), UTF-32 LE/BE | `k` encoded in each |
| Base64 standard and URL-safe | the encoding of `k` at all three alignment offsets (the stable inner core for offsets 1 and 2), with and without padding |
| Hex | upper- and lower-case hex of `k` |
| **Fragments** | any contiguous substring of `k` of length ≥ `secret_fragment_min_chars` = `max(8, ceil(n / 3))`, in the raw, percent-encoded and UTF-16 forms. Hex fragments of ≥ `2 × secret_fragment_min_chars` hex characters |

The fragment threshold is a versioned provisional policy parameter (§12.1). With realistic
key lengths (≥ 24 characters), a random-looking fragment of that length colliding by
chance with provider content is negligible. A true accidental collision fails **safe**:
the response is quarantined.

**Content-encoded bodies.** The request sends `accept-encoding: identity`. If the response
still has a `content-encoding`:

- `gzip`/`deflate`: decoded in memory under the `max_response_bytes` bound (with a
  decompression-ratio guard). Both the wire and decoded bytes are scanned. Raw evidence
  stores the decoded body, with `content_encoding` recorded in the acquisition row.
- Anything else, nested encodings, or decode failure or bound breach means the body
  **cannot be inspected**. It is not persisted.

**When a scan hits, or inspection is impossible**

- **No body bytes are persisted** in any form: no raw object, no redacted derivative, no
  hash of the body. A digest of secret-bearing bytes is itself derived from the secret, so
  none is kept.
- Only secret-safe quarantine metadata is written to `quarantine.jsonl`:
  `{acquisition_id, provider_request_hash, T1, http_status, byte_length,
  content_type (only if the header value is itself clean), header_names[] (names only),
  detection_classes[] (e.g. ["BODY_UTF16", "HEADER_VALUE"]), reason}`. The metadata is
  itself scanned before write.
- The response gets `QUARANTINED / SECRET_ECHO` or `QUARANTINED / UNINSPECTABLE_BODY`. For
  `SECRET_ECHO`, all live acquisition halts, capability rows go `BLOCKED`, and a human must
  rotate the key (re-G1).
- Header values that are clean but outside the allowlist are dropped as before
  (allowlist: `date`, `content-type`, `content-length`, `content-encoding`, `etag`,
  `last-modified`, `retry-after`, names matching `^x-(ratelimit|requests)-[a-z-]{1,40}$`;
  values capped at 256 characters).

### 7.7 Total transport exception boundary (closes A6)

`transport_http.send` never lets credential-bearing exception text, URL, traceback,
chained cause/context or warning leave the module. It **does not** change the meaning of
process-control exceptions. Two classes of exception are handled differently.

**(a) Ordinary transport/request failures** (every `Exception` subclass: DNS, connect,
TLS, timeout, reset, protocol, decode, `http.client` errors, and anything a fault injector
raises as an `Exception`) are converted to the adapter's secret-safe failure
representation and **not raised**:

1. The send path (URL construction, connection, TLS, request write, response read,
   decoding) runs inside `try: … except Exception as exc:`.
2. The handler extracts only `{"class": type(exc).__name__, "errno": <int or None>}`
   into `sanitized_error`. It never records `str(exc)`, `exc.args`, attributes, notes,
   `__cause__` or `__context__`.
3. It then clears `exc.__traceback__` and deletes every local holding the keyed URL or
   request line.
4. After leaving the `except` block, so that no exception context remains, it returns
   `TransportResult(outcome="NO_RESPONSE" | "TRUNCATED", sanitized_error=…)`. This
   sanitized result **is** the safe adapter transport exception: the only form in which
   an ordinary failure leaves the transport.

**(b) Process-control exceptions keep their semantics.** `KeyboardInterrupt` and
`SystemExit` are never converted, demoted or swallowed:

1. The same `try` has, after `except Exception`, exactly one
   `except BaseException as exc:` clause. It is the only `BaseException` handler anywhere
   in `genesis_adapters` (FRZ-11), and it never completes normally: it always leads to
   step 3. It records only the class and, for `SystemExit`, the exit code:
   - `type(exc.code) is int` → that integer;
   - `exc.code is None` → `None`;
   - anything else (e.g. a string, which may carry text) → `1`. That keeps the process
     exit status Python would have produced, without keeping the text.
2. It clears `exc.__traceback__` and deletes `exc` and every keyed local (URL, request
   line, connection object).
3. **After** the `except` block ends (so the fresh exception has
   `__context__ is None`, not merely a suppressed context), it raises a **fresh**
   `KeyboardInterrupt()` or `SystemExit(code)` (`SystemExit()` when `code is None`)
   **`from None`**. The fresh exception has no args beyond the integer code, and
   `__cause__`, `__context__` and `__notes__` are all absent. Its traceback holds only the
   transport frame, from which all keyed locals were deleted.
4. The result is that `KeyboardInterrupt` reaches the process top level as
   `KeyboardInterrupt`, and `SystemExit` as `SystemExit` with the integer code preserved.
5. Any other non-`Exception` `BaseException` (e.g. `GeneratorExit`; not expected in a
   synchronous transport) goes through the same clause: a fresh no-argument instance of
   the same class, raised `from None` after the clause. If the class can't be built with
   no arguments, a fresh `SystemExit(1)` is raised instead. Process-control meaning is
   never turned into an ordinary result.

**No demotion anywhere above the transport.** No adapter code (runner, acquisition,
scheduler, CLI, emit, reader) may catch `KeyboardInterrupt`, `SystemExit` or
`BaseException`. That rules out bare `except:`, `except BaseException`,
`except (KeyboardInterrupt | SystemExit)` and
`contextlib.suppress(BaseException/KeyboardInterrupt/SystemExit)`. It also rules out
`return`/`break`/`continue` inside `finally`, which would swallow them. `except Exception`
is allowed because it cannot catch them. The only permitted handler is (b) in
`transport_http.send`. Cleanup uses `try/finally` without flow-altering statements. Static
test FRZ-11 enforces all of this.

**Other hygiene**

1. `http.client` debug level is forced to 0. No `logging` handler is attached in the
   transport. `warnings` raised inside the send path are captured and discarded (their
   text may name the URL).
2. The transport never uses `urllib.request.urlopen` with a URL-bearing `Request` that
   can surface in `HTTPError.url`/`.filename`. It uses `http.client.HTTPSConnection` with
   host and path passed separately. The key-bearing query exists only in a request-line
   local inside the send frame, and is deleted on every exit path.
3. Defence in depth at runner level: the CLI installs `sys.excepthook`,
   `threading.excepthook` and `sys.unraisablehook` handlers that print only a sanitized
   class name (and nothing else) and scan any text they would emit. These hooks do **not**
   change control flow or exit status. The interpreter still exits for an uncaught
   `KeyboardInterrupt` with its normal SIGINT status, and handles `SystemExit` natively
   (it never reaches `sys.excepthook`). `faulthandler` is not enabled in live mode.

**Adversarial test TX-01** (Stage 7). The runner runs in a **subprocess**, started through
a thin test harness. The harness calls the runner's real `main()`; its outermost frame
records `type(exc).__name__` and the `SystemExit` code of whatever reaches it into a
result file (no text) and then re-raises unchanged. A fault-injecting connection class
fires at every send stage (connect, write, read headers, read body, decode):

1. **Ordinary errors:** an `Exception` whose message, `args`, `filename`, `url`
   attribute, `__notes__` and chained `__cause__`/`__context__` all contain the
   credential-bearing URL, and a `warnings.warn` carrying the URL. Expected: the
   acquisition records the sanitized `NO_RESPONSE`/`TRUNCATED` result (class/errno only),
   the runner continues or ends normally, and nothing reaches the top level.
2. **Injected `KeyboardInterrupt`** (constructed with the URL as its argument, with the URL
   also in `__notes__`/`__cause__`). Expected: the harness records `KeyboardInterrupt`;
   the subprocess ends with the platform's uncaught-SIGINT status (POSIX `-2`/`130`,
   Windows `0xC000013A`); the runner did **not** swallow or convert it.
3. **Injected `SystemExit(37)`**, and separately `SystemExit("<keyed URL>")`. Expected: the
   harness records `SystemExit`, and the return code is exactly `37`, or `1` for the string
   case, with the string itself never printed. `SystemExit(None)` returns `0`.
4. **Introspection:** for 2 and 3, the harness also checks that the exception reaching it
   has `__cause__ is None`, `__context__ is None`, no `__notes__`, args of `()` or
   `(int,)`, and that no frame in its traceback has a local whose `repr` contains any
   §7.6 form of the sentinel.

Pass also requires, for every case:

- captured **stdout** clean;
- captured **stderr** clean;
- every **log** clean;
- every **evidence** file clean;
- every **provenance** record clean (acquisition/quota/coverage ledgers, `requests/`,
  `quarantine.jsonl`, run record, harness result file);

each checked for every §7.6 form of the sentinel key.

---

## 8. Identity rules — D7

### 8.1 Genesis ID function

```text
gid(kind, **parts) = kind + ":" + sha256(canonical_json({
    "domain": "genesis.adapters.identity.v1", "kind": kind, "parts": parts}))
```

The full 64-hex digest is used. It is never truncated and never joined with a delimiter, so
it has no ambiguity of the kind `canonical.stable_id` has with `"|"`.

**Native ID canonicalization.** Each provider ID field has a declared JSON type in the
response schema (`int` or `str`). A value of the other type is `SCHEMA_REJECTED`, so no
coercion happens (`17` ≠ `"17"`). Ints are rendered base-10. Strings must match
`^[A-Za-z0-9_.:-]{1,64}$`. `native_type` is part of every native-derived ID.

### 8.2 Entities

| Entity | Genesis ID | Established by | Never established by |
| --- | --- | --- | --- |
| Competition | pinned slug, e.g. `soccer.eng.premier-league`, `soccer.esp.laliga` | `oddspapi_v4_identity_map.json`: `{provider_tournament_id, native_type, genesis_competition_id, sport:"soccer"}`. Exactly two entries in slice 1 | tournament name, country name |
| Participant | `gid("part", provider="oddspapi", ns="v4.participant", native_type, native)` | provider participant ID | team name (stored as `display_name` attribute only) |
| Event | `gid("evt", provider="oddspapi", ns="v4.fixture", native_type, native)` | provider fixture ID, bound on first sight to (competition, home, away) in `IdentityRegistry` | names, kickoff time |
| Bookmaker | pinned slug, e.g. `bk.<slug>` | identity map `{provider_bookmaker_key, genesis_bookmaker_id, kind:"fixed_odds_sportsbook", declared:true}` | display name |
| Market | `gid("mkt", event_id, family, line, period)` | market map entry for the provider market ID (plus line field where the provider encodes lines separately) | market name, outcome labels |
| Selection | `gid("sel", market_id, selection)`, `selection ∈ {HOME, DRAW, AWAY, OVER, UNDER}` | market map outcome ID → selection code | labels such as "1", "X", "Over" |
| Market book (PIT entity) | `gid("book", market_id, bookmaker_id)` | the (market, bookmaker) pair | — |

### 8.3 Identity registry (append-only, `identity.jsonl`)

- Row `fixture_bound`: `{event_id, provider_fixture_id, native_type, competition_id,
  home_participant_id, away_participant_id, first_seen_at: T1, raw_observation_id}`.
  It is written the first time a fixture ID is seen in a schema-valid response.
- Row `participant_seen`: `{participant_id, provider_participant_id, display_name,
  first_seen_at, raw_observation_id}`. Name drift appends a new row (`NAME_DRIFT` note).
  Drift never changes identity.
- **Conflict:** a later response binds the same fixture ID to a different competition, home
  or away participant, or swaps home and away. Result: `IDENTITY_CONFLICT`, the event is
  **quarantined** (§15 F-21) and a human must review. A human resolution is a new identity
  map version and so a new derivation source (§13.3).
- Home = away, or a missing participant ID, gives `PARTICIPANT_AMBIGUOUS`.
- Every normalized document pins `identity_registry_head = {sequence, record_hash}` of the
  registry state used, so re-derivation replays exactly that prefix.
- **Scheduled start join.** If the ODDS response carries fixture start and participants,
  those are used (same `T1`). Otherwise the parser joins the newest FIXTURES observation
  with `T1_fixtures ≤ T1_odds` and `T1_odds − T1_fixtures ≤ 86400 s`, pinning its
  `observation_id` in the document. A missing or older snapshot gives
  `EVENT_METADATA_STALE` (BLOCKED). G2 decides which case holds.

### 8.4 Bookmakers

- The operational policy declares 1–3 bookmakers. The policy validator rejects more than 3,
  and rejects any whose `kind ≠ fixed_odds_sportsbook`.
- The canonical `MarketBookDocument` has **no** bookmaker-count limit. Test MKT-02
  normalizes five bookmakers under a test-only policy.
- Bookmakers in a response that are not declared are ignored. They stay in raw evidence,
  are counted in coverage as `OUT_OF_SCOPE_BOOKMAKER`, and can later be derived from the
  same raw bytes under a new policy (a new derivation source).

### 8.5 Markets, lines, selections (exact O/U 2.5)

`oddspapi_v4_market_map.json` entries:

```json
{"provider_market_id": <native>, "native_type": "int|str",
 "family": "SOCCER_1X2_FT" | "SOCCER_TOTAL_GOALS_OU_FT",
 "period": "FT_REGULAR",
 "line": null | "2.5",
 "line_source": "none" | "market_definition" | "outcome_field:<name>",
 "outcomes": {"<provider_outcome_id>": "HOME"|"DRAW"|"AWAY"|"OVER"|"UNDER", ...},
 "doc_reference": "...", "verified_live": false}
```

Rules:

1. A provider market ID not in the map is out of scope. It is counted and never
   normalized.
2. The line is read from the declared `line_source`, parsed with `Decimal` from the JSON
   literal (`parse_float=Decimal`), and must satisfy `Decimal(value) == Decimal("2.5")`
   exactly. So `2.5`, `2.50` and `"2.5"` (if typed `str`) are equal, while `2.25`, `2.75`,
   `1.5`, `3.5`, `2.4999` and any Asian quarter line are **excluded**, never merged.
3. A missing or non-numeric line, or a line from a source other than the declared one, is
   excluded (`LINE_UNIDENTIFIED`).
4. Two entries resolving to the same (event, family, line, bookmaker) in one response:
   identical content collapses; different content gives BLOCKED `CONTRADICTORY_DUPLICATE`.
5. Outcomes are mapped **only by provider outcome ID**. A book is complete only when it has
   exactly the family's selection set (1X2: HOME, DRAW, AWAY; O/U: OVER, UNDER). A missing
   outcome gives BLOCKED `INCOMPLETE_SELECTIONS`. An extra, unmapped outcome ID inside a
   mapped market gives BLOCKED `UNMAPPED_OUTCOME` (schema drift).
6. Provider market and outcome IDs for slice 1 are pinned from the G2 `META_MARKETS`
   capture. Until then the map holds synthetic fixture IDs flagged
   `"fixture_only": true`, and the operational loader refuses any map that still has
   fixture-only entries.

---

## 9. Canonical market representation and immutable schemas — D6 (resolves Q4)

The frozen `MarketSnapshot` is left untouched. Slice 1 owns one normalized document type.
It is published as an `EvidenceStore` artifact and is the payload of one PIT record.

### 9.1 `MarketBookDocument` (schema `genesis.adapters.oddspapi.market-book.v1`)

```json
{
  "schema": "genesis.adapters.oddspapi.market-book.v1",
  "derivation_kind": "RESPONSE",
  "derivation_version": "mb1-<16hex>",
  "provider": "oddspapi", "api_version": "v4",
  "raw_artifact_hash": "<64hex>", "raw_observation_id": "<64hex>",
  "provider_request_hash": "<64hex>",
  "acquisition_id": "<64hex>",
  "identity_registry_head": {"sequence": 0, "record_hash": "<64hex>"},
  "expected_scope_hash": "<64hex>|null",
  "fixture_join_observation_id": "<64hex>|null",
  "sport": "soccer", "competition_id": "soccer.eng.premier-league",
  "event_id": "evt:<64hex>", "provider_fixture_id": {"native_type": "int", "value": "123"},
  "home_participant_id": "part:<64hex>", "away_participant_id": "part:<64hex>",
  "scheduled_start_as_known": "2026-10-03T14:00:00.000000Z",
  "bookmaker_id": "bk.<slug>", "provider_bookmaker_key": "<key>",
  "market_id": "mkt:<64hex>", "market_family": "SOCCER_TOTAL_GOALS_OU_FT",
  "line": "2.5", "period": "FT_REGULAR",
  "entity_id": "book:<64hex>",
  "market_state": "OPEN|SUSPENDED|ABSENT|BLOCKED|INVALIDATED",
  "state_reasons": ["<AdapterFailure code>", ...],
  "selections": {
    "OVER":  {"selection_id": "sel:<64hex>", "provider_outcome_id": {...}, "odds_decimal": "1.91"},
    "UNDER": {"selection_id": "sel:<64hex>", "provider_outcome_id": {...}, "odds_decimal": "1.95"}
  },
  "provider_status": {"event": {...raw typed values...}, "market": {...}, "outcomes": {...}},
  "provider_timestamps": {"<field path>": "<iso as given>", ...},
  "times": {"request_started_at": "…Z", "response_received_at": "…Z"},
  "valid_from": "…Z", "valid_to": "…Z|null",
  "side": "BACK"
}
```

- `selections` is present **only** when `market_state = OPEN`. Every other state omits it,
  so any manifest `field_id` such as `$.selections.OVER.odds_decimal` fails the frozen
  "field is absent from exact bytes" check. A non-OPEN head can never supply a price
  (test EV-06).
- `odds_decimal` is `format(Decimal(literal).normalize(), "f")`, parsed from the JSON
  literal with `parse_float=Decimal`. It must be finite, within
  `odds_min ≤ odds ≤ odds_max`, and have at most `odds_max_fraction_digits` fractional
  digits (policy fields, §12.1).
- A `RESPONSE` document (every state except `INVALIDATED`) depends **only** on raw bytes,
  the acquisition record (`T0`, `T1`, request), pinned map, schema and policy digests
  (through `derivation_version`), the pinned identity-registry prefix, the expected-scope
  artifact and the fixture-join observation. It holds no `T2`/`T3` and no clock reads, so
  re-derivation is byte-identical (EV-03).
- Serialization: `genesis.repro.canonical_json`. `artifact_hash = sha256(bytes)`.

### 9.1a `INVALIDATED` document (`derivation_kind = "INVALIDATION"`)

An invalidation is not derived from a provider response, so it has its own deterministic
input: one row of the append-only invalidation ledger (`invalidations.jsonl`, §13.2).

```json
{
  "schema": "genesis.adapters.oddspapi.market-book.v1",
  "derivation_kind": "INVALIDATION",
  "derivation_version": "<same source derivation_version as the invalidated record>",
  "invalidation_id": "<64hex>",
  "invalidation_ledger_head": {"sequence": 0, "record_hash": "<64hex>"},
  "invalidated_observation_id": "<64hex>",
  "invalidated_artifact_hash": "<64hex>",
  "invalidated_pit_record_id": "pit:<64hex>",
  "invalidation_class": "OBSERVATION_DEFECT|DERIVATION_DEFECT|PROVIDER_ERROR_NOTICE|OPERATOR",
  "invalidation_reason": "<AdapterFailure code>",
  "provider": "oddspapi", "api_version": "v4",
  "sport": "...", "competition_id": "...", "event_id": "...", "bookmaker_id": "...",
  "market_id": "...", "market_family": "...", "line": "...", "period": "...",
  "entity_id": "book:<64hex>",
  "scheduled_start_as_known": "<copied from the invalidated document>",
  "market_state": "INVALIDATED",
  "state_reasons": ["<AdapterFailure code>"],
  "times": {"invalidation_recorded_at": "<T_inv>"},
  "valid_from": "<T_inv>", "valid_to": null,
  "side": "BACK"
}
```

Every field is a pure function of (invalidation ledger row, invalidated normalized
document bytes). `selections` is absent. `verify_derivation` recomputes it from those two
inputs (§11.5, §13.2).

### 9.2 `derivation_version`

```text
derivation_version = "mb1-" + sha256(canonical_json({
   "code_version": genesis_adapters.oddspapi.normalize.CODE_VERSION,
   "identity_map_digest": ..., "market_map_digest": ..., "status_map_digest": ...,
   "response_schema_digest": ..., "policy_digest": ..., "endpoint_spec_digest": ...}))[:16]
```

It is the normalized contract's `parser_version`, and it is embedded in the contract ID
and PIT `source_id` (§11.2). `policy_digest` covers **every** field of
`oddspapi_slice1_policy.json`, including all provisional freshness, timing, tolerance,
coherence and fragment parameters (§12.1). Any change to code semantics, maps, closed
schemas or any policy value therefore creates a new source (§13.3). This is also what
makes the provisional parameters auditable: every observation names the exact
parameter set that produced its `valid_to`.

### 9.3 Other adapter-owned immutable records

| Record | Store | Key fields |
| --- | --- | --- |
| `CanonicalRequest` | `requests/<h>.json` | §7.3 |
| `AcquisitionRecord` rows | `acquisition.jsonl` | `acquisition_id` (= quota `request_id` digest part), `window_id`, `purpose` (`SCHEDULED`/`CONDITIONAL`/`RETRY`/`METADATA`/`G2_VERIFICATION`), `attempt`, `provider_request_hash`, row types `planned{provider_metering, provider_request_weight, provider_documented_billable, genesis_debit_units}` → `quota_decided{Tq, frozen_ledger_reason, genesis_units_debited, cache_entry_id?}` → `sent{T0}` → `completed{T1, outcome, http_status, headers, content_encoding, byte_length, raw_observation_id?, sanitized_error?, provider_reported_usage?}` → `normalized{T2, T3, derivation_version, expected_scope_hash, identity_registry_head, normalized_observation_ids[], pit_record_ids[], coverage_entry_ids[]}` or `quarantined{quarantine_id}` or `reconciled{outcome: ORPHANED_RESERVATION}` |
| Quarantine metadata | `quarantine.jsonl` | secret-safe fields only (§7.6) |
| `InvalidationRecord` rows | `invalidations.jsonl` | §13.2 |
| `IdentityRegistry` rows | `identity.jsonl` | §8.3 |
| Expected scope | `scopes/<hash>.json` | §12.4 |
| `AdapterAuthorityLedger` rows | `authority.jsonl` | §16.6 |

---

## 10. Provider status allowlists — D8

`oddspapi_v4_status_map.json`:

```json
{"event_status": [{"field": "<path>", "json_type": "int|str|bool", "value": <v>,
                   "genesis": "PREMATCH" | "NOT_PREMATCH", "doc_reference": "...",
                   "verified_live": false}],
 "market_status": [{"field": ..., "json_type": ..., "value": ..., "genesis": "OPEN" | "SUSPENDED"}],
 "outcome_status": [{"field": ..., "json_type": ..., "value": ..., "genesis": "ACTIVE" | "INACTIVE"}]}
```

Rules:

1. Matching is on `(field, json_type, value)`. `1` and `"1"` are different. Anything not
   listed is `UNKNOWN_*_STATUS`, which gives a BLOCKED head (identity resolvable) or an
   exclusion (identity not resolvable).
2. The book is OPEN only if the event is `PREMATCH`, the market is `OPEN` (or the provider
   has no market-level status and the schema declares that), every required outcome is
   `ACTIVE` with a valid price, and every timestamp check passes.
3. Any `INACTIVE` outcome or `SUSPENDED` market gives SUSPENDED (no prices).
4. Event `NOT_PREMATCH` (live, finished, postponed, cancelled, abandoned, …) gives BLOCKED
   `EVENT_NOT_PREMATCH` for every in-scope book of that event.
5. **Contradictions** give BLOCKED `CONTRADICTORY_STATUS`:
   - event `NOT_PREMATCH` with an `ACTIVE` outcome;
   - `PREMATCH` with `S ≤ T1`;
   - an `ACTIVE` outcome with a missing, zero or `≤ 1.0` price;
   - two status fields for the same level that disagree.
6. Where Prep A found the provider documentation ambiguous, the value is **left out** of the
   map (so it is unknown and BLOCKED) until G2 evidence and a human-reviewed map update add
   it.
7. G3 requires every map entry used by the source to have `verified_live: true`.
8. Each map row carries `doc_reference`. The map digest is part of `derivation_version`.

**Price coherence** (versioned provisional policy): for OPEN books, `Σ 1/odds` must lie
in `overround_1x2` for 1X2 and in `overround_ou` for O/U (§12.1). Outside the band gives
BLOCKED `PRICE_INCOHERENT` (`CONTRADICTORY_EVIDENCE`).

### 10.1 Closed provider schemas and additive drift (closes A8)

`adapters/config/oddspapi_v4_response_schemas.json` defines one closed schema per endpoint
role, keyed by `response_schema_id`. The validator is `schema.py`: a small, dependency-free
closed-object checker. Nothing is added to `requirements.lock`.

**Semantic structures.** Every JSON object on a path that carries status, price, line,
identity or market semantics is **closed** (`additional_properties: false`). That means
the envelope, event/fixture, participant, bookmaker block, market, outcome, price, line
and status objects, and the schema for each lists **all** permitted keys with JSON types
and required/optional flags.

**Declared-inert keys.** A key the provider sends but that has no semantic effect (e.g. a
display string, a logo URL) must be listed explicitly as `inert` in the closed schema
(type-checked, never read). The inert classification is made at G2 from live evidence and
reviewed by a human. It is part of `response_schema_digest`, so it is part of
`derivation_version`.

**Drift rules** (no silent ignore):

| Unexpected content | Scope of effect | Result |
| --- | --- | --- |
| Unknown key, or known key with the wrong JSON type, inside an outcome, price, line, market-status or market object | that book | BLOCKED head, `SCHEMA_DRIFT`; no `selections` |
| Same, inside an event/fixture, participant or event-status object | every in-scope book of that event | BLOCKED heads, `SCHEMA_DRIFT` |
| Same, inside a bookmaker block | every in-scope book of that event × bookmaker | BLOCKED heads, `SCHEMA_DRIFT` |
| Same, in the envelope or at any level where the affected entities can't be resolved | whole response | response REJECTED `SCHEMA_DRIFT`; no observations, **no tombstones**; raw retained (subject to §7.6) |
| Unknown **enum-like value** (status code, market-type code, period code) | as above | the status rules in §10, or `SCHEMA_DRIFT` for non-status codes |

`SCHEMA_DRIFT` is always CRITICAL for G3 purposes (§16.5). The remedy is a human-reviewed
schema update (new `derivation_version`); drift is never auto-accepted.

---

## 11. Raw versus normalized evidence — D12

### 11.1 Flow (strict order; each step durable before the next)

```text
plan → gate checks (§16) → QuotaGate.reserve (Tq) ──blocked──▶ acquisition(quota_decided, blocked) + coverage NOT_ATTEMPTED; stop
   │allowed (Genesis debit) / verified cache hit (META_* only → cached bytes; no new observation; stop)
   ▼
acquisition(sent, T0) → transport (total; §7.7) → T1
   ▼
content decode (bounded) + secret scan of wire body, decoded body, all header names/values (§7.6)
   ──hit──▶ quarantine.jsonl (secret-safe metadata only; no body bytes, no body hash); halt
   ──uninspectable──▶ quarantine.jsonl (metadata only); no raw evidence; stop
   ▼
raw EvidenceStore.publish (PROSPECTIVE_CAPTURED)  → acquisition(completed, raw_observation_id)
   ▼
[META_* only] VerifiedCacheStore.publish(bytes, expires = T1 + cache_ttl_seconds[role])
   ▼
skew check / status-code / strict JSON / closed envelope schema ──fail──▶ coverage REJECTED; stop (raw retained)
   ▼
parser (pure; closed schemas §10.1) → ParsedResponse (books, tombstones, drift blocks, exclusions)
   ▼
T2 ← clock; for each book: normalized EvidenceStore.publish (DERIVED)
             for each OPEN book: StructuredEvidenceStore.publish(ResearchEvidence)
   ▼
T3 ← clock; for each book: PITStore.append(BitemporalRecord)
   ▼
CoverageLedger entries; acquisition(normalized, …)
```

### 11.2 Contracts and sources (registered at Stage 3/5 in the runtime registries)

| Item | Raw | Normalized |
| --- | --- | --- |
| `contract_id` | `oddspapi-v4-raw-response-v1` | `oddspapi-v4-market-book-<derivation_version>` |
| `provider` | `oddspapi` | `oddspapi` |
| `source_type` | `oddspapi_v4_rest_response` | `oddspapi_v4_market_book` |
| `uri_pattern` | `oddspapi-request:sha256:*` | `genesis-derived:oddspapi-v4-market-book:<derivation_version>:*` |
| `source_uri` | `oddspapi-request:sha256:<h>` | `RESPONSE`: `genesis-derived:oddspapi-v4-market-book:<derivation_version>:<entity_id>:<raw_observation_id>`. `INVALIDATION`: `genesis-derived:oddspapi-v4-market-book:<derivation_version>:<entity_id>:invalidation:<invalidation_id>` |
| `availability_class` | `PROSPECTIVE_CAPTURED` (`supports_prospective_capture=True`) | `DERIVED` (per `SOURCE_AVAILABILITY.md`: parsed projections are derived artifacts carrying the raw hash and parser version) |
| `parser_version` | `raw-capture-v1` | `<derivation_version>` |
| `timestamp_precision` | `microsecond` | `microsecond` |
| `availability_rule` | `retrieved_at = trusted T1` | `available at T1; ready at T3; valid until valid_to` |
| `licensing_note` | pinned at G1 from the reverified terms. Fixture-only value: `FIXTURE-ONLY-NO-PROVIDER-TERMS` | same |
| PIT `source_id` | — (raw is never a PIT input) | `oddspapi.v4.soccer.market_book.<derivation_version>` |
| `SourceInputBinding` | — | 1:1 normalized contract ↔ PIT source, `approval_reference` = G3 record ID |

### 11.3 Observation field values

| Field | Raw observation | Normalized observation (`RESPONSE`) | Normalized observation (`INVALIDATION`) |
| --- | --- | --- | --- |
| `retrieved_at` | `T1` | `T1` | `T_inv` (when the invalidation information reached Genesis) |
| `first_seen_at` | `T1` | `T1` | `T_inv` |
| `parse_ready_at` | `T1` | `T2` | `T2_inv` (clock after the document is built) |
| `publisher_timestamp` | `None` (`Hd` lives in the acquisition row) | max `Tp` of the book, or `None` | `None` |
| `valid_from` / `valid_to` | `None` / `None` | `T1` / per §6.2 | `T_inv` / `None` |
| `upstream_version` | `v4` | `v4` |
| `content_type` | response `content-type` (must start with `application/json`) | `application/json` |

### 11.4 PIT record per book

```text
record_id   = "pit:" + sha256(canonical_json({"domain":"genesis.adapters.pit-record.v1",
                        "source_id": S_ID, "artifact_hash": normalized_artifact_hash}))
entity_id   = book entity_id          source_id = S_ID
payload_hash= normalized_artifact_hash
RESPONSE:     available_at = T1   published_at = max Tp | None   retrieved_at = T1   ready_at = T3
              valid_from = T1     valid_to = per §6.2
INVALIDATION: available_at = T_inv  published_at = None  retrieved_at = T_inv  ready_at = T3_inv
              valid_from = T_inv  valid_to = None
superseded_by = None   superseded_at = None       (always)
```

`record_id` is keyed on the artifact, not the observation (whose ID includes `T2`). A
crash-resume re-publish therefore cannot create a second PIT record for the same book.
The resume path looks up the existing normalized observation with
`EvidenceStore.get_observations(artifact_hash)`. It requires exactly one observation under
the normalized contract and reuses it (PIT-08).

### 11.5 Reconciliation with the frozen `FeatureInputManifest-v1`

The adapter builds manifest bodies (`manifest.py`) for one (event, market) at cutoff `D`:

- `event_id`, `market_id`: Genesis IDs.
- `required_inputs[]`, one per (bookmaker, selection) used:
  - `role: "feature"`, `input_key: "odds.<bookmaker_id>.<SELECTION>"`,
    `entity_id: book entity_id`, `source_id: S_ID`,
    `source_contract_id: normalized contract`;
  - `source_capability_version` and `source_capability_record_hash`: the unique capability
    head row at `D` (`record_hash` of that `capabilities.jsonl` row);
  - `raw_artifact_hash`: **the normalized artifact hash**. This is the frozen field's
    meaning: the verifier compares it to `observation.artifact_hash` and to
    `record.payload_hash`;
  - `observation_id`: the normalized observation. `pit_record_id` and `pit_record_hash`
    come from the PIT row;
  - `field_id: "$.selections.<SELECTION>.odds_decimal"` (dict-only path, as the frozen
    walker needs), `transform_artifact_hash: identity_transform_hash(field_id)`.
- `structured_evidence_hashes`: the `ResearchEvidence` digests of the pinned OPEN books.
- The adapter-side soundness check is `verify.verify_derivation(observation_id)`. It is
  **deterministic for every normalized document** and dispatches on `derivation_kind`:
  - `RESPONSE` (OPEN, SUSPENDED, ABSENT, BLOCKED, including SCHEMA_DRIFT blocks): load the
    raw bytes by `raw_artifact_hash`, replay the parser at the pinned
    `derivation_version` with the pinned registry prefix, scope and join, and require
    byte equality with the normalized artifact. Raw bytes are therefore bound
    transitively: the normalized hash commits to `raw_artifact_hash` and
    `raw_observation_id`.
  - `INVALIDATION`: load the `invalidations.jsonl` row by `invalidation_id` (the pinned
    `invalidation_ledger_head` must be a prefix of the verified ledger and must contain
    the row), load the invalidated normalized document by `invalidated_observation_id`
    (its artifact hash must equal `invalidated_artifact_hash`), rebuild §9.1a from those
    two inputs, and require byte equality. It also checks that `invalidated_pit_record_id`
    names a PIT record whose `payload_hash` is the invalidated artifact and whose `entity_id`
    and `source_id` equal the invalidation record's.
  - Any other `derivation_kind`, or a document whose inputs are missing, is a verification
    failure. A failure never "passes by omission". The G3 criterion "100% of normalized
    documents pass `verify_derivation`" is therefore satisfiable and total.
- An `EvidencePack` for these manifests has `source_artifact_hashes` = the set of
  normalized artifact hashes. The frozen `verify_for_pack` then passes **unchanged**
  (test EV-05).

Raw responses are not listed as separate `evidence`-role inputs in slice 1. Doing so would
require a separate PIT source for raw captures (the binding is 1:1). That adds a
capability and binding with no safety benefit over transitive binding plus
`verify_derivation`. It is deferred (§21).

### 11.6 `ResearchEvidence` per OPEN book

`evidence_id = gid("rev", observation_id)`, `event_id`,
`category = "market_price.bookmaker_back"`,
`normalized_claim = canonical_json({"market_id", "bookmaker_id", "line",
"odds": {SEL: odds}}).decode().rstrip("\n")`, `source_ref = ProvenanceRef(
artifact_hash=normalized hash, contract_id, source_uri, retrieved_at=T1,
parse_ready_at=T2, availability_class=DERIVED, parser_version=derivation_version,
observation_id)`, `source_timestamp = max Tp | None`, `retrieved_at = T1`,
`status = CONFIRMED`, `freshness_expires_at = valid_to`,
`extractor_version = derivation_version`, `ready_at = T2`.

---

## 12. Freshness, staleness, cache, carry-forward — D9 (resolves Q5)

### 12.1 Slice-1 policy parameters (`oddspapi_slice1_policy.json`) — closes A1

**Classification.** Every value in this table is a **versioned provisional slice-1 policy
parameter. None of them is Genesis architectural law.** The frozen repository gives
authority for the *mechanisms*: PIT admissibility, `valid_to`, fail-closed staleness
(`SOURCE_AVAILABILITY.md`), the PASS taxonomy, and the quota ceilings. It gives no
authority for these *numbers*. They are engineering starting points chosen for a
~7-calls/day budget and PAPER-only use. Any of them may be changed by a reviewed config
commit, without an architecture change, provided that:

1. the file carries `"policy_version"` and `"classification":
   "PROVISIONAL_SLICE1_POLICY"`. The loader refuses a file lacking either;
2. `policy_digest = sha256(canonical_json(file))` covers every field. It feeds
   `derivation_version` (§9.2), so **any change yields a new derivation source**, contract
   and capability (§13.3). Old observations keep the parameters they were derived under;
3. code reads every value through `SlicePolicy` fields. Literal durations, bounds or
   thresholds in `genesis_adapters` are forbidden (static test FRZ-10).

| Field | Provisional value | Used by |
| --- | --- | --- |
| `price_ttl_seconds` | 3600 | OPEN `valid_to` (§6.2) |
| `prematch_guard_seconds` | 300 | OPEN eligibility and `valid_to` cap (§6.3) |
| `provider_future_tolerance_seconds` | 5 | `TIMESTAMP_FUTURE` (§6.4) |
| `clock_skew_max_seconds` | 120 | `CLOCK_SKEW` (§6.1). Also the provider-clock attribution margin of the UTC boundary guard (§14.6) |
| `request_timeout_seconds` | 60 | Hard transport deadline measured from `Tq`, and the debit-to-receipt bound of the UTC boundary guard (§14.6, §20.1). No other timeout literal exists in adapter code |
| `wall_monotonic_drift_max_ms` | 1000 | `ClockFault` (§6.1) |
| `fixture_join_max_age_seconds` | 86400 | fixture join (§8.3) |
| `max_response_bytes` / `max_decompression_ratio` | 8388608 / 20 | size and decode bounds (§7.6) |
| `secret_fragment_min_chars` | `max(8, ceil(n/3))` (formula; `8` and `3` are the fields) | fragment detection (§7.6) |
| `odds_min` / `odds_max` / `odds_max_fraction_digits` | `"1.01"` / `"1000"` / 4 | price validity (§9.1) |
| `overround_1x2` / `overround_ou` | `["1.00","1.30"]` / `["1.00","1.20"]` | price coherence (§10) |
| `cache_ttl_seconds` META_SPORTS/TOURNAMENTS/BOOKMAKERS/MARKETS | 2592000 | metadata cache (§12.2) |
| `cache_ttl_seconds` FIXTURES | 86400 | fixtures cache |
| `cache_ttl_seconds` ODDS | not cacheable (structural, not a parameter) | — |
| `retry_min_backoff_seconds` / `max_retries_per_window` | 120 / 1 | §14.3 |
| `conditional_refresh_min_lead_seconds` | 900 | §14.5 |
| `schedule_cluster_hours` / `schedule_prekick_offset_minutes` / `schedule_matchday_offset_hours` / `schedule_inventory_utc` / `schedule_inventory_horizon_hours` / `schedule_fixtures_days_utc` | 3 / 75 / 6 / `"08:00"` / 72 / `["MON 06:00","THU 06:00"]` | §14.5 |
| budget pools (`metadata`, `fixtures`, `scheduled_odds`, `conditional`, `scheduled_daily_max`, `conditional_daily_max`) | 4 / 18 / 135 / 30 / 6 / 1 | §14.5 |
| `g3_min_observation_days` | 14 | minimum observation window only (§16.5) |

### 12.2 Rules

1. **Freshness is measured from `T1` only**, never from provider timestamps.
2. An OPEN price is usable at `D` only when it is the unique as-of head and `T3 ≤ D <
   valid_to`, where `valid_to = min(T1 + price_ttl_seconds, S − prematch_guard_seconds)`.
   The frozen PIT admissibility applies this, so no second freshness implementation exists
   that could disagree.
3. After `valid_to` the book has **no usable observation**. The reader returns
   `Unusable(STALE)`, and the consumer maps it to `PASS_STALE_EVIDENCE`.
4. **No carry-forward, ever.** A price is never re-stamped, re-emitted with a new
   `valid_from`, extended by a failed or blocked refresh, or revived by a cache hit.
5. **Suspended / pulled markets.** A SUSPENDED observation or an ABSENT tombstone becomes
   the head (latest `valid_from`) and blocks every older OPEN record, even one still inside
   its TTL.
6. **Tombstones never expire** (`valid_to = None`). An older OPEN record cannot resurface
   after a tombstone ages, whatever happens to `S`. Only a newer capture supersedes a
   tombstone.
7. **Verified cache hit** means: the frozen `QuotaLedger.request` returned `reason ==
   "verified_cache_hit"` for a `CacheReference`, after `VerifiedCacheStore.resolve`
   re-verified the bytes (hash and length), provider, policy digest, exact
   `provider_request_hash`, `captured_at ≤ Tq < expires_at` and no invalidation. A hit
   costs 0 units and returns the **original** capture's bytes. It is used only for `META_*`
   (identity/market maps, fixture join), and it **never** creates an odds observation or a
   PIT record. A fixture join through a cache hit uses the original capture's
   `observation_id` and `T1` for its age check.
8. **ODDS are never cached**: `QuotaGate` refuses to publish or look up a cache entry for
   role `ODDS` (FR-04). Crash de-duplication for ODDS uses the acquisition ledger (§14.4).
9. **No silent fallback.** A cache miss, expiry, invalidation or verification failure is
   recorded (the quota row is a `quota_billable_call`, i.e. a Genesis budget debit, and
   the acquisition row carries `cache_miss_reason`), then the debited path runs under
   quota.
10. **Quota cache objects are retained forever.** `QuotaLedger` replay
    (`_validated_state`, run on every construction and every `request`) re-resolves every
    historical `quota_verified_cache_hit` row through `VerifiedCacheStore.resolve`, which
    re-reads and re-hashes the object bytes. Deleting, moving, compacting or rewriting any
    cache object or `cache-authority.jsonl` row that a ledger row references would make the
    **whole quota ledger** fail replay (`persisted cache hit lacks valid proof`) and halt
    all acquisition. So: no cache garbage collection in slice 1; backups and restores treat
    `quota/cache/` and `quota/ledger.jsonl` as one unit; `verify` (Stage 6/G3) runs
    `QuotaLedger.verify()` with the cache store attached (test FR-07).

### 12.3 Reader (`reader.MarketBookReader.head(entity_id, D)`) — verifier parity (closes A9)

The reader must accept **exactly** what the frozen
`FeatureInputManifestStore.verify_for_pack` would accept for the same head at cutoff `D`.
It adds adapter-only refusals on top, and never removes a verifier refusal. Both paths use
one shared predicate, `reader.admissible_head(entity_id, source_id, D)`. The manifest
builder calls it too, so builder, reader and verifier cannot diverge.

`admissible_head` performs, in order:

1. **Source:** exactly one READY market-book source at `D` (§13.4), and
   `capabilities.require_ready_at(S_ID, D)`. The capability head row at `D` must be
   unique (same rule as the verifier's `record_hash` head check). Otherwise
   `Unusable(DATA_CAPABILITY_NOT_READY | AMBIGUOUS_SOURCE)`.
2. **Binding:** `SourceInputBindingStore.require(source_id, contract_id, provider)`.
3. **PIT admissibility** (frozen `BitemporalRecord.admissible_at(D)`): `available_at ≤ D`,
   `retrieved_at ≤ D`, `ready_at ≤ D`, `valid_from ≤ D`, `valid_to is None or D <
   valid_to`. `pit.as_of_query(entity_id, D, source_id=S_ID)`. A `PITViolation` becomes
   `Unusable(AMBIGUOUS)`. An empty result becomes `Unusable(MISSING_OR_STALE)`.
4. **Unique head:** the single admissible record with max `valid_from`. A tie means
   `Unusable(AMBIGUOUS)`.
5. **Observation parity** with the verifier's exact checks on the head's normalized
   observation: exactly one observation for `payload_hash` under the bound contract;
   contract fields match (provider, source_type, `source_uri` pattern, parser_version,
   licensing_note, availability_class); `observation.retrieved_at ≤ D`;
   `observation.parse_ready_at ≤ D`;
   **`observation.publisher_timestamp is None or observation.publisher_timestamp ≤ D`**
   (the same value as PIT `published_at`); `observation.valid_from is None or ≤ D`;
   `observation.valid_to is None or D < observation.valid_to`;
   `contract.check_window(AvailabilityWindow(retrieved_at, parse_ready_at), D)`.
6. **No fallback on a parity failure.** If the head fails any check in 5, notably
   `published_at > D`, the result is `Unusable(NOT_PUBLISHED_AT_CUTOFF | PARITY_FAILURE)`.
   The reader never falls back to an older record, because the frozen verifier would
   also reject a manifest pinning that older record (it is not the unique head).
7. **Adapter-only refusals** (stricter, never looser): `market_state ≠ OPEN` →
   `Unusable(<state>, reasons)`; `D ≥ S − prematch_guard_seconds` →
   `Unusable(PREMATCH_WINDOW_CLOSED)`; failed `verify_derivation` for the head →
   `Unusable(DERIVATION_UNVERIFIED)`.
8. Return `UsableBook`.

Parity test RDR-01: for every fixture scenario and a grid of cutoffs around each record's
`T1`, `T3`, `published_at`, `valid_to` and `T_inv`, `admissible_head` returns usable
**iff** a manifest pinning that head passes the frozen `verify_for_pack` and the
adapter-only refusals in step 7 do not apply.

### 12.4 Expected scope (for ABSENT tombstones)

Before sending an ODDS request, the runner computes the expected scope: the set of book
entities that (a) belong to the request's competitions and declared bookmakers and (b) have
an admissible OPEN or SUSPENDED head at `Tq`. The set is written immutably to
`scopes/<hash>.json` and its hash recorded in the acquisition row. After a **complete**
response (not partial, §15 F-15; not rejected, F-13/F-14/F-38), every expected-scope book not present gets an ABSENT tombstone
(`valid_from = T1`). A partial or failed response produces **no** tombstones.

---

## 13. Corrections and supersession — D5 (resolves Q2)

The frozen facts are: `PITStore.append` is append-only with no update path; `record_id`
is unique; `as_of_query` raises on equal top `valid_from`; `verify_for_pack` requires
the pinned record to be the unique max-`valid_from` admissible head at the cutoff.

### 13.1 Cases

| Case | Mechanism | Historical as-of |
| --- | --- | --- |
| C-a Provider serves a new price | New observation, `valid_from = T1_new`, becomes the head | Cutoffs before `T3_new` still resolve to the old head |
| C-b Market suspended, pulled, or event no longer pre-match | SUSPENDED / ABSENT / BLOCKED head (no prices, `valid_to = None`) | Same |
| C-c A specific observation is found defective (provider palpable-error notice, a failed `verify_derivation`, or an operator finding) | **Invalidation** (§13.2): an append-only `InvalidationRecord` plus an `INVALIDATED` head with its own admissible time | Cutoffs before the invalidation's admissible time are unchanged (§13.2) |
| C-d Parser, map, schema or policy defect affecting a class of observations | **Derivation-source change** (§13.3): the old source is blocked from `T_fix`, a new source takes over. Individual still-current observations may *also* be invalidated through §13.2 | At `D < T_fix` unchanged |
| C-e Identity mapping error | Same as C-d (maps are inside `derivation_version`). Affected events are quarantined until the new source is READY | Same as C-d |
| C-f Provider revises historical data | Out of scope (no historical endpoints) | — |

### 13.2 Invalidation (closes A10)

A newly discovered defect **can** invalidate an observation that is still current, i.e.
still the unique head and still inside its `valid_to`. The r1 claim that corrected
records would "already be past `valid_to`" is withdrawn: it held only when correction
latency happened to exceed `price_ttl_seconds`, which nothing guarantees.

**Record.** `invalidations.jsonl` is an adapter-owned `AppendOnlyJsonl`. Each row is:

```text
{invalidation_id = sha256(canonical_json(row without invalidation_id)),
 invalidated_observation_id, invalidated_artifact_hash, invalidated_pit_record_id,
 entity_id, source_id, invalidation_class, reason (AdapterFailure code),
 recorded_at = T_inv (trusted clock), actor: "ADAPTER_AUTOMATIC" | "OPERATOR",
 evidence_refs[] (acquisition / observation / quarantine / G-review IDs)}
```

Rows are never edited or deleted. A mistaken invalidation is not "undone": the next
genuine capture supersedes the INVALIDATED head in the ordinary way. Invalidation only
ever **reduces** usability. It is a fail-safe action, not an approval, so adapter code may
append `ADAPTER_AUTOMATIC` rows (e.g. when `verify_derivation` fails for a head), and the
operator may append `OPERATOR` rows with `cli.py invalidate`. Neither needs a gate record.

**Emission** (under the acquisition-quiescence lock, so no capture interleaves):

1. Validate the target: the observation exists under a known market-book contract, its
   artifact hash matches, and `invalidated_pit_record_id` names its PIT record.
2. `T_inv ← clock`. If `T_inv ≤ valid_from` of **any** record in the same
   (entity, source) scope, re-read the clock until it is strictly greater. The trusted
   clock is monotonic, so this terminates and never back-dates.
3. Append the ledger row.
4. **Head test** (deterministic, from the verified PIT log at `T_inv`): let `R` be the
   record with max `valid_from` in the scope.
   - If `R` **is** the invalidated record, the price could still be (or become) the
     usable head. Emit the §9.1a document (`T2_inv ← clock`, publish, DERIVED), then
     `T3_inv ← clock` and append a PIT record `(available_at = retrieved_at = valid_from =
     T_inv, ready_at = T3_inv, valid_to = None, published_at = None)`.
   - If `R` is **newer** than the invalidated record, the invalidated price can never be
     the head again: `valid_from` ordering is fixed and records are immutable. No PIT
     record is needed. The ledger row alone records the finding
     (`head_effect: "NONE_ALREADY_SUPERSEDED"`, recorded in the row's companion
     `invalidation_applied` row).
5. Coverage entry `QUARANTINED`, `CONTRADICTORY_EVIDENCE` / `ARTIFACT_TAMPERED` per class.

**Semantics at a cutoff `D`:**

- `D < T3_inv`: the INVALIDATED record is inadmissible (frozen `ready_at > D`). As-of and
  `verify_for_pack` behave exactly as before, so **historical reconstruction at earlier
  cutoffs is unchanged**, and manifests built earlier still verify.
- `D ≥ T3_inv`: the INVALIDATED record is admissible and has the latest `valid_from`, so it
  is the unique head. The invalidated price is **no longer the usable head**. The reader
  returns `Unusable(INVALIDATED)`, and a new manifest pinning the old record fails the
  frozen unique-head check.
- In the window `T_inv ≤ D < T3_inv` (milliseconds), the invalidation is not yet
  admissible. Decisions in that window are excluded by the acquisition-quiescence lock
  (§6.3): a decision runner cannot take `D` while the invalidation holds the lock.
- A later genuine capture (`valid_from > T_inv`) supersedes the INVALIDATED head normally.

**Verification.** `verify_derivation` for `derivation_kind = INVALIDATION` is defined in
§11.5. It is deterministic from (ledger row, invalidated document), so
"100% of normalized documents pass `verify_derivation`" remains satisfiable (PIT-06,
INV-01…04).

### 13.3 Derivation-source change

A new `derivation_version` means:

- a new normalized contract, a new PIT `source_id`, a new binding and a new capability
  (UNKNOWN until its own G3 acceptance);
- the old source gets a capability row `BLOCKED` at `T_fix`. Adapter code may make that
  downgrade; it may never make an upgrade. From `D ≥ T_fix` every old-source record fails
  `require_ready_at`, including still-current prices, so no per-observation invalidation
  is needed to stop them.

Re-deriving still-retained raw captures into the new source is **permitted** and
deterministic. Such records carry `available_at = retrieved_at = valid_from = T1`
(original) and `ready_at = T3_rederive`. They are admissible only from `T3_rederive`
**and** only once the new source is READY, and only while `D < valid_to`. Nothing
depends on them being already expired. Historical cutoffs before `T3_rederive` are
unaffected. Re-derivation for audit only writes to a scratch store.

### 13.4 Invariants

- `superseded_by` and `superseded_at` are **always `None`**. No record is ever rewritten.
- At most **one** market-book source may be READY at any `D`. The manifest builder and
  reader enumerate the known `oddspapi.v4.soccer.market_book.*` sources and fail closed on
  zero or more than one.
- A raw artifact is never re-published under different bytes (frozen `immutable_write`).
- Coverage entries use the frozen `supersedes_entry_id` only to link an adapter's own later
  coverage entry (e.g. quarantine released by a new source) to the earlier one. Coverage is
  audit, not decision input.

---

## 14. Quota, retries, polling — D10

### 14.1 Frozen authority reused unchanged

- Live: `QuotaLedger(path, policy=load_quota_policy("config/oddspapi_quota_policy_v2.json"),
  cache_store=VerifiedCacheStore(...))`. `require_operational()` enforces
  `oddspapi` and `(250, 220, 30, 7)`.
- Tests: `QuotaPolicy.test_fixture(...)` with `allow_test_policy=True`. The runner refuses a
  test policy in live mode.
- Every attempt calls `request(request_id=…, occurred_at=Tq,
  billable_units=genesis_debit_units(role), budget_class=BudgetClass.NORMAL,
  authorization_id=None, cache=CacheReference|None, provider_id="oddspapi",
  provider_request_hash=h)`.
- **The adapter never constructs `QuotaReserveAuthorization`, never calls
  `grant_authorization`/`revoke_authorization`, and never passes
  `BudgetClass.RESERVE`** (FRZ-07). The 30-unit reserve stays exclusively under human
  control. If the normal budget runs out, acquisition stops.

### 14.2 Provider metering vs Genesis budget debit (closes A3)

Two different facts that r1 conflated:

| Concept | Field(s) | Source | Meaning |
| --- | --- | --- | --- |
| **Provider metering** | `provider_metering`, `provider_request_weight`, `provider_documented_billable` (endpoint spec §7.2, copied to each `planned` acquisition row) | OddsPapi documentation / reverified terms, confirmed at G2 | What OddsPapi *says* a request costs its account |
| **Provider-reported usage** | `provider_reported_usage` (`completed` row, from verified usage headers if any) | OddsPapi response | What OddsPapi *reports* it has counted |
| **Genesis budget debit** | `genesis_units_debited` (`quota_decided` row) = the frozen ledger's `billable_units` | Frozen `QuotaLedger` | What Genesis charges **its own internal budget** |

The frozen ledger vocabulary (`quota_billable_call`, `billable_units`, `billable_call_reserved`)
records **Genesis's internal budget authority**. A `quota_billable_call` row is **not
evidence that OddsPapi billed the account**. It only proves Genesis debited its own budget
before sending. Reports, dashboards and audit text must use "Genesis debit" for ledger
rows and "provider usage" only for provider-reported figures.

Debit rules:

| Situation | Genesis debit | Rationale |
| --- | --- | --- |
| Allowed attempt, `PER_REQUEST` | `genesis_debit_units` (≥ 1) before sending | The frozen ledger has no post-call accounting. Debit-before-send is the only conservative order |
| Allowed attempt, `FIXED_WEIGHT w` | `genesis_debit_units ≥ w` before sending (frozen `billable_units = w` is supported) | A fixed weight is bounded pre-send, so no reopen is needed (§20) |
| Allowed attempt, `NON_METERED` (provider-free) | `genesis_debit_units ≥ 1` anyway. Recorded with `provider_documented_billable = false` | The frozen ledger rejects `billable_units ≤ 0` on a debited row. Conservative over-debit is safe and needs **no** reopen. Only a wish to debit 0 would need one (FR-4, not triggered) |
| `VARIABLE` / `UNKNOWN` metering with no pre-send bound | Role not usable | Cannot be bounded pre-send (§20 FR-1) |
| Any failure after the debit (DNS, connect, TLS, timeout, reset, 3xx/4xx/5xx, 429, schema, quarantine) | Debit stands. **No refunds** (none exist in the frozen API) | The provider may meter any request that reached it. Over-debiting is safe |
| Retry | New attempt with a new `request_id` (`attempt+1`), debited again | Frozen request IDs are single-use |
| Verified cache hit (META_* only) | 0 (`quota_verified_cache_hit`) | Frozen S4 semantics. No request is sent |
| Gate refusal (no approval, no credential, circuit open) | None: gates are checked **before** `request()` | Nothing is sent |
| Provider-reported usage > Genesis `monthly_used` debit in the same accounting window | Halt all live acquisition (`QUOTA_DIVERGENCE`); human review | Possible key misuse or unknown metering. The adapter never "tops up" the ledger with synthetic rows |
| Provider-reported usage < Genesis debit | Recorded only | Expected under conservative debiting |

### 14.3 Retry and circuit breaker

- At most `max_retries_per_window` retries per planned window. Only for `NO_RESPONSE` (no
  HTTP status received) or HTTP 5xx. A retry fires at least `retry_min_backoff_seconds`
  after `T1` (or the failure time), only while the window is still before
  `S − prematch_guard_seconds` for its fixtures, and only with quota headroom.
  Retries draw on unplanned headroom, not the conditional pool.
- No retry on 3xx, 4xx, 429, schema, secret-echo or clock failures.
- 429: circuit open for that endpoint role until the next UTC day. Two 429s in one UTC day
  open the circuit for all roles until the next day.
- 401/403: circuit open for all roles indefinitely, plus a capability row `BLOCKED` for
  every market-book source. A human must re-approve (G1 re-check).

### 14.4 Crash and idempotency

- `request_id` is deterministic per (window, request, attempt).
- On restart, a `quota_decided` row with no `completed` row becomes `reconciled{outcome:
  ORPHANED_RESERVATION}`. Its Genesis debit stands and it is **not** re-sent under the same ID.
  Calling `request()` again with the same ID and a new `occurred_at` makes the frozen
  ledger raise `RegistryConflict`. That surfaces as a halt, never a retry.
- A `completed` row with raw evidence but no `normalized` row resumes normalization
  deterministically. New `T2`/`T3` are stamped at resume time, which is later and therefore
  conservative.

### 14.5 Budget and polling (envelope from Prep C)

All pool sizes, window offsets and times below are **provisional slice-1 policy
parameters** (§12.1), in Genesis debit units. They are not law. The frozen ceilings
(daily 7, normal 220, reserve 30, total 250) are the only fixed limits.

| Pool | Monthly ceiling | Daily |
| --- | --- | --- |
| Metadata (`META_*`, cache 30 d) | ≤ 4 | — |
| Fixtures (2 competitions × ~2/week, cache 24 h) | ≤ 18 | — |
| Scheduled odds (inventory + pre-match windows) | ≤ 135 | scheduled total (all pools) ≤ 6/day |
| Conditional targeted refresh | ≤ 30 (≤ `conditional_daily_max`, provisional 1/day) | — |
| **Planned total** | **≤ 187** | — |
| Unplanned headroom (retries, cache misses) | 33 (= 220 − 187) | 7-unit daily cap enforced by the frozen ledger |
| Protected reserve | 30. Never touched by the adapter | — |

Scheduler (`scheduler.py`, pure, deterministic from the fixture list and the policy):

- **Kickoff clusters:** fixtures of either competition whose kickoffs fall inside the same
  `schedule_cluster_hours` block (provisional 3).
- **Windows by priority** (offsets and times are `schedule_*` policy fields):
  1. `schedule_prekick_offset_minutes` before each cluster (provisional 75);
  2. `schedule_matchday_offset_hours` before the matchday's first kickoff (provisional 6);
  3. daily inventory at `schedule_inventory_utc` (provisional 08:00 UTC), only if a
     fixture is within `schedule_inventory_horizon_hours` (provisional 72);
  4. fixtures refresh on `schedule_fixtures_days_utc` (provisional Mon and Thu 06:00 UTC);
  5. monthly metadata.
- Where the endpoint supports several tournaments and bookmakers per call (verified at G2),
  one call covers both competitions and all declared bookmakers. Otherwise it is one call
  per competition.
- **Projection:** at plan time, `monthly_used + remaining_planned ≤ Σ pool ceilings`
  (provisional 187) and each day's plan ≤ `scheduled_daily_max` (provisional 6). If not,
  drop windows from the lowest priority up, never the other way round.
  The plan and every drop are recorded.
- **Conditional targeted refresh** (never automatic). All of these must hold:
  1. A PAPER consumer registered a refresh request for a specific (event, market)
     whose head is unusable only because of `STALE` or `MISSING`, not because of a
     BLOCKED/SUSPENDED state.
  2. `S − prematch_guard_seconds − now ≥ conditional_refresh_min_lead_seconds`.
  3. The conditional pool has capacity (`conditional_daily_max`, `conditional` monthly pool).
  4. The frozen ledger allows it: daily < 7 and normal < 220.
  5. The projection still covers the remaining scheduled windows.
  6. The circuit is closed.
  7. The UTC boundary guard (§14.6) permits a send now.

  A refused refresh is recorded with its reason.

### 14.6 UTC day/month boundary guard (closes A4 debit-to-receipt edge)

**Problem.** The frozen ledger attributes a debit to the UTC day and month of `Tq`. The
provider attributes the request to whenever it receives (and timestamps) it. A request
debited at 23:59:59.9 on the last day of a month and received just after midnight would
be counted by Genesis in one day/month and by the provider in the next. That breaks the
same-window counting behind §20.1 B1.

**Invariant (runner).** Genesis must not send a provider request when
`Tq + request_timeout_seconds` would cross a UTC calendar-day or UTC calendar-month
boundary. Precisely, with `B_day(Tq)` = the next UTC midnight strictly after `Tq`, and
`B_month(Tq)` = the next first-of-month UTC midnight strictly after `Tq`, a send is
permitted only if all four hold:

```text
W1  Tq + request_timeout_seconds + clock_skew_max_seconds < B_day(Tq)
W2  Tq + request_timeout_seconds + clock_skew_max_seconds < B_month(Tq)
W3  Tq − clock_skew_max_seconds ≥ start of Tq's UTC day
W4  Tq − clock_skew_max_seconds ≥ start of Tq's UTC month
```

- The `request_timeout_seconds` term is the invariant the review requires. W1 and W2
  alone, with the skew terms removed, would already refuse any send whose permitted
  receipt window crosses a boundary.
- The `clock_skew_max_seconds` terms are a strictly stronger addition for providers that
  attribute receipt by **their own** clock. That clock may differ from the trusted clock
  by up to `clock_skew_max_seconds`, which each response's `Date` check enforces (§6.1).
  The terms keep provider-clock attribution inside the same UTC day/month as `Tq` too.
  `request_timeout_seconds` itself is never reduced by them.
- W2 and W4 are implied by W1 and W3, since every month boundary is a day boundary. They
  are still checked and tested separately (defence in depth against a boundary-arithmetic
  bug).

**Enforcement.**

1. `Tq` is read from the trusted clock **once**, and that same value is used for the guard
   check and passed as `occurred_at` to `QuotaLedger.request`. The guard runs **before**
   the ledger call, so a refused send is never debited.
2. Refusal gives acquisition `planned` + `refused{reason: WINDOW_BOUNDARY_GUARD}` and
   coverage NOT_ATTEMPTED (F-43). The window is rescheduled deterministically to the first
   permitted instant after the boundary (`boundary + clock_skew_max_seconds`), subject to
   the new day's budget and §14.5 priorities.
3. **Hard transport deadline** = `Tq + request_timeout_seconds` (trusted clock) for the
   whole attempt: connect, TLS, request write, response read. Socket timeouts are set from
   the remaining time before every blocking operation. If `T0` would be at or after the
   deadline, the request is not written. At the deadline the connection is aborted and
   the attempt records `NO_RESPONSE`/`TRUNCATED` (debit stands). So every provider receipt
   the model permits happens within `[Tq, Tq + request_timeout_seconds)`, or within
   `± clock_skew_max_seconds` of that under provider-clock attribution, and W1–W4 put all
   of it inside the same UTC day and month as the debit.
4. Retries (§14.3) and conditional refreshes (§14.5) obey the guard with their own `Tq`.
   The scheduler (§14.5) never plans a window inside a guard zone.
5. A `CLOCK_SKEW` quarantine (F-12) means the skew bound W1–W4 rely on was just exceeded.
   All further sends are suspended until the next UTC day and until a successful
   `Date`-header check re-establishes skew within bounds.
6. `request_timeout_seconds` is a §12.1 policy field. It is inside `policy_digest` and
   therefore `derivation_version` (FR-08), and FRZ-10 forbids any other numeric timeout in
   adapter code (`timeout=` arguments, `settimeout(...)` literals, `sleep` literals). The
   policy loader rejects `request_timeout_seconds ≤ 0` and any policy where the guard zone
   `request_timeout_seconds + 2 × clock_skew_max_seconds` is ≥ 1 hour (sanity bound so a
   typo cannot silently block most of a day).

With provisional values (60 s, 120 s), the guard refuses sends in `[23:57:00, 00:02:00)`
UTC each day. The scheduler plans around that zone.

---

## 15. Failure semantics — D13

Default: **no usable observation**. Columns: *Evidence* = what is retained; *Coverage* =
frozen `CoverageStatus` + frozen `ReasonCode` (adapter detail code in `note`); *Head* =
PIT effect. "BLOCKED head" means a BLOCKED `MarketBookDocument` + PIT record for each
affected in-scope book whose entity is resolvable; unresolvable items get coverage only.
Wherever a row says "raw" is retained, that is **subject to §7.6**: credential safety
dominates raw retention, so any secret hit or uninspectable body turns the row into F-11
or F-11b.

| # | Failure | Evidence retained | Coverage | Observation / head |
| --- | --- | --- | --- | --- |
| F-01 | Gate missing (no G1/G2/G2R, circuit open, wrong clock, test policy in live) | acquisition `planned` + refusal | NOT_ATTEMPTED, `CONFIGURATION_MISMATCH` | none |
| F-02 | Quota blocked (daily/normal/genesis/provider exhausted) | quota `quota_request_blocked` row + acquisition | NOT_ATTEMPTED, `ATTEMPT_BUDGET_EXHAUSTED` | none; prior heads age out by TTL |
| F-03 | Quota time regressed / `ClockFault` | quota row (if written) + acquisition; halt | NOT_ATTEMPTED, `CONFIGURATION_MISMATCH` (`CLOCK_FAULT`) | none; runner halts |
| F-04 | Credential missing, bad permissions, fingerprint mismatch | acquisition refusal | NOT_ATTEMPTED, `CONFIGURATION_MISMATCH` | none; halt |
| F-05 | Transport error before any response | Genesis debit stands; acquisition `completed{NO_RESPONSE, sanitized_error}` | MISSING, `MISSING_EVIDENCE` | none; ≤ 1 retry (§14.3) |
| F-06 | Truncated body / length mismatch / oversize | partial bytes stored as raw (`outcome=TRUNCATED`) after secret scan | REJECTED, `SCHEMA_REJECTED` | none, no tombstones |
| F-07 | 3xx | raw body (scanned) + headers | REJECTED, `SOURCE_CONTRACT_VIOLATION` (`REDIRECT_REFUSED`) | none |
| F-08 | 401/403 | raw body (scanned) | REJECTED, `CONFIGURATION_MISMATCH` (`AUTH_REJECTED`) | none; capability BLOCKED; circuit open |
| F-09 | 429 | raw body (scanned) + retry-after | NOT_ATTEMPTED, `ATTEMPT_BUDGET_EXHAUSTED` (`RATE_LIMITED`) | none; circuit per §14.3 |
| F-10 | 5xx / provider error envelope in 2xx | raw body | MISSING, `MISSING_EVIDENCE` (`PROVIDER_ERROR`) | none; ≤ 1 retry (5xx only) |
| F-11 | Secret detected in body (any §7.6 form, wire or decoded) or in any header name/value | **no body bytes, no body hash, no redacted derivative**; secret-safe metadata only in `quarantine.jsonl` (§7.6) | QUARANTINED, `ARTIFACT_TAMPERED` (`SECRET_ECHO`) | none; halt; capability BLOCKED; human rotates key |
| F-11b | Body cannot be inspected before storage (unsupported/nested content-encoding, decode failure, size/ratio bound) | secret-safe metadata only in `quarantine.jsonl`; no raw evidence | QUARANTINED, `SCHEMA_REJECTED` (`UNINSPECTABLE_BODY`) | none, no tombstones |
| F-12 | Clock skew / missing Date (live) | raw | QUARANTINED, `CRITICAL_UNCERTAINTY` (`CLOCK_SKEW`) | none; all sends suspended until the next UTC day and a clean `Date` check (§14.6) |
| F-13 | Non-JSON, invalid UTF-8, duplicate keys, NaN/Infinity, wrong content-type | raw | REJECTED, `SCHEMA_REJECTED` | none, no tombstones |
| F-14 | Envelope schema mismatch (missing required keys, wrong types) | raw | REJECTED, `SCHEMA_REJECTED` | none, no tombstones |
| F-15 | Partial payload (provider completeness flag, or a required list missing for part of the scope) | raw | REJECTED (scope), `MISSING_EVIDENCE` (`PARTIAL_RESPONSE`) | well-formed books present **are** emitted; **no ABSENT tombstones** |
| F-16 | Competition not allowlisted | raw | REJECTED, `UNSUPPORTED_MARKET` (`OUT_OF_SCOPE_COMPETITION`), aggregated | none |
| F-17 | Bookmaker not declared / market ID not mapped / line ≠ 2.5 / line unidentified | raw | REJECTED, `UNSUPPORTED_MARKET` (`OUT_OF_SCOPE_*` / `LINE_UNIDENTIFIED`), aggregated | none (never merged) |
| F-18 | Duplicate book with differing content | raw | REJECTED, `CONTRADICTORY_EVIDENCE` (`CONTRADICTORY_DUPLICATE`) | BLOCKED head |
| F-19 | Incomplete or unmapped outcome set | raw | REJECTED, `SCHEMA_REJECTED` | BLOCKED head |
| F-20 | Invalid price / incoherent overround | raw | REJECTED, `PRICE_SANITY_FAILED` / `CONTRADICTORY_EVIDENCE` | BLOCKED head |
| F-21 | Fixture identity conflict | raw + registry conflict row | AMBIGUOUS, `AMBIGUOUS_IDENTITY` (`IDENTITY_CONFLICT`) | BLOCKED heads for all known books of the event; quarantine until a new derivation source |
| F-22 | Participant ambiguous (home = away, missing ID, wrong type) | raw | AMBIGUOUS, `AMBIGUOUS_IDENTITY` | BLOCKED heads if the fixture ID resolves, else none |
| F-23 | Unknown event / market / outcome status | raw | REJECTED, `CRITICAL_UNCERTAINTY` (`UNKNOWN_*_STATUS`) | BLOCKED head(s) |
| F-24 | Contradictory status | raw | REJECTED, `CONTRADICTORY_EVIDENCE` | BLOCKED head(s) |
| F-25 | Market suspended / outcome inactive | raw | AVAILABLE (state recorded; artifact = normalized hash) | SUSPENDED head (no prices) |
| F-26 | Event not pre-match | raw | REJECTED, `EXPIRED` (`EVENT_NOT_PREMATCH`) | BLOCKED heads |
| F-27 | Capture after guard (`T1 ≥ S − prematch_guard_seconds`) | raw | REJECTED, `EXPIRED` (`PREMATCH_WINDOW_CLOSED`) | none (older OPEN records already end at `S − guard`) |
| F-28 | Provider timestamp anomaly (§6.4) | raw | REJECTED, `NOT_AVAILABLE_AT_DECISION` (`TIMESTAMP_*`) | BLOCKED head |
| F-29 | Fixture join missing or stale | raw | MISSING, `STALE_EVIDENCE` (`EVENT_METADATA_STALE`) | BLOCKED heads |
| F-30 | Expected book absent from a complete response | raw + scope artifact | AVAILABLE (state recorded) | ABSENT head |
| F-31 | Config / map digest mismatch at runtime | none new | NOT_ATTEMPTED, `CONFIGURATION_MISMATCH` | none; halt |
| F-32 | Evidence immutability conflict / tampered bytes on read | existing bytes untouched | QUARANTINED, `ARTIFACT_TAMPERED` | none; halt |
| F-33 | PIT append conflict | none new | QUARANTINED, `ARTIFACT_TAMPERED` | none; halt |
| F-34 | Cache miss / expiry / invalid (META_*) | Genesis debit row (`quota_billable_call`) + acquisition `cache_miss_reason` | (per debited-request outcome) | per debited-request outcome; never silent |
| F-35 | Orphaned reservation after crash | acquisition `reconciled` | MISSING, `MISSING_EVIDENCE` (`ORPHANED_RESERVATION`) | none |
| F-36 | Two READY market-book sources at `D` / no READY source | — | (reader) `Unusable` | none usable (`PASS_DATA_CAPABILITY_NOT_READY` or ambiguity) |
| F-37 | Quota divergence vs provider headers | acquisition + headers | NOT_ATTEMPTED, `CONFIGURATION_MISMATCH` (`QUOTA_DIVERGENCE`) | none; halt |
| F-38 | Closed-schema drift (unknown key / wrong type in a semantic structure, §10.1) | raw (subject to §7.6) | REJECTED, `SCHEMA_REJECTED` (`SCHEMA_DRIFT`) | BLOCKED head(s) at the affected scope; response-level drift → none, no tombstones |
| F-39 | Head fails verifier parity at `D` (e.g. `published_at > D`, contract mismatch, capability head not unique) | — | (reader) `Unusable(NOT_PUBLISHED_AT_CUTOFF \| PARITY_FAILURE)` | none usable; **no fallback** to an older record |
| F-40 | Observation invalidated (§13.2) | ledger row + INVALIDATED document + PIT record (if the target is the head) | QUARANTINED, `CONTRADICTORY_EVIDENCE` / `ARTIFACT_TAMPERED` | INVALIDATED head from `T3_inv`; earlier cutoffs unchanged |
| F-41 | Module-provenance guard failure (§2.4) | run record with guard verdict | NOT_ATTEMPTED, `CONFIGURATION_MISMATCH` (`MODULE_PROVENANCE`) | none; runner/suite refuses to start |
| F-42 | Quota cache object or cache-authority row referenced by a ledger row is missing or altered | existing bytes untouched | QUARANTINED, `ARTIFACT_TAMPERED` (`QUOTA_REPLAY_BROKEN`) | none; all acquisition halts until restored from backup (§12.2 rule 10) |
| F-43 | Send refused by the UTC boundary guard (§14.6 W1–W4) | acquisition `planned` + `refused{WINDOW_BOUNDARY_GUARD}`; **no** quota row (guard runs before the ledger) | NOT_ATTEMPTED, `ATTEMPT_BUDGET_EXHAUSTED` (`WINDOW_BOUNDARY_GUARD`) | none; window rescheduled after the boundary |

`errors.AdapterFailure` enumerates every detail code above. Each code maps to exactly one
frozen `ReasonCode`, and a test (FM-00) asserts the mapping is total.

---

## 16. Authority and approval gates — D11 (resolves Q9)

Code can check gates. Only a human can satisfy them. Agents (including the implementing
model) **must never** create, edit or append gate records, store a credential, or make a
request to an OddsPapi host. Invalidation rows (§13.2) and capability downgrades to
BLOCKED/UNKNOWN are fail-safe reductions of usability. They are not approvals, and adapter
code may write them.

### 16.1 G0 — architecture accepted (before Stage 0)

The human accepts this document at its commit SHA and records it in
`adapters/DECISIONS/ADR-A001-v05-slice1-architecture.md` (status ACCEPTED, approver,
date, reviewed commit). That permits Stages 0–7 with fixtures only.

### 16.2 G1 — storing a read-only API credential

Prerequisites:

- Stages 0–7 GREEN, including a GREEN secret-handling suite.
- The human has **reverified OddsPapi terms** (the frozen policy carries
  `provider_terms_reverification_required: true`) and recorded, per endpoint role, the
  allowance, accounting window(s), metering type and weights (§7.2), plus permitted
  personal/research use, local storage of responses and one account per person. A dated
  snapshot goes in `adapters/evidence/provider_terms/` with its SHA-256.
- The **boundability check** of §20 FR-1 passes. It is recorded as a table (provider
  limit per window vs Genesis's maximum possible debit in that window) in the G1 evidence.
  If it fails for a role, that role is unusable. If it fails for every role needed by
  slice 1, stop: **FOUNDATION REOPEN REQUIRED** (FR-1). A more generous allowance,
  non-metered endpoints, fixed weights or a different accounting window do **not** by
  themselves fail the check.
- The key belongs to the operator's single legitimate account and is used only for
  read-only data access.
- Storage path and permissions comply with §7.5.
- A rotation/revocation procedure is written in `adapters/README.md`.

Record: `{gate:"G1", approval_reference, approver, granted_at (trusted clock),
terms_snapshot_sha256, licensing_note (exact string for contracts), credential_fingerprint,
credential_path_policy, valid_through}`.

### 16.3 G2 — the first live OddsPapi requests

Prerequisites: G1; OS time-sync attestation; the runner in `--live-verification` mode.

Scope: an **exhaustive list of ≤ 5 canonical requests** pinned by `provider_request_hash`.
For example: `META_BOOKMAKERS`, `META_MARKETS` (soccer), `META_TOURNAMENTS` (soccer),
`FIXTURES` (one competition), `ODDS` (one competition, declared bookmakers). The record also
fixes a maximum call count equal to the list length and a validity window ≤ 72 h. The
runner refuses any request not on the list.

Output (raw only; no normalization emitted operationally):

- a **schema verification report** comparing live bytes with the doc-derived fixture
  schemas (fields, types, status values, timestamp formats and offsets, `Date` header
  presence, content-encoding, quota/usage headers, per-role metering evidence,
  multi-tournament and bookmaker-filter support), plus the complete closed-schema key
  inventory per semantic structure with proposed `inert` classifications (§10.1);
- proposed pinned map values (tournament, market, outcome and bookmaker IDs) as a
  **human-reviewed commit** to `adapters/config/`. The commit flips the corresponding
  `verified_live: true`. It creates a new `derivation_version`.

Record: `{gate:"G2", approval_reference, approver, granted_at, request_hashes[],
max_calls, valid_from, valid_through}`.

### 16.4 G2R — recurring scheduled capture (capability still not READY)

Prerequisites:

- G2 report accepted.
- Maps pinned with no `fixture_only` entries.
- Fixtures regenerated from, or checked against, the live schema, with RED→GREEN evidence
  of every parser change.
- Scheduler plan within §14.5.

Record: `{gate:"G2R", derivation_version, policy_digest, plan_digest, valid_from,
valid_through ≤ 35 days}`.

During G2R, market-book sources are registered with `operational_status = UNKNOWN` and
`point_in_time_reliability = "unverified"`. PIT records accumulate but nothing is
consumable, because `require_ready_at` fails.

### 16.5 G3 — marking a provider capability READY (closes A2)

READY is decided by **explicit evidence against acceptance criteria**, never by elapsed
time. Every criterion below is mandatory, and each is evidenced under
`adapters/evidence/G3/` with the artifact hashes listed in the G3 record.

**Acceptance criteria (all required):**

- **AC-1 Integrity.** 100% of normalized documents (both derivation kinds) pass
  `verify_derivation`. `QuotaLedger.verify()` (with cache store attached, §12.2 rule 10),
  `EvidenceStore.verify_manifest()`, `VerifiedCacheStore.verify()` and PIT, identity,
  invalidation and acquisition ledger verification all pass. The runtime secret scan
  (§7.6) is clean.
- **AC-2 Failure record.** No unresolved CRITICAL/HIGH failure in the observation window.
  CRITICAL: F-08, F-11, F-11b, F-12, F-21, F-31–F-33, F-37, F-38, F-41, F-42. Every
  CRITICAL occurrence is root-caused, and any fix is a new `derivation_version` with its
  own window.
- **AC-3 Schema.** The schema verification report covers every endpoint role used. Every
  closed-schema field, every inert key (§10.1), every status-map and market-map entry used
  is `verified_live: true`. Zero unresolved `SCHEMA_DRIFT`.
- **AC-4 Coverage content.** Live OPEN books were observed for **each** competition ×
  **each** market family × **each** declared bookmaker. At least one SUSPENDED or ABSENT
  transition and at least one event leaving `PREMATCH` were observed and handled correctly.
  Any in-scope code path not observed live is listed explicitly with its residual risk,
  and the human accepts that list in the G3 record.
- **AC-5 Parity.** `admissible_head` vs frozen `verify_for_pack` parity (RDR-01) holds on
  live-captured data for a sample of cutoffs per competition × family.
- **AC-6 Time.** Clock attestation was present for every live run. Zero `CLOCK_SKEW`
  quarantines in the final 7 days of the window (a provisional sub-window, §12.1). No
  `ClockFault`.
- **AC-7 Quota.** The Genesis debit never exceeded the frozen ceilings. Provider-reported
  usage (if available) reconciles with the Genesis debit with no `QUOTA_DIVERGENCE`. No
  reserve use.
- **AC-8 Foundation.** Frozen suite unchanged and GREEN. Freeze guard (FRZ-01…03) and
  module-provenance guard (FRZ-09) GREEN in the live runner's recorded startups.
- **AC-9 Review.** An **independent hostile review** of the adapter branch (same standard
  as the T-series audits) finds no unresolved CRITICAL/HIGH.

**Observation window.** Capture must span at least `g3_min_observation_days` (provisional
14, §12.1) of G2R operation under the **same** `derivation_version`. That is a minimum,
**not** a sufficient condition: meeting it proves nothing unless AC-1…AC-9 are also met.
If AC-4 isn't met when the minimum elapses, the window continues.

Record: `{gate:"G3", derivation_version, source_id, contract_id, review_reference,
acceptance_evidence: {AC-1..AC-9: sha256}, unobserved_paths_accepted[],
observation_window: {from, to}, approver, granted_at}`.

READY for the data source authorizes **only** decision-time use of these observations by
PAPER-mode consumers that hold their own authorities. It does **not** authorize PAPER
qualification, strategy readiness or live execution (D18).

Then the operator CLI (not adapter runtime code) appends:

- `SourceCapability(source_id, provider="oddspapi", access_method="rest_pregame_v4",
  cost_tier="<from G1 terms record>", …, point_in_time_reliability="prospective_verified",
  revision_behaviour="append_only_supersede", operational_status=READY, recorded_at=now,
  version=derivation_version+"-ready-1")`;
- the `SourceInputBinding(approval_reference=G3 record id)`;
- `MarketCapability(..., market_supported_by_data_adapter=True, all others None)`.

Adapter runtime code may only ever register `BLOCKED` or `UNKNOWN` capability rows (G-03).

### 16.6 Gate record integrity

- `AdapterAuthorityLedger` is an `AppendOnlyJsonl` at `authority.jsonl`. It is operator-
  owned and written only by `cli.py approve`. That command refuses to run without an
  interactive TTY and a typed confirmation phrase, and it requires `approval_reference` to
  name an out-of-band human artifact (e.g. a signed tag, a PR approval URL, or an ADR
  commit).
- Gate checks verify the record exists, is inside its window, and pins digests matching the
  current config and code (`derivation_version`, request hashes, credential fingerprint).
- **Honest limit.** File-level controls cannot prove that a human wrote a record. Integrity
  rests on operator discipline, the implementation prompt's prohibition, and review of the
  authority ledger at G3. §21 records this.

---

## 17. Interfaces (Python, `genesis_adapters`)

```python
# clock.py
class ClockFault(RuntimeError): ...
class TrustedClock(Protocol):
    def now(self) -> str: ...                      # canonical iso_utc
class SystemUtcClock:                              # the only production clock
    def __init__(self, *, drift_max_ms: int, floor: str | None = None): ...   # from SlicePolicy
    def now(self) -> str: ...

# secrets.py
class Secret:
    fingerprint: str
    def reveal_for_transport(self, token: object) -> str: ...
@dataclass(frozen=True)
class SecretScanResult:
    hit: bool; detection_classes: tuple[str, ...]      # never offsets, never matched text
def scan_for_secret(data: bytes, secret: Secret, *, policy: SlicePolicy) -> SecretScanResult: ...
    # every §7.6 form: raw, URL/percent/+/double, JSON \u escapes, UTF-16/32 LE/BE,
    # base64 std/url-safe (3 alignments), hex, fragments >= secret_fragment_min_chars
def scan_headers(headers: Sequence[tuple[bytes, bytes]], secret: Secret, *,
                 policy: SlicePolicy) -> SecretScanResult: ...

# provenance_guard.py
class ModuleProvenanceError(RuntimeError): ...
def verify_loaded_genesis_modules(repo: Path, *, manifest_path: Path) -> dict: ...  # §2.4; returns verdict record

# schema.py  (closed schemas, §10.1)
@dataclass(frozen=True)
class DriftFinding:
    path: str; kind: Literal["UNKNOWN_KEY", "WRONG_TYPE", "MISSING_REQUIRED", "UNKNOWN_ENUM"]
    scope: Literal["BOOK", "EVENT_BOOKMAKER", "EVENT", "RESPONSE"]
def validate_closed(value: Any, schema: ClosedSchema) -> tuple[DriftFinding, ...]: ...

# config.py
@dataclass(frozen=True)
class SlicePolicy:                     # every provisional parameter of §12.1; no defaults in code
    policy_version: str; classification: Literal["PROVISIONAL_SLICE1_POLICY"]
    price_ttl_seconds: int; prematch_guard_seconds: int; ...   # full §12.1 field list
    @property
    def digest(self) -> str: ...

# ids.py
def gid(kind: str, **parts: object) -> str: ...
def native_id(value: object, *, declared_type: Literal["int", "str"]) -> dict: ...

# jsonstrict.py
class StrictJsonError(ValueError): ...
def loads_strict(data: bytes, *, max_bytes: int) -> Any: ...   # Decimal floats, dup keys, NaN

# oddspapi/endpoints.py
@dataclass(frozen=True)
class CanonicalRequest:
    role: str; method: str; scheme: str; host: str; path: str
    query: tuple[tuple[str, str], ...]; headers: tuple[tuple[str, str], ...]
    api_version: str = "v4"
    def to_json(self) -> dict: ...
    def canonical_bytes(self) -> bytes: ...
    @property
    def provider_request_hash(self) -> str: ...
def build_request(spec: EndpointSpec, **params: object) -> CanonicalRequest: ...

# oddspapi/transport.py
@dataclass(frozen=True)
class TransportResult:
    outcome: Literal["RESPONSE", "NO_RESPONSE", "TRUNCATED"]
    http_status: int | None; headers: tuple[tuple[str, str], ...]
    body: bytes | None; sanitized_error: dict | None
    request_started_at: str; response_received_at: str | None
class Transport(Protocol):
    def send(self, request: CanonicalRequest, *, clock: TrustedClock) -> TransportResult: ...
        # §7.7: every Exception -> sanitized TransportResult (never raised);
        # KeyboardInterrupt / SystemExit(int code) re-raised as fresh instances `from None`
        # after the handler (no args text, no cause/context, keyed locals deleted);
        # hard deadline Tq + request_timeout_seconds (§14.6)

# oddspapi/quota_gate.py
class QuotaGate:
    def __init__(self, ledger: QuotaLedger, cache: VerifiedCacheStore, *, cache_index_path: Path): ...
    def reserve(self, *, request: CanonicalRequest, request_id: str, occurred_at: str) -> QuotaDecision: ...
    def cached_bytes(self, decision: QuotaDecision, request: CanonicalRequest) -> bytes | None: ...
    def publish_cache(self, request: CanonicalRequest, payload: bytes, *, captured_at: str) -> None: ...  # META_* only

# oddspapi/acquisition.py
class AcquisitionRunner:
    def __init__(self, *, root: Path, clock: TrustedClock, transport: Transport,
                 quota: QuotaGate, authority: AdapterAuthorityLedger, config: AdapterConfig,
                 live: bool): ...
    def acquire(self, plan_item: PlanItem) -> AcquisitionOutcome: ...
    def reconcile_after_restart(self) -> tuple[str, ...]: ...

# oddspapi/parser.py  (PURE)
@dataclass(frozen=True)
class ParseContext:
    acquisition_id: str; request: CanonicalRequest; raw_artifact_hash: str
    raw_observation_id: str; request_started_at: str; response_received_at: str
    date_header: str | None; maps: AdapterMaps; policy: SlicePolicy
    identity_prefix: tuple[dict, ...]; expected_scope: frozenset[str] | None
    fixture_join: FixtureSnapshot | None; response_complete_hint: bool
def parse_odds_response(raw: bytes, ctx: ParseContext) -> ParsedResponse: ...

# oddspapi/normalize.py  (PURE)
CODE_VERSION: str
def market_book_documents(parsed: ParsedResponse, ctx: ParseContext) -> tuple[bytes, ...]: ...

# oddspapi/emit.py
def emit_response(parsed: ParsedResponse, docs: tuple[bytes, ...], *, stores: AdapterStores,
                  clock: TrustedClock) -> EmitResult: ...        # stamps T2, T3
def emit_invalidation(*, invalidated_observation_id: str, invalidation_class: str,
                      reason: str, actor: Literal["ADAPTER_AUTOMATIC", "OPERATOR"],
                      evidence_refs: Sequence[str], stores: AdapterStores,
                      clock: TrustedClock) -> InvalidationResult: ...   # §13.2; head_effect in result

# oddspapi/reader.py
def admissible_head(entity_id: str, decision_at: str, *,
                    stores: AdapterStores) -> UsableBook | Unusable: ...   # shared predicate, §12.3
class MarketBookReader:
    def head(self, entity_id: str, decision_at: str) -> UsableBook | Unusable: ...  # = admissible_head

# oddspapi/manifest.py
def build_manifest_body(*, event_id: str, market_id: str, decision_at: str,
                        books: Sequence[UsableBook], selections: Sequence[str],
                        stores: AdapterStores) -> dict: ...

# oddspapi/verify.py
def verify_derivation(normalized_observation_id: str, *, stores: AdapterStores) -> None: ...
    # dispatches on derivation_kind: RESPONSE (raw replay) | INVALIDATION (ledger row + target doc)
def scan_runtime_for_secret(root: Path, secret: Secret) -> tuple[Path, ...]: ...
def verify_frozen_trees(repo: Path, commit: str = "HEAD") -> None: ...

# oddspapi/scheduler.py  (PURE)
def plan_month(fixtures: Sequence[FixtureInfo], *, policy: SlicePolicy, month: str,
               used: QuotaUsage) -> MonthPlan: ...
def admit_conditional_refresh(request: RefreshRequest, *, state: SchedulerState,
                              now: str) -> RefreshDecision: ...

# oddspapi/authority.py
class AdapterAuthorityLedger:
    def require_gate(self, gate: str, *, at: str, **pins: str) -> dict: ...
```

---

## 18. Test matrix (RED → GREEN)

Each test is written first and shown RED (import error or wrong behaviour) against the
stage's starting commit, then GREEN. Transcripts go in `adapters/evidence/S<n>/`.
Every test that involves a policy parameter reads the value from the test's
`SlicePolicy` and asserts at the boundary (`value − 1 unit` / `value` / `value + 1 unit`).
No test hard-codes a provisional number, so changing a parameter never silently weakens
a test.

### Freeze and boundaries

| ID | Test | RED before |
| --- | --- | --- |
| FRZ-01 | The six `HEAD:<tree>` SHAs equal §2.1 | guard absent |
| FRZ-02 | The guard **fails** on a synthetic commit (temp clone) that adds `src/genesis/x.py` and on one that edits `config/…json` | guard absent |
| FRZ-03 | `git status --porcelain -- src tests config tools DECISIONS v04_pack` is empty after the adapter suite runs | — |
| FRZ-04 | Frozen suite command GREEN with the same pass/skip counts as the Stage 0 baseline transcript (gate command, recorded) | — |
| FRZ-05 | AST: `genesis_adapters` imports only public names from `genesis.*`; no attribute assignment to `genesis` modules or classes; no subclass of a frozen authority class overriding a method | scanner absent |
| FRZ-06 | AST: `socket`, `ssl`, `http.*`, `urllib.request`, `requests`, `httpx`, `aiohttp` imported only by `transport_http.py`; `Secret.reveal_for_transport` called only there | scanner absent |
| FRZ-07 | AST: no `QuotaReserveAuthorization`, `grant_authorization`, `revoke_authorization` or `BudgetClass.RESERVE` in `genesis_adapters` | scanner absent |
| FRZ-08 | AST: `FixedClock` and `FakeTransport` defined only in `adapter_tests`; `OperationalStatus.READY` never referenced by adapter runtime modules (only `cli.py approve`) | scanner absent |
| FRZ-09 | Runtime module-provenance guard (§2.4). GREEN on a clean run. **Fails closed**, in subprocesses, for: a shadow `genesis` package via `PYTHONPATH`; a `.pth` file in a temporary site directory; a competing `genesis` on a lower-precedence `sys.path` entry; one frozen module's bytes modified in a temp copy of the repo; a planted stale `.pyc` with no `-B`/fresh pycache prefix; a non-`SourceFileLoader` loader. The manifest equals `git ls-tree -r 51cb635…` blob IDs | guard absent |
| FRZ-10 | AST: no numeric literal duration, bound, threshold or **timeout** in `genesis_adapters` (including `timeout=` keyword arguments, `settimeout(...)`, `socket.setdefaulttimeout(...)`, `sleep(...)` with a literal) outside `config.py` schema defaults (which are forbidden too: `SlicePolicy` has no defaults); every §12.1 field, including `request_timeout_seconds`, is read through `SlicePolicy`; changing any policy field changes `policy_digest` and `derivation_version` | scanner absent |
| FRZ-11 | AST: no bare `except:`, `except BaseException`, `except KeyboardInterrupt`, `except SystemExit` (alone or in a tuple), or `contextlib.suppress` of those, anywhere in `genesis_adapters` except the single documented `except BaseException` clause in `transport_http.send`; that clause has no `return` and is always followed by the fresh re-raise after the block; no `return`/`break`/`continue` inside any `finally` | scanner absent |

### Credentials and request identity

| ID | Test |
| --- | --- |
| REQ-01 | Builder rejects the credential param and its case/alias variants (`apiKey`, `APIKEY`, `api_key`, `token`, …) |
| REQ-02 | Golden vectors: a pinned request → pinned `provider_request_hash`; param order and bookmaker-set order do not change the hash |
| REQ-03 | Changing path, any param value, bookmaker set, API version or host changes the hash |
| REQ-04 | Full fixture pipeline with sentinel secret `GENESIS-SENTINEL-KEY-…`: no file under the runtime root, no log line and no exception message contains the sentinel in any §7.6 form (including fragments) |
| REQ-05 | `Secret`: `repr`/`str` masked; `json`, `pickle`, `copy` and `deepcopy` raise; `canonical_json` refuses |
| REQ-06 | A transport exception whose message contains the secret URL → acquisition row holds only the sanitized class/errno (unit level; TX-01 is the end-to-end version) |
| REQ-07 | Response body echoing the secret → **no body bytes, no body hash, no redacted derivative** anywhere; only secret-safe metadata in `quarantine.jsonl`; halt; capability BLOCKED (F-11) |
| SEC-01 | Detector matrix: for each §7.6 form (raw; percent upper/lower; `+`; double-encoded; `apiKey=` query fragment; JSON `\u` full and mixed; UTF-16 LE/BE ± BOM; UTF-32 LE/BE; base64 std/url-safe at offsets 0/1/2 ± padding; hex upper/lower; fragments at exactly `secret_fragment_min_chars` and one shorter) embedded in a fixture body → hit exactly when expected |
| SEC-02 | Secret in a response **header value** (and in a header name) → F-11, even for headers outside the allowlist |
| SEC-03 | gzip body whose decoded form contains the secret (and a second case where only the wire bytes do) → F-11; unsupported/nested content-encoding, corrupt gzip, over-ratio or oversize decode → F-11b with no raw evidence |
| SEC-04 | Quarantine metadata is itself scanned; a metadata field that would contain the secret (e.g. a dirty `content-type`) is dropped, never written |
| SEC-05 | Runtime-root scan (`scan_runtime_for_secret`) detects every §7.6 form planted in a file anywhere under the root |
| TX-01 | Transport exception boundary (§7.7), run in a **subprocess** via the recording harness. (1) Ordinary `Exception`s at connect / write / read-headers / read-body / decode, with the credential-bearing URL in message, `args`, `url`, `filename`, `__notes__` and chained `__cause__`/`__context__`, plus a `warnings.warn` carrying the URL → sanitized `NO_RESPONSE`/`TRUNCATED` result (class/errno only), nothing reaches the top level. (2) Injected `KeyboardInterrupt(<URL>)` → harness records `KeyboardInterrupt`, exit status is the platform uncaught-SIGINT status, runner did not swallow it. (3) Injected `SystemExit(37)` → harness records `SystemExit`, return code exactly 37; `SystemExit("<URL>")` → return code 1 and the string never printed; `SystemExit(None)` → 0. (4) For (2)/(3): `__cause__`/`__context__` are `None`, no `__notes__`, args `()`/`(int,)`, no traceback-frame local contains the sentinel. For every case, **stdout, stderr, logs, evidence and provenance** (incl. the harness result file) are clean for every §7.6 form |
| REQ-08 | Raw `source_uri` = `oddspapi-request:sha256:<h>` and matches the contract `uri_pattern`; canonical bytes stored at `requests/<h>.json` with `sha256(file) == h` |

### Clock and timestamps

| ID | Test |
| --- | --- |
| CLK-01 | `SystemUtcClock` is non-decreasing; a simulated wall jump just above `wall_monotonic_drift_max_ms` raises `ClockFault`, just below does not; a floor below durable heads raises |
| CLK-02 | Live runner refuses `FixedClock`, a test quota policy, and missing time-sync attestation |
| CLK-03 | Persisted `Tq ≤ T0 < T1 ≤ T2 ≤ T3`; replay rejects rows violating it |
| CLK-04 | `|Hd − T1| = clock_skew_max_seconds + 1 s` → quarantine; `= clock_skew_max_seconds` → accepted; missing `Date` in live mode → quarantine |
| TS-01…05 | Naive, non-UTC offset, unparseable, future (`T1 + provider_future_tolerance_seconds + 1 s` rejected, `T1 + provider_future_tolerance_seconds` accepted), `S ≤ T1` while pre-match → BLOCKED with the exact reason code |
| TS-06 | `T1 = S − prematch_guard_seconds` → no OPEN (F-27); `T1 = S − prematch_guard_seconds − 1 s` → OPEN with `valid_to = S − prematch_guard_seconds` |
| TS-07 | PIT fields equal §11.4 exactly for OPEN and for each tombstone state |

### Identity

| ID | Test |
| --- | --- |
| ID-01 | Golden `gid` vectors for every kind |
| ID-02 | `17` vs `"17"` in one ID field → `SCHEMA_REJECTED` |
| ID-03 | Same names with different provider IDs → different participants; same ID with a new name → same participant plus a `NAME_DRIFT` row |
| ID-04 | Fixture rebound to other participants, competition or swapped home/away → `IDENTITY_CONFLICT`, BLOCKED heads for known books, quarantine |
| ID-05 | Home = away / missing participant ID → `PARTICIPANT_AMBIGUOUS` |
| ID-06 | Non-allowlisted tournament → no observation, aggregated coverage |
| ID-07 | Undeclared bookmaker → excluded; declared-set order irrelevant |
| ID-08 | Mutation: changing every display name in a fixture leaves every Genesis ID and artifact hash unchanged, except `participant_seen` drift rows |
| ID-09 | Operational loader refuses maps containing `fixture_only` entries |

### Markets

| ID | Test |
| --- | --- |
| MKT-01 | 3 bookmakers × {1X2, O/U 2.5} → 6 books, distinct `entity_id`, same `market_id` across bookmakers |
| MKT-02 | 5 bookmakers normalize under a test-only policy; the operational policy validator rejects > 3 and non-sportsbook kinds |
| MKT-03 | Lines {1.5, 2.25, 2.5, 2.75, 3.5} → only 2.5 emitted; `2.50` literal ≡ 2.5; `2.4999` excluded |
| MKT-04 | Two differing 2.5 entries for one bookmaker → BLOCKED `CONTRADICTORY_DUPLICATE`; identical duplicates collapse |
| MKT-05 | O/U market without a line, or line from an undeclared source → excluded |
| MKT-06 | 1X2 missing draw → BLOCKED `INCOMPLETE_SELECTIONS`; extra unmapped outcome → BLOCKED `UNMAPPED_OUTCOME` |
| MKT-07 | Odds: `1.0`, `0`, `-2`, `NaN`, `Infinity`, just above `odds_max`, one digit more than `odds_max_fraction_digits` rejected; `2` → `"2"`; `1.910` → `"1.91"`; the value never passes through `float` |
| MKT-08 | Overround bands: just inside passes, just outside → BLOCKED |
| MKT-09 | Swapping outcome labels while keeping outcome IDs changes no mapping |

### Status

| ID | Test |
| --- | --- |
| ST-01 | Every allowlisted value maps exactly |
| ST-02 | Unknown event status → BLOCKED, no `selections` key |
| ST-03 | Unknown market/outcome status → BLOCKED |
| ST-04 | Contradictions (finished + active price; active + missing price) → BLOCKED `CONTRADICTORY_STATUS` |
| ST-05 | Suspended → SUSPENDED head that supersedes an earlier OPEN still inside its TTL (reader returns `Unusable(SUSPENDED)`) |
| ST-06 | Type-mismatched status value (`1` vs `"1"`) → unknown |

### Evidence

| ID | Test |
| --- | --- |
| EV-01 | Raw bytes stored byte-exact; full SHA-256; `get_bytes` verifies |
| EV-02 | Tampering an object file → `get_bytes`/`verify_manifest` fail; re-publishing different bytes at an existing path → `ImmutableConflict` |
| EV-03 | For every fixture, `verify_derivation` reproduces byte-identical normalized documents from raw bytes, the acquisition record and pinned context |
| EV-04 | Normalized observations match the contract (`parser_version = derivation_version`, DERIVED, `source_uri` pattern); the document carries `raw_artifact_hash` and `raw_observation_id` |
| EV-05 | End-to-end: build a manifest body at `D`, publish it, build an `EvidencePack` v2 → frozen `verify_for_pack` returns the pinned records (test registries: capability READY, binding approved with a `synthetic-test-only-` reference) |
| EV-06 | A manifest pinning a SUSPENDED/BLOCKED/ABSENT head fails the frozen verifier; a manifest pinning an OPEN record that is no longer the head fails it too |
| EV-07 | Malformed JSON, duplicate keys, NaN, invalid UTF-8, wrong content-type, oversize → raw retained, no normalized observation, coverage REJECTED |
| EV-08 | Partial payload → present books emitted, zero ABSENT tombstones |

### PIT and corrections

| ID | Test |
| --- | --- |
| PIT-01 | Two captures: as-of between `T3_1` and `T3_2` → first; after `T3_2` → second |
| PIT-02 | As-of at `T3 − 1 µs` → not visible |
| PIT-03 | Two records with equal `valid_from` for one entity → reader `Unusable(AMBIGUOUS)` (frozen `PITViolation`) |
| PIT-04 | SUSPENDED/BLOCKED head blocks an older OPEN still within its TTL, and keeps blocking after the old OPEN's `valid_to` and after a changed `S` |
| PIT-05 | Complete response lacking an expected-scope book → ABSENT tombstone; partial or failed response → none |
| PIT-06 | Invalidation (§13.2): as-of `< T3_inv` returns the original, `≥ T3_inv` → `Unusable(INVALIDATED)`; a manifest built at an earlier `D` still verifies; invalidating a superseded record → no PIT record (`NONE_ALREADY_SUPERSEDED`). Detailed in INV-01…04 |
| PIT-07 | Derivation change: new source; old capability BLOCKED at `T_fix`; as-of `< T_fix` uses the old source; `≥ T_fix` the old source fails; two READY sources → fail closed |
| PIT-08 | `superseded_*` always `None`; `record_id` deterministic from (source, artifact); crash between normalized publish and PIT append → resume reuses the observation, one PIT row |
| PIT-09 | Wipe the derived stores, rebuild from raw + acquisition ledger → identical normalized artifact hashes and PIT `record_id`s |

### Freshness and cache

| ID | Test |
| --- | --- |
| FR-01 | As-of at `T1 + price_ttl_seconds − 1 µs` usable; at `T1 + price_ttl_seconds` → `Unusable(MISSING_OR_STALE)` |
| FR-02 | `valid_to` capped at `S − prematch_guard_seconds` |
| FR-03 | A failed or blocked refresh leaves the old record's `valid_to` unchanged and adds no record |
| FR-04 | ODDS: cache publish and lookup refused; a cache hit never creates a normalized observation or PIT record |
| FR-05 | META cache hit: 0 units, frozen `quota_verified_cache_hit` row; expired or invalidated entry → billable row with `cache_miss_reason` |
| FR-06 | Cache entry for a different `provider_request_hash` → not usable |
| FR-07 | Retention: after a META cache hit is recorded, deleting or altering the referenced cache object or its `cache-authority.jsonl` row makes `QuotaLedger` construction/verify fail (F-42) and halts acquisition; the adapter has no code path that deletes cache objects (AST) |
| FR-08 | Changing any single §12.1 parameter (e.g. `price_ttl_seconds`) in a test policy changes `policy_digest`, `derivation_version`, contract ID and PIT `source_id`; old observations keep their old `valid_to` |

### Quota

| ID | Test |
| --- | --- |
| Q-01 | Every `sent` acquisition has exactly one prior allowed quota row with the same `request_id` and `provider_request_hash`; no send without it |
| Q-02 | Eighth request of a UTC day → blocked, not sent, F-02 coverage |
| Q-03 | 221st normal unit → blocked; adapter never requests RESERVE |
| Q-04 | Timeout, 5xx, 429, 401 each keep their Genesis debit; a retry is debited again under a new `request_id` |
| Q-05 | Retry policy table (§14.3) exhaustively |
| Q-06 | Crash after reservation → `ORPHANED_RESERVATION`, no re-send; re-request with the same ID and a new time → halt (frozen `RegistryConflict`) |
| Q-07 | Clock regression vs ledger head → `ClockFault` halt |
| Q-08 | Scheduler: plan ≤ Σ pool ceilings/month, ≤ `scheduled_daily_max`/day, priority drop order; conditional refresh admitted only when all §14.5 conditions hold |
| Q-09 | Provider usage header > ledger → `QUOTA_DIVERGENCE` halt |
| Q-10 | Live mode loads the frozen active policy unchanged (digest `3cdf9e3e…a0f9`); tests only with `test_fixture` |
| BILL-01 | Acquisition rows carry `provider_metering`, `provider_request_weight`, `provider_documented_billable` (planned) separately from `genesis_units_debited` (quota_decided) and `provider_reported_usage` (completed); a `NON_METERED` role still debits `genesis_debit_units ≥ 1` and records `provider_documented_billable = false` |
| BILL-02 | `FIXED_WEIGHT w` role debits `billable_units = genesis_debit_units ≥ w` in one frozen request; config with `genesis_debit_units < w` is refused at load |
| BILL-03 | `VARIABLE`/`UNKNOWN` metering role → refused at plan time, never sent |
| BILL-04 | No adapter text, report or record calls a ledger debit "provider billed"; the summary/report generator labels ledger figures "Genesis debit" and header figures "provider-reported usage" (string-level test over generated reports) |
| BILL-05 | Boundability check (§20.1 FR-1): table-driven over provider terms {allowance 300/month; 250/month; 230/month; rolling 30-day 250; non-UTC month 250; UTC-aligned daily 7; UTC-aligned daily 5; non-aligned daily 10; fixed weight 2; non-metered} → pass/fail exactly as §20.1 specifies. Evaluated both **with** the §14.6 guard (counting over `W`) and in **fallback** mode (counting over `W⁺` built from the policy's `request_timeout_seconds` and `clock_skew_max_seconds`), including the UTC-aligned daily-7 case that passes only with the guard |
| BND-01 | Day boundary, exact edges (W1/W3), with `m = request_timeout_seconds + clock_skew_max_seconds` read from the test policy: `Tq = midnight − m − 1 µs` → sent; `Tq = midnight − m` → refused; `Tq = midnight − request_timeout_seconds` → refused; `Tq = midnight − 1 µs` → refused; `Tq = midnight` → refused; `Tq = midnight + clock_skew_max_seconds − 1 µs` → refused; `Tq = midnight + clock_skew_max_seconds` → sent |
| BND-02 | Month boundary, same exact-edge grid (W2/W4) at month rollovers: 30→31-day months, 28 Feb (non-leap), 29 Feb (leap), 31 Dec → 1 Jan. Each W-condition is also tested in isolation through a stub boundary calculator, so the "month implied by day" redundancy can't mask a month-arithmetic bug |
| BND-03 | A refused send makes no `QuotaLedger.request` call and writes no quota row; acquisition `refused{WINDOW_BOUNDARY_GUARD}` + coverage NOT_ATTEMPTED (F-43); the guard `Tq` and the ledger `occurred_at` are the same value for permitted sends |
| BND-04 | Hard deadline: a fake slow server makes the transport abort at exactly `Tq + request_timeout_seconds` (fixed clock); `T0 ≥ deadline` → request not written; outcome `NO_RESPONSE`/`TRUNCATED`, debit stands |
| BND-05 | `request_timeout_seconds` is in `policy_digest`: changing only it changes `policy_digest`, `derivation_version`, contract ID and `source_id`; the loader rejects `≤ 0`, a missing field, and a guard zone ≥ 1 hour |
| BND-06 | Scheduler never plans a window inside a guard zone; retries and conditional refreshes landing in a zone are refused or deferred to `boundary + clock_skew_max_seconds` |
| BND-07 | After a `CLOCK_SKEW` quarantine, all sends are refused until the next UTC day and a clean `Date` check (§14.6 rule 5) |

### Gates

| ID | Test |
| --- | --- |
| G-01 | Live transport refuses without G1/G2 (or G2R) records, a matching credential fingerprint, file permissions and time-sync attestation |
| G-02 | Under G2 only the pinned request hashes are sendable, at most `max_calls`, inside the window |
| G-03 | Adapter runtime can register BLOCKED/UNKNOWN capability rows only; READY only via `cli.py approve` after a G3 record |
| G-04 | 401/403 → capability BLOCKED for all market-book sources, circuit open |

### Failure matrix

| ID | Test |
| --- | --- |
| FM-00 | `AdapterFailure → ReasonCode` mapping is total and single-valued |
| FM-01…43 | Table-driven: for each §15 row (including F-11b), assert retained evidence, coverage status/reason/note, and the observation/head effect |

### Closed schemas, reader parity, invalidation

| ID | Test |
| --- | --- |
| SCH-01 | For each semantic structure (outcome, price, line, market, market-status, bookmaker block, event/fixture, participant, event-status, envelope): an added unknown key → `BLOCKED / SCHEMA_DRIFT` at exactly the §10.1 scope, with no `selections`; the same key declared `inert` → accepted and never read |
| SCH-02 | Wrong JSON type for a known key, missing required key, unknown enum-like code → drift or status rule per §10.1 |
| SCH-03 | Envelope-level drift → response REJECTED, zero observations, zero tombstones |
| SCH-04 | Schema-file change → new `response_schema_digest` and `derivation_version` |
| RDR-01 | Parity: for every fixture scenario and a cutoff grid around `T1`, `T3`, `published_at`, `valid_to`, `T_inv`, `admissible_head` is usable **iff** frozen `verify_for_pack` accepts a manifest pinning that head, and the adapter-only refusals don't apply |
| RDR-02 | `published_at > D` on the head (via `provider_future_tolerance_seconds`) → `Unusable(NOT_PUBLISHED_AT_CUTOFF)` and **no** fallback to the older record; the frozen verifier also rejects both the head and the older record at that `D` |
| RDR-03 | Capability head not unique at `D`, binding missing, or contract mismatch → `Unusable`, matching verifier rejection |
| INV-01 | Invalidating a **still-current** OPEN head: as-of at `D < T3_inv` → original usable (manifest built then still verifies); `D ≥ T3_inv` → `Unusable(INVALIDATED)`; a new manifest pinning the old record fails the frozen verifier |
| INV-02 | Invalidating an already-superseded record → no PIT record, ledger `head_effect = NONE_ALREADY_SUPERSEDED`; as-of unchanged at all cutoffs |
| INV-03 | `verify_derivation` on INVALIDATION documents: byte-identical rebuild from (ledger row, target document); tampered ledger row, wrong target hash or wrong `invalidated_pit_record_id` → failure; unknown `derivation_kind` → failure |
| INV-04 | `T_inv` tie with an existing `valid_from` → clock re-read until strictly greater; a later genuine capture supersedes the INVALIDATED head; automatic invalidation after a failed `verify_derivation` of a head |

---

## 19. Staged implementation sequence

Global GREEN criteria for **every** stage:

1. Adapter suite fully GREEN.
2. Frozen suite GREEN with counts identical to the Stage 0 baseline.
3. `compileall` clean.
4. `git diff --check` clean.
5. FRZ-01/02/03/05–11 GREEN (FRZ-10 from S1 on), including the module-provenance guard at suite start.
6. No file changed under a frozen tree.
7. RED and GREEN transcripts plus `HASHES.sha256` committed under `adapters/evidence/S<n>/`.
8. One commit per stage (or RED commit + GREEN commit), message prefix `v05(S<n>):`.

| Stage | Build | Stage-specific GREEN |
| --- | --- | --- |
| **S0** Skeleton + freeze and provenance guards | `adapters/` tree, `README.md`, nested `.gitattributes`, `adapter_tests/__init__.py`, `support.py` shell, `verify.verify_frozen_trees`, `provenance_guard` + `frozen_genesis_modules.json` (generated from the frozen tree with Git), static scanners | FRZ-01…09, FRZ-11. Frozen-suite baseline transcript recorded (platform, Python, counts), F-41 |
| **S1** Primitives | `ids`, `jsonstrict`, `schema` (closed validator), `clock`, `secrets.Secret` + `scan_for_secret`/`scan_headers` (no loader), `config` (`SlicePolicy` with no defaults, loaders, digests, `derivation_version`), `endpoints` (incl. metering fields) | REQ-01/02/03/05/08 (hash part), SEC-01, SEC-05, CLK-01, ID-01/02, MKT-07 (literal parsing), FRZ-10, FR-08 (digest part), SCH-04 |
| **S2** Quota + acquisition | `quota_gate`, `transport` protocol, `FakeTransport` (tests), `acquisition` ledger/runner (fixture mode) with the §14.6 UTC boundary guard before every ledger call, retry/circuit, restart reconciliation, metering/debit fields | Q-01…07, Q-10, BILL-01…03, BILL-05, BND-01…03, BND-05, CLK-03, REQ-06, F-01…F-05, F-07…F-10, F-35, F-43 |
| **S3** Raw capture | Raw contract registration, pre-persistence secret scan of wire/decoded body and all headers, bounded content decoding, quarantine metadata, skew check, size cap, raw publish, META cache publish with retention | EV-01/02/07, REQ-07, SEC-02…04, CLK-04, FR-05/06/07, F-06, F-11, F-11b, F-12…F-14, F-34, F-42 |
| **S4** Parsing + normalization (pure) | `maps`, closed response schemas, `identity_registry`, `parser`, `normalize` (RESPONSE kind), doc-derived fixtures + `FIXTURES.sha256` | MKT-*, ST-*, SCH-01…03, ID-02…09, TS-01…06, EV-03/04/08, F-15…F-29, F-38 (document level) |
| **S5** Emission + PIT + reader | `emit` (normalized evidence, structured evidence, PIT, coverage), expected scope, tombstones, invalidation ledger + INVALIDATION documents, derivation-versioned sources, `admissible_head` / `reader` | PIT-01…09, INV-01…04, RDR-02/03, FR-01…04, FR-08, TS-07, ST-05, F-25…F-33, F-36, F-39, F-40 |
| **S6** Manifest + end-to-end | `manifest` (via `admissible_head`), `verify_derivation` (both kinds), full fixture pipeline, failure matrix, runtime secret scan, deterministic rebuild | EV-05/06, RDR-01, PIT-09, FM-00…43, REQ-04 |
| **S7** Scheduler, authority, dormant live transport | `scheduler`, `authority`, `transport_http` (§7.7 exception boundary that preserves process-control exceptions; hard deadline `Tq + request_timeout_seconds`; tested **only** against a loopback HTTPS test server with a self-signed CA injected for tests; the production host is pinned and never contacted), `CredentialSource` (tested with a temp file holding the sentinel), `cli` (sanitizing, flow-neutral excepthooks; no `BaseException` handlers; `-B` + fresh pycache prefix; provenance guard at startup) | Q-08/09, BILL-04, BND-04, BND-06, BND-07, G-01…04, CLK-02, TX-01 (ordinary errors sanitized; `KeyboardInterrupt`/`SystemExit` preserved), FRZ-09 (runner startup), FRZ-11, F-37. Proof that no test contacts a non-loopback address (socket audit hook in `adapter_tests`) |
| **STOP** | — | Implementation ends here. G1, G2, G2R and G3 are human actions (§16). The implementing agent does not perform them |

---

## 20. Foundation reopen register

**No FOUNDATION REOPEN is required for slice 1.** These are the known triggers.

### 20.1 FR-1 — provider terms that the frozen quota authority cannot safely bound (closes A4)

The frozen authority is `(provider_monthly_allowance 250, normal 220, reserve 30,
daily 7)`, hard-coded in `QuotaPolicy.require_operational` and pinned in the frozen
`config/oddspapi_quota_policy_v2.json`. It debits whole units per request **before**
sending, per UTC day and UTC calendar month. A reopen is needed **only** when real
provider terms cannot be safely bounded by that authority. The test, run at G1 and
again whenever terms change (BILL-05):

- **B1 — Window bound.** For every provider accounting window `W` with limit `L_W`
  (provider units), the maximum Genesis debit whose provider receipt can fall inside `W`
  must not exceed `L_W`: `GenesisMax(W) = min(7 × U_W, 250 × M_W)`, where `U_W` is the
  number of UTC days and `M_W` the number of UTC calendar months that `W` can overlap at
  worst-case alignment.
  - 250 (not 220) is used because the frozen authority lets a human-granted reserve be
    spent.
  - Provider consumption never exceeds the Genesis debit, because each debit is ≥ the
    provider weight (§7.2).
  - **Why counting over `W` itself is valid:** the §14.6 boundary guard (W1–W4) plus the
    hard transport deadline ensure every provider receipt permitted by the model (receipt
    within `request_timeout_seconds` of `Tq`, attributed by either clock within
    `clock_skew_max_seconds`) falls in the **same** UTC day and UTC month as its debit at
    `Tq`. Receipts inside `W` therefore come only from debits made on UTC days/months that
    `W` itself overlaps, and the per-UTC-day (7) and per-UTC-month (250) frozen caps bound
    them.
  - **General fallback.** If the same-window send restriction is ever removed or relaxed,
    this shortcut no longer holds. `U_W` and `M_W` must then be computed over `W`
    **extended backwards** by the maximum possible debit-to-receipt latency
    (`request_timeout_seconds`, plus `clock_skew_max_seconds` on each side if the provider
    attributes by its own clock). That is,
    `W⁺ = [start(W) − request_timeout_seconds − clock_skew_max_seconds, end(W) +
    clock_skew_max_seconds)`, and B1 becomes `min(7 × U_{W⁺}, 250 × M_{W⁺}) ≤ L_W`.
    Removing the guard is itself a design change requiring re-review.
- **B2 — Pre-send cost bound.** Every endpoint role that slice 1 uses has a cost fixed
  before sending (`PER_REQUEST`, `FIXED_WEIGHT`, or `NON_METERED`), so
  `genesis_debit_units ≥ provider_request_weight` can be reserved before the request goes out.

**FOUNDATION REOPEN REQUIRED** only if B1 or B2 fails for a role that slice 1 cannot drop.
Examples:

- the provider's UTC-calendar-month allowance is below 250 (Genesis could spend up to 250
  in that month, including a human-granted reserve). This relies on the §14.6 guard
  keeping every receipt in the debit's UTC month;
- a provider daily limit below `7 × U_day`. Under the §14.6 guard: below 7 for a
  UTC-aligned provider day (`U_day = 1`), or below 14 for a provider day not aligned to UTC
  (it overlaps 2 UTC days at worst). Without the guard (fallback), even a UTC-aligned
  provider day extends backwards over the previous UTC day, so `U = 2` and the limit
  must be ≥ 14;
- request cost depends on the response (per-event, per-bookmaker or per-market charging
  not known before sending), so it can't be reserved pre-send under the frozen ledger.

**Do not by themselves require a reopen:**

| Situation | Why it is safely bounded |
| --- | --- |
| A more generous allowance (e.g. 500/month) | Genesis stays inside its stricter frozen ceiling |
| Genuinely non-metered endpoints | Genesis debits ≥ 1 anyway (§14.2), a conservative over-debit |
| Conservatively debiting Genesis budget for a provider-free endpoint | Same. `provider_documented_billable = false` records the difference |
| Fixed request weights (e.g. 2 units per ODDS call) | Reserved pre-send as `billable_units = genesis_debit_units ≥ w` (frozen `request` supports `billable_units > 1`) |
| A different provider accounting window, e.g. a rolling 30 days or a non-UTC month | Passes B1 when `GenesisMax(W) ≤ L_W`. **Under the §14.6 guard**, a rolling 30-day window overlaps ≤ 31 UTC days, so ≤ 217; a non-UTC calendar month (≤ 31 days) overlaps ≤ 32 UTC days, so ≤ 224. Both are within a 250 limit. Under the fallback (guard removed), `W⁺` adds at most one more UTC day for the provisional values, giving ≤ 224 and ≤ 231, still within 250. The figures are recomputed from the actual policy values at G1 (BILL-05) |
| Per-second / per-minute rate limits | Not part of the frozen authority. Bounded by the adapter's own spacing (≤ 7 requests/day, serialized) and the 429 circuit (§14.3) |

If only some roles fail, those roles are unusable (§7.2) and slice 1 proceeds if the rest
suffice. Declining to activate the provider at all is always an option and never needs a
reopen.

### 20.2 Register

| ID | Trigger | Why it would need a reopen | Status |
| --- | --- | --- | --- |
| FR-1 | Provider terms fail boundability B1/B2 (§20.1) for a role slice 1 needs | The frozen ceiling/window/debit model cannot then keep provider consumption within the provider's limits | **FOUNDATION REOPEN REQUIRED if triggered.** Live acquisition for that role must not start |
| FR-2 | A second quota/ingestion writer, multi-host deployment, or foundation consumers needing trusted time | `QuotaLedger`/ingestion accept writer-declared times (freeze residual). The adapter mitigates only its own path (§6.1) | Deferred; **reopen required before** any second writer |
| FR-3 | A foundation consumer (selection/execution) must read bookmaker prices directly | `MarketSnapshot` lacks bookmaker/line/status vocabulary and has no consumer | Deferred. Slice 1 is adapter-owned |
| FR-4 | Wish to debit genuinely non-metered endpoints at 0 Genesis units | The frozen ledger rejects `billable_units ≤ 0` on debited rows | **Not triggered.** Optional future optimization. Slice 1 debits ≥ 1 (safe over-debit, no reopen) |
| FR-5 | Logging redaction gap (`apiKey`/`apikey`, URL-embedded secrets not masked by `genesis.logging._redact`) | Frozen `SENSITIVE_KEYS` | Deferred hygiene fix. Slice 1 never passes secrets to any logger (REQ-04) |
| FR-6 | Retroactive PIT supersession | Not needed: tombstone heads and derivation sources replace it (§13) | Closed by design. No reopen |

---

## 21. Residual assumptions and deferred work

Verified at G2 (until then, fixture-only):

- A1 Endpoint paths, parameter names, multi-tournament and bookmaker-filter support, and
  the `apiKey` query-parameter credential placement (Prep A).
- A2 Response field names and types for fixtures, participants, market/outcome IDs, lines,
  prices and statuses. Whether ODDS responses include kickoff and participants (§8.3).
- A3 Provider timestamp formats and offsets. The semantics of per-outcome timestamps
  ("changed" vs "checked") — provenance only until verified.
- A4 `Date` header presence. Content-encoding behaviour with `accept-encoding: identity`.
  Quota/usage headers.
- A5 Status value sets. Ambiguous documented values stay excluded (BLOCKED) until
  evidenced.
- A6 Whether any declared bookmaker is an exchange. Exchanges are excluded regardless.

Policy assumptions (versioned; change = new `derivation_version`):

- A7 Every §12.1 value (price TTL, prematch guard, future tolerance, clock skew, drift,
  odds bounds, overround bands, fragment threshold, retry backoff, schedule offsets,
  budget pools, `g3_min_observation_days`) is a **provisional slice-1 policy parameter
  with no frozen-repository authority**. None is Genesis architectural law. Each is
  expected to be revisited with G2R evidence.
- A8 Budget split 4/18/135/30 within 187 Genesis debit units. Windows and priorities
  (§14.5).
- A12 OddsPapi metering type and weights per role (`provider_metering`) are doc-derived
  until G1/G2. Provider-reported usage headers may not exist; then AC-7 relies on the
  Genesis debit alone.
- A13 Closed-schema `inert` key classifications are made from G2 evidence. Until then
  every unknown key in a semantic structure is drift.

Operational:

- A9 Single process, single host, file-backed stores (frozen assumption). The filesystem
  handles ~10⁵ small artifacts per month.
- A10 Gate-record authenticity rests on operator discipline (§16.6).
- A11 The frozen-suite baseline count on the implementation platform is recorded at S0,
  not assumed. The freeze record's 493/1-skip is Windows; Linux skips the containment tests.

Deferred (not slice 1):

- Raw captures as separate `evidence`-role manifest inputs (§11.5).
- Historical reconstruction.
- Additional competitions, markets, lines or bookmakers.
- Exchanges and LAY (needs the LAY price-sanity fix first).
- Cross-provider participant crosswalk.
- The Betfair and The Odds API adapters (future-source candidates per Prep A).
- Cloud scheduling.
- A `MarketSnapshot` projection (FR-3).

---

## 22. Prep B resolution index

Numbering follows the task brief where it gave numbers; other items are indexed by topic.

| Prep B item | Resolution |
| --- | --- |
| Freeze semantics vs new files under frozen trees | §2: new sibling tree `adapters/`; tree-SHA invariance guard |
| Q1 / Q3: `available_at` vs `retrieved_at`, `first_seen_at`, `parse_ready_at`; trusted clock | §6 |
| Q2: corrections/supersession for immutable PIT records | §13 |
| Reject vs normalize non-UTC offsets | §6.4: reject (frozen `SOURCE_AVAILABILITY.md` rule 2) |
| Q4: `MarketSnapshot` lacks bookmaker/line/status | §9: adapter-owned `MarketBookDocument`; `MarketSnapshot` untouched (§20 FR-3) |
| Q5: staleness / cache freshness / polling | §12, §14.5 |
| Provider-request-hash canonicalization | §7.3 |
| Trusted-clock authority | §6.1 |
| Q9: authority for credentials / live read-only calls | §16 |
| Source/market readiness and human-approval boundaries | §16.4–16.5; `MarketCapability` stays not-ready for qualification |
| No repository-defined adapter location | §4 |

Contradictions found in the repository and how they are settled:

| # | Contradiction | Settlement |
| --- | --- | --- |
| X1 | `V04_FOUNDATION_FREEZE.md` says to branch from `4f11606`; the tag is `2278e2a` | Both have identical executable trees. The guard pins tree SHAs, not a base commit (§2.1.6) |
| X2 | `SOURCE_AVAILABILITY.md` rule 5 ("corrections add a new record") vs `BitemporalRecord.superseded_*` fields that can't be set retroactively | Corrections are new heads/sources. `superseded_*` always `None` (§13) |
| X3 | `DATA_DICTIONARY.md` presents `MarketSnapshot` as the price record, but nothing consumes it and it can't express bookmaker/line | Adapter-owned document. No foundation edit (§9) |
| X4 | `OPERATIONS_RUNBOOK.md` "do not add credentials to this repository" vs a live provider needing a key | Key lives outside the repository and runtime root, behind G1 (§7.5) |
| X5 | Frozen log redaction claims sensitive-key masking but misses `apiKey` and URL-embedded secrets | Secrets unreachable by construction. Deferred hygiene (§20 FR-5) |
| X6 | The v0.4 blueprint allows "non-metered endpoints accordingly", but the frozen ledger cannot record zero-unit debits | Provider metering and Genesis debit are separate fields. Genesis debits ≥ 1 (§14.2). No reopen (FR-4 not triggered) |
| X8 | Frozen ledger vocabulary says "billable", which reads as provider billing | Ledger rows are Genesis internal budget debits, not evidence of provider billing (§14.2) |
| X7 | Feature manifest field `raw_artifact_hash` vs the need to pin decision-consumable normalized bytes | The field carries the normalized artifact hash. Raw is bound transitively plus `verify_derivation` (§11.5) |

---

## 23. Implementation prompt (copy-paste)

```text
ROLE
You are implementing Project Genesis V0.5 slice 1 (OddsPapi read-only adapter) exactly as
specified by the design authority V05_ADAPTER_ARCHITECTURE.md (revision r3) at the
repository root. That document is binding. Where it and your judgement differ, it wins.
If it is internally inconsistent or impossible against the frozen code, STOP and report
the exact conflict. Do not work around it.

REPOSITORY STATE
- Work on the branch you were given, which descends from tag v0.4-foundation-freeze
  (2278e2a68083f7ac58d796b1ed9c43d50020b6b0) and contains the r3 design commit.
- Frozen trees (NO-TOUCH: no file added/edited/deleted/renamed): src/, tests/, config/,
  tools/, DECISIONS/, v04_pack/. Their tree SHAs must stay exactly:
    src 51cb635bc42b993815b6c02a23c4c3ceb7d98476
    tests e90b298180068fec03ba7e2fa81957082e7fb3ce
    config abd22db01ff482a8da84634ee740ba382b68c804
    tools a0e3411edb4e068fd4708050516cb6870834e7ac
    DECISIONS cc97ec6f841f1e3fbe6dbb57c9cb6e1ac24fdb64
    v04_pack 3c3c1c27d80ed6f10c32ac6605a5f438b2e7de12
- Also never modify: remediation_evidence/**, .gitignore, top-level .gitattributes,
  pyproject.toml, requirements.lock, V05_ADAPTER_ARCHITECTURE.md. Never rewrite history,
  force-push, or amend.
- All new work goes under adapters/ exactly per §4 (package genesis_adapters in
  adapters/src, tests package adapter_tests in adapters/adapter_tests, config in
  adapters/config, evidence in adapters/evidence/S<n>/). Runtime data defaults to
  runtime/adapters/oddspapi (already git-ignored) and is never committed.

ABSOLUTE PROHIBITIONS
- No network access to any OddsPapi (or other provider) host. No credential creation,
  storage or use. No real API key anywhere. Tests use only the sentinel
  "GENESIS-SENTINEL-KEY-0123456789abcdef".
- Do not create, edit or append any gate/approval record (G0, G1, G2, G2R, G3), any
  authority.jsonl outside tests' temp dirs, or any ADR marked ACCEPTED. Do not register
  any SourceCapability as READY outside test temp registries. (Invalidation rows and
  BLOCKED/UNKNOWN capability downgrades are fail-safe and allowed, §13.2 / §16.)
- Do not construct QuotaReserveAuthorization, call grant_authorization /
  revoke_authorization, or use BudgetClass.RESERVE.
- Do not monkeypatch, subclass-override or call private (_-prefixed) members of any
  genesis.* module. Use only the public frozen APIs listed in §5.
- Do not import socket/ssl/http/urllib.request/requests/httpx/aiohttp anywhere except
  genesis_adapters/oddspapi/transport_http.py (Stage 7). Its tests use only a loopback
  test server.
- Never use float for odds, lines or money. Parse JSON with parse_float=Decimal.
- Never normalize non-UTC provider timestamps. Reject them per §6.4.
- Never carry a price forward, re-stamp an observation, or create an observation from a
  cache hit. ODDS responses are never cached. Never delete, move or rewrite quota cache
  objects or cache-authority rows (§12.2 rule 10).
- Never write a provisional policy value as a literal in code. Every duration, bound,
  threshold, timeout (including request_timeout_seconds), pool size and schedule offset
  comes from SlicePolicy (§12.1), which has no code defaults. These values are
  provisional slice-1 policy parameters, not law.
- CREDENTIAL SAFETY DOMINATES RAW RETENTION (§7.6). Secret-bearing or uninspectable
  bytes never enter durable storage in any form: no raw object, no redacted derivative,
  no body hash. Only secret-safe quarantine metadata is written, and it is scanned too.
- Transport exception boundary (§7.7). Ordinary Exceptions are converted to the
  sanitized TransportResult (class/errno only) and never raised. KeyboardInterrupt and
  SystemExit are NEVER converted, demoted or swallowed. transport_http.send re-raises a
  fresh KeyboardInterrupt() / SystemExit(int code) (non-int code -> 1, None -> None)
  `from None`, AFTER its except block, with keyed locals deleted. No other adapter code
  may catch BaseException, KeyboardInterrupt or SystemExit, use a bare except, or put
  return/break/continue in finally (FRZ-11). Never record str(exc)/exc.args. Never
  persist a URL string.
- Never send a provider request unless the §14.6 UTC boundary guard (W1-W4) permits it:
  refuse when Tq + request_timeout_seconds (+ clock_skew_max_seconds) would cross a UTC
  day or month boundary, or when Tq - clock_skew_max_seconds precedes the start of Tq's
  UTC day/month. The guard runs BEFORE QuotaLedger.request, using the same Tq, so a
  refused send is never debited. Enforce the hard transport deadline
  Tq + request_timeout_seconds.
- Never silently ignore an unknown field in a semantic provider structure. Closed schemas
  per §10.1. Drift is BLOCKED / SCHEMA_DRIFT.
- Never describe a quota-ledger debit as provider billing. Keep provider_metering,
  provider_documented_billable, provider_reported_usage and genesis_units_debited as
  separate fields (§14.2).

KEY SEMANTICS YOU MUST IMPLEMENT EXACTLY
- Freeze + runtime provenance: FRZ-01…03 tree/worktree guards; FRZ-09 module-provenance
  guard (§2.4) at adapter-suite start and at every runner/CLI startup, with the pinned
  frozen_genesis_modules.json generated from the frozen src tree via git.
- Time/PIT: §6 (trusted SystemUtcClock; Tq ≤ T0 < T1 ≤ T2 ≤ T3; available_at =
  retrieved_at = first_seen_at = valid_from = T1; ready_at = T3; OPEN valid_to =
  min(T1 + price_ttl_seconds, S − prematch_guard_seconds); tombstones valid_to = None).
- Reader parity (§12.3): one shared predicate admissible_head(), used by reader and
  manifest builder. It mirrors every frozen verify_for_pack check at cutoff D, including
  publisher_timestamp/published_at <= D. It never falls back to an older record. RDR-01
  proves the iff-parity.
- Invalidation (§13.2): append-only invalidations.jsonl. INVALIDATED head with
  valid_from = T_inv and ready_at = T3_inv, effective only from its own admissible time.
  Earlier as-of is unchanged. If the target is already superseded, no PIT record.
  verify_derivation is deterministic for both derivation kinds (§11.5).
- Quota (§14): debit genesis_debit_units (>= provider weight, >= 1) NORMAL before send;
  no refunds; VARIABLE/UNKNOWN metering roles are unusable; retries per §14.3 using
  policy fields; UTC boundary guard and hard deadline per §14.6. After a CLOCK_SKEW
  quarantine, suspend sends until the next UTC day and a clean Date check.
- Boundability (§20.1) is a G1 human check against real terms. Implement only its
  table-driven evaluator (BILL-05), covering both guarded counting over W and the
  fallback counting over W+.
- Failure semantics: every §15 row F-01…F-43 (including F-11b), table-driven.

METHOD
- Implement Stages S0 → S7 of §19 in order. For each stage:
  1. Write the stage's tests from §18 first. Run them and save the RED transcript to
     adapters/evidence/S<n>/RED.txt (import errors or failing asserts are acceptable RED).
  2. Implement the minimum code to make them GREEN, following §2.4 and §6–§17
     field-for-field (names, schemas, time rules, IDs, reason mappings, failure rows).
  3. Run, and save transcripts to adapters/evidence/S<n>/:
       python -B -m unittest discover -s adapters/adapter_tests -t adapters -v   (GREEN.txt)
       python -m unittest discover -s tests -t . -v                               (FROZEN.txt)
       python -m compileall -q src tests adapters/src adapters/adapter_tests
       git diff --check
       for t in src tests config tools DECISIONS v04_pack; do git rev-parse HEAD:$t; done
     plus HASHES.sha256 over the transcripts. (Set PYTHONPYCACHEPREFIX to a fresh temp
     dir for the adapter suite, per §2.4.)
  4. GREEN requires: all adapter tests pass; frozen suite pass/skip counts identical to the
     S0 baseline; freeze guard, module-provenance guard and static scanners (FRZ-05…11)
     pass; no frozen-tree change.
  5. Commit with prefix "v05(S<n>): …". Push only to the assigned branch.
- Fixtures: build doc-derived synthetic OddsPapi v4 payloads under
  adapters/adapter_tests/fixtures/oddspapi/v4/, clearly marked fixture_only, with
  FIXTURES.sha256. Include:
  - the happy path (2 competitions, 3 bookmakers, 1X2 + O/U lines
    1.5/2.25/2.5/2.75/3.5) and a 5-bookmaker variant;
  - every payload-driven failure row;
  - identity conflicts; unknown and contradictory status; timestamp anomalies; partial
    payload;
  - closed-schema drift at every §10.1 scope and declared-inert keys;
  - secret echo in every §7.6 form (body, headers, gzip, UTF-16, base64, fragments);
  - duplicate keys, NaN, oversize, uninspectable encodings.
- Clocks: production code receives a TrustedClock. Tests use FixedClock from
  adapter_tests/support.py only. Parsers/normalizers are pure and never read a clock.
- Determinism: canonical_json from genesis.repro for every hashed/persisted JSON; gid()
  per §8.1; derivation_version per §9.2 (it includes the full policy digest and the
  closed-schema digest); PIT record_id per §11.4.
- Evidence flow order exactly per §11.1. PIT timestamps exactly per §6.2 and §11.4.
- The end-to-end test (EV-05) and the parity test (RDR-01) must pass against the frozen
  FeatureInputManifestStore.verify_for_pack unchanged, using temp registries with a
  synthetic-test-only binding reference.
- TX-01 must run the runner's real main() in a subprocess through a recording harness.
  It must prove:
  - ordinary keyed-URL errors become the sanitized result and never reach the top level;
  - an injected KeyboardInterrupt reaches the top level as KeyboardInterrupt, with the
    uncaught-SIGINT exit status;
  - an injected SystemExit(37) reaches the top level as SystemExit with return code 37
    (and a string code gives 1, never printed);
  - neither is swallowed or converted by the runner;
  - the reaching exception has no cause/context/notes and no sentinel in any traceback
    local;
  - stdout, stderr, logs, evidence and provenance are clean for every §7.6 form of the
    sentinel.
- BND-01/02 must test the exact edges (just before and after each guard edge) at UTC
  midnight and at month rollovers, including leap-year February and year-end. All edges
  are computed from the test policy's request_timeout_seconds and
  clock_skew_max_seconds; no literal.

STOP CONDITIONS (report and halt, do not improvise)
- Any requirement appears to need a change inside a frozen tree → report
  "FOUNDATION REOPEN REQUIRED: <item>" with the exact frozen file/line, and stop.
- Any test would need network access, a real credential, or an approval record.
- Frozen suite count changes, any frozen tree SHA changes, or the module-provenance guard
  cannot be made to pass on a clean checkout.
- After S7: stop. Do not attempt G1/G2/G2R/G3, the §20.1 boundability check against real
  terms, or any live request.

DELIVERABLE
- Stages S0–S7 committed with RED/GREEN evidence, and adapters/README.md with run
  commands.
- A final adapters/evidence/S7/SUMMARY.md listing:
  - per-stage test counts and frozen-suite counts;
  - freeze-guard and module-provenance-guard output;
  - every §18 test ID with its pass status;
  - any deviation (there should be none), with justification.
```

---

## 24. r2 AMBER remediation map

| Finding | Closure | Sections changed |
| --- | --- | --- |
| A1 Freshness policy has no frozen authority | TTL, guard and every other number reclassified as **versioned provisional slice-1 policy parameters, not law**. They are named `SlicePolicy` fields with no code defaults and no literals (FRZ-10). `policy_digest` covers every field and feeds `derivation_version`, so any change creates a new source (FR-08) | D9, §3.1, §6.1–6.4, §9.1–9.2, §10, §12.1–12.2, §14.3, §14.5, §15 F-27, §18, §21 A7 |
| A2 14-day READY rule | READY now requires explicit acceptance criteria AC-1…AC-9 (integrity, failure record, schema, coverage content, parity, time, quota, foundation, hostile review). `g3_min_observation_days` is only a provisional **minimum** window, explicitly not sufficient | §12.1, §16.5 |
| A3 Provider billability conflated with Genesis budget | Separate fields: `provider_metering`, `provider_request_weight`, `provider_documented_billable`, `provider_reported_usage`, `genesis_units_debited`/`genesis_debit_units`. Frozen `quota_billable_call` is declared a **Genesis internal debit**, not evidence of provider billing (BILL-01…04) | D10, §7.2, §9.3, §12.2 r9, §14.1–14.2, §14.4–14.5, §15, §18, §22 X6/X8 |
| A4 Over-broad reopen trigger | r2: FR-1 replaced by the §20.1 boundability test (B1 window bound `min(7×U_W, 250×M_W) ≤ L_W`, B2 pre-send cost bound) with explicit non-triggers. **r3:** new policy field `request_timeout_seconds` (in `policy_digest`, no other timeout literal, FRZ-10). §14.6 runner invariant W1–W4 refuses a send when `Tq + request_timeout_seconds` (plus the provider-clock skew margin) would cross a UTC day or month boundary, checked before the ledger debit; hard transport deadline `Tq + request_timeout_seconds`. B1 now states why same-window counting is valid, and documents the backwards-extended `W⁺` fallback. Examples corrected to say which bounds depend on the guard (BND-01…07, BILL-05) | D14, §12.1, §14.5, §14.6, §15 F-12/F-43, §17, §18, §19, §20.1, §23 |
| A5 Credential safety vs raw retention | Precedence rule stated verbatim (D15, §7.6). Detector covers URL/query, exception text, header names/values, UTF-8, UTF-16/32, JSON escapes, base64 (3 alignments), hex, fragments ≥ `secret_fragment_min_chars`, and wire plus decoded content-encoded bodies. Uninspectable bodies are not persisted (F-11b). No redacted derivative or body hash is kept (SEC-01…05, REQ-07) | D15, §7.6, §9.3, §11.1, §15 intro/F-11/F-11b, §18 |
| A6 Transport exception boundary | r2: sanitizing boundary and TX-01. **r3:** `TransportInterrupted` removed. Ordinary `Exception`s become the sanitized `TransportResult` (never raised). `KeyboardInterrupt` and `SystemExit` keep their semantics: fresh `KeyboardInterrupt()` / `SystemExit(int code)` (non-int code → 1, text dropped) raised `from None` **after** the handler, so there is no cause or context and keyed locals are deleted. No adapter code may catch or demote them (FRZ-11). Excepthooks are flow-neutral. TX-01 proves in a subprocess that both reach top level with the correct type and code, are not swallowed, and leave stdout/stderr/logs/evidence/provenance clean | §7.7, §17, §18 TX-01/FRZ-11, §19 S0/S7, §23 |
| A7 Runtime module provenance | FRZ-09 guard at suite and runner startup: `genesis` origin/path uniqueness, per-module realpath, `SourceFileLoader`, blob SHA-1 + SHA-256 vs pinned manifest from the frozen tree, no competing `genesis` on any `sys.path` entry, `.pth` inspection, `-B` + fresh pycache prefix. Attacked with `PYTHONPATH`, `.pth`, competing package, modified module, stale `.pyc` | D16, §2.4, §4, §15 F-41, §17, §18 FRZ-09, §19 S0/S7 |
| A8 Closed schemas / additive drift | All semantic provider structures closed; inert keys declared explicitly from G2 evidence; unknown key/type gives `BLOCKED / SCHEMA_DRIFT` at a defined scope, with envelope drift rejecting the whole response without tombstones. Schema digest is part of `derivation_version` (SCH-01…04) | D17, §4, §9.2, §10.1, §11.1, §15 F-38, §16.5 AC-3, §18 |
| A9 Head reader parity | Shared predicate `admissible_head` mirrors every frozen `verify_for_pack` check, including `publisher_timestamp`/`published_at ≤ D`, contract/binding/capability-head uniqueness and `check_window`, with no fallback. The manifest builder uses the same predicate. Iff-parity test RDR-01, plus RDR-02/03 | §6.2, §6.3, §12.3, §15 F-39, §16.5 AC-5, §17, §18 |
| A10 INVALIDATED semantics | Incorrect "already past `valid_to`" justification removed. Append-only `invalidations.jsonl`; INVALIDATED head effective from its own `T3_inv`; earlier as-of unchanged; a still-current invalidated price stops being the usable head once admissible; superseded targets get no head. `verify_derivation` is defined deterministically for `derivation_kind = INVALIDATION` (INV-01…04) | D5 context, §6.2, §9.1a, §9.3, §11.2–11.5, §13.1–13.4, §15 F-40, §17, §18 |

Preserved from the hostile review, unchanged in r2:

- `adapters/` stays outside all six frozen trees, and all six tree SHAs equal the V0.4
  freeze record.
- No `src/`, `tests/`, `config/`, `tools/`, `DECISIONS/` or `v04_pack/` modification, and
  no foundation semantic change.
- No credential or network use, and no self-authored approvals.
- Successful ingestion does not authorize PAPER qualification, strategy readiness or live
  execution (D18).
- Quota cache objects referenced by historical ledger rows stay available forever, because
  replay re-resolves them (§12.2 rule 10, FR-07, F-42).
