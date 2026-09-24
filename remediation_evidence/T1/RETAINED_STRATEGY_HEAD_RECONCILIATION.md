# Retained strategy-head fixture reconciliation

Date: 2026-09-24

Retained test:
`tests.test_registry_and_selection.RegistryAndSelectionTests.test_attempt_budget_is_consumed_and_strategy_is_pass_first`.

Original blob before adaptation:
`997b065283152852f645c6b7f7c16223305c7aee`.

Original invariant: reopening the append-only strategy registry after a valid
IDEA → EXPLORATION transition must replay the current lifecycle as
`StrategyLifecycle.EXPLORATION`.

The retained test accessed the former private in-memory cache `_latest`. T1/B7
intentionally removed that cache because action authority must come from a
fresh verified durable head, not a stale instance field. The production public
API `current_head("s", "v1")` performs that exact replay.

Only the lookup expression changed. The expected value and assertion strength
are unchanged. No lifecycle, policy, identity or terminal-release semantics
changed.

Pre-adaptation retained command/result:

```text
python -m unittest <retained R0-R10/S1-S5 modules> -q
Ran 196 tests in 188.674s
FAILED (errors=1)

AttributeError: 'StrategyRegistry' object has no attribute '_latest'
```

This is a fixture/interface adaptation, not a green exception; the full
retained command must be rerun.
