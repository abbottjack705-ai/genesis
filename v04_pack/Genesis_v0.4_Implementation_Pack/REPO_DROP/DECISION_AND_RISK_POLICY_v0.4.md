# Genesis v0.4 — Decision, Staking and Risk Policy

This file is a concise implementation companion to the full blueprint.

## Qualification order

```text
SUPPORTED SPORT / MARKET / SOURCE
        |
        v
POINT-IN-TIME + FROZEN EVIDENCE PACK
        |
        v
MODEL IN SUPPORT + CALIBRATION VALID
        |
        v
CRITICAL EVIDENCE COMPLETE / FRESH
        |
        v
NO CRITICAL CONTRADICTION
        |
        v
ODDS PROFILE PASS
        |
        v
PRICE SANITY PASS
        |
        v
UNCERTAINTY / STABILITY PASS
        |
        v
PORTFOLIO / CORRELATION / RISK PASS
        |
        v
QUALIFIED
```

Ranking occurs only after qualification.

## Price sanity

```text
price_sanity_margin = model_probability - commission_adjusted_break_even_probability
```

Initial normal-profile classification:

```text
>= 0.00            NORMAL_PASS
[-0.02, 0.00)      NEAR_FAIR_TOLERANCE
< -0.02            FAIL
```

A tolerance-zone candidate requires strong evidence/model status and may not carry another soft concern.

Exceptional short-price bets (1.40–1.49) require non-negative margin.

## Odds

```text
NORMAL: 1.50–3.00
EXCEPTIONAL_SHORT: 1.40–1.49
BELOW_1.40: standard PASS
ABOVE_3.00: separate future strategy profile
```

## Stakes

```text
1u = 2.5% bankroll
supported tiers = 1u, 1.5u, 2u, 2.5u, 3u
3u = hard initial per-bet maximum
```

Each strategy card defines exact deterministic tier conditions.

## Portfolio

```text
no cumulative daily turnover cap
hard open-liability target ~= 60% bankroll
correlated cluster target ~= 10–12.5% bankroll, pending simulation
```

Matched, partially matched, still-matchable unmatched, pending and UNKNOWN exposure count appropriately.

## Daily search aims

```text
Mon–Thu: 2–5
Friday: 4–10
Saturday: 7–13
Sunday: 4–10
```

These never alter thresholds.

## Candidate expiration / recertification

Before order submission:

- candidate not expired;
- critical volatile evidence refreshed;
- market still open;
- executable odds still eligible;
- liquidity/size okay;
- risk/correlation still okay;
- strategy active;
- no kill condition;
- no duplicate or UNKNOWN prior order.

Material new evidence creates a new candidate version; it does not mutate the old one.
