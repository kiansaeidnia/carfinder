"""drive.com.au marketplace — newer aggregator, mostly dealer stock.

The search router is path-segment based and unknown segments hard-404
(observed run 4), while the exact make/model segment shapes are not
documented anywhere stable. So this source self-navigates instead of
guessing: fetch the known-good QLD search hub, find the site's own
make/model filter URLs in the page (HTML and embedded JSON), follow the
best one, then paginate it.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin

from ..http import Fetcher, FetchResult
from ..models import Listing, Query, RunConfig, SourceResult
from . import common
from .base import Source

log = logging.getLogger("carfinder.sources")

# (make token, model tokens preferred-first) for filter-link discovery.
_TOKENS = {
    "kia-ev6": ("kia", ["ev6", "ev-6"]),
    "byd-sealion-7": ("byd", ["sealion-7", "sealion7", "sea-lion-7", "sealion"]),
    "subaru-solterra": ("subaru", ["solterra"]),
}


class Drive(Source):
    name = "drive"
    site_url = "https://www.drive.com.au"
    interesting_hrefs = r"/cars-for-sale/(?:car|search)/[^\"'\s<>#?]+"

    HUBS = ["/cars-for-sale/search/qld/", "/cars-for-sale/search/"]

    def candidate_urls(self, query: Query, cfg: RunConfig, page: int) -> list[str]:
        return [urljoin(self.site_url, h) for h in self.HUBS]

    def parse(self, result: FetchResult, query: Query) -> list[dict[str, Any]]:
        raws: list[dict[str, Any]] = []
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

    # ---------------------------------------------------------- discovery

    @staticmethod
    def _search_paths(html: str) -> list[str]:
        hay = html.replace("\\/", "/")
        return list(dict.fromkeys(
            re.findall(r"/cars-for-sale/search/[a-z0-9/_-]+", hay, re.IGNORECASE)))

    def _pick_filter_url(self, paths: list[str], make: str,
                         model_tokens: list[str]) -> tuple[str | None, str | None]:
        """(model_url, make_url) — most specific filter links available."""
        def seg_ok(path: str, token: str) -> bool:
            return bool(re.search(rf"/{re.escape(token)}(?:/|$)", path.lower()))

        model_url = None
        for token in model_tokens:
            hits = [p for p in paths if token in p.lower()]
            if hits:
                # Shortest = least extra filters baked in.
                model_url = min(hits, key=len)
                break
        make_hits = [p for p in paths if seg_ok(p, make)]
        make_url = min(make_hits, key=len) if make_hits else None
        return model_url, make_url

    def search(self, query: Query, cfg: RunConfig, fetcher: Fetcher) -> SourceResult:
        make, model_tokens = _TOKENS[query.key]

        hub_fetch: FetchResult | None = None
        target: str | None = None
        last_status = 0
        for hub in self.candidate_urls(query, cfg, 1):
            fetch = fetcher.get(hub)
            if not fetch.ok:
                last_status = fetch.status
                log.info("drive: hub %s -> status %s via %s", hub, fetch.status,
                         fetch.engine)
                continue
            hub_fetch = fetch
            paths = self._search_paths(fetch.text)
            model_url, make_url = self._pick_filter_url(paths, make, model_tokens)
            log.info("drive: hub %s discovered model_url=%s make_url=%s "
                     "(from %d search paths)", hub, model_url, make_url, len(paths))
            if model_url:
                target = urljoin(self.site_url, model_url)
                break
            if make_url and target is None:
                # One hop down: the make page lists model filter links.
                make_fetch = fetcher.get(urljoin(self.site_url, make_url))
                if make_fetch.ok:
                    sub_paths = self._search_paths(make_fetch.text)
                    sub_model, _ = self._pick_filter_url(sub_paths, make, model_tokens)
                    log.info("drive: make page %s discovered model_url=%s "
                             "(from %d search paths)", make_url, sub_model,
                             len(sub_paths))
                    if sub_model:
                        target = urljoin(self.site_url, sub_model)
                        break
                    # No model link (no stock?) — scan the make page itself.
                    target = urljoin(self.site_url, make_url)
                    hub_fetch = make_fetch
                    break

        if hub_fetch is None:
            return SourceResult(source=self.name, query_key=query.key, ok=False,
                                error=f"all hub URLs blocked or failed "
                                      f"(last status {last_status})")
        if target is None:
            # Nothing about this make on the hub at all; log what we saw.
            self._log_diagnostics(hub_fetch, [], query)
            return SourceResult(source=self.name, query_key=query.key, ok=True,
                                listings=[], url_used=hub_fetch.url,
                                engine=hub_fetch.engine)

        listings: dict[str, Listing] = {}
        raw_count = 0
        engine = hub_fetch.engine
        url_used = target
        for page in range(1, cfg.max_pages + 1):
            page_url = target if page == 1 else (
                f"{target}{'&' if '?' in target else '?'}page={page}")
            fetch = fetcher.get(page_url)
            if not fetch.ok:
                log.info("drive: %s -> status %s via %s", page_url, fetch.status,
                         fetch.engine)
                break
            engine = fetch.engine
            raws = self.parse(fetch, query)
            raw_count += len(raws)
            new_on_page = 0
            for raw in raws:
                listing = self._to_listing(raw, query)
                if listing is not None and listing.key not in listings:
                    listings[listing.key] = listing
                    new_on_page += 1
            if page == 1 and raws and new_on_page == 0:
                self._log_diagnostics(fetch, raws, query)
            if not raws or new_on_page == 0:
                break

        return SourceResult(source=self.name, query_key=query.key, ok=True,
                            listings=list(listings.values()), raw_count=raw_count,
                            url_used=url_used, engine=engine)
