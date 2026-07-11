"""Core data types shared across the package."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(frozen=True)
class Query:
    """One car model we are hunting for."""

    key: str                      # stable identifier, e.g. "kia-ev6"
    make: str                     # "Kia"
    model: str                    # "EV6"
    title_pattern: str            # regex a listing title/model string must match
    exclude_pattern: str | None = None   # regex that must NOT match (wrong siblings)
    highlight_variant: str | None = None # variant regex to star in the report
    keywords: str = ""            # free-text search term for keyword-based sites

    def matches(self, text: str) -> bool:
        if not text:
            return False
        if not re.search(self.title_pattern, text, re.IGNORECASE):
            return False
        if self.exclude_pattern and re.search(self.exclude_pattern, text, re.IGNORECASE):
            return False
        return True

    def variant_matches(self, text: str) -> bool:
        if not self.highlight_variant or not text:
            return False
        return bool(re.search(self.highlight_variant, text, re.IGNORECASE))


@dataclass
class Listing:
    """A single car advertisement, normalised across sources."""

    source: str
    source_id: str
    url: str
    title: str
    query_key: str
    price: int | None = None
    price_text: str = ""
    year: int | None = None
    odometer_km: int | None = None
    condition: str | None = None      # "new" | "demo" | "used" | None
    variant: str | None = None
    location: str | None = None       # raw location text, e.g. "Cairns, QLD"
    state: str | None = None          # "QLD", "NSW", ...
    distance_km: float | None = None  # straight-line distance from origin
    variant_match: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.source}:{self.source_id}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Listing":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class RunConfig:
    """Settings for one scrape run."""

    origin_name: str = "Cairns QLD 4870"
    origin_lat: float = -16.9186
    origin_lng: float = 145.7781
    radius_km: float = 250.0
    strict_variant: bool = False       # drop non-highlight variants (Sealion 7 Premium only)
    drop_unknown_distance: bool = False
    max_pages: int = 3                 # per source per query
    request_delay: float = 2.0
    timeout: float = 40.0
    use_playwright: str = "auto"       # "auto" | "always" | "never"
    dump_dir: str | None = None        # save raw responses here for debugging


@dataclass
class SourceResult:
    """Outcome of scraping one source for one query."""

    source: str
    query_key: str
    ok: bool
    listings: list[Listing] = field(default_factory=list)
    error: str | None = None
    url_used: str | None = None
    raw_count: int = 0        # listings seen before model/geo filtering
    engine: str = "requests"  # "requests" | "playwright"
