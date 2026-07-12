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
Actions** and is what the daily watcher effectively monitors.

## Getting the blocked sites to work

The block is about **IP reputation, not cleverness**. carsales and friends run
Kasada/Cloudflare-class bot protection that scores the connection's IP and
behaviour; datacenter/cloud IPs (like GitHub's) are distrusted no matter what
headers a scraper sends. That's deliberate on their part, and it's why the
right fix is to look like the ordinary shopper you are — from an ordinary
connection — rather than to try to defeat the protection itself.

In rough order of effort vs. payoff:

1. **Run it from home.** Your home internet is a residential IP these sites
   trust. `python -m carfinder` on your own machine (with Playwright installed,
   see above) is expected to reach all five. This is the recommended way to do
   a proper sweep; treat the daily Actions run as the automated lookout on top.

2. **Turn on the sites' own "saved search" email alerts.** This is the most
   reliable notifier for the four sites that block datacenter IPs, and it needs
   no scraping at all — the site emails you when a new match is listed:
   - carsales — save your EV6 / Sealion 7 / Solterra search, enable email alerts
   - CarsGuide, Autotrader, Gumtree, Drive — same "save search / notify me" flow
   Set the location to Cairns + your radius and let carfinder cover drive.com.au
   plus anything you run locally. Between the two you miss very little.

3. **Automate from a residential IP with a self-hosted runner.** Install a
   [self-hosted GitHub runner](https://docs.github.com/en/actions/hosting-your-own-runners)
   on a machine at home (an always-on mini-PC or a Raspberry Pi is plenty),
   then change `runs-on: ubuntu-latest` to `runs-on: self-hosted` in
   `.github/workflows/watch.yml`. The daily job then scrapes from your home IP
   on schedule — full coverage, fully automated. (Add `PLAYWRIGHT_*` browser
   setup to the runner, or run `--playwright never` and accept lighter parsing.)

4. **Go to the source for brand-new stock.** Kia/Subaru/BYD each have a
   "locate a car" / stock-locator tool, and the Cairns dealers list their own
   inventory. For MY26 cars that barely exist used yet, a saved alert at the
   dealer is often faster than any marketplace.

### What this tool deliberately does not do

It won't try to defeat the anti-bot systems themselves — no CAPTCHA-solving
services, no reverse-engineered Kasada/Cloudflare challenge tokens, no
residential-proxy rotation to evade an IP ban. That crosses from "scrape
politely" into circumventing access controls (against these sites' terms, and
a good way to get an IP or account banned), and against Kasada from a
datacenter IP it doesn't reliably work anyway. The residential-IP routes above
are the honest and the effective answer at once.

If a source shows persistent parse failures (as opposed to a block), its
diagnostics — page title, URL samples, harvested objects — are right in the
Actions log, and `--dump-html DIR` saves the raw pages so a selector can be
fixed.

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
python -m pytest tests/ -q       # 63 offline tests
python -m carfinder --sources demo   # full pipeline on fake data, no network
```

## Fair use

Personal, low-volume use only: a few pages per site per day, throttled, for
your own car search. Don't redistribute the data; it belongs to the
respective sites. Check each site's terms before cranking anything up.
