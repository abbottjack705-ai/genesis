# Project Genesis V0.4 foundation

This is a fresh repository for the foundational implementation of Project
Genesis, the research-backed, PASS-first sports-betting system described by
the V0.4 blueprint.

The current milestone is deliberately non-strategic and offline/paper-only. It
provides durable evidence, provenance, controlled point-in-time access,
versioned policy, frozen evidence packs, decision identity, candidate/gate
retention, protected-evaluation interfaces, risk, paper order, settlement,
quota, logging, and accounting contracts. There is no market-data downloader,
bookmaker browser automation, Betfair client, provider-specific adapter, live
order placement, profitable-strategy search, or outcome experiment.

Run the deterministic test suite from the repository root:

```text
python -m unittest discover -s tests -t . -v
```

The repository uses a `src/` layout and a stdlib-only runtime so the first
contracts do not depend on an unpinned analytics stack. Later sport adapters
must enter through the contracts documented in `ARCHITECTURE.md`.
