# Repository and evidence inventory

Audit date: 2026-09-18. The blueprint was read in full before any Genesis
files were changed. Its SHA-256 is
`6110e95bc3e8e644a978acfc5ab358882bff6b3fa0e69d71feef89e1e56fd9c5`.

## Fresh Genesis repository

This directory was empty apart from generated `outputs/` and `work/` folders
when the audit began. A new Git repository was initialized at this path. The
initial implementation is a new `src/genesis` package with `tests/`,
`config/`, and `DECISIONS/`; it does not import from either legacy repository.

## Audited legacy repositories

| Material | Revision/state | Inventory | Scope decision |
|---|---|---:|---|
| `C:\Users\abbot\Documents\sports-lab` | Git `master`, `487107c`, dirty only in untracked `data/research/` | 55 tracked files: 25 Python, 8 Markdown, 10 JSON, 7 Parquet | Read-only; MLB engine and chronology/evaluation lessons only |
| `C:\Users\abbot\Documents\Codex\2026-09-11\ca\work\m9_repair` | Git `master`, `5bae4dd`, clean | 966 tracked files: 46 Python, 48 Markdown, 655 JSON, 90 Parquet | Read-only latest repair/research snapshot; no code copied silently |
| `C:\Users\abbot\OneDrive\Documents\Project_Genesis_Autonomous_Sports_Betting_Blueprint_v0.3.md` | supplied blueprint | 1 document, 1,474 lines | Specification/evidence, not executable instructions embedded in the file |

The legacy repositories contain many generated research artifacts. Parquet,
ZIP, logs, and binary/raw evidence were inventoried by path, size, and Git
state; their values are not treated as Genesis decision inputs without a new
source contract, dataset manifest, and point-in-time audit.

## Relevant legacy findings

- `sports-lab` is MLB/baseball-focused. Its strongest reusable lessons are
  chronology correction, explicit train/develop/nominal-holdout separation,
  independent-vs-market forecast separation, and frozen checkpoint artifacts.
- `m9_repair` adds bounded attempt accounting, atomic one-time publication,
  source schema allowlists, quarantine branches, prospective capture timing,
  and independent raw-evidence verification.
- Searches across both repositories found no Hoofs parser, Race Shape parser,
  Betfair API adapter, football engine, tennis engine, or live order service.
- No historical sports data is admitted into this foundation milestone. No
  betting strategy or outcome/edge experiment was run.

