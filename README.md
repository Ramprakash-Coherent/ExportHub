# ExportHub Scraper

Scrapes supplier companies + their products from [exporthub.com](https://www.exporthub.com)
for the keywords in `agri_keywords_master.csv`, filtered to one country at a time.

## Setup

```bash
pip install curl_cffi beautifulsoup4 pandas playwright
```

## 1. One-time session setup

exporthub.com is behind a Cloudflare JS challenge, so a `cf_clearance` cookie
must be obtained once with a real browser:

```bash
python exporthub_scraper.py --login
```

One Chrome window opens, waits for the challenge to clear, saves `eh_state.json`,
and closes itself. Everything after that runs over plain HTTP — no browser.

Re-run `--login` if you start seeing `! challenge hit - session expired`
(clearance normally lasts hours).

**Optional:** sign in inside that window before it closes. Anonymous visitors are
capped at **40 suppliers per keyword** ("Load More" redirects to signup); a
logged-in session lifts that cap and the saved state keeps your account.

## 2. Scrape

```bash
python exporthub_scraper.py                            # UAE (default), all 697 keywords
python exporthub_scraper.py --country "Saudi Arabia"   # any other country
python exporthub_scraper.py --limit 5                  # quick test, first 5 keywords
python exporthub_scraper.py --priority 1               # priority-1 keywords only
python exporthub_scraper.py --group product_goods      # only that keyword group
python exporthub_scraper.py --no-profiles              # skip profile pages (fast, fewer fields)
python exporthub_scraper.py --resume                   # continue an interrupted run
python exporthub_scraper.py --list-countries           # all 59 supported countries
```

Progress is checkpointed to `.checkpoint_<COUNTRY>.json` after every keyword, so
Ctrl-C is safe — rerun with `--resume`.

## Output

### `exporthub_companies_<COUNTRY>.csv`

One row per unique company (`company_name` is unique; duplicate site listings are
merged, keeping every `source_url` and search term).

| column | source |
|---|---|
| `id` | 1..n, sequential |
| `company_name` | search card / profile |
| `business_nature`, `no_employees`, `year_established`, `annual_turnover`, `country_region`, `main_products`, `legal_status`, `payment_terms` | profile stat tiles |
| `contact_person`, `address`, `city`, `country` | card + profile |
| `export_focus`, `registered_capital`, `ownership_status`, `export_percentage`, `factory_size`, `production_lines`, `research_team_size` | profile "Facts" block |
| `description` | About paragraph |
| `source_url` | profile URL(s), ` \| `-joined if merged |
| `product_count` | number of rows for this company in the products CSV |
| `search_term` | keyword(s) that found it, ` \| `-joined |
| `entity_role` | `Entities` column, mapped from the keyword |
| `keyword_group`, `keyword_priority` | `Group` / `Priority`, mapped from the keyword |

### `exporthub_products_<COUNTRY>.csv`

| column | notes |
|---|---|
| `id` | company id — foreign key to the companies CSV |
| `company_name` | denormalised for readability |
| `product_name` | one row per product |


## Results: UAE run (completed 2026-09-10)

| | |
|---|---|
| Keywords searched | 697 / 697 |
| Keywords with UAE suppliers | 475 (222 have none on ExportHub) |
| Companies (unique names) | **3,086** |
| Products | **5,954** |
| Profiles fetched | 3,225 / 3,225 |
| Dead profile links (HTTP 404) | 19 |

All integrity checks pass: unique `company_name`, sequential ids,
`product_count` matching product rows, valid foreign keys, 100% UAE rows.

100% filled: `company_name`, `business_nature`, `no_employees`,
`year_established`, `country_region`, `main_products`, `contact_person`,
`city`, `country`, `source_url`, `search_term`, `entity_role`,
`keyword_group`, `keyword_priority`. `description` 75%; the "Facts" fields
(`factory_size`, `export_focus`, `registered_capital`, ...) 25-33% - that is
ExportHub's own data coverage, since most suppliers publish only a short blurb.

### Operational notes from that run

* **Cloudflare clearance expires after a few hours.** A long run can outlive it.
  The scraper now raises `SessionExpired` and stops so the remaining work stays
  resumable; refresh with `--login` and continue with `--resume`.
* **Some suppliers appear in search but their profile page 404s** (19 here).
  Those are marked done and keep their search-derived fields.
* **Console encoding**: company names include Arabic/CJK text. Output goes
  through a `say()` helper and UTF-8 stdout, because the default Windows cp1252
  console otherwise raises `UnicodeEncodeError` mid-run.


## Deeper coverage: combined keyword set

`listings/` holds 51 Excel files of role-based search terms (`Entity` + `Listing`,
e.g. "Fertilizer Supplier", "Coco Peat Exporter"). These complement the master
CSV's product terms - only 101 of ~7,000 terms overlap - so merging them gives
roughly 10x the search coverage.

```bash
python build_keywords.py          # -> agri_keywords_combined.csv
python build_keywords.py --stats  # report only, write nothing
```

| source | keywords |
|---|---|
| `agri_keywords_master.csv` | 697 |
| `listings/*.xlsx` (51 files) | 7,092 rows |
| **combined, deduplicated** | **7,485** (6,788 new) |

Listing terms inherit `Group`/`Priority` from the master row for the same
entity; all 51 listing entities resolve against master (case-insensitively,
and master's two compound `"A; B"` entities are indexed per part), so no row
falls back to a default. Master rows win on any keyword collision. A `Source`
column records which file each keyword came from.

Then scrape with the bigger set:

```bash
python exporthub_scraper.py --login                              # sign in here for depth
python exporthub_scraper.py --keywords agri_keywords_combined.csv
```

Signing in during `--login` matters most at this scale: anonymous sessions cap
each keyword at 40 suppliers, so the extra keywords otherwise return more
overlap rather than more companies. Expect a long run (7,485 keywords); it is
checkpointed and resumable, and the CSVs refresh as it goes.

Sanity check on the value of merging: a 2-keyword test with new listing terms
returned 3 companies that the entire 697-keyword run had missed.




## Results by country

| country | companies | products | description fill |
|---|---|---|---|
| United Arab Emirates | **4,331** | 8,110 | 77% |
| Saudi Arabia | **2,348** | 3,508 | 85% |
| Oman | **976** | 1,477 | 78% |
| Qatar | **778** | 1,123 | 77% |
| Kuwait | **734** | 1,080 | 84% |
| Bahrain | **431** | 635 | 85% |
| **total** | **9,598** | **15,933** | |

All six pass every integrity check: unique company names, sequential ids,
`product_count` matching product rows, valid foreign keys, correct country on
every row, 0 companies left unprofiled.

Cities look right per country - Dubai/Abu Dhabi; Riyadh 1,484 / Jeddah 238;
Muscat 858; Doha 668; Kuwait City 619; Manama 370 / Al Muharraq 46.

Note: a couple of Bahrain rows show Chinese cities (e.g. "Ningbo, Bahrain").
That is ExportHub's own mislabelled data, not a filter failure - the site
itself lists those suppliers under Bahrain.

### Country ids: use the homepage dropdown, not the sidebar

The search sidebar only lists countries that have results for the *current*
keyword, so it is an incomplete source - probing 8 broad keywords never
surfaced Bahrain at all. The homepage `<select name="country">` lists all ~250
countries in the same id space (verified: UAE 2, Kuwait 123, Saudi 193,
Oman 172, Qatar 187, China 48, India 105 all matched).

```bash
python harvest_countries.py --full --update   # authoritative, ~250 countries
python harvest_countries.py --update          # sidebar probe, ~150 countries
```

`COUNTRY_IDS` now holds 249 countries. Bahrain = 23.

### The sidebar bug (fixed) - it cost ~1,400 companies

The scraper used to skip a keyword when the country's checkbox was missing from
the search sidebar. **That was wrong**: the sidebar is only a partial list. For
"Greenhouse Manufacturer" (5,000 suppliers) it showed 62 countries including
Lesotho, Mauritius and Syria while omitting Kuwait *and* Saudi Arabia - yet
POSTing `filter[]=123` anyway returned 40 Kuwaiti suppliers.

The scraper now always attempts the filter POST and decides emptiness from the
response. Re-running every country with the fix:

| country | before | after | gain |
|---|---|---|---|
| Kuwait | 502 | 734 | **+46%** |
| UAE | 3,516 | 4,331 | **+23%** |
| Saudi Arabia | 2,018 | 2,348 | **+16%** |

The gradient matches the cause: countries ExportHub lists less often in its
sidebar lost the most. Never reintroduce a "checkbox present?" guard.

### Rate limiting - important for multi-country runs

After ~2-3 hours of continuous scraping, Cloudflare stops clearing the
challenge (not just cookie expiry - a fresh browser is held at "Just a moment"
too). Cool-downs ran 30 minutes to ~2.5 hours, getting longer as the day's
volume accumulated.

Recovery that works: open the site in a real browser, let it solve the
challenge, and re-save `eh_state.json`. HTTP access returns immediately after.

`run_queue.py` automates a whole country list, including waiting out blocks and
resuming the country it was working on:

```bash
python run_queue.py --countries "Oman" "Qatar"
python run_queue.py --countries "Qatar" --interval 900 --max-wait 12
```

`auto_resume.py` does the same for a single country. Leave gaps between country
runs rather than chaining them.


## India run (GrowIQX keyword set)

| | |
|---|---|
| Keywords | 6,358 (`GrowIQX_master_keywords_G1toG7_adapted.csv`) |
| Companies | **18,075** |
| Products | **34,306** |
| Description fill | 98.4% |
| Dead profile pages | 44 (HTTP 404/500 on ExportHub's side) |

All integrity checks pass. Top cities: New Delhi 2,748, Mumbai 2,745,
Delhi 1,053, Ahmedabad 944, Chennai 824.

The GrowIQX file uses `keyword, sub_category, main_group`; `adapt_keywords.py`
maps it to the scraper schema (`Entities` <- sub_category, `Group` <-
main_group, `Priority` = 1):

```bash
python adapt_keywords.py GrowIQX_master_keywords_G1toG7.csv
python run_queue.py --countries "India" --keywords GrowIQX_master_keywords_G1toG7_adapted.csv
```

### Lessons from the India run

* **Chrome auto-updates break the session.** `cf_clearance` is bound to the
  user agent that earned it. When Chrome went 152 -> 153 the browser kept
  clearing the challenge but every scraper request still got 403. Symptom:
  browser works, HTTP doesn't. Fix: update `UA` in the scripts to match
  `navigator.userAgent`.
* **Killing the scraper mid-write can wipe the checkpoint.** One stop left
  `.checkpoint_India.json` as 20 MB of null bytes. It was rebuilt from the
  companies CSV (losing ~800 in-memory companies, re-found later). Prefer
  letting `run_queue.py` run instead of force-stopping it.
* **HTTP 522** means ExportHub's origin server is down, not a block on you -
  just wait.


## Extending the master keyword file (recommended path)

`extend_keywords.py` adds new keywords to `agri_keywords_master.csv` **in the
same pattern** - concrete 2-4 word business/facility terms, not mechanical role
variants. This is the approach that actually pays off, unlike the 7,485-keyword
listings dump.

```bash
python extend_keywords.py           # -> agri_keywords_extended.csv (919)
python extend_keywords.py --stats   # report only
python extend_keywords.py --verify  # probe new keywords live, keep productive
```

It fills thin entities (several had only 4-5 keywords vs 20-47 for the
strongest), adds regional agriculture (Gulf/MENA, Asia, Africa, LatAm) so the
file suits any `--country`, and introduces 4 entities the master lacked:
beekeeping/apiculture, mushrooms/specialty crops, post-harvest & processing
equipment, sericulture/fibre crops.

### Verified against live search (222 new keywords, UAE)

| | |
|---|---|
| productive | **207 / 222 (93%)** |
| no UAE results | 15 |
| companies found that the 697-keyword run missed | **305** |

Best performers: `Grain Silo Operator` (26 new), `Agriculture Private Equity`
(14), `CEA Industry Association` (11), `GlobalGAP Certification Body` (10).

Two files are produced:

* `agri_keywords_extended.csv` (919) - full set, **use for other countries**;
  the 15 UAE-dead keywords (Oil Palm Plantation, Pulses Exporter, ...) are kept
  because they should produce results in Malaysia, India, etc.
* `agri_keywords_extended_uae.csv` (904) - UAE-verified lean set.

### Result of running it (UAE)

| | before | after |
|---|---|---|
| companies | 3,086 | **3,516** (+430) |
| products | 5,954 | **6,743** (+789) |
| entity roles | 52 | 56 |

All integrity checks pass; 0 companies left unprofiled.

```bash
python exporthub_scraper.py --keywords agri_keywords_extended_uae.csv --resume
```

`--resume` reuses the checkpoint, so only the new keywords are scraped.

## Can the keyword count be reduced without losing coverage?

Mostly no - and the measurements are worth keeping, because the intuitive
prunings all turn out to be wrong.

**Role suffixes are the productive part, not redundancy.** Probing live UAE
results:

| keyword | UAE results |
|---|---|
| `Greenhouse Supplier` | 36 |
| `Greenhouse Manufacturer` | 40 |
| overlap between them | **0** |
| `Greenhouse` (bare noun) | **3** - misses all 76 |

So collapsing "X Supplier"/"X Manufacturer" into "X" would lose ~96% of those
companies. All 2,226 role variants are kept.

**The set is genuinely diverse.** Of 4,148 distinct concept heads in the
non-role keywords, 3,674 (89%) appear exactly once. There is no large block of
near-duplicates to remove.

**Where the real redundancy is:** deep modifier tails on a shared head. The
three `Agri Equipment {B2B, Cold Storage, Agency}` each returned 35 UAE results
for a union of 39 - heavy overlap, but each still adds 1-2 unique companies.

**Set-cover on the finished UAE run:** 281 of the 697 keywords that ran (40%)
were enough to reach 100% of the 3,225 companies. But 253 keywords were the
*only* source of at least one company, and which keywords those are is not
predictable before running them - and differs per country.

```bash
python prune_keywords.py            # -> agri_keywords_pruned.csv (6,936)
python prune_keywords.py --tail 1   # more aggressive (~6,500)
python prune_keywords.py --stats    # report only
```

The pruner drops only: single-word keywords (19% hit rate in the real run),
two suffix classes that produced nothing (`pump` 0/4, `film` 1/4), and modifier
tails beyond `--tail` per concept head. It never drops a curated master keyword
(zero UAE results does not imply zero results for another country) nor any
keyword already proven productive by a checkpoint.

Result: **7,485 -> 6,936 keywords (-7%)**, all 54 entities, all 697 master
keywords, and all 2,226 role variants retained.

### Things that do NOT speed this up

* **Skipping the search GET.** The CSRF token *is* reusable across keywords, so
  the flow can be one POST per keyword instead of GET+POST. Measured: 3.8s/kw
  vs 3.1s/kw - no gain. The server is the bottleneck, not the request count, so
  the simpler GET-then-POST flow was kept.
* **A cheap pre-flight "does this keyword have results?" probe.** It needs the
  same GET as the real search (~3s each), so probing 7,485 keywords costs ~6h
  and saves nothing.

The honest lever on runtime is scope, not cleverness: use `--priority 1`,
`--group`, or `--limit` to scrape a subset, and `--no-profiles` to skip the
per-company profile pass.

## Notes on the site

* **Country filter is a POST**, not a URL param. The form is `#country_filters`
  and needs a `_token` CSRF value plus `filter[]=<country id>`; appending
  `filter[]=2` to the URL just redirects to `signup.html`. The scraper reproduces
  the POST and then verifies each row's location actually names the target
  country, so a silently-unapplied filter yields zero rows rather than
  wrong-country data.
* **Product lists come from the profile home tab** (`.prod-del_pdnm`).
  `/<company>/products.html` looks like a fuller catalogue but actually lists
  *other* companies' products — do not use it.
* **Sparse fields are the site's own data coverage**, not a parser bug. Many
  companies publish only a short blurb with no "Facts" block, so
  `factory_size`, `export_focus`, etc. fill for a minority of rows.
* **Cloudflare fingerprinting**: for `--login`, Chrome is launched stock on
  purpose. Overriding the user agent or adding `--disable-blink-features=AutomationControlled`
  gets the session blocked. `UA` in the script must stay in sync with the browser
  that earned the cookie (the script warns if it doesn't).
