# Genesis v0.4 Implementation Pack — START HERE

This pack consolidates:

- Project Genesis v0.3;
- the Gemini decision-science review;
- the Perplexity external-verification/API/data review;
- the Grok operational-failure review;
- the DeepSeek review using the Nemotron statistical-red-team prompt;
- the Qwen 3.8 Max software-architecture review;
- the user's subsequent objective, odds, volume, budget, staking, exposure and cloud-runtime clarifications;
- the Sol reconciliation decisions made in this conversation.

## Files

1. `01_PROJECT_GENESIS_v0.4.md` — authoritative full blueprint.
2. `02_AUDIT_RECONCILIATION_v0.4.md` — what was accepted/modified/rejected and why.
3. `03_PROJECT_LAWS_v0.4.md` — short-form fixed intent/invariants.
4. `04_CHANGELOG_v0.3_TO_v0.4.md` — material changes from v0.3.
5. `05_DECISION_AND_RISK_POLICY_v0.4.md` — concise bet/price/staking/risk rules.
6. `06_RUNTIME_AND_COST_TARGET_v0.4.md` — autonomous cloud + API budget target.
7. `07_RISK_POLICY_DRAFT.yaml` — machine-readable starting policy (NOT live-approved).
8. `08_ODDSPAPI_BUDGET_DRAFT.yaml` — machine-readable call-budget target.
9. `09_V0.4_ACCEPTANCE_CHECKLIST.md` — foundation acceptance checklist.
10. `10_LUNA_GAP_ANALYSIS_PROMPT.md` — **use this first with Luna**.
11. `11_LUNA_IMPLEMENTATION_PROMPT_AFTER_GAP.md` — use only after reviewing the gap analysis.
12. `12_ASTRA_FINAL_AUDIT_PROMPT.md` — use when Astra is available again.

## What to do now

### Step 1

Put files 1–9 in the root of the fresh Genesis repository. Rename if desired to remove numeric prefixes, but preserve content/version.

Recommended repository names:

```text
PROJECT_GENESIS_v0.4.md
PROJECT_LAWS_v0.4.md
AUDIT_RECONCILIATION_v0.4.md
CHANGELOG_v0.3_TO_v0.4.md
DECISION_AND_RISK_POLICY_v0.4.md
RUNTIME_AND_COST_TARGET_v0.4.md
RISK_POLICY_DRAFT.yaml
ODDSPAPI_BUDGET_DRAFT.yaml
V0.4_ACCEPTANCE_CHECKLIST.md
```

### Step 2

Start a Luna/Codex task using **only** `10_LUNA_GAP_ANALYSIS_PROMPT.md` as the opening instruction.

Do not tell Luna to implement everything immediately.

The first goal is a trustworthy `V03_TO_V04_GAP_ANALYSIS.md` and `V04_MIGRATION_PLAN.md`.

### Step 3

Review that gap analysis. Bring it back to Sol if you want an independent check before spending more Reserve/Work usage.

### Step 4

Once the migration plan is accepted, use `11_LUNA_IMPLEMENTATION_PROMPT_AFTER_GAP.md`.

### Step 5

When Astra-6 High is available again, give it the authoritative v0.4 files **plus the actual repository state/test evidence**, then use `12_ASTRA_FINAL_AUDIT_PROMPT.md`.

## Important

Do not give Luna five competing auditor reports and ask it to decide which philosophy wins. The reconciliation has already been done here. The v0.4 blueprint is the authoritative synthesis.

The raw audits remain useful evidence, but implementation should follow v0.4 unless a new independent audit identifies a concrete material defect.
