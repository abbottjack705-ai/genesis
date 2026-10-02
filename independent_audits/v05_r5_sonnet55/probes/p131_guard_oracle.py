"""AREA B: independent oracle for the W1..W4 UTC boundary guard over edges and random times, several policies."""
from boot import *
import random, types
from datetime import datetime, timedelta, timezone
from genesis_adapters.oddspapi.acquisition import boundary_guard
from genesis.time import iso_utc
U = timezone.utc
def oracle(tq: datetime, timeout_s: int, skew_s: int) -> bool:
    us = lambda d: int((d - datetime(1970, 1, 1, tzinfo=U)) / timedelta(microseconds=1))
    t = us(tq); T = timeout_s * 10**6; S = skew_s * 10**6
    ds = datetime(tq.year, tq.month, tq.day, tzinfo=U); nd = ds + timedelta(days=1)
    ms = datetime(tq.year, tq.month, 1, tzinfo=U)
    nm = datetime(tq.year + (tq.month == 12), tq.month % 12 + 1, 1, tzinfo=U)
    return (t + T + S < us(nd)) and (t + T + S < us(nm)) and (t - S >= us(ds)) and (t - S >= us(ms))
rng = random.Random(1)
bad = 0; total = 0
edges = []
for (y, m, d) in [(2026, 10, 3), (2026, 10, 31), (2028, 2, 28), (2028, 2, 29), (2027, 2, 28), (2026, 12, 31), (2026, 4, 30), (2026, 1, 1)]:
    day_end = datetime(y, m, d, tzinfo=U) + timedelta(days=1)
    edges += [day_end, datetime(y, m, d, tzinfo=U)]
for timeout_s, skew_s in ((60, 120), (1, 1), (0 + 30, 0 + 5), (300, 600), (1799, 900 - 1)):
    pol = types.SimpleNamespace(request_timeout_seconds=timeout_s, clock_skew_max_seconds=skew_s)
    pts = []
    for e in edges:
        for k in (-timeout_s - skew_s, -timeout_s, -skew_s, 0, skew_s):
            for dm in (-1, 0, 1):
                pts.append(e + timedelta(seconds=k, microseconds=dm))
    pts += [datetime(2026, 1, 1, tzinfo=U) + timedelta(microseconds=rng.randrange(0, 365 * 3 * 86400 * 10**6)) for _ in range(4000)]
    for tq in pts:
        total += 1
        got = boundary_guard(iso_utc(tq), pol).permitted
        if got != oracle(tq, timeout_s, skew_s):
            bad += 1
            if bad <= 3: print("MISMATCH", iso_utc(tq), (timeout_s, skew_s), "impl", got)
print("checked", total, "mismatches", bad)
