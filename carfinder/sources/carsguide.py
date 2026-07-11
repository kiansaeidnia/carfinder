"""carsguide.com.au — dealer-heavy inventory, historically scrape-friendly
with JSON-LD on search result pages.
"""

from __future__ import annotations

from typing import Any

from ..http import FetchResult
from ..models import Query, RunConfig
from . import common
from .base import Source

_SLUGS = {
    "kia-ev6": ("kia", "ev6"),
    "byd-sealion-7": ("byd", "sealion-7"),
    "subaru-solterra": ("subaru", "solterra"),
}


class CarsGuide(Source):
    name = "carsguide"
    site_url = "https://www.carsguide.com.au"
    interesting_hrefs = r"/buy-a-car/[^\"'#?]+"

    def candidate_urls(self, query: Query, cfg: RunConfig, page: int) -> list[str]:
        make, model = _SLUGS[query.key]
        page_q = f"?page={page}" if page > 1 else ""
        return [
            f"{self.site_url}/buy-a-car/{make}/{model}/queensland{page_q}",
            f"{self.site_url}/buy-a-car/{make}/{model}{page_q}",
            f"{self.site_url}/buy-a-car/all-new-used/{make}-{model}{page_q}",
        ]

    def parse(self, result: FetchResult, query: Query) -> list[dict[str, Any]]:
        soup = common.soup_of(result.text)
        raws: list[dict[str, Any]] = []

        for node in common.extract_jsonld_vehicles(soup):
            raw = common.jsonld_to_raw(node, result.url)
            if raw["title"] or raw["url"]:
                raws.append(raw)

        data = common.extract_next_data(result.text)
        if data is not None:
            raws.extend(common.walk_for_listings(data, result.url))

        # Cards merge unconditionally: junk from the state-blob walk must not
        # suppress real listings present in the HTML (URL-keyed dedupe below).
        raws.extend(common.harvest_cards(soup, r"/buy-a-car/.+\d{5,}", result.url))

        seen: dict[str, dict[str, Any]] = {}
        for raw in raws:
            key = raw.get("url") or raw.get("source_id") or raw.get("title", "")
            if key and key not in seen:
                seen[key] = raw
            elif key:
                for k, v in raw.items():
                    if v and not seen[key].get(k):
                        seen[key][k] = v
        return list(seen.values())
