"""Offline demo source: deterministic fake listings.

Lets the full pipeline (matching, geo filter, state tracking, reports) run
without network access — used by the test suite and `--sources demo`.
"""

from __future__ import annotations

from typing import Any

from ..http import FetchResult
from ..models import Query, RunConfig
from .base import Source

_FAKES: dict[str, list[dict[str, Any]]] = {
    "kia-ev6": [
        {"title": "2022 Kia EV6 GT-Line AWD", "source_id": "DEMO-1001",
         "url": "https://example.com/demo/1001", "price": 62990,
         "price_text": "$62,990", "year": 2022, "odometer_km": 31500,
         "condition": "used", "location": "Cairns, QLD 4870"},
        {"title": "2023 Kia EV6 Air RWD", "source_id": "DEMO-1002",
         "url": "https://example.com/demo/1002", "price": 55990,
         "price_text": "$55,990", "year": 2023, "odometer_km": 12000,
         "condition": "used", "location": "Townsville, QLD"},
    ],
    "byd-sealion-7": [
        {"title": "2025 BYD Sealion 7 Premium", "source_id": "DEMO-2001",
         "url": "https://example.com/demo/2001", "price": 54990,
         "price_text": "$54,990", "year": 2025, "odometer_km": 25,
         "condition": "new", "variant": "Premium", "location": "Smithfield, QLD 4878"},
        {"title": "2025 BYD Sealion 7 Performance", "source_id": "DEMO-2002",
         "url": "https://example.com/demo/2002", "price": 63990,
         "price_text": "$63,990", "year": 2025, "odometer_km": 900,
         "condition": "demo", "variant": "Performance", "location": "Brisbane, QLD"},
        # Must be filtered out by the model regex (Sealion 6 != Sealion 7):
        {"title": "2024 BYD Sealion 6 Dynamic", "source_id": "DEMO-2003",
         "url": "https://example.com/demo/2003", "price": 42990,
         "price_text": "$42,990", "year": 2024, "location": "Cairns, QLD"},
    ],
    "subaru-solterra": [
        {"title": "2026 Subaru Solterra AWD Touring", "source_id": "DEMO-3001",
         "url": "https://example.com/demo/3001", "price": 69990,
         "price_text": "$69,990", "year": 2026, "odometer_km": 10,
         "condition": "new", "location": "Portsmith, QLD 4870"},
    ],
}


class Demo(Source):
    name = "demo"
    site_url = "https://example.com"

    def candidate_urls(self, query: Query, cfg: RunConfig, page: int) -> list[str]:
        return []

    def parse(self, result: FetchResult, query: Query) -> list[dict[str, Any]]:
        return []

    def search(self, query, cfg, fetcher):  # type: ignore[override]
        from ..models import SourceResult
        raws = _FAKES.get(query.key, [])
        listings = [l for l in (self._to_listing(r, query) for r in raws) if l]
        return SourceResult(source=self.name, query_key=query.key, ok=True,
                            listings=listings, raw_count=len(raws),
                            url_used=self.site_url, engine="demo")
