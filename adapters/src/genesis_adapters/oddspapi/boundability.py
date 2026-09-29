"""Table-driven boundability evaluator (design section 20.1; a G1 human-check aid, BILL-05).

Decides whether real provider terms can be safely bounded by the frozen quota authority
(daily cap x UTC days, monthly ceiling x UTC months), in two modes:

* ``GUARDED``  - counting over the provider window ``W`` itself (valid because the section 14.6
  boundary guard keeps every receipt in its debit's UTC day and month);
* ``FALLBACK`` - counting over the backwards- and forwards-extended window ``W+`` built from
  ``request_timeout_seconds`` and ``clock_skew_max_seconds`` (if the guard is ever relaxed).

The evaluator never contacts a provider and never edits any authority.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import timedelta

DAY = timedelta(days=1)
_YEAR = 2027                       # any non-leap year: only the month-length range is used
LONGEST_MONTH = max(calendar.monthrange(_YEAR, month)[1] for month in range(1, 13))
SHORTEST_MONTH = min(calendar.monthrange(_YEAR, month)[1] for month in range(1, 13))
KINDS = ("UTC_DAY", "NON_ALIGNED_DAY", "UTC_MONTH", "NON_UTC_MONTH", "ROLLING_DAYS")
MODES = ("GUARDED", "FALLBACK")
METERINGS = ("PER_REQUEST", "FIXED_WEIGHT", "NON_METERED", "VARIABLE", "UNKNOWN")


@dataclass(frozen=True)
class ProviderWindow:
    kind: str
    limit: int
    length_days: int | None = None


@dataclass(frozen=True)
class RoleTerms:
    role: str
    metering: str
    weight: int | None
    genesis_debit_units: int
    windows: tuple[ProviderWindow, ...]


@dataclass(frozen=True)
class WindowRow:
    kind: str
    limit: int
    days: int
    months: int
    genesis_max: int
    ok: bool
    note: str


@dataclass(frozen=True)
class BoundabilityResult:
    mode: str
    b2_ok: bool
    rows: tuple[WindowRow, ...]
    passes: bool


def _unaligned_days(length: timedelta) -> int:
    """UTC days an interval of ``length`` can touch at worst-case alignment."""

    whole, remainder = divmod(length, DAY)
    return whole + (1 if remainder == timedelta(0) else 2)


def _unaligned_months(length: timedelta) -> int:
    return -(-length // timedelta(days=SHORTEST_MONTH)) + 1


def _geometry(window: ProviderWindow, *, extend_before: timedelta, extend_after: timedelta) -> tuple[int, int]:
    """(UTC days, UTC months) the window can overlap; extensions are zero in GUARDED mode."""

    extended = extend_before > timedelta(0) or extend_after > timedelta(0)
    padding = (extend_before > timedelta(0)) + (extend_after > timedelta(0))
    if window.kind == "UTC_DAY":
        return (1 + padding, 1 + (1 if extended else 0))
    if window.kind == "UTC_MONTH":
        return (LONGEST_MONTH + padding, 1 + padding)
    if window.kind == "NON_ALIGNED_DAY":
        length = DAY
    elif window.kind == "NON_UTC_MONTH":
        length = timedelta(days=LONGEST_MONTH)
    else:
        length = timedelta(days=window.length_days)
    length = length + extend_before + extend_after
    return (_unaligned_days(length), _unaligned_months(length))


def evaluate_boundability(terms: RoleTerms, *, slice_policy, quota_policy, mode: str) -> BoundabilityResult:
    """B1 (window bound) and B2 (pre-send cost bound) for one role's provider terms."""

    if mode not in MODES:
        raise ValueError("mode must be GUARDED or FALLBACK")
    if not terms.windows:
        raise ValueError("at least one provider window is required")
    if terms.metering not in METERINGS:
        raise ValueError("unknown metering")
    daily_cap = quota_policy.daily_billable_budget
    monthly_ceiling = quota_policy.genesis_monthly_limit           # normal + reserve (reserve is spendable)
    if mode == "FALLBACK":
        before = timedelta(seconds=slice_policy.request_timeout_seconds + slice_policy.clock_skew_max_seconds)
        after = timedelta(seconds=slice_policy.clock_skew_max_seconds)
    else:
        before = after = timedelta(0)

    rows = []
    for window in terms.windows:
        if window.kind not in KINDS:
            raise ValueError("unknown window kind")
        if type(window.limit) is not int or window.limit < 1:
            raise ValueError("window limit must be a positive integer")
        if window.kind == "ROLLING_DAYS" and (type(window.length_days) is not int or window.length_days < 1):
            raise ValueError("a rolling window needs a positive length_days")
        days, months = _geometry(window, extend_before=before, extend_after=after)
        genesis_max = min(daily_cap * days, monthly_ceiling * months)
        formula_ok = genesis_max <= window.limit
        # The design names a provider UTC-calendar-month allowance below the Genesis ceiling as a
        # reopen example even though B1 alone would give min(cap x days, ceiling): the stricter
        # reading is enforced (a false "reopen" is safe; a false "pass" is not).
        example_ok = not (window.kind == "UTC_MONTH" and window.limit < monthly_ceiling)
        notes = [f"B1 min({daily_cap}*{days}, {monthly_ceiling}*{months}) = {genesis_max} vs limit {window.limit}"]
        if not example_ok:
            notes.append("UTC calendar-month allowance is below the Genesis monthly ceiling")
        rows.append(WindowRow(window.kind, window.limit, days, months, genesis_max,
                              formula_ok and example_ok, "; ".join(notes)))

    if terms.metering == "PER_REQUEST":
        b2_ok = terms.weight == 1 and terms.genesis_debit_units >= 1
    elif terms.metering == "FIXED_WEIGHT":
        b2_ok = type(terms.weight) is int and terms.weight >= 1 and terms.genesis_debit_units >= terms.weight
    elif terms.metering == "NON_METERED":
        b2_ok = terms.weight == 0 and terms.genesis_debit_units >= 1
    else:
        b2_ok = False
    return BoundabilityResult(mode, b2_ok, tuple(rows), b2_ok and all(row.ok for row in rows))
