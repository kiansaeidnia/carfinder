"""Polite HTTP fetching with an optional headless-browser fallback.

Plain `requests` is tried first. When a site answers with a bot challenge
(Kasada on carsales, Cloudflare elsewhere) and Playwright + Chromium are
available, the page is re-fetched in a real browser. Playwright is an
optional dependency — without it those sources simply report "blocked".
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests

log = logging.getLogger("carfinder.http")

DEFAULT_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "Accept-Language": "en-AU,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}

_CHALLENGE_MARKERS = (
    "kpsdk",                 # Kasada
    "just a moment",         # Cloudflare
    "cf-challenge",
    "px-captcha",            # PerimeterX
    "are you a human",
    "access denied",
    "request unsuccessful",
    "incapsula",
)


@dataclass
class FetchResult:
    url: str
    status: int
    text: str
    engine: str = "requests"   # "requests" | "playwright"

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300 and len(self.text) > 500 and not self.challenged

    @property
    def challenged(self) -> bool:
        if self.status in (403, 429, 503):
            return True
        head = self.text[:4000].lower()
        return any(marker in head for marker in _CHALLENGE_MARKERS)


class Fetcher:
    def __init__(self, delay: float = 2.0, timeout: float = 40.0,
                 dump_dir: str | None = None, use_playwright: str = "auto"):
        self.delay = delay
        self.timeout = timeout
        self.dump_dir = Path(dump_dir) if dump_dir else None
        self.use_playwright = use_playwright  # "auto" | "always" | "never"
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self._last_request = 0.0
        self._dump_seq = 0
        self._pw = None            # (playwright, browser, context) once started
        self._pw_failed = False

    # ---------------------------------------------------------------- public

    def get(self, url: str) -> FetchResult:
        """Fetch a URL, falling back to a headless browser on bot challenges."""
        if self.use_playwright == "always":
            result = self._get_playwright(url) or self._get_requests(url)
        else:
            result = self._get_requests(url)
            if result.challenged and self.use_playwright != "never":
                log.info("challenge detected on %s (status %s) - retrying via browser",
                         urlparse(url).netloc, result.status)
                pw_result = self._get_playwright(url)
                if pw_result is not None:
                    result = pw_result
        self._dump(url, result)
        return result

    def close(self) -> None:
        if self._pw is not None:
            playwright, browser, _ = self._pw
            try:
                browser.close()
                playwright.stop()
            except Exception:
                pass
            self._pw = None

    # -------------------------------------------------------------- internal

    def _throttle(self) -> None:
        wait = self.delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def _get_requests(self, url: str) -> FetchResult:
        self._throttle()
        try:
            resp = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            return FetchResult(url=str(resp.url), status=resp.status_code,
                               text=resp.text, engine="requests")
        except requests.RequestException as exc:
            log.warning("requests failed for %s: %s", url, exc)
            return FetchResult(url=url, status=0, text=f"__error__ {exc}", engine="requests")

    def _ensure_browser(self):
        if self._pw is not None or self._pw_failed:
            return self._pw
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            log.info("playwright not installed - browser fallback unavailable")
            self._pw_failed = True
            return None
        try:
            playwright = sync_playwright().start()
            launch_kwargs = {
                "headless": True,
                "args": ["--disable-blink-features=AutomationControlled",
                         "--no-sandbox"],
            }
            # Honour a pre-installed browser if the standard download is absent.
            explicit = os.environ.get("CARFINDER_CHROMIUM")
            if explicit:
                launch_kwargs["executable_path"] = explicit
            browser = playwright.chromium.launch(**launch_kwargs)
            context = browser.new_context(
                user_agent=DEFAULT_HEADERS["User-Agent"],
                locale="en-AU",
                timezone_id="Australia/Brisbane",
                viewport={"width": 1366, "height": 900},
            )
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            self._pw = (playwright, browser, context)
        except Exception as exc:
            log.warning("could not start playwright browser: %s", exc)
            self._pw_failed = True
            self._pw = None
        return self._pw

    def _get_playwright(self, url: str) -> FetchResult | None:
        pw = self._ensure_browser()
        if pw is None:
            return None
        _, _, context = pw
        self._throttle()
        page = context.new_page()
        try:
            resp = page.goto(url, timeout=self.timeout * 1000, wait_until="domcontentloaded")
            # Give client-side rendering and any challenge JS a moment.
            page.wait_for_timeout(4000)
            for _ in range(3):
                head = page.content()[:4000].lower()
                if not any(m in head for m in _CHALLENGE_MARKERS):
                    break
                page.wait_for_timeout(3000)
            status = resp.status if resp else 0
            html = page.content()
            return FetchResult(url=page.url, status=status, text=html, engine="playwright")
        except Exception as exc:
            log.warning("playwright fetch failed for %s: %s", url, exc)
            return FetchResult(url=url, status=0, text=f"__error__ {exc}", engine="playwright")
        finally:
            page.close()

    def _dump(self, url: str, result: FetchResult) -> None:
        if not self.dump_dir:
            return
        try:
            self.dump_dir.mkdir(parents=True, exist_ok=True)
            self._dump_seq += 1
            slug = re.sub(r"[^a-z0-9]+", "-", url.lower())[:120].strip("-")
            path = self.dump_dir / f"{self._dump_seq:03d}_{result.status}_{result.engine}_{slug}.html"
            path.write_text(result.text, encoding="utf-8", errors="replace")
        except OSError as exc:
            log.warning("could not dump response for %s: %s", url, exc)
