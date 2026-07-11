"""Persistent listing history: what's new, what changed price, what vanished."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import Listing

STATE_VERSION = 1


@dataclass
class MergeOutcome:
    new_keys: list[str] = field(default_factory=list)
    price_changes: list[tuple[str, int, int]] = field(default_factory=list)  # key, old, new
    vanished_keys: list[str] = field(default_factory=list)


def load_state(path: Path) -> dict[str, Any]:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "listings" in data:
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"version": STATE_VERSION, "listings": {}, "runs": []}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1, ensure_ascii=False, sort_keys=True),
                    encoding="utf-8")


def merge_run(state: dict[str, Any], listings: list[Listing], run_date: str,
              sources_ok: list[str]) -> MergeOutcome:
    """Fold one scrape run into the state (mutates ``state``).

    A listing is only marked vanished when its source scraped successfully in
    this run but the listing wasn't there — a blocked source must not make its
    cars look sold.
    """
    outcome = MergeOutcome()
    entries: dict[str, Any] = state["listings"]
    seen_keys = set()

    for listing in listings:
        key = listing.key
        seen_keys.add(key)
        entry = entries.get(key)
        if entry is None:
            entry = listing.to_dict()
            entry["first_seen"] = run_date
            entry["last_seen"] = run_date
            entry["active"] = True
            entry["price_history"] = ([[run_date, listing.price]]
                                      if listing.price is not None else [])
            entries[key] = entry
            outcome.new_keys.append(key)
            continue
        old_price = entry.get("price")
        fresh = listing.to_dict()
        # Never let a sparse re-scrape blank out fields we already knew;
        # variant_match is a recomputed bool, so False is a real value there.
        for field_name, value in fresh.items():
            if value not in (None, "", [], {}, False) or field_name == "variant_match":
                entry[field_name] = value
        entry["last_seen"] = run_date
        entry["active"] = True
        entry.pop("vanished_on", None)  # it's back (relisted or was missed)
        if (listing.price is not None and old_price is not None
                and listing.price != old_price):
            outcome.price_changes.append((key, old_price, listing.price))
            entry.setdefault("price_history", []).append([run_date, listing.price])
        elif listing.price is not None and not entry.get("price_history"):
            entry["price_history"] = [[run_date, listing.price]]

    for key, entry in entries.items():
        if key in seen_keys or not entry.get("active"):
            continue
        if entry.get("source") in sources_ok:
            entry["active"] = False
            entry["vanished_on"] = run_date
            outcome.vanished_keys.append(key)

    state["runs"] = (state.get("runs") or [])[-29:] + [{
        "date": run_date,
        "total_active": sum(1 for e in entries.values() if e.get("active")),
        "new": len(outcome.new_keys),
        "sources_ok": sources_ok,
    }]
    return outcome


def active_entries(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [e for e in state["listings"].values() if e.get("active")]
