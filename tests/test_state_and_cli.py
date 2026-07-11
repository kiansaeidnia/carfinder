"""State merging semantics and a full offline end-to-end run."""

import json
from pathlib import Path

from carfinder.cli import run
from carfinder.models import Listing
from carfinder.state import active_entries, load_state, merge_run, save_state


def make_listing(source_id: str, price: int | None = 50000, source="demo",
                 query_key="kia-ev6") -> Listing:
    return Listing(source=source, source_id=source_id,
                   url=f"https://example.com/{source_id}",
                   title=f"Kia EV6 {source_id}", query_key=query_key,
                   price=price, price_text=f"${price:,}" if price else "",
                   location="Cairns, QLD", distance_km=1.0)


class TestStateMerge:
    def test_new_listing_detected(self):
        state = {"version": 1, "listings": {}, "runs": []}
        outcome = merge_run(state, [make_listing("A")], "2026-07-11", ["demo"])
        assert outcome.new_keys == ["demo:A"]
        assert state["listings"]["demo:A"]["first_seen"] == "2026-07-11"

    def test_second_run_not_new_and_price_change(self):
        state = {"version": 1, "listings": {}, "runs": []}
        merge_run(state, [make_listing("A", 50000)], "2026-07-10", ["demo"])
        outcome = merge_run(state, [make_listing("A", 48000)], "2026-07-11", ["demo"])
        assert outcome.new_keys == []
        assert outcome.price_changes == [("demo:A", 50000, 48000)]
        entry = state["listings"]["demo:A"]
        assert entry["first_seen"] == "2026-07-10"
        assert entry["last_seen"] == "2026-07-11"
        assert entry["price_history"] == [["2026-07-10", 50000], ["2026-07-11", 48000]]

    def test_vanish_only_when_source_scraped_ok(self):
        state = {"version": 1, "listings": {}, "runs": []}
        merge_run(state, [make_listing("A")], "2026-07-10", ["demo"])
        # Next run: source failed -> listing must NOT be marked vanished.
        outcome = merge_run(state, [], "2026-07-11", [])
        assert outcome.vanished_keys == []
        assert state["listings"]["demo:A"]["active"] is True
        # Next run: source ok and listing gone -> vanished.
        outcome = merge_run(state, [], "2026-07-12", ["demo"])
        assert outcome.vanished_keys == ["demo:A"]
        assert state["listings"]["demo:A"]["active"] is False

    def test_sparse_rescrape_keeps_known_fields(self):
        state = {"version": 1, "listings": {}, "runs": []}
        rich = make_listing("A")
        rich.odometer_km = 12345
        merge_run(state, [rich], "2026-07-10", ["demo"])
        sparse = make_listing("A")
        sparse.odometer_km = None
        merge_run(state, [sparse], "2026-07-11", ["demo"])
        assert state["listings"]["demo:A"]["odometer_km"] == 12345

    def test_state_roundtrip(self, tmp_path: Path):
        state = {"version": 1, "listings": {}, "runs": []}
        merge_run(state, [make_listing("A")], "2026-07-11", ["demo"])
        path = tmp_path / "listings.json"
        save_state(path, state)
        loaded = load_state(path)
        assert loaded["listings"]["demo:A"]["title"] == "Kia EV6 A"
        assert len(active_entries(loaded)) == 1


class TestEndToEndDemo:
    def test_demo_run_produces_outputs(self, tmp_path: Path):
        out = tmp_path / "data"
        code = run(["--sources", "demo", "--out", str(out), "--radius", "250"])
        assert code == 0
        for name in ("listings.json", "latest.csv", "report.html",
                     "run-summary.md", "run-summary.json", "new-listings.md"):
            assert (out / name).exists(), name

        summary = json.loads((out / "run-summary.json").read_text())
        # Radius 250 keeps: EV6 Cairns, Sealion 7 Premium Smithfield,
        # Solterra Portsmith. Drops: EV6 Townsville (~284 km), Sealion 7
        # Performance Brisbane. Regex drops the Sealion 6 outright.
        assert summary["active"] == 3
        assert summary["new"] == 3

        csv_text = (out / "latest.csv").read_text()
        assert "DEMO-1001" in csv_text            # Cairns EV6
        assert "DEMO-2001" in csv_text            # Smithfield Sealion 7 Premium
        assert "DEMO-3001" in csv_text            # Portsmith Solterra
        assert "DEMO-1002" not in csv_text        # Townsville: outside 250 km
        assert "DEMO-2002" not in csv_text        # Brisbane: outside 250 km
        assert "Sealion 6" not in csv_text        # wrong model

        html = (out / "report.html").read_text()
        assert "Sealion 7 Premium" in html
        assert "NEW" in html
        assert "⭐" in html                        # premium variant starred

    def test_wider_radius_keeps_townsville(self, tmp_path: Path):
        out = tmp_path / "data"
        code = run(["--sources", "demo", "--out", str(out), "--radius", "600"])
        assert code == 0
        csv_text = (out / "latest.csv").read_text()
        assert "DEMO-1002" in csv_text

    def test_strict_variant_drops_non_premium_sealion(self, tmp_path: Path):
        out = tmp_path / "data"
        code = run(["--sources", "demo", "--out", str(out), "--radius", "3000",
                    "--strict-variant"])
        assert code == 0
        csv_text = (out / "latest.csv").read_text()
        assert "DEMO-2001" in csv_text            # Premium kept
        assert "DEMO-2002" not in csv_text        # Performance dropped
        assert "DEMO-1001" in csv_text            # EV6 unaffected by strictness

    def test_second_run_no_new(self, tmp_path: Path):
        out = tmp_path / "data"
        assert run(["--sources", "demo", "--out", str(out)]) == 0
        assert run(["--sources", "demo", "--out", str(out)]) == 0
        summary = json.loads((out / "run-summary.json").read_text())
        assert summary["new"] == 0
        assert not (out / "new-listings.md").exists()

    def test_unknown_source_rejected(self, tmp_path: Path):
        assert run(["--sources", "nope", "--out", str(tmp_path / "d")]) == 2
