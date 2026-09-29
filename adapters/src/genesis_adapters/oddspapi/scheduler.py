"""PURE, deterministic window planning and conditional-refresh admission (design 14.5, 14.6 rule 4).

Every offset, cap and pool size comes from the pinned slice-1 policy; the frozen quota ceilings are passed in
by the caller from the frozen policy. The plan and every drop or shift are part of the returned value, and
the plan's digest is what a G2R record pins.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Mapping, Sequence

from genesis.repro import canonical_json, sha256_bytes
from genesis.time import iso_utc, parse_utc

from genesis_adapters.oddspapi.acquisition import boundary_guard

UTC = timezone.utc
KIND_PREKICK, KIND_MATCHDAY, KIND_INVENTORY, KIND_FIXTURES, KIND_METADATA = (
    "PREKICK", "MATCHDAY", "INVENTORY", "FIXTURES", "METADATA")
PRIORITY = {KIND_PREKICK: 1, KIND_MATCHDAY: 2, KIND_INVENTORY: 3, KIND_FIXTURES: 4, KIND_METADATA: 5}
POOL = {KIND_PREKICK: "scheduled_odds", KIND_MATCHDAY: "scheduled_odds", KIND_INVENTORY: "scheduled_odds",
        KIND_FIXTURES: "fixtures", KIND_METADATA: "metadata"}
ROLE = {KIND_PREKICK: "ODDS", KIND_MATCHDAY: "ODDS", KIND_INVENTORY: "ODDS", KIND_FIXTURES: "FIXTURES"}
META_ROLES = ("META_SPORTS", "META_TOURNAMENTS", "META_BOOKMAKERS", "META_MARKETS")
WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
CONDITIONAL_POOL = "conditional"
REFRESHABLE_CODES = frozenset({"STALE", "MISSING_OR_STALE"})


@dataclass(frozen=True)
class Kickoff:
    fixture_id: str
    start: str                                   # canonical UTC


@dataclass(frozen=True)
class QuotaUsage:
    as_of: str                                   # plan only windows at or after this instant
    monthly_used: int                            # Genesis units already debited this month
    by_pool: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Window:
    window_id: str
    kind: str
    role: str
    at: str
    pool: str
    priority: int
    fixture_ids: tuple[str, ...]


@dataclass(frozen=True)
class Change:
    window_id: str
    what: str                                    # DROPPED:<reason> | SHIFTED
    detail: str


@dataclass(frozen=True)
class MonthPlan:
    month: str
    windows: tuple[Window, ...]
    changes: tuple[Change, ...]
    digest: str


def _hhmm(text: str) -> tuple[int, int]:
    hours, minutes = text.split(":")
    return int(hours), int(minutes)


def _window(kind: str, at: datetime, fixtures: Sequence[str], role: str | None = None) -> Window:
    stamp = iso_utc(at)
    role = role or ROLE[kind]
    ident = "win:" + sha256_bytes(canonical_json({"kind": kind, "role": role, "at": stamp,
                                                  "fixtures": sorted(fixtures)}))
    return Window(ident, kind, role, stamp, POOL[kind], PRIORITY[kind], tuple(sorted(fixtures)))


def _clusters(kickoffs: Sequence[Kickoff], hours: int) -> list[list[Kickoff]]:
    ordered = sorted(kickoffs, key=lambda k: (parse_utc(k.start), k.fixture_id))
    clusters: list[list[Kickoff]] = []
    for kickoff in ordered:
        if clusters and parse_utc(kickoff.start) < parse_utc(clusters[-1][0].start) + timedelta(hours=hours):
            clusters[-1].append(kickoff)
        else:
            clusters.append([kickoff])
    return clusters


def _candidates(kickoffs: Sequence[Kickoff], policy, start: datetime, end: datetime) -> list[Window]:
    windows: list[Window] = []
    for cluster in _clusters(kickoffs, policy.schedule_cluster_hours):
        first = parse_utc(cluster[0].start)
        windows.append(_window(KIND_PREKICK, first - timedelta(minutes=policy.schedule_prekick_offset_minutes),
                               [k.fixture_id for k in cluster]))
    by_day: dict = {}
    for kickoff in kickoffs:
        by_day.setdefault(parse_utc(kickoff.start).date(), []).append(kickoff)
    for day, members in sorted(by_day.items()):
        first = min(parse_utc(k.start) for k in members)
        windows.append(_window(KIND_MATCHDAY, first - timedelta(hours=policy.schedule_matchday_offset_hours),
                               [k.fixture_id for k in members]))
    hour, minute = _hhmm(policy.schedule_inventory_utc)
    horizon = timedelta(hours=policy.schedule_inventory_horizon_hours)
    fixture_slots = {}
    for slot in policy.schedule_fixtures_days_utc:
        name, clock = slot.split(" ")
        fixture_slots.setdefault(WEEKDAYS.index(name), []).append(_hhmm(clock))
    day = start
    while day < end:
        at = day.replace(hour=hour, minute=minute)
        upcoming = [k.fixture_id for k in kickoffs if at < parse_utc(k.start) <= at + horizon]
        if upcoming:
            windows.append(_window(KIND_INVENTORY, at, upcoming))
        for fixture_hour, fixture_minute in fixture_slots.get(day.weekday(), ()):
            windows.append(_window(KIND_FIXTURES, day.replace(hour=fixture_hour, minute=fixture_minute), []))
        day += timedelta(days=1)
    for role in META_ROLES:
        windows.append(_window(KIND_METADATA, start.replace(hour=hour, minute=minute), [], role=role))
    return windows


def plan_month(kickoffs: Sequence[Kickoff], *, policy, month: str, used: QuotaUsage) -> MonthPlan:
    """The deterministic plan for ``month`` ("YYYY-MM"): guard zones avoided, caps and pools respected, drops
    taken from the lowest priority up and recorded."""

    year, number = (int(part) for part in month.split("-"))
    start = datetime(year, number, 1, tzinfo=UTC)
    end = datetime(year + (number == 12), number % 12 + 1, 1, tzinfo=UTC)
    changes: list[Change] = []
    guard = timedelta(seconds=policy.prematch_guard_seconds)
    starts = {k.fixture_id: parse_utc(k.start) for k in kickoffs}
    kept: list[Window] = []
    for window in sorted(_candidates(kickoffs, policy, start, end), key=lambda w: (w.at, w.priority, w.window_id)):
        decision = boundary_guard(window.at, policy)
        if not decision.permitted:                                   # BND-06: never inside a guard zone
            changes.append(Change(window.window_id, "SHIFTED", f"{window.at}->{decision.next_permitted}"))
            window = Window(window.window_id, window.kind, window.role, decision.next_permitted, window.pool,
                            window.priority, window.fixture_ids)
        moment = parse_utc(window.at)
        if moment < parse_utc(used.as_of) or not start <= moment < end:
            continue
        if window.fixture_ids and window.role == "ODDS" and any(
                moment >= starts[f] - guard for f in window.fixture_ids):
            changes.append(Change(window.window_id, "DROPPED:AFTER_PREMATCH_GUARD", window.at))
            continue
        kept.append(window)

    def drop(windows: list[Window], reason: str, count: int) -> list[Window]:
        victims = sorted(windows, key=lambda w: (-w.priority, w.at, w.window_id), reverse=False)[:count]
        for victim in victims:
            changes.append(Change(victim.window_id, f"DROPPED:{reason}", victim.at))
        gone = {victim.window_id for victim in victims}
        return [w for w in windows if w.window_id not in gone]

    by_day: dict = {}
    for window in kept:
        by_day.setdefault(parse_utc(window.at).date(), []).append(window)
    kept = []
    for day in sorted(by_day):
        members = by_day[day]
        excess = len(members) - policy.scheduled_daily_max
        kept += drop(members, "DAILY_CAP", excess) if excess > 0 else members
    for pool, ceiling in sorted(policy.budget_pools.items()):
        if pool == CONDITIONAL_POOL:
            continue
        members = [w for w in kept if w.pool == pool]
        excess = len(members) + used.by_pool.get(pool, 0) - ceiling
        if excess > 0:
            survivors = drop(members, "POOL_CEILING", excess)
            kept = [w for w in kept if w.pool != pool] + survivors
    total = sum(policy.budget_pools.values())
    excess = used.monthly_used + len(kept) - total
    if excess > 0:
        kept = drop(kept, "PROJECTION", excess)
    windows = tuple(sorted(kept, key=lambda w: (w.at, w.priority, w.window_id)))
    body = {"month": month, "windows": [w.__dict__ for w in windows],
            "changes": [c.__dict__ for c in changes]}
    return MonthPlan(month, windows, tuple(changes), sha256_bytes(canonical_json(body)))


# --------------------------------------------------------------------------------------
# Conditional targeted refresh (never automatic)
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class RefreshRequest:
    event_id: str
    market_id: str
    head_code: str                               # the reader's Unusable code for the head
    kickoff: str


@dataclass(frozen=True)
class SchedulerState:
    policy: object
    conditional_used_today: int
    conditional_used_month: int
    ledger_daily_used: int
    ledger_daily_cap: int                        # frozen quota policy
    ledger_normal_used: int
    ledger_normal_cap: int                       # frozen quota policy
    monthly_used: int
    remaining_scheduled: int
    circuit_open: bool


@dataclass(frozen=True)
class RefreshDecision:
    admitted: bool
    reason: str


def admit_conditional_refresh(request: RefreshRequest, *, state: SchedulerState, now: str) -> RefreshDecision:
    """Admit only when EVERY design 14.5 condition holds; otherwise the first failing one is the reason."""

    policy = state.policy
    lead = parse_utc(request.kickoff) - timedelta(seconds=policy.prematch_guard_seconds) - parse_utc(now)
    checks = (
        (request.head_code in REFRESHABLE_CODES, "HEAD_NOT_STALE_OR_MISSING"),
        (lead >= timedelta(seconds=policy.conditional_refresh_min_lead_seconds), "TOO_CLOSE_TO_KICKOFF"),
        (state.conditional_used_today < policy.conditional_daily_max, "CONDITIONAL_DAILY_CAP"),
        (state.conditional_used_month < policy.budget_pools[CONDITIONAL_POOL], "CONDITIONAL_POOL_EXHAUSTED"),
        (state.ledger_daily_used < state.ledger_daily_cap and state.ledger_normal_used < state.ledger_normal_cap,
         "FROZEN_LEDGER_WOULD_BLOCK"),
        (state.monthly_used + 1 + state.remaining_scheduled <= sum(policy.budget_pools.values()),
         "PROJECTION_WOULD_BREAK"),
        (not state.circuit_open, "CIRCUIT_OPEN"),
        (boundary_guard(now, policy).permitted, "WINDOW_BOUNDARY_GUARD"),
    )
    for ok, reason in checks:
        if not ok:
            return RefreshDecision(False, reason)
    return RefreshDecision(True, "ADMITTED")
