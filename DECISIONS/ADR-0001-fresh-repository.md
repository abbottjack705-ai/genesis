# ADR-0001: Genesis starts in a fresh repository

Status: accepted

The supplied `sports-lab` and `m9_repair` material is legacy MLB/sports-engine
work, not the authoritative V0.3 repository. Genesis therefore starts in a
fresh repository with new contracts. Legacy behavior may be selectively
reimplemented only after it is mapped to the V0.3 data, provenance, and
point-in-time rules and covered by new tests.

Consequences: there is no accidental inheritance of V2/V3/V4 assumptions;
some useful utilities will be duplicated deliberately; and a later adapter
must document every import or port rather than relying on implicit coupling.

