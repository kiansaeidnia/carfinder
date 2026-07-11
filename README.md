# carfinder 🚗

Watches Australian car listing sites for three EVs near **Cairns, QLD**:

| Model | Notes |
|---|---|
| **Kia EV6** | any variant |
| **BYD Sealion 7** | all variants listed; **Premium** gets a ⭐ (use `--strict-variant` to keep only Premium) |
| **Subaru Solterra** | any variant (also matches the common "Soltera" misspelling in ads) |

Sources: **carsales**, **autotrader**, **carsguide**, **gumtree**, **drive** —
each scraped politely (throttled, a handful of pages per model per day).
Facebook Marketplace is deliberately not included: it requires a logged-in
session and aggressively blocks automation.

Results are filtered to a radius around Cairns (default **250 km**
straight-line — Port Douglas, the Tablelands, Innisfail, Tully, Cooktown; use
`--radius 600` to reach Townsville, or bigger to go state-wide). Listings whose
suburb can't be resolved are kept and marked `?` rather than silently dropped —
for cars this rare a false inclusion beats a miss. Interstate listings are
excluded.

## Quick start (run it yourself)

```bash
pip install -r requirements.txt
python -m carfinder
```

Outputs land in `data/`:

- **`report.html`** — the human-friendly report: grouped by model, sorted by
  distance, NEW badges, ⭐ variant matches, per-source status.
- **`latest.csv`** — same data for spreadsheets.
- **`listings.json`** — history: first/last seen, price history, vanished ads.
- **`run-summary.md` / `run-summary.json`** — run stats.

Useful flags:

```text
--radius 600            widen the search (km, straight-line from Cairns)
--origin "lat,lng"      watch somewhere else entirely
--strict-variant        Sealion 7: keep only the Premium variant
--sources carsales,gumtree     limit sources
--queries kia-ev6              limit models
--drop-unknown          drop listings whose distance can't be resolved
--dump-html DIR         save every fetched page (debugging)
--playwright never      disable the headless-browser fallback
```

### Better hit-rate against bot protection

carsales (and sometimes others) sit behind Kasada; plain HTTP requests are
usually rejected. With Playwright installed the scraper automatically retries
challenged pages in headless Chromium:

```bash
pip install playwright
playwright install chromium
```

Best results come from running on a residential connection (your home
internet) rather than cloud/datacenter IPs, which these sites distrust.

## The daily watcher

`.github/workflows/watch.yml` runs every morning at **06:00 Cairns time**, and
can be run on demand from the Actions tab (**Run workflow**). Each run:

1. scrapes all sources (with the Playwright fallback),
2. commits refreshed `data/` to the repo,
3. appends a readable summary to the workflow run page,
4. **opens a GitHub issue assigned to you whenever new listings or price
   changes appear** — that's your notification channel (GitHub emails you),
5. uploads `report.html`/`latest.csv` and the raw fetched pages as artifacts.

Quiet days produce no issue and no noise. A listing is only marked *vanished*
(sold/withdrawn) when its source scraped successfully without it — a blocked
site never makes cars look sold.

### Expectations, honestly stated

Scrapers live downstream of sites that change markup and tune anti-bot
systems whenever they like. This tool is built to degrade gracefully — every
run reports per-source status (`ok` / blocked / parse-failure) in the report
footer and job summary instead of pretending.

**Verified behaviour from GitHub-hosted runners** (shakedown runs on
2026-07-11): carsales, autotrader, carsguide and gumtree all answer 403 to
GitHub's datacenter IPs — even through the headless-browser fallback — so on
Actions they will show as blocked in the summary. **drive.com.au works from
Actions** and is what the daily watcher effectively monitors. Your home
connection is a normal shopper to all five sites, so `python -m carfinder`
run locally is expected to give full coverage — that's the recommended way
to do a proper sweep, with the Actions run as your automated daily lookout.

If you want full-coverage automation, add a
[self-hosted runner](https://docs.github.com/en/actions/hosting-your-own-runners)
on a home machine and switch `runs-on` in the workflow — the watcher then
scrapes from your residential IP on schedule. If a source shows persistent
parse failures, its diagnostics (page title, URL samples, harvested objects)
are right in the Actions log, and `--dump-html DIR` saves the raw pages.

## Tweaking

- **Models**: edit `carfinder/config.py` (`QUERIES` + per-site slugs in each
  source module).
- **Schedule**: cron in `.github/workflows/watch.yml`.
- **Radius/flags in the watcher**: edit the `python -m carfinder` line there.
- **Localities**: `carfinder/geo.py` maps suburbs/postcodes to coordinates for
  distance filtering; add any the report shows as `?`.

## Development

```bash
pip install -r requirements.txt pytest
python -m pytest tests/ -q       # 47 offline tests
python -m carfinder --sources demo   # full pipeline on fake data, no network
```

## Fair use

Personal, low-volume use only: a few pages per site per day, throttled, for
your own car search. Don't redistribute the data; it belongs to the
respective sites. Check each site's terms before cranking anything up.
