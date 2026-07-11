"""drive.com.au marketplace — newer aggregator, mostly dealer stock.

The least-certain source of the five (young site, markup in flux); treated
as best-effort. Next.js state blob first, then JSON-LD, then anchors.
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


class Drive(Source):
    name = "drive"
    site_url = "https://www.drive.com.au"

    # Logged by diagnostics so failed runs reveal the site's real URL shapes.
    interesting_hrefs = r"/cars-for-sale/(?:car|search)/[^\"'#?]+"

    def candidate_urls(self, query: Query, cfg: RunConfig, page: int) -> list[str]:
        make, model = _SLUGS[query.key]
        page_seg = f"?page={page}" if page > 1 else ""
        # Observed (run 3 diagnostics): filters are path segments, e.g.
        # /cars-for-sale/search/qld/ and /cars-for-sale/search/used/, and
        # unknown segments soft-404 to a generic page — the base.search
        # soft-404 guard sorts the survivors out.
        return [
            f"{self.site_url}/cars-for-sale/search/qld/{make}/{model}/{page_seg}",
            f"{self.site_url}/cars-for-sale/search/{make}/{model}/{page_seg}",
            f"{self.site_url}/cars-for-sale/search/qld/{make}-{model}/{page_seg}",
            f"{self.site_url}/cars-for-sale/search/qld/{make}/{page_seg}",
        ]

    def parse(self, result: FetchResult, query: Query) -> list[dict[str, Any]]:
        raws: list[dict[str, Any]] = []

        # All strategies run and merge: the state blob may only contain page
        # furniture (featured rails etc.) while the real cards are in HTML —
        # an early return on junk would mask them.
        data = common.extract_next_data(result.text)
        if data is not None:
            raws.extend(common.walk_for_listings(data, result.url))

        soup = common.soup_of(result.text)
        for node in common.extract_jsonld_vehicles(soup):
            raw = common.jsonld_to_raw(node, result.url)
            if raw["title"] or raw["url"]:
                raws.append(raw)

        raws.extend(common.harvest_cards(soup, r"/cars-for-sale/car/", result.url))

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
