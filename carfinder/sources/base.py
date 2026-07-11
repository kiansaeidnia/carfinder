"""Base class all sources implement."""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from typing import Any

from ..http import Fetcher, FetchResult
from ..models import Listing, Query, RunConfig, SourceResult
from . import common

log = logging.getLogger("carfinder.sources")


class Source(ABC):
    name: str = "base"
    site_url: str = ""
    # Optional regex; diagnostics logs sample hrefs matching it so a failed
    # run's logs reveal the site's actual URL shapes.
    interesting_hrefs: str | None = None

    @abstractmethod
    def candidate_urls(self, query: Query, cfg: RunConfig, page: int) -> list[str]:
        """Search URLs to try for this query/page, best guess first."""

    @abstractmethod
    def parse(self, result: FetchResult, query: Query) -> list[dict[str, Any]]:
        """Raw listing dicts extracted from a fetched search page."""

    # ------------------------------------------------------------------ run

    def search(self, query: Query, cfg: RunConfig, fetcher: Fetcher) -> SourceResult:
        listings: dict[str, Listing] = {}
        raw_count = 0
        url_used: str | None = None
        engine = "requests"
        error: str | None = None
        working_idx: int | None = None  # which candidate URL pattern worked on page 1
        last_status = 0

        for page in range(1, cfg.max_pages + 1):
            all_candidates = self.candidate_urls(query, cfg, page)
            if working_idx is not None:
                if working_idx >= len(all_candidates):
                    break
                candidates = [(working_idx, all_candidates[working_idx])]
            else:
                candidates = list(enumerate(all_candidates))

            page_raws: list[dict[str, Any]] = []
            page_fetch: FetchResult | None = None
            fallback: tuple[FetchResult, list[dict[str, Any]]] | None = None
            for idx, url in candidates:
                fetch = fetcher.get(url)
                if not fetch.ok:
                    last_status = fetch.status
                    log.info("%s: %s -> status %s via %s", self.name, url,
                             fetch.status, fetch.engine)
                    continue
                raws = self.parse(fetch, query)
                if not raws:
                    log.info("%s: %s fetched OK but no listings parsed",
                             self.name, url)
                    self._log_diagnostics(fetch, raws, query)
                    fallback = fallback or (fetch, [])
                    continue
                # Guard against soft-404s: sites route unknown search paths
                # to a generic page full of unrelated cars. A candidate only
                # wins when something on it matches the model we want.
                if any(self._to_listing(r, query) is not None for r in raws):
                    page_fetch = fetch
                    page_raws = raws
                    working_idx = idx
                    break
                log.info("%s: %s parsed %d listings but none match %s",
                         self.name, url, len(raws), query.key)
                fallback = fallback or (fetch, raws)
            if page_fetch is None and fallback is not None and working_idx is None:
                # No candidate produced a match; keep the first parseable
                # page for honest diagnostics and source-ok accounting.
                page_fetch, page_raws = fallback
                if page_raws:
                    self._log_diagnostics(page_fetch, page_raws, query)

            if page_fetch is None:
                if page == 1:
                    error = f"all candidate URLs blocked or failed (last status {last_status})"
                break
            url_used = url_used or page_fetch.url
            engine = page_fetch.engine
            raw_count += len(page_raws)

            new_on_page = 0
            for raw in page_raws:
                listing = self._to_listing(raw, query)
                if listing is not None and listing.key not in listings:
                    listings[listing.key] = listing
                    new_on_page += 1
            if not page_raws or new_on_page == 0:
                break

        ok = error is None
        result = SourceResult(source=self.name, query_key=query.key, ok=ok,
                              listings=list(listings.values()), error=error,
                              url_used=url_used, raw_count=raw_count, engine=engine)
        self.log_kept_samples(result)
        return result

    @staticmethod
    def log_kept_samples(result: SourceResult) -> None:
        """A few kept listings into the log — data-quality problems (junk
        titles, missing URLs/locations) should be visible straight from CI."""
        for listing in result.listings[:3]:
            log.info("%s kept [%s]: %r | %s | %s | %s", result.source,
                     result.query_key, listing.title[:70],
                     listing.price_text or "no price",
                     listing.location or "no location", listing.url or "NO URL")

    # ------------------------------------------------------------- helpers

    def _to_listing(self, raw: dict[str, Any], query: Query) -> Listing | None:
        title = common.clean_text(str(raw.get("title") or ""))
        match_text = " ".join(str(raw.get(k) or "") for k in
                              ("title", "variant", "card_text", "make", "model"))
        if not query.matches(match_text):
            return None
        url = str(raw.get("url") or "")
        source_id = str(raw.get("source_id") or "") or self._id_from_url(url)
        if not source_id:
            return None
        variant = raw.get("variant")
        variant_text = " ".join(str(raw.get(k) or "") for k in ("title", "variant", "card_text"))
        price = raw.get("price")
        if not isinstance(price, int):
            price = common.parse_price(str(raw.get("price_text") or "")) if raw.get("price_text") else None
        location = raw.get("location")
        card_text = str(raw.get("card_text") or "")
        return Listing(
            source=self.name,
            source_id=source_id,
            url=url,
            title=title[:160],
            query_key=query.key,
            price=price,
            price_text=common.clean_text(str(raw.get("price_text") or "")) or
                       (f"${price:,}" if price else ""),
            year=raw.get("year") or common.parse_year(title),
            odometer_km=raw.get("odometer_km"),
            condition=raw.get("condition") or common.infer_condition(card_text),
            variant=common.clean_text(str(variant)) if variant else None,
            location=common.clean_text(str(location)) if location else None,
            variant_match=query.variant_matches(variant_text),
        )

    def _log_diagnostics(self, fetch: FetchResult, raws: list[dict[str, Any]],
                         query: Query) -> None:
        """Fingerprint a page that yielded nothing useful, into the log.

        Runs on CI where the raw HTML artifact may be awkward to reach; these
        lines alone should reveal whether the page was a challenge shell, an
        empty result list, or a parser/selector mismatch.
        """
        text = fetch.text
        title_m = re.search(r"<title[^>]*>(.*?)</title>", text, re.DOTALL | re.IGNORECASE)
        anchors = re.findall(r'<a[^>]+href="([^"]+)"', text)
        prefixes: dict[str, int] = {}
        for href in anchors:
            path = href.split("?")[0]
            if path.startswith("http"):
                path = "/" + path.split("/", 3)[-1] if path.count("/") >= 3 else path
            parts = [p for p in path.split("/") if p]
            prefix = "/" + "/".join(parts[:2]) if parts else "/"
            prefixes[prefix] = prefixes.get(prefix, 0) + 1
        top = sorted(prefixes.items(), key=lambda kv: -kv[1])[:12]
        log.info(
            "%s diagnostics [%s]: status=%s engine=%s bytes=%d title=%r "
            "next_data=%s jsonld_blocks=%d anchors=%d",
            self.name, query.key, fetch.status, fetch.engine, len(text),
            (title_m.group(1).strip()[:100] if title_m else None),
            '"__NEXT_DATA__"' in text or "id=\"__NEXT_DATA__\"" in text,
            text.count("application/ld+json"), len(anchors))
        log.info("%s diagnostics [%s]: top anchor prefixes: %s",
                 self.name, query.key,
                 ", ".join(f"{p}({n})" for p, n in top) or "none")
        if self.interesting_hrefs:
            # Scan the whole document, not just <a> tags — SPA router paths
            # often live in embedded JSON. Rank query-relevant and deeper
            # paths first so filter-URL shapes surface within the sample.
            hay = text.replace("\\/", "/")
            found: list[str] = []
            for m in re.finditer(self.interesting_hrefs, hay):
                s = m.group(0)
                if s not in found:
                    found.append(s)
            tokens = [t for t in re.split(r"[\s/-]+",
                                          f"{query.make} {query.model}".lower())
                      if len(t) >= 2]
            found.sort(key=lambda s: (not any(t in s.lower() for t in tokens),
                                      -s.count("/")))
            log.info("%s diagnostics [%s]: sample hrefs: %s",
                     self.name, query.key, " | ".join(found[:14]) or "none")
        for raw in raws[:8]:
            log.info("%s diagnostics [%s]: raw title=%r price=%r url=%r loc=%r",
                     self.name, query.key, str(raw.get("title"))[:90],
                     raw.get("price") or raw.get("price_text"),
                     str(raw.get("url"))[:110], raw.get("location"))

    @staticmethod
    def _id_from_url(url: str) -> str:
        if not url:
            return ""
        # Common ad-id shapes across AU classifieds:
        for pattern in (r"(SSE-AD-\d+)", r"(OAG-AD-\d+)", r"/(\d{7,})/?(?:[?#]|$)",
                        r"[/-](\d{6,})(?:[/?#]|$)"):
            m = re.search(pattern, url, re.IGNORECASE)
            if m:
                return m.group(1)
        # Fall back to the URL path itself (stable enough for dedupe).
        return re.sub(r"[?#].*$", "", url).rstrip("/").rsplit("/", 1)[-1][:80]
