# Genesis v0.4 — Runtime, Data Budget and Cost Target

## End-state operating model

Genesis runs as scheduled/event-driven cloud software. The user's laptop may be off.

Luna/Codex is used to build, audit, repair and improve Genesis. It is not the always-on betting runtime.

## Pre-profit budget

Target:

```text
fixed infrastructure + routine data <= £10/month
```

Any paid dependency outside that budget requires explicit user approval.

Do not assume the user will buy a large one-off live API credential.

## OddsPapi planning budget

Design around one legitimate free allowance:

```text
<= 7 billable current-data calls/day
<= 220 calls/month planning target
>= 30 monthly calls held in reserve
```

Use:

- batched multi-event/tournament queries;
- cached static metadata;
- regional/time-zone execution windows;
- targeted refreshes only where needed;
- a quota ledger with hard fail-safe.

Do not design around rotating accounts/keys to evade provider quotas.

## Time-zone scheduling concept

```text
EARLY MORNING: Asian events
MORNING: global slate/inventory
MIDDAY/AFTERNOON: UK + Europe
EVENING: late Europe
NIGHT: North American sports
```

Capital can be reused as earlier positions settle. There is no daily turnover limit; only current open liability and correlation limits.

## Cloud components

Provider-neutral V1 target:

- scheduler;
- stateless workers/jobs;
- small durable relational store;
- immutable object/file store;
- cache;
- lightweight dashboard/API;
- monitoring/alerts.

Prefer free/serverless tiers while paper/shadow operation remains within their limits.

## Execution

Use a venue-neutral interface.

Before MICRO_LIVE:

1. identify officially supported venue(s);
2. verify current access/cost/API terms;
3. choose a venue inside the actual user budget;
4. keep broker credentials only in isolated execution runtime;
5. do not enable live because a provider happens to be easy to automate unofficially.
