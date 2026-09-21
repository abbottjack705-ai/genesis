# Migration, compatibility, scope and residual risks

## Compatibility decisions

- JSONL is authoritative. SQLite sidecars serialize cross-process operations and
  contain no domain records used as business truth.
- Existing valid legacy JSONL rows remain in their original order/hash chain and
  may be extended without rewriting them.
- Legacy evidence metadata imports as a deterministic single observation only
  when the exact raw artifact and source contract can be verified.
- Legacy evidence packs without structured identity are replayable for audit but
  cannot authorize qualification.
- Legacy candidate decisions lacking full V2 identity cannot qualify.
- Legacy risk approvals/orders missing exact V2 binding fields do not become
  active authority.
- A legacy settlement history migrates only when it has one unambiguous initial
  head and at most one valid direct correction. Duplicate-unlinked or deeper
  ambiguous history fails closed.
- Legacy quota fields require an explicitly named A or B interpretation; values
  are never used to guess operator intent.
- Unsupported or incomplete active risk/order event schemas fail closed.
- Registered V2 protected campaigns cannot use the legacy in-process evaluator.

No migration infers a missing tier, observation time, evidence identity,
candidate survivor, settlement winner, quota interpretation or order intent.

## Scope attestation

The Git history from the audited baseline through R10 adds only generic
foundation enforcement, tests, configuration and audit evidence. It adds no:

- sport/source/venue adapter or data acquisition;
- strategy/model search, strategy card or outcome backtest;
- external provider/API/network call;
- credential, browser automation or exchange client;
- dashboard/PWA;
- cloud/VPS deployment or monitoring service;
- live order placement or LLM execution override;
- future chaos-certification system;
- £100 canary.

No real protected campaign, sporting outcome experiment or profitability test was
run. The Genesis objective, odds bands, non-quota daily aims, breadth-before-
leniency law, `1u = 2.5%`, <=3u single-bet law, no daily-turnover-cap law,
approximately 60% open-liability ceiling, and outcome-hold policy were preserved.

## Residual external facts and risks

1. **Independent review:** no independent post-build hostile audit is claimed by
   this implementation task. This is the only remaining R10 acceptance item.
2. **Provider terms:** the assumed 250-call OddsPapi ceiling and its exact current
   commercial/technical semantics were not externally verified. No provider is
   connected.
3. **Protected deployment:** the evaluator is a local spawned-process contract,
   not a separately administered label vault/service. Real activation is disabled.
4. **Source facts:** availability, entitlement, revision/ready-time semantics and
   historical completeness for any real source remain unknown.
5. **Sport semantics:** no real sport, market, selection, correlation or settlement
   rules have been authorized or implemented.
6. **Statistical evidence:** there is no real calibration, selected-set performance,
   profitability, edge, robustness or prospective evidence.
7. **Operations:** cloud runtime, cost, monitoring, secret isolation and failure
   recovery for an eventual deployed system remain unselected and untested.
8. **Venue reconciliation:** generic PAPER UNKNOWN/reconciliation contracts exist,
   but no venue-specific reconciliation or official fill feed exists.
9. **Risk calibration:** starting hard laws are enforced, but future empirical
   cluster caps and bankroll drawdown triggers remain separate approval work.
10. **Adapter choice:** the first read-only adapter is not selected or authorized.

These limitations do not justify weakening a foundation invariant. They keep the
project NO-GO for adapter work until independent audit and explicit approval.
