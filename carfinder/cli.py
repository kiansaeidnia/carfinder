"""Command-line entry point: scrape, filter, track, report."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import geo
from .config import QUERIES, QUERIES_BY_KEY
from .http import Fetcher
from .models import Listing, RunConfig, SourceResult
from .report import render_html, render_markdown_summary, write_csv
from .sources import ALL_SOURCES, DEFAULT_SOURCES
from .state import active_entries, load_state, merge_run, save_state

log = logging.getLogger("carfinder")

EXIT_OK = 0
EXIT_ALL_SOURCES_FAILED = 3


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="carfinder",
        description="Watch AU car sites for a Kia EV6 / BYD Sealion 7 / "
                    "Subaru Solterra near Cairns.")
    p.add_argument("--radius", type=float, default=250.0,
                   help="max straight-line distance from origin in km (default 250)")
    p.add_argument("--origin", default="-16.9186,145.7781",
                   help="origin as 'lat,lng' (default: Cairns)")
    p.add_argument("--origin-name", default="Cairns QLD 4870")
    p.add_argument("--sources", default=",".join(DEFAULT_SOURCES),
                   help=f"comma-separated sources (available: {', '.join(ALL_SOURCES)})")
    p.add_argument("--queries", default=",".join(q.key for q in QUERIES),
                   help="comma-separated model keys "
                        f"(available: {', '.join(q.key for q in QUERIES)})")
    p.add_argument("--strict-variant", action="store_true",
                   help="Sealion 7: keep only listings matching the Premium variant")
    p.add_argument("--drop-unknown", action="store_true",
                   help="drop listings whose distance can't be determined "
                        "(default: keep QLD/unknown-state ones, flagged '?')")
    p.add_argument("--max-pages", type=int, default=3,
                   help="max result pages per source per model (default 3)")
    p.add_argument("--delay", type=float, default=2.0,
                   help="seconds between requests (default 2)")
    p.add_argument("--out", default="data", help="output directory (default data/)")
    p.add_argument("--dump-html", metavar="DIR", default=None,
                   help="save every fetched page to DIR for debugging")
    p.add_argument("--playwright", choices=["auto", "always", "never"], default="auto",
                   help="browser fallback for bot-challenged sites (default auto)")
    p.add_argument("--no-state", action="store_true",
                   help="don't read/write listing history (report only)")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def geo_filter(listings: list[Listing], cfg: RunConfig) -> list[Listing]:
    kept: list[Listing] = []
    origin = (cfg.origin_lat, cfg.origin_lng)
    for listing in listings:
        listing.state = geo.extract_state(listing.location)
        listing.distance_km = geo.distance_km(listing.location, origin)
        if listing.distance_km is not None:
            if listing.distance_km <= cfg.radius_km:
                kept.append(listing)
            continue
        # Unknown distance: interstate is certainly out of range of any sane
        # Cairns radius; QLD/unknown stays in (flagged) unless --drop-unknown.
        if cfg.drop_unknown_distance:
            continue
        if listing.state in (None, "QLD"):
            listing.extra["unknown_distance"] = True
            kept.append(listing)
    return kept


def dedupe_across_sources(listings: list[Listing]) -> list[Listing]:
    """Same physical car advertised on several sites: keep all copies but
    note the duplication so the report reader isn't double-counting."""
    groups: dict[tuple, list[Listing]] = {}
    for listing in listings:
        if listing.price is None or listing.year is None:
            continue
        loc = (listing.location or "").lower().split(",")[0].strip()
        groups.setdefault((listing.query_key, listing.year, listing.price, loc),
                          []).append(listing)
    for group in groups.values():
        if len(group) > 1:
            sources = {l.source for l in group}
            if len(sources) > 1:
                for listing in group:
                    others = sorted(sources - {listing.source})
                    listing.extra["also_on"] = others
    return listings


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s")

    try:
        lat, lng = (float(x) for x in args.origin.split(","))
    except ValueError:
        print(f"error: --origin must be 'lat,lng', got {args.origin!r}", file=sys.stderr)
        return 2

    cfg = RunConfig(origin_name=args.origin_name, origin_lat=lat, origin_lng=lng,
                    radius_km=args.radius, strict_variant=args.strict_variant,
                    drop_unknown_distance=args.drop_unknown,
                    max_pages=args.max_pages, request_delay=args.delay,
                    dump_dir=args.dump_html, use_playwright=args.playwright)

    source_names = [s.strip() for s in args.sources.split(",") if s.strip()]
    unknown = [s for s in source_names if s not in ALL_SOURCES]
    if unknown:
        print(f"error: unknown source(s): {', '.join(unknown)}", file=sys.stderr)
        return 2
    query_keys = [q.strip() for q in args.queries.split(",") if q.strip()]
    unknown_q = [q for q in query_keys if q not in QUERIES_BY_KEY]
    if unknown_q:
        print(f"error: unknown query key(s): {', '.join(unknown_q)}", file=sys.stderr)
        return 2
    queries = [QUERIES_BY_KEY[k] for k in query_keys]

    run_date = datetime.now(ZoneInfo("Australia/Brisbane")).strftime("%Y-%m-%d")
    out_dir = Path(args.out)
    fetcher = Fetcher(delay=cfg.request_delay, timeout=cfg.timeout,
                      dump_dir=cfg.dump_dir, use_playwright=cfg.use_playwright)

    results: list[SourceResult] = []
    try:
        for name in source_names:
            source = ALL_SOURCES[name]()
            for query in queries:
                log.info("searching %s for %s %s ...", name, query.make, query.model)
                try:
                    result = source.search(query, cfg, fetcher)
                except Exception as exc:  # a broken source must not kill the run
                    log.exception("source %s crashed on %s", name, query.key)
                    result = SourceResult(source=name, query_key=query.key,
                                          ok=False, error=f"crash: {exc}")
                results.append(result)
                log.info("  -> %d raw, %d matched, ok=%s",
                         result.raw_count, len(result.listings), result.ok)
    finally:
        fetcher.close()

    all_listings = [l for r in results for l in r.listings]
    if cfg.strict_variant:
        all_listings = [l for l in all_listings
                        if QUERIES_BY_KEY[l.query_key].highlight_variant is None
                        or l.variant_match]
    filtered = geo_filter(all_listings, cfg)
    filtered = dedupe_across_sources(filtered)

    # ---- persistence + outputs
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path = out_dir / "listings.json"
    state = load_state(state_path) if not args.no_state else \
        {"version": 1, "listings": {}, "runs": []}
    sources_ok = sorted({r.source for r in results if r.ok})
    outcome = merge_run(state, filtered, run_date, sources_ok)
    if not args.no_state:
        save_state(state_path, state)

    entries = sorted(active_entries(state),
                     key=lambda e: (e.get("query_key", ""),
                                    e.get("distance_km") is None,
                                    e.get("distance_km") or 0))
    write_csv(out_dir / "latest.csv", entries)
    summary_md = render_markdown_summary(entries, outcome.new_keys,
                                         outcome.price_changes, results,
                                         run_date, cfg.radius_km, cfg.origin_name)
    (out_dir / "run-summary.md").write_text(summary_md, encoding="utf-8")
    (out_dir / "report.html").write_text(
        render_html(entries, outcome.new_keys, results, run_date,
                    cfg.radius_km, cfg.origin_name), encoding="utf-8")

    # Machine-readable run stats for CI.
    (out_dir / "run-summary.json").write_text(json.dumps({
        "date": run_date,
        "active": len(entries),
        "new": len(outcome.new_keys),
        "price_changes": len(outcome.price_changes),
        "vanished": len(outcome.vanished_keys),
        "sources": [{"source": r.source, "query": r.query_key, "ok": r.ok,
                     "raw": r.raw_count, "kept": len(r.listings),
                     "engine": r.engine, "error": r.error, "url": r.url_used}
                    for r in results],
    }, indent=1), encoding="utf-8")

    # New-listings file only exists when there is something to announce —
    # CI uses its presence to decide whether to open an issue.
    new_md_path = out_dir / "new-listings.md"
    if outcome.new_keys or outcome.price_changes:
        by_key = {e["source"] + ":" + e["source_id"]: e for e in entries}
        lines = [f"New matches on {run_date} within ~{cfg.radius_km:.0f} km of "
                 f"{cfg.origin_name}:", ""]
        for key in outcome.new_keys:
            e = by_key.get(key)
            if not e:
                continue
            star = " ⭐" if e.get("variant_match") else ""
            price = f"${e['price']:,}" if e.get("price") else (e.get("price_text") or "price n/a")
            km = f"{e['odometer_km']:,} km" if e.get("odometer_km") is not None else "odo n/a"
            dist = f"{e['distance_km']:.0f} km away" if e.get("distance_km") is not None \
                else "distance unknown"
            lines.append(f"- **{e.get('title')}**{star} — {price}, {km}, "
                         f"{e.get('location') or '?'} ({dist}) — "
                         f"[{e.get('source')}]({e.get('url')})")
        for key, old, new in outcome.price_changes:
            e = by_key.get(key)
            if not e:
                continue
            arrow = "🔻" if new < old else "🔺"
            lines.append(f"- {arrow} price change: **{e.get('title')}** "
                         f"${old:,} → ${new:,} ([{e.get('source')}]({e.get('url')}))")
        lines += ["", f"Full report: see `data/report.html` / `data/latest.csv`."]
        new_md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    elif new_md_path.exists():
        new_md_path.unlink()

    # ---- console output
    print(f"\n{'=' * 62}")
    print(f"carfinder run {run_date} — {len(entries)} active listings, "
          f"{len(outcome.new_keys)} new, {len(outcome.price_changes)} price changes")
    for r in results:
        status = "ok " if r.ok else "FAIL"
        print(f"  [{status}] {r.source:<10} {r.query_key:<16} raw={r.raw_count:<3} "
              f"kept={len(r.listings):<3} {r.error or ''}")
    print(f"outputs in {out_dir}/  (report.html, latest.csv, run-summary.md)")
    print("=" * 62)

    if results and not any(r.ok for r in results):
        return EXIT_ALL_SOURCES_FAILED
    return EXIT_OK


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
