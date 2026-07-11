"""gumtree.com.au — private sellers and small dealers.

Keyword search inside the cars category (c18320) using the long-stable
``/s-cars-vans-utes/<keywords>/k0c18320`` URL shape, no location segment —
locality filtering happens client-side like everywhere else. Ad links use
``/s-ad/<suburb>/<slug>/<id>``.
"""

from __future__ import annotations

import re
from typing import Any

from ..http import FetchResult
from ..models import Query, RunConfig
from . import common
from .base import Source


class Gumtree(Source):
    name = "gumtree"
    site_url = "https://www.gumtree.com.au"
    interesting_hrefs = r"/s-(?:ad|cars-vans-utes)/[^\"'#?]+"

    def candidate_urls(self, query: Query, cfg: RunConfig, page: int) -> list[str]:
        kw = query.keywords.replace(" ", "+")
        page_seg = f"page-{page}/" if page > 1 else ""
        return [
            f"{self.site_url}/s-cars-vans-utes/{page_seg}{kw}/k0c18320",
            f"{self.site_url}/s-cars-vans-utes/qld/{page_seg}{kw}/k0c18320l3008841",
        ]

    def parse(self, result: FetchResult, query: Query) -> list[dict[str, Any]]:
        soup = common.soup_of(result.text)
        raws: list[dict[str, Any]] = []

        for node in common.extract_jsonld_vehicles(soup):
            raw = common.jsonld_to_raw(node, result.url)
            if raw["title"] or raw["url"]:
                raws.append(raw)

        # Gumtree renders ad data into a JS state blob on most page builds.
        data = common.extract_embedded_json(
            result.text,
            [r"window\.APP_DATA\s*=", r"window\.__data\s*=", r"__PRELOADED_STATE__\s*="])
        if data is not None:
            raws.extend(common.walk_for_listings(data, result.url))

        cards = common.harvest_cards(soup, r"/s-ad/", result.url)
        raws.extend(cards)

        seen: dict[str, dict[str, Any]] = {}
        for raw in raws:
            url = raw.get("url") or ""
            key = self._ad_id(url) or url or raw.get("title", "")
            if key and key not in seen:
                if url and not raw.get("source_id"):
                    ad_id = self._ad_id(url)
                    if ad_id:
                        raw["source_id"] = ad_id
                if not raw.get("location"):
                    raw["location"] = self._suburb_from_url(url)
                seen[key] = raw
            elif key:
                for k, v in raw.items():
                    if v and not seen[key].get(k):
                        seen[key][k] = v
        return list(seen.values())

    @staticmethod
    def _ad_id(url: str) -> str | None:
        m = re.search(r"/(\d{9,})(?:[/?#]|$)", url)
        return m.group(1) if m else None

    @staticmethod
    def _suburb_from_url(url: str) -> str | None:
        # /s-ad/<suburb-slug>/<category-ish>/<slug>/<id>
        m = re.search(r"/s-ad/([a-z-]+)/", url)
        if not m:
            return None
        return m.group(1).replace("-", " ").title()
