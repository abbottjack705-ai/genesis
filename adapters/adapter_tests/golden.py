"""Pinned golden vectors (generated once with an independent hashlib/json implementation,
cross-checked against the production functions, then frozen). Changing any of these means
an identity or request-hash contract changed."""

GID_VECTORS = [
    "part:36c364dfcdaa8f4e5b58ab1dca72e17ebc76ff60074fb42e9addb82c10d5f8cc",
    "evt:059ee6f856804dc220fe7bb3239c9dac26534536578d01662a5e24e47a0978bf",
    "mkt:3e9eba79f0c88ec3e3ff7dd917e6b16eb8b3489ac7b1ee152926034ef5fe5af2",
    "mkt:068048358bb3c85ffb251b7b79e5f619a501626bdee549bc7239df8caccbc935",
    "sel:95811040f31c0206460f2de2a34e7d64224868fa35ce64ad30d28a9a36415e59",
    "book:4829386acd2e8a83c9e81b9c4c65cb4293b95532489ab61d9def1824c82cfaff",
    "rev:fae53681c8e630d920a87e498948a356ac95cff9a182e0d7cb839724f7697503",
]

ODDS_REQUEST_HASH = "56ad96a7e667e06090f9e7c7079b7c31d4b31df604a32192b49b13462c905c85"
TOURNAMENTS_REQUEST_HASH = "a596acb815e8ae38811d0ab6f3bf9d67501c1d841c70244b1d55492146bab140"
