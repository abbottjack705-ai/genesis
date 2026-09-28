# adapters/ — Genesis V0.5 slice-1 (OddsPapi, read-only, fixture/offline)

Authority: `V05_ADAPTER_ARCHITECTURE.md` (revision r3) at the repository root. That document
is binding; this directory implements its Stages S0–S7 against deterministic fixtures.

**Nothing here contacts the network, stores a credential, or records an approval.** The
gates G0, G1, G2, G2R and G3 (design section 16) are human actions and are not performed by
any code or test in this tree. Successful ingestion, even at READY, does not authorize PAPER
qualification, strategy readiness or live execution.

## Layout

| Path | Contents |
| --- | --- |
| `src/genesis_adapters/` | production package (sits beside, never inside, the frozen `src/genesis`) |
| `adapter_tests/` | test package (`FixedClock`, `FakeTransport` and other test doubles live only here) |
| `config/` | pinned adapter configuration, policy, maps, closed schemas, frozen-module manifest |
| `evidence/S0 … S7/` | RED/GREEN transcripts, hashes and the final `S7/SUMMARY.md` |
| `DECISIONS/` | reserved for human approval records — **empty on purpose** |

The six frozen trees (`src`, `tests`, `config`, `tools`, `DECISIONS`, `v04_pack`) are never
edited; their tree SHAs must be unchanged at every commit (see "Freeze check").

## Run commands (from the repository root)

The runtime module-provenance guard (design section 2.4) requires isolated bytecode, so the
adapter suite must run with `-B` and a fresh `PYTHONPYCACHEPREFIX`:

```text
# bash
PYTHONPYCACHEPREFIX="$(mktemp -d)" python -B -m unittest discover -s adapters/adapter_tests -t adapters -v

# PowerShell
$env:PYTHONPYCACHEPREFIX = (New-Item -ItemType Directory -Path (Join-Path $env:TEMP ([guid]::NewGuid()))).FullName
python -B -m unittest discover -s adapters/adapter_tests -t adapters -v
```

Frozen suite (unchanged command, unchanged meaning; ~10 minutes):

```text
python -m unittest discover -s tests -t . -v
```

Static checks:

```text
python -m compileall -q src tests adapters/src adapters/adapter_tests
git diff --check
```

## Freeze check

```text
for t in src tests config tools DECISIONS v04_pack; do git rev-parse HEAD:$t; done
git diff --name-status v0.4-foundation-freeze HEAD -- src tests config tools DECISIONS v04_pack   # must print nothing
```

Expected tree SHAs: `src 51cb635b…`, `tests e90b2981…`, `config abd22db0…`, `tools a0e3411e…`,
`DECISIONS cc97ec6f…`, `v04_pack 3c3c1c27…` (full values in `V05_ADAPTER_ARCHITECTURE.md` section 2.1).

Line endings: `adapters/.gitattributes` stores `adapter_tests/fixtures/**` and `config/**` without
end-of-line conversion so pinned digests hold on every checkout.
