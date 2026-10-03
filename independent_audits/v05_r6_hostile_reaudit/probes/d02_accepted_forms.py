"""D02: which Date forms does parse_http_date accept as an aware UTC instant (informational: lenient parsing)."""
import sys, os
sys.path.insert(0, sys.argv[1] + "/adapters"); os.chdir(sys.argv[1])
import adapter_tests  # noqa: provenance guard + network hook
from genesis_adapters.oddspapi.raw_capture import parse_http_date
GOOD = "Thu, 01 Oct 2026 12:00:30 GMT"
CORPUS = [
    "Mon, 01 Jan 99999999999 00:00:00 GMT", "Mon, 01 Jan 9999999999999999999999999 00:00:00 GMT",
    "Fri, 31 Dec 9999 23:59:59 GMT", "Sat, 01 Jan 10000 00:00:00 GMT", "Mon, 01 Jan 0001 00:00:00 GMT",
    "Mon, 01 Jan 0000 00:00:00 GMT", "Mon, 01 Jan -1 00:00:00 GMT", "Mon, 01 Jan 70 00:00:00 GMT",
    "Mon, 01 Jan 69 00:00:00 GMT", "Thu, 29 Feb 2026 12:00:00 GMT", "Tue, 29 Feb 2028 12:00:00 GMT",
    "Thu, 30 Feb 2026 12:00:00 GMT", "Thu, 01 Oct 2026 24:00:00 GMT", "Thu, 01 Oct 2026 23:59:60 GMT",
    "Thu, 01 Oct 2026 23:59:61 GMT", "Thu, 01 Oct 2026 12:00:30 UT", "Thu, 01 Oct 2026 12:00:30 UTC",
    "Thu, 01 Oct 2026 12:00:30 Z", "Thu, 01 Oct 2026 12:00:30 +0000", "Thu, 01 Oct 2026 12:00:30 -0000",
    "Thu, 01 Oct 2026 12:00:30 +0001", "Thu, 01 Oct 2026 12:00:30 EST", "Thu, 01 Oct 2026 12:00:30 +2400",
    "Thu, 01 Oct 2026 12:00:30 +9999", "Thu, 01 Oct 2026 12:00:30 -9999", "Thu, 01 Oct 2026 12:00:30",
    "Thursday, 01-Oct-26 12:00:30 GMT", "Thu Oct  1 12:00:30 2026", "2026-10-01T12:00:30Z", "", " ", "\t",
    "GMT", "Thu, 01 Oct 2026", "Thu, 01 Oct 2026 12:00:30 GMT\x00", "Thu, 01 Oct 2026 12:00:30 GMT\r\n",
    "Thu, 01 Oct 2026 12:00:30 GÉT", "Thu, 01 Oct 2026 12:00:30 ÿþ", "é" * 50,
    "Thu, 01 Oct " + "9" * 255 + " 12:00:30 GMT", "Thu, 01 Oct " + "9" * 5000 + " 12:00:30 GMT",
    "Thu, 01 Oct 2026 " + "9" * 400 + ":15:00 GMT", "Thu, 99999999999 Oct 2026 12:00:30 GMT",
    "Thu, 01 Oct 2026 12:00:30.999999 GMT", "Thu, 01 Oct 2026 12:00 GMT", "01 Oct 2026 12:00:30 GMT",
    "Thu, 01 Oct 2026 12:00:30 GMT GMT", "Thu, 01 Foo 2026 12:00:30 GMT", "Thu,, 01 Oct 2026 12:00:30 GMT",
    "Thu, 01 Oct 2026 12:00:30 +00:00", "Thu, 01 Oct 2026 12:00:30 +000000000000000000000000000000000",
    "Thu, 01 Oct 2026 -12:00:30 GMT", "Thu, -01 Oct 2026 12:00:30 GMT", "Thu, 1e9 Oct 2026 12:00:30 GMT",
    GOOD,
]

for value in CORPUS:
    moment = parse_http_date(value)
    if moment is not None:
        print("accepted %-45r -> %s" % (value[:45], moment.isoformat()))
