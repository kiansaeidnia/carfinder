"""carsales.com.au — Australia's largest marketplace.

Protected by Kasada, so plain requests are usually rejected; the Fetcher's
Playwright fallback does the heavy lifting here. SEO search paths
(/cars/<make>/<model>/) have been stable for many years, and search pages
carry a JSON-LD ItemList plus detail links containing SSE-AD ids.
"""

from __future__ import annotations

from typing import Any

from ..http import FetchResult
from ..models import Query, RunConfig
from . import common
from .base import Source

_SLUGS = {
    "kia-ev6": "kia/ev6",
    "byd-sealion-7": "byd/sealion-7",
    "subaru-solterra": "subaru/solterra",
}


class Carsales(Source):
    name = "carsales"
    site_url = "https://www.carsales.com.au"
    interesting_hrefs = r"/cars/[^\"'#?]+"

    def candidate_urls(self, query: Query, cfg: RunConfig, page: int) -> list[str]:
        slug = _SLUGS[query.key]
        offset = (page - 1) * 12
        suffix = f"?sort=~Price&offset={offset}" if page > 1 else "?sort=~Price"
        return [
            # State-scoped SEO paths first (fewer pages to walk), then national.
            f"{self.site_url}/cars/{slug}/queensland-state/{suffix}",
            f"{self.site_url}/cars/{slug}/qld-state/{suffix}",
            f"{self.site_url}/cars/{slug}/{suffix}",
        ]

    def parse(self, result: FetchResult, query: Query) -> list[dict[str, Any]]:
        soup = common.soup_of(result.text)
        raws: list[dict[str, Any]] = []

        for node in common.extract_jsonld_vehicles(soup):
            raw = common.jsonld_to_raw(node, result.url)
            if raw["title"] or raw["url"]:
                raws.append(raw)

        # HTML cards regardless — carsales cards carry location text the
        # JSON-LD usually lacks; merge by URL with cards winning on location.
        cards = common.harvest_cards(soup, r"/cars/details/", result.url)
        by_url = {r.get("url"): r for r in raws if r.get("url")}
        for card in cards:
            existing = by_url.get(card["url"])
            if existing:
                for key, value in card.items():
                    if value and not existing.get(key):
                        existing[key] = value
            else:
                raws.append(card)

        for raw in raws:
            if not raw.get("location"):
                raw["location"] = common.extract_location_au(raw.get("card_text", ""))
        return raws
