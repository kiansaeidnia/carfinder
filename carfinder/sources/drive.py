"""drive.com.au marketplace — newer aggregator, mostly dealer stock.

Verified URL pattern (run 5): /cars-for-sale/search/{state}/{region}/{make}/{model}/
e.g. /cars-for-sale/search/qld/all/kia/ev6/ — car details at
/cars-for-sale/car/<id>/ where <id> is numeric or 'g-'-prefixed.

Strategy: try directly-constructed search URLs first; if none yields a
matching listing, self-navigate (QLD hub -> make page -> model link) so a
changed URL scheme heals itself. Listings from the state blob and the HTML
cards describe the same cars under differently-prefixed ids, so dedupe is
digit-normalised. Locations in search results are state-only, so a capped
number of detail pages are fetched to resolve suburbs for radius filtering.
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

_SLUGS = {
    "kia-ev6": ("kia", "ev6"),
    "byd-sealion-7": ("byd", "sealion-7"),
    "subaru-solterra": ("subaru", "solterra"),
}

# Strict model tokens for filter-link discovery. Deliberately no bare
# "sealion": run 5 showed it latching onto the sealion-6 page.
_MODEL_TOKENS = {
    "kia-ev6": ["ev6", "ev-6"],
    "byd-sealion-7": ["sealion-7", "sealion7", "sea-lion-7"],
    "subaru-solterra": ["solterra"],
}

_DETAIL_LOOKUPS_PER_QUERY = 12


class Drive(Source):
    name = "drive"
    site_url = "https://www.drive.com.au"
    interesting_hrefs = r"/cars-for-sale/(?:car|search)/[^\"'\s<>#?]+"

    HUBS = ["/cars-for-sale/search/qld/", "/cars-for-sale/search/"]

    def candidate_urls(self, query: Query, cfg: RunConfig, page: int) -> list[str]:
        make, model = _SLUGS[query.key]
        return [
            f"{self.site_url}/cars-for-sale/search/qld/all/{make}/{model}/",
            f"{self.site_url}/cars-for-sale/search/all/all/{make}/{model}/",
        ]

    # ------------------------------------------------------------- parsing

    @staticmethod
    def _digit_id(raw: dict[str, Any]) -> str | None:
        """Stable digit-only id: 'g-134798' and '/car/134798/' are one car."""
        for cand in (str(raw.get("source_id") or ""), str(raw.get("url") or "")):
            m = re.search(r"(?:^|[/-])g?-?(\d{5,})(?:[/?#]|$)", cand)
            if m:
                return m.group(1)
        digits = re.sub(r"\D", "", str(raw.get("source_id") or ""))
        return digits if len(digits) >= 5 else None

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

        merged: dict[str, dict[str, Any]] = {}
        for raw in raws:
            key = self._digit_id(raw) or raw.get("url") or raw.get("title", "")
            if not key:
                continue
            if key not in merged:
                merged[key] = raw
                continue
            target = merged[key]
            for k, v in raw.items():
                if not v:
                    continue
                # Prefer real vehicle titles over image-alt junk.
                if k == "title" and common.junk_title(str(target.get("title") or "")) \
                        and not common.junk_title(str(v)):
                    target[k] = v
                elif not target.get(k):
                    target[k] = v
        out = []
        for key, raw in merged.items():
            raw["source_id"] = key if key.isdigit() else raw.get("source_id") or key
            if not raw.get("url") and str(raw["source_id"]).isdigit():
                raw["url"] = f"{self.site_url}/cars-for-sale/car/{raw['source_id']}/"
            out.append(raw)
        return out

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
            hits = [p for p in paths if seg_ok(p, token)]
            if hits:
                model_url = min(hits, key=len)
                break
        make_hits = [p for p in paths if seg_ok(p, make)]
        make_url = min(make_hits, key=len) if make_hits else None
        return model_url, make_url

    def _discover_target(self, query: Query, fetcher: Fetcher) -> tuple[str | None,
                                                                        FetchResult | None,
                                                                        int]:
        make, _ = _SLUGS[query.key]
        tokens = _MODEL_TOKENS[query.key]
        hub_fetch: FetchResult | None = None
        last_status = 0
        for hub in self.HUBS:
            fetch = fetcher.get(urljoin(self.site_url, hub))
            if not fetch.ok:
                last_status = fetch.status
                log.info("drive: hub %s -> status %s via %s", hub, fetch.status,
                         fetch.engine)
                continue
            hub_fetch = fetch
            paths = self._search_paths(fetch.text)
            model_url, make_url = self._pick_filter_url(paths, make, tokens)
            log.info("drive: hub %s discovered model_url=%s make_url=%s "
                     "(from %d search paths)", hub, model_url, make_url, len(paths))
            if model_url:
                return urljoin(self.site_url, model_url), hub_fetch, last_status
            if make_url:
                make_fetch = fetcher.get(urljoin(self.site_url, make_url))
                if make_fetch.ok:
                    hub_fetch = make_fetch
                    sub_model, _ = self._pick_filter_url(
                        self._search_paths(make_fetch.text), make, tokens)
                    log.info("drive: make page %s discovered model_url=%s",
                             make_url, sub_model)
                    if sub_model:
                        return urljoin(self.site_url, sub_model), hub_fetch, last_status
            # No such model on this hub; try the next (national) hub.
        return None, hub_fetch, last_status

    # --------------------------------------------------------------- search

    def search(self, query: Query, cfg: RunConfig, fetcher: Fetcher) -> SourceResult:
        target: str | None = None
        probe_fetch: FetchResult | None = None
        first_page_raws: list[dict[str, Any]] = []
        last_status = 0

        # 1) Directly-constructed URLs from the verified pattern.
        for url in self.candidate_urls(query, cfg, 1):
            fetch = fetcher.get(url)
            if not fetch.ok:
                last_status = fetch.status
                log.info("drive: %s -> status %s via %s", url, fetch.status,
                         fetch.engine)
                continue
            raws = self.parse(fetch, query)
            if any(self._to_listing(r, query) is not None for r in raws):
                target, probe_fetch, first_page_raws = url, fetch, raws
                log.info("drive: constructed URL works: %s", url)
                break

        # 2) Self-navigation fallback (scheme changed or model unlisted).
        if target is None:
            target, hub_fetch, hub_status = self._discover_target(query, fetcher)
            last_status = last_status or hub_status
            if target is None:
                if hub_fetch is None:
                    return SourceResult(source=self.name, query_key=query.key,
                                        ok=False,
                                        error=f"all search/hub URLs blocked or "
                                              f"failed (last status {last_status})")
                self._log_diagnostics(hub_fetch, [], query)
                return SourceResult(source=self.name, query_key=query.key, ok=True,
                                    listings=[], url_used=hub_fetch.url,
                                    engine=hub_fetch.engine)

        listings: dict[str, Listing] = {}
        raw_count = 0
        engine = probe_fetch.engine if probe_fetch else "requests"
        for page in range(1, cfg.max_pages + 1):
            if page == 1 and probe_fetch is not None:
                fetch, raws = probe_fetch, first_page_raws
            else:
                page_url = target if page == 1 else (
                    f"{target}{'&' if '?' in target else '?'}page={page}")
                fetch = fetcher.get(page_url)
                if not fetch.ok:
                    log.info("drive: %s -> status %s via %s", page_url,
                             fetch.status, fetch.engine)
                    break
                raws = self.parse(fetch, query)
            engine = fetch.engine
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

        self._enrich_locations(list(listings.values()), fetcher)
        result = SourceResult(source=self.name, query_key=query.key, ok=True,
                              listings=list(listings.values()), raw_count=raw_count,
                              url_used=target, engine=engine)
        self.log_kept_samples(result)
        return result

    # ---------------------------------------------------------- enrichment

    def _enrich_locations(self, listings: list[Listing], fetcher: Fetcher) -> None:
        """Search results carry state-only locations; pull suburbs from a few
        detail pages so radius filtering has something to work with."""
        from .. import geo
        budget = _DETAIL_LOOKUPS_PER_QUERY
        for listing in listings:
            if budget <= 0:
                break
            if not listing.url:
                continue
            if geo.resolve_coords(listing.location) is not None and \
                    (listing.location or "").strip().upper() not in ("QLD", "QUEENSLAND"):
                continue
            budget -= 1
            fetch = fetcher.get(listing.url)
            if not fetch.ok:
                continue
            loc = self._location_from_detail(fetch.text)
            if loc:
                listing.location = loc
                listing.extra["location_from_detail"] = True

    @staticmethod
    def _location_from_detail(html: str) -> str | None:
        soup = common.soup_of(html)
        for node in common.extract_jsonld_vehicles(soup):
            raw = common.jsonld_to_raw(node, "")
            if raw.get("location"):
                return raw["location"]
        text = common.clean_text(soup.get_text(" ")[:20000])
        return common.extract_location_au(text)
