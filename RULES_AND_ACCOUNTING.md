# Rules and accounting

The foundation uses decimal odds `o > 1` and implied probability `1/o`.

- Back win P&L: `stake * (odds - 1)`, less commission on positive gross win.
- Back loss P&L: `-stake`.
- Lay win (selection wins) P&L: `-stake * (odds - 1)`.
- Lay loss (selection loses) P&L: `stake`, less commission on positive win.
- Void/non-runner: zero P&L and returned stake for a back.
- Dead heat: the back profit is multiplied by the declared winner fraction;
  lay dead heat is rejected until a venue-specific rule is supplied.
- Partial fills are represented as separate matched fragments; unmatched
  stake is not settled.

Money is quantized to two decimal places with `ROUND_HALF_UP` only at the
settlement boundary. The rules are arithmetic primitives, not proof of a
strategy or a venue's complete rules.

