"""The cars being hunted and per-site slugs for building search URLs."""

from __future__ import annotations

from .models import Query

# Notes on the patterns:
#  - EV6 must not swallow EV5/EV9 ("ev" followed by exactly 6) and "EV" inside
#    other words; \b plus a no-digit lookahead handles "EV6", "EV 6", "EV-6".
#  - Sealion 7 must not match Sealion 6 / Sealion 8, or "Seal" (BYD Seal is a
#    different car). Sellers write "Sealion", "Sea Lion" and "SEALION".
#  - Solterra is frequently misspelled "Soltera" in private ads (the user did
#    too) so both spellings are accepted.
QUERIES: list[Query] = [
    Query(
        key="kia-ev6",
        make="Kia",
        model="EV6",
        title_pattern=r"\bev[\s-]?6\b(?![0-9])",
        keywords="kia ev6",
    ),
    Query(
        key="byd-sealion-7",
        make="BYD",
        model="Sealion 7",
        title_pattern=r"\bsea\s?lion[\s-]?7\b(?![0-9])",
        highlight_variant=r"\bpremium\b",
        keywords="byd sealion 7",
    ),
    Query(
        key="subaru-solterra",
        make="Subaru",
        model="Solterra",
        title_pattern=r"\bsolt+err?a\b",
        keywords="subaru solterra",
    ),
]

QUERIES_BY_KEY = {q.key: q for q in QUERIES}

# URL slugs per source. Keyed by query key; each source picks what it needs.
SLUGS: dict[str, dict[str, str]] = {
    "kia-ev6": {
        "make_slug": "kia",
        "model_slug": "ev6",
        "carsguide_slug": "kia/ev6",
    },
    "byd-sealion-7": {
        "make_slug": "byd",
        "model_slug": "sealion-7",
        "carsguide_slug": "byd/sealion-7",
    },
    "subaru-solterra": {
        "make_slug": "subaru",
        "model_slug": "solterra",
        "carsguide_slug": "subaru/solterra",
    },
}
