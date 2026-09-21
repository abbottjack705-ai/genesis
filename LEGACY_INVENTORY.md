# Legacy inventory and reuse decisions

Audit date: 2026-09-18. Legacy repositories were read-only throughout. No
legacy file is imported by the Genesis package.

| Source path | Original purpose | Reusable? | Risks / assumptions | Genesis disposition |
|---|---|---|---|---|
| `C:\Users\abbot\Documents\sports-lab\chronology.py` | MLB schedule chronology, suspended-game handling, conservative history eligibility | Yes, design pattern only | MLB schedule fields; saved dates are not verified publication times | Reimplemented generically in `genesis.time`/`labels`; rewrite per sport later |
| `C:\Users\abbot\Documents\sports-lab\checkpoint.py` | Resumable stage/partition checkpointing and output digests | Yes, design pattern | Mutable single-project `STATE.json`; short digest in some paths; not a content-addressed evidence store | Do not copy yet; replace with append-only registries and full SHA-256 evidence |
| `C:\Users\abbot\Documents\sports-lab\rates.py`, `m7_sim.py` | MLB as-of team/player rates and simulation inputs | No as Genesis common code | MLB-only fields, sport assumptions, historical source availability rules | Reject for common core; future MLB adapter must revalidate from source contracts |
| `C:\Users\abbot\Documents\sports-lab\score.py`, `m9_diagnostics.py` | Chronological evaluation, Brier/calibration diagnostics, independent/market separation | Yes, methods only | MLB run-line target, existing holdout already consumed, no betting settlement | Rewrite as sport-neutral evaluation module after audit; no code copied now |
| `C:\Users\abbot\Documents\sports-lab\SIM.py` | MLB Monte Carlo scoring and market probabilities | Not yet | Hard-coded baseball assumptions and no Genesis market contract | Reject for V0.3 foundation |
| `C:\Users\abbot\Documents\sports-lab\baseball_v2_engine.py` | MLB V2 Monte Carlo market engine | No for common core | Explicit comments say inputs are not reliable; hard-coded model constants | Reject; no strategy or model reuse |
| `C:\Users\abbot\Documents\sports-lab\baseball_v2_players.py` | MLB player-layer simulation and derived markets | No for common core | Baseball-specific player/event semantics; no source provenance boundary | Reject; revisit only as isolated MLB research adapter |
| `C:\Users\abbot\Documents\sports-lab\odds_parse.py`, `join.py` | Parse bookmaker odds and join to MLB schedules | Limited | Bookmaker-specific `bet365`, retrospective data, no Betfair exchange semantics | Reimplement as a future source adapter with `MarketSnapshot` and availability contracts |
| `C:\Users\abbot\Documents\sports-lab\pregame_probables.py`, `gamelogs.py`, `schedules.py` | MLB source acquisition and pregame data | Limited | External source timing and MLB schema; credentials/network assumptions | Do not copy; future MLB adapter must capture raw bytes and source timestamps first |
| `C:\Users\abbot\Documents\sports-lab\test_m7_chronology.py`, `test_score.py`, `test_m9_diagnostics.py` | Synthetic chronology, split, leakage, and reproducibility tests | Yes, strongest reuse | Tests are coupled to MLB rows and legacy module names | Port test ideas into new Genesis tests; no direct imports |
| `C:\Users\abbot\Documents\Codex\2026-09-11\ca\work\m9_repair\m19_archive_pilot.py` | Bounded archived source pilot with immutable attempts and quarantine | Yes, design and selected utility ideas | MLB API fields, retrospective archive semantics, live endpoint assumptions | Reimplemented as generic `EvidenceStore`, provenance, coverage, and future capture contracts |
| `...\m20_source_contract.py` | Fixed source field/schema contract pilot | Yes, design | Source-specific allowlists and no general manifest model | Rewrite per source; use allowlist/quarantine pattern |
| `...\m21_recorder.py` | Offline synthetic prospective recorder with fake clock/transport | Yes, testing pattern | Synthetic-only; no production isolation; MLB identity fields | Port fake-clock and fail-closed tests later; do not copy code |
| `...\m21_scenarios.py`, `test_m21_recorder.py` | Adversarial recorder scenario suite | Yes, test ideas | MLB-specific forbidden paths and capture semantics | Port to each future adapter; current foundation covers generic future-input adversaries |
| `...\m19_archive_pilot.py:put_once` | Atomic no-overwrite publication | Yes | File-backed and single-host | Reimplemented in `genesis.repro.immutable_write` and tested |
| `...\m19_archive_pilot.py:sha`, `artifact` | SHA-256 evidence and artifact tamper checks | Yes | Legacy used path-local artifact inventories | Reimplemented with full hashes and hash-chained manifests |
| `...\checkpoint.py:Run` | Mark/remaining/done attempt accounting | Yes, behavior | Mutable marks can be stale; not sufficient for adaptive experiment custody | Replaced by append-only experiment registry with non-refundable attempts |
| `C:\Users\abbot\OneDrive\Documents\Autonomous_Exchange_Edge_Lab_Project_Genesis_v0.1.docx` | Older Genesis/edge-lab reference document | Reference only | Older objective may conflict with V0.3; not authoritative | Do not import assumptions; V0.3 blueprint and current contracts govern |
| Hoofs / Race Shape / Betfair implementation | Requested legacy areas | Not found | No supplied source, semantics, or verified availability | Record unavailable; build no placeholder parser or adapter |

The legacy component list is intentionally conservative. “Reusable” means a
testable engineering idea, not permission to copy code or carry forward a
model, sport, timestamp, or betting assumption.

