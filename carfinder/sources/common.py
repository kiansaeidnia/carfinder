"""Shared parsing helpers used by every source.

Listing sites change markup constantly, so each source tries several
extraction strategies in order of fidelity:

  1. schema.org JSON-LD (``<script type="application/ld+json">`` with
     Vehicle/Car/Product items) — richest and most stable when present.
  2. Framework state blobs (``__NEXT_DATA__`` or other embedded JSON) walked
     generically for listing-shaped objects.
  3. Plain HTML anchor harvesting — find detail-page links and read the text
     of the card around them.

Everything harvested is filtered afterwards against the Query regex, so the
strategies are deliberately greedy: collecting junk is fine, missing a real
listing is not.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

log = logging.getLogger("carfinder.parse")

# --------------------------------------------------------------------- text


def parse_price(text: str | None) -> int | None:
    """'$72,990 Drive Away' -> 72990. Returns None for POA/EOI/absent."""
    if not text:
        return None
    m = re.search(r"\$\s*([\d,]{4,})", text)
    if not m:
        m = re.search(r"\b(\d{2,3},\d{3})\b", text)
    if not m:
        return None
    try:
        value = int(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return value if 1_000 <= value <= 500_000 else None


def parse_km(text: str | None) -> int | None:
    """'12,345 km' -> 12345."""
    if not text:
        return None
    m = re.search(r"([\d,]+)\s*(?:km\b|kms\b|kilometre)", text, re.IGNORECASE)
    if not m:
        return None
    try:
        value = int(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return value if 0 <= value <= 500_000 else None


def parse_year(text: str | None) -> int | None:
    if not text:
        return None
    m = re.search(r"\b(20[12]\d)\b", text)
    return int(m.group(1)) if m else None


def infer_condition(text: str | None) -> str | None:
    if not text:
        return None
    t = text.lower()
    if re.search(r"\bdemo\b|\bdemonstrator\b|\bex.?demo\b", t):
        return "demo"
    if re.search(r"\bnew\s+car\b|\bbrand\s+new\b|\bnew\s+in\s+stock\b", t):
        return "new"
    if re.search(r"\bused\b|\bpre.?owned\b|\bsecond.?hand\b", t):
        return "used"
    return None


def clean_text(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


# ------------------------------------------------------------------- JSON-LD

_VEHICLE_TYPES = {"vehicle", "car", "product", "motorizedvehicle", "automobile"}


def _jsonld_blocks(soup: BeautifulSoup) -> Iterable[Any]:
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            yield json.loads(raw)
        except json.JSONDecodeError:
            # Some sites embed multiple JSON objects or trailing garbage.
            for candidate in re.findall(r"\{.*\}", raw, re.DOTALL):
                try:
                    yield json.loads(candidate)
                    break
                except json.JSONDecodeError:
                    continue


def extract_jsonld_vehicles(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """All schema.org objects that look like a vehicle offer."""
    found: list[dict[str, Any]] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            node_type = node.get("@type")
            types = {str(t).lower() for t in (node_type if isinstance(node_type, list)
                                              else [node_type] if node_type else [])}
            if types & _VEHICLE_TYPES:
                found.append(node)
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    for block in _jsonld_blocks(soup):
        visit(block)
    return found


def jsonld_to_raw(node: dict[str, Any], base_url: str) -> dict[str, Any]:
    """Flatten a schema.org Vehicle/Product node into our raw-listing dict."""
    offers = node.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    price = offers.get("price") if isinstance(offers, dict) else None
    if isinstance(price, str):
        price = parse_price(price) or parse_price("$" + price)
    url = node.get("url") or (offers.get("url") if isinstance(offers, dict) else None) or ""
    if url:
        url = urljoin(base_url, str(url))
    name = clean_text(str(node.get("name") or ""))
    odo = node.get("mileageFromOdometer")
    if isinstance(odo, dict):
        odo = odo.get("value")
    try:
        odo_km = int(float(odo)) if odo not in (None, "") else None
    except (TypeError, ValueError):
        odo_km = None
    location = None
    seller = offers.get("seller") if isinstance(offers, dict) else None
    if isinstance(seller, dict):
        address = seller.get("address")
        if isinstance(address, dict):
            location = clean_text(" ".join(
                str(address.get(k) or "") for k in
                ("addressLocality", "addressRegion", "postalCode")))
    condition = None
    item_condition = str(node.get("itemCondition") or
                         (offers.get("itemCondition") if isinstance(offers, dict) else "") or "")
    if "new" in item_condition.lower():
        condition = "new"
    elif "used" in item_condition.lower():
        condition = "used"
    return {
        "title": name,
        "url": url,
        "price": price if isinstance(price, int) else parse_price(str(price) if price else None),
        "price_text": str(price or ""),
        "odometer_km": odo_km,
        "location": location or None,
        "condition": condition,
        "year": parse_year(name) or parse_year(str(node.get("vehicleModelDate") or
                                                    node.get("productionDate") or "")),
    }


# --------------------------------------------------------- framework blobs


def extract_next_data(html: str) -> Any | None:
    m = re.search(
        r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def extract_embedded_json(html: str, var_patterns: list[str]) -> Any | None:
    """Pull ``window.FOO = {...};`` style blobs by regex, balancing braces."""
    for pattern in var_patterns:
        m = re.search(pattern, html)
        if not m:
            continue
        start = html.index("{", m.end() - 1) if "{" not in m.group(0) else m.start() + m.group(0).index("{")
        blob = _balanced_json(html, start)
        if blob is None:
            continue
        try:
            return json.loads(blob)
        except json.JSONDecodeError:
            continue
    return None


def _balanced_json(text: str, start: int) -> str | None:
    if start >= len(text) or text[start] != "{":
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, min(len(text), start + 3_000_000)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


_TITLE_KEYS = ("title", "name", "heading", "adTitle", "displayTitle")
_URL_KEYS = ("url", "detailsUrl", "detailUrl", "href", "link", "seoUrl", "adUrl", "canonicalUrl")
_ID_KEYS = ("id", "adId", "listingId", "networkId", "stockNumber", "sseId")
_PRICE_KEYS = ("price", "priceText", "displayPrice", "advertisedPrice", "priceDisplay", "askingPrice")


def walk_for_listings(node: Any, base_url: str,
                      out: list[dict[str, Any]] | None = None,
                      depth: int = 0) -> list[dict[str, Any]]:
    """Generic walk over a framework state blob collecting listing-shaped dicts.

    A dict counts as listing-shaped when it carries a title-ish key AND a
    price-ish or URL-ish key. The Query regex filter downstream discards
    false positives.
    """
    if out is None:
        out = []
    if depth > 14:
        return out
    if isinstance(node, dict):
        title = next((node[k] for k in _TITLE_KEYS
                      if isinstance(node.get(k), str) and len(node[k]) > 6), None)
        if title:
            price_val = next((node[k] for k in _PRICE_KEYS if node.get(k) is not None), None)
            url_val = next((node[k] for k in _URL_KEYS
                            if isinstance(node.get(k), str) and node[k]), None)
            if price_val is not None or url_val:
                raw: dict[str, Any] = {"title": clean_text(title)}
                if url_val:
                    raw["url"] = urljoin(base_url, url_val)
                id_val = next((node[k] for k in _ID_KEYS if node.get(k) not in (None, "")), None)
                if id_val is not None:
                    raw["source_id"] = str(id_val)
                if isinstance(price_val, (int, float)) and 1000 <= price_val <= 500_000:
                    raw["price"] = int(price_val)
                    raw["price_text"] = f"${int(price_val):,}"
                elif price_val is not None:
                    raw["price_text"] = clean_text(str(price_val))
                    raw["price"] = parse_price(raw["price_text"])
                # Location-ish nested values.
                for key in ("location", "suburb", "city", "dealerLocation", "region", "address"):
                    val = node.get(key)
                    if isinstance(val, str) and val:
                        raw["location"] = clean_text(val)
                        break
                    if isinstance(val, dict):
                        parts = [str(val.get(k) or "") for k in
                                 ("suburb", "city", "locality", "state", "region", "postcode", "postCode")]
                        joined = clean_text(" ".join(p for p in parts if p))
                        if joined:
                            raw["location"] = joined
                            break
                for key in ("odometer", "kilometres", "kms", "mileage"):
                    val = node.get(key)
                    if isinstance(val, (int, float)) and 0 <= val <= 500_000:
                        raw["odometer_km"] = int(val)
                        break
                    if isinstance(val, str):
                        km = parse_km(val) or parse_km(val + " km")
                        if km is not None:
                            raw["odometer_km"] = km
                            break
                cond = node.get("condition") or node.get("listingType") or node.get("adType")
                if isinstance(cond, str):
                    raw["condition"] = infer_condition(cond) or infer_condition(cond + " car")
                raw["year"] = parse_year(title) or (
                    int(node["year"]) if str(node.get("year", "")).isdigit() else None)
                variant = node.get("variant") or node.get("badge") or node.get("trim")
                if isinstance(variant, str) and variant:
                    raw["variant"] = clean_text(variant)
                out.append(raw)
        for value in node.values():
            walk_for_listings(value, base_url, out, depth + 1)
    elif isinstance(node, list):
        for item in node:
            walk_for_listings(item, base_url, out, depth + 1)
    return out


# ------------------------------------------------------------- HTML cards


def harvest_cards(soup: BeautifulSoup, href_pattern: str,
                  base_url: str, max_hops: int = 6) -> list[dict[str, Any]]:
    """Find detail-page anchors and mine the surrounding card's text.

    ``href_pattern`` is a regex the anchor's href must match. For each unique
    matching href, walk up the DOM a few levels to a container that looks like
    a self-contained card and pull price/km/year/location from its text.
    """
    seen: dict[str, dict[str, Any]] = {}
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if not re.search(href_pattern, href):
            continue
        url = urljoin(base_url, href.split("#")[0])
        if url in seen:
            continue
        card = anchor
        for _ in range(max_hops):
            if card.parent is None:
                break
            card = card.parent
            text = clean_text(card.get_text(" "))
            # A plausible card mentions a price or km reading and isn't the
            # whole page.
            if 40 < len(text) < 1200 and (re.search(r"\$[\d,]{4,}", text)
                                          or re.search(r"[\d,]+\s*km\b", text, re.I)):
                break
        text = clean_text(card.get_text(" "))
        if len(text) > 2000:  # walked up too far — use anchor text only
            text = clean_text(anchor.get_text(" "))
        title = clean_text(anchor.get_text(" "))
        if len(title) < 8:
            heading = card.find(re.compile("^h[1-6]$")) if hasattr(card, "find") else None
            if heading:
                title = clean_text(heading.get_text(" "))
        price_m = re.search(r"\$[\d,]{4,}(?:\s*(?:drive\s*away|excl\.?\s*govt|egc))?",
                            text, re.IGNORECASE)
        seen[url] = {
            "title": title or text[:120],
            "url": url,
            "card_text": text,
            "price": parse_price(text),
            "price_text": price_m.group(0) if price_m else "",
            "odometer_km": parse_km(text),
            "year": parse_year(title) or parse_year(text),
            "condition": infer_condition(text),
        }
    return list(seen.values())


def soup_of(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")
