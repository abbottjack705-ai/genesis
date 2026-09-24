# T1 checkpoint attestation

Date: 2026-09-24
Base commit: `27dd525c1fd7d531c4833c4bf7e44204a9345f19`
Scope: B1 + B2 + B3 + B7 only

The RED-before evidence, legacy-v2 authority decision, retained-fixture
reconciliations, targeted/adversarial results, retained-suite result, full-suite
result, restart/concurrency/crash result, source identities and diff review are
complete under `remediation_evidence/T1/`.

Acceptance gates:

- original hostile fixed outcomes: 4/4;
- consolidated T1: 70/70;
- retained R0–R10 and S1–S5: 196/196;
- full repository: 266/266;
- explicit restart/concurrency/crash: 36/36;
- `python -m compileall -q src tests`: exit 0;
- `git diff --check`: exit 0.

The final commit and tree IDs are necessarily generated after this evidence is
committed and are reported in the external handoff. A commit cannot contain its
own final identity without changing it.

Disposition: local T1 green only. B4/B5/B6/B8 and the independent post-S5
HOLD remain. This checkpoint grants no adapter, model, strategy,
shadow-research, protected-campaign or live-money GO.
