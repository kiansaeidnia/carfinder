"""CSV, HTML and Markdown outputs for a scrape run."""

from __future__ import annotations

import csv
import html
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import QUERIES_BY_KEY
from .models import SourceResult

CSV_COLUMNS = [
    "query_key", "source", "source_id", "title", "year", "variant", "price",
    "price_text", "odometer_km", "condition", "location", "distance_km",
    "variant_match", "first_seen", "last_seen", "url",
]


def _fmt_price(entry: dict[str, Any]) -> str:
    if entry.get("price"):
        return f"${entry['price']:,}"
    return entry.get("price_text") or "—"


def _fmt_km(entry: dict[str, Any]) -> str:
    km = entry.get("odometer_km")
    return f"{km:,} km" if km is not None else "—"


def _fmt_distance(entry: dict[str, Any]) -> str:
    d = entry.get("distance_km")
    if d is None:
        return "?"
    return f"{d:.0f} km"


def _sort_key(entry: dict[str, Any]):
    d = entry.get("distance_km")
    p = entry.get("price")
    return (d is None, d if d is not None else 0,
            p is None, p if p is not None else 0)


def write_csv(path: Path, entries: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for entry in sorted(entries, key=lambda e: (e.get("query_key", ""), *_sort_key(e))):
            writer.writerow({k: entry.get(k, "") for k in CSV_COLUMNS})


def render_markdown_summary(entries: list[dict[str, Any]], new_keys: list[str],
                            price_changes: list[tuple[str, int, int]],
                            results: list[SourceResult], run_date: str,
                            radius_km: float, origin_name: str) -> str:
    """Markdown used for the GitHub job summary and new-listing issues."""
    lines = [f"# Car watch — {run_date}",
             "",
             f"Search: within ~{radius_km:.0f} km of {origin_name} "
             f"(straight-line), plus QLD listings with unknown distance.",
             ""]
    by_key = {e["source"] + ":" + e["source_id"]: e for e in entries}

    new_entries = [by_key[k] for k in new_keys if k in by_key]
    lines.append(f"## New since last run: {len(new_entries)}")
    lines.append("")
    if new_entries:
        for e in sorted(new_entries, key=_sort_key):
            star = " ⭐" if e.get("variant_match") else ""
            lines.append(
                f"- **{e.get('title', '?')}**{star} — {_fmt_price(e)}, {_fmt_km(e)}, "
                f"{e.get('location') or '?'} ({_fmt_distance(e)} away) — "
                f"[{e.get('source')}]({e.get('url')})")
    else:
        lines.append("_none_")
    lines.append("")

    if price_changes:
        lines.append("## Price changes")
        lines.append("")
        for key, old, new in price_changes:
            e = by_key.get(key)
            if not e:
                continue
            arrow = "🔻" if new < old else "🔺"
            lines.append(f"- {arrow} **{e.get('title', '?')}** — ${old:,} → ${new:,} "
                         f"([{e.get('source')}]({e.get('url')}))")
        lines.append("")

    lines.append(f"## All current matches: {len(entries)}")
    lines.append("")
    for qkey, query in QUERIES_BY_KEY.items():
        group = [e for e in entries if e.get("query_key") == qkey]
        lines.append(f"### {query.make} {query.model} — {len(group)}")
        lines.append("")
        for e in sorted(group, key=_sort_key):
            star = " ⭐" if e.get("variant_match") else ""
            lines.append(
                f"- {e.get('title', '?')}{star} — {_fmt_price(e)}, {_fmt_km(e)}, "
                f"{e.get('location') or '?'} ({_fmt_distance(e)}) — "
                f"[{e.get('source')}]({e.get('url')})")
        if not group:
            lines.append("_none found_")
        lines.append("")

    lines.append("## Source status")
    lines.append("")
    lines.append("| Source | Model | Status | Raw hits | Kept |")
    lines.append("|---|---|---|---:|---:|")
    for r in results:
        status = "✅ ok" if r.ok else f"❌ {r.error}"
        lines.append(f"| {r.source} | {r.query_key} | {status} | {r.raw_count} "
                     f"| {len(r.listings)} |")
    return "\n".join(lines) + "\n"


_CSS = """
:root { --bg:#fff; --fg:#1a1a1a; --muted:#666; --card:#f6f6f6; --accent:#0b6e4f;
        --new:#ffd166; --border:#ddd; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#121212; --fg:#eee; --muted:#aaa; --card:#1e1e1e;
          --accent:#4cc9a4; --new:#b8860b; --border:#333; }
}
* { box-sizing: border-box; }
body { margin:0 auto; max-width:1080px; padding:24px 16px; background:var(--bg);
       color:var(--fg); font:15px/1.5 system-ui,-apple-system,'Segoe UI',sans-serif; }
h1 { font-size:1.5em; } h2 { font-size:1.2em; margin-top:1.6em; }
.meta { color:var(--muted); font-size:0.9em; }
table { border-collapse:collapse; width:100%; font-size:0.92em; }
th, td { text-align:left; padding:7px 9px; border-bottom:1px solid var(--border);
         vertical-align:top; }
th { position:sticky; top:0; background:var(--bg); }
td.num { text-align:right; white-space:nowrap; }
.badge-new { background:var(--new); color:#000; border-radius:4px; padding:1px 6px;
             font-size:0.8em; font-weight:600; margin-left:6px; }
.star { color:var(--accent); font-weight:700; }
a { color:var(--accent); }
.wrap { overflow-x:auto; }
.status-ok { color:var(--accent); } .status-bad { color:#c0392b; }
.footer { margin-top:2.5em; color:var(--muted); font-size:0.85em; }
"""


def render_html(entries: list[dict[str, Any]], new_keys: list[str],
                results: list[SourceResult], run_date: str,
                radius_km: float, origin_name: str) -> str:
    new_set = set(new_keys)

    def esc(value: Any) -> str:
        return html.escape(str(value if value is not None else "—"))

    sections = []
    for qkey, query in QUERIES_BY_KEY.items():
        group = sorted([e for e in entries if e.get("query_key") == qkey], key=_sort_key)
        rows = []
        for e in group:
            key = f"{e.get('source')}:{e.get('source_id')}"
            badge = '<span class="badge-new">NEW</span>' if key in new_set else ""
            star = ' <span class="star" title="variant match">⭐</span>' if e.get("variant_match") else ""
            rows.append(
                "<tr>"
                f"<td><a href=\"{esc(e.get('url'))}\" target=\"_blank\" rel=\"noopener\">"
                f"{esc(e.get('title'))}</a>{star}{badge}</td>"
                f"<td class=\"num\">{esc(_fmt_price(e))}</td>"
                f"<td class=\"num\">{esc(_fmt_km(e))}</td>"
                f"<td>{esc(e.get('condition'))}</td>"
                f"<td>{esc(e.get('location'))}</td>"
                f"<td class=\"num\">{esc(_fmt_distance(e))}</td>"
                f"<td>{esc(e.get('source'))}</td>"
                f"<td class=\"num\">{esc(e.get('first_seen'))}</td>"
                "</tr>")
        body = ("\n".join(rows) if rows else
                '<tr><td colspan="8"><em>none found</em></td></tr>')
        sections.append(
            f"<h2>{esc(query.make)} {esc(query.model)} "
            f"<span class=\"meta\">({len(group)})</span></h2>\n"
            '<div class="wrap"><table>\n'
            "<tr><th>Listing</th><th>Price</th><th>Odometer</th><th>Cond.</th>"
            "<th>Location</th><th>Distance</th><th>Source</th><th>First seen</th></tr>\n"
            f"{body}\n</table></div>")

    status_rows = "\n".join(
        "<tr>"
        f"<td>{esc(r.source)}</td><td>{esc(r.query_key)}</td>"
        f"<td class=\"{'status-ok' if r.ok else 'status-bad'}\">"
        f"{'ok' if r.ok else esc(r.error)}</td>"
        f"<td class=\"num\">{r.raw_count}</td><td class=\"num\">{len(r.listings)}</td>"
        f"<td>{esc(r.engine)}</td>"
        "</tr>" for r in results)

    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cairns car watch — {esc(run_date)}</title>
<style>{_CSS}</style></head><body>
<h1>🚗 Cairns car watch</h1>
<p class="meta">Run {esc(run_date)} · within ~{radius_km:.0f} km of {esc(origin_name)}
(straight-line) · Kia EV6 / BYD Sealion 7 (⭐ = Premium) / Subaru Solterra ·
{len(entries)} active listings · {len(new_keys)} new</p>
{''.join(sections)}
<h2>Source status</h2>
<div class="wrap"><table>
<tr><th>Source</th><th>Model</th><th>Status</th><th>Raw</th><th>Kept</th><th>Engine</th></tr>
{status_rows}
</table></div>
<p class="footer">Generated {esc(generated)} by carfinder. Distances are
straight-line from {esc(origin_name)}; "?" = locality not recognised (listing
kept rather than dropped). Listings vanish from this report once their ad is
removed. Data belongs to the respective sites — personal use only.</p>
</body></html>
"""
