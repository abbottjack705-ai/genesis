from boot import *
import random
from genesis_adapters.oddspapi.raw_capture import parse_http_date
from email.utils import format_datetime
from datetime import datetime, timezone
rng = random.Random(3)
esc = {}
cands = ["Mon, 01 Jan 99999999999 00:00:00 GMT", "Mon, 01 Jan 0000 00:00:00 GMT", "Thu, 99 Oct 2026 25:61:61 GMT", "", " ", "\x00", "Wed, 21 Oct 2026 07:28:00 +9999", "Wed, 21 Oct 2026 07:28:00 -0000",
         "Wed, 21 Oct 2026 07:28:00 UT", "Wed, 21 Oct 2026 07:28:00 PST", "21 Oct 2026", "Wed, 21 Oct 26 07:28:00 GMT", "Wed, 21 Oct 2026 07:28:60 GMT", "Wed, 21 Oct 2026 07:28:00.123 GMT",
         "Wed, 21 Oct 2026 24:00:00 GMT", "Wed, 21 Oct 9999 23:59:59 GMT", "Fri, 31 Dec 9999 23:59:59 -2359", "Mon, 01 Jan 0001 00:00:00 +0100", "\ud800", "é"*50, "9"*5000]
for _ in range(20000):
    s = "".join(rng.choice("0123456789 :,-+ABCDEFGMTUWonThuFriSat\x00\ud800é") for _ in range(rng.randrange(1, 40)))
    cands.append(s)
for s in cands:
    try: parse_http_date(s)
    except BaseException as e: esc.setdefault(type(e).__name__, s[:60])
print("parse_http_date escapes:", esc or "none")
