"""
ExportHub.com country-specific supplier scraper.

Scrapes suppliers from exporthub.com for a list of keywords, filtered to a
target country, and writes two CSVs:

  1. exporthub_companies_<COUNTRY>.csv  - one row per unique company
  2. exporthub_products_<COUNTRY>.csv   - one row per product, `id` = company id

How it works
------------
exporthub.com sits behind a Cloudflare JS challenge, so a `cf_clearance` cookie
has to be obtained once with a real browser. After that the whole scrape runs
over plain HTTP via curl_cffi (Chrome TLS impersonation) -- nothing stays open,
which is far faster than driving a browser and spawns no windows.

One-time session setup (~30s):

    python exporthub_scraper.py --login

That opens a single Chrome window, waits for the challenge to clear, saves
`eh_state.json`, and closes. Reuse it for later runs; redo it if you start
seeing "challenge hit" warnings (clearance usually lasts hours).

The country filter is a POST to the search URL (form `#country_filters`) with a
`_token` CSRF value plus `filter[]=<country id>`. The URL never changes and GET
params are ignored, so the scraper reproduces that POST.

Usage
-----
    python exporthub_scraper.py --login                   # one-time setup
    python exporthub_scraper.py                           # UAE, all 697 keywords
    python exporthub_scraper.py --country "Saudi Arabia"  # any other country
    python exporthub_scraper.py --limit 5                 # quick test
    python exporthub_scraper.py --priority 1              # priority-1 keywords only
    python exporthub_scraper.py --resume                  # continue an interrupted run
    python exporthub_scraper.py --list-countries

Note: anonymous visitors get at most 40 suppliers per keyword ("Load More"
redirects to signup.html). Sign in inside the --login window to lift that cap;
the saved session then carries your account.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
import time
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup
from curl_cffi import requests as cr

BASE = "https://www.exporthub.com"
HERE = Path(__file__).resolve().parent
KEYWORDS_CSV = HERE / "agri_keywords_master.csv"
STATE_FILE = HERE / "eh_state.json"

# cf_clearance is bound to the UA that earned it - keep these in sync.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36")

# Country name -> ExportHub filter id, taken from the site's own "country"
# <select> on the homepage (the same id space the search-sidebar checkboxes
# use, verified against 7 known ids). This is authoritative - unlike the
# search sidebar, which only lists countries with results for the current
# keyword and is missing ~100 countries including Bahrain (id 23).
# Regenerate with: python harvest_countries.py --full
COUNTRY_IDS = {
  "Afghanistan": 3, "Aland Islands": 15, "Albania": 6, "Algeria": 62,
  "American Samoa": 11, "Andorra": 1, "Angola": 8, "Anguilla": 5,
  "Antarctica": 9, "Antigua And Barbuda": 4, "Argentina": 10, "Armenia": 7,
  "Aruba": 14, "Australia": 13, "Austria": 12, "Azerbaijan": 16,
  "Bahamas": 32, "Bahrain": 23, "Bangladesh": 19, "Barbados": 18,
  "Belarus": 36, "Belgium": 20, "Belize": 37, "Benin": 25, "Bermuda": 27,
  "Bhutan": 33, "Bolivia": 29, "Bonaire": 30, "Bosnia Herzegovina": 17,
  "Botswana": 35, "Bouvet Island": 34, "Brazil": 31,
  "British Indian Ocean Territory": 106, "Brunei": 28, "Bulgaria": 22,
  "Burkina Faso": 21, "Burundi": 24, "Cambodia": 117, "Cameroon": 47,
  "Canada": 38, "Cape Verde": 52, "Cayman Islands": 124,
  "Central African Republic": 41, "Chad": 215, "Chile": 46, "China": 48,
  "Christmas Island": 54, "Cocos Keeling Islands": 39, "Colombia": 49,
  "Comoros": 119, "Congo": 40, "Cook Islands": 45, "Costa Rica": 50,
  "Cote Divoire": 44, "Croatia": 98, "Cuba": 51, "Curacao": 53, "Cyprus": 55,
  "Czech Republic": 56, "Denmark": 59, "Djibouti": 58, "Dominica": 60,
  "Dominican Republic": 61, "East Timor": 221, "Ecuador": 63, "Egypt": 65,
  "El Salvador": 210, "Equatorial Guinea": 88, "Eritrea": 67, "Estonia": 64,
  "Ethiopia": 69, "Falkland Islands": 72, "Faroe Islands": 74, "Fiji": 71,
  "Finland": 70, "France": 75, "French Guiana": 80, "French Polynesia": 175,
  "French Southern Territories": 216, "Gabon": 76, "Gambia": 85,
  "Georgia": 79, "Germany": 57, "Ghana": 82, "Gibraltar": 83, "Greece": 89,
  "Greenland": 84, "Grenada": 78, "Guadeloupe": 87, "Guam": 92,
  "Guatemala": 91, "Guernsey": 81, "Guinea": 86, "Guinea Bissau": 93,
  "Guyana": 94, "Haiti": 99, "Heard Island And Mcdonald Islands": 96,
  "Holy See": 237, "Honduras": 97, "Hong Kong": 95, "Hungary": 100,
  "Iceland": 109, "India": 105, "Indonesia": 101, "Iran": 108, "Iraq": 107,
  "Ireland": 102, "Isle Of Man": 104, "Israel": 103, "Italy": 110,
  "Jamaica": 112, "Japan": 114, "Jersey": 111, "Jordan": 113,
  "Kazakhstan": 125, "Kenya": 115, "Kiribati": 118, "Kuwait": 123,
  "Kyrgyzstan": 116, "Laos": 126, "Latvia": 135, "Lebanon": 127,
  "Lesotho": 132, "Liberia": 131, "Libya": 136, "Liechtenstein": 129,
  "Lithuania": 133, "Luxembourg": 134, "Macao": 148, "Macedonia": 144,
  "Madagascar": 142, "Malawi": 156, "Malaysia": 158, "Maldives": 155,
  "Mali": 145, "Malta": 153, "Marshall Islands": 143, "Martinique": 150,
  "Mauritania": 151, "Mauritius": 154, "Mayotte": 247, "Mexico": 157,
  "Micronesia": 73, "Moldova": 139, "Monaco": 138, "Mongolia": 147,
  "Montenegro": 140, "Montserrat": 152, "Morocco": 137, "Mozambique": 159,
  "Myanmar": 146, "Namibia": 160, "Nauru": 169, "Nepal": 168,
  "Netherlands": 166, "New Caledonia": 161, "New Zealand": 171,
  "Nicaragua": 165, "Niger": 162, "Nigeria": 164, "Niue": 170,
  "Norfolk Island": 163, "North Korea": 122, "Northern Mariana Islands": 149,
  "Norway": 167, "Oman": 172, "Pakistan": 178, "Palau": 185, "Palestine": 183,
  "Panama": 173, "Papua New Guinea": 176, "Paraguay": 186, "Peru": 174,
  "Philippines": 177, "Pitcairn Islands": 181, "Poland": 179, "Portugal": 184,
  "Puerto Rico": 182, "Qatar": 187, "Reunion": 188, "Romania": 189,
  "Russia": 191, "Rwanda": 192, "Saint Barthelemy": 26, "Saint Helena": 199,
  "Saint Kitts And Nevis": 120, "Saint Lucia": 128,
  "Saint Martin French Part": 141, "Saint Pierre And Miquelon": 180,
  "Saint Vincent": 238, "Samoa": 245, "San Marino": 204,
  "Sao Tome And Principe": 209, "Saudi Arabia": 193, "Senegal": 205,
  "Serbia": 190, "Seychelles": 195, "Sierra Leone": 203, "Singapore": 198,
  "Sint Maarten": 211, "Slovakia": 202, "Slovenia": 200,
  "Solomon Islands": 194, "Somalia": 206, "South Africa": 248,
  "South Georgia And The South Sandwich Islands": 90, "South Korea": 121,
  "South Sudan": 208, "Spain": 68, "Sri Lanka": 130, "Sudan": 196,
  "Suriname": 207, "Svalbard And Jan Mayen": 201, "Swaziland": 213,
  "Sweden": 197, "Switzerland": 43, "Syrian Arab Republic": 212,
  "Taiwan": 228, "Tajikistan": 219, "Tanzania": 229, "Thailand": 218,
  "Togo": 217, "Tokelau": 220, "Tonga": 224, "Trinidad And Tobago": 226,
  "Tunisia": 223, "Turkey": 225, "Turkmenistan": 222,
  "Turks And Caicos Islands": 214, "Tuvalu": 227, "Uganda": 231,
  "Ukraine": 230, "United Arab Emirates": 2, "United Kingdom": 232,
  "United States": 234, "United States Minor Outlying Islands": 233,
  "Uruguay": 235, "Us Virgin Islands": 241, "Uzbekistan": 236, "Vanuatu": 243,
  "Venezuela": 239, "Vietnam": 242, "Virgin Islands British": 240,
  "Wallis And Futuna Islands": 244, "Western Sahara": 66, "Yemen": 246,
  "Yugoslavia": 251, "Zambia": 249, "Zimbabwe": 250,
}

# Stat tiles on a company profile -> output column.
TILE_MAP = {
    "Business Nature": "business_nature",
    "No. Employees": "no_employees",
    "Year Established": "year_established",
    "Annual Turnover": "annual_turnover",
    "Country/Region": "country_region",
    "Main Products": "main_products",
    "Legal Status": "legal_status",
    "Payment Terms": "payment_terms",
}

# "Key: value" facts embedded in the About paragraph.
FACT_MAP = {
    "Address": "address",
    "Export Focus": "export_focus",
    "Registered Capital": "registered_capital",
    "Ownership Status": "ownership_status",
    "Export Percentage": "export_percentage",
    "Factory Size": "factory_size",
    "Production Lines": "production_lines",
    "Research Team Size": "research_team_size",
}

COMPANY_COLUMNS = [
    "id", "company_name", "business_nature", "no_employees", "year_established",
    "annual_turnover", "country_region", "main_products", "legal_status",
    "payment_terms", "contact_person", "address", "city", "country",
    "export_focus", "registered_capital", "ownership_status",
    "export_percentage", "factory_size", "production_lines",
    "research_team_size", "description", "source_url", "product_count",
    "search_term", "entity_role", "keyword_group", "keyword_priority",
]

PRODUCT_COLUMNS = ["id", "company_name", "product_name"]


# --------------------------------------------------------------------------
# session
# --------------------------------------------------------------------------

def do_login(state_path: Path, headful: bool = True) -> bool:
    """Open ONE Chrome window, clear the Cloudflare challenge, save cookies."""
    from playwright.sync_api import sync_playwright

    print("Opening a browser to clear the Cloudflare challenge...")
    print("You may sign in if you want (optional; lifts the 40-per-keyword cap).")
    print("The window closes automatically once the challenge clears.\n")
    ok = False
    with sync_playwright() as pw:
        # Stock launch on purpose: overriding the UA or adding automation flags
        # (e.g. --disable-blink-features) makes Cloudflare block the session.
        ctx = pw.chromium.launch_persistent_context(
            str(HERE / ".eh_profile"), channel="chrome",
            headless=not headful, viewport={"width": 1280, "height": 800},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(f"{BASE}/search?type=1&keyword=Vertical+Farming+Rack",
                  wait_until="domcontentloaded", timeout=90000)
        for i in range(60):  # up to ~3 min, no reloads (reloading restarts it)
            try:
                if page.evaluate(
                    "() => !!document.querySelector('a.k-word-product__title')"
                ):
                    ok = True
                    print(f"  challenge cleared after ~{i * 3}s")
                    break
            except Exception:
                pass  # execution context torn down mid-challenge
            time.sleep(3)

        if ok:
            ctx.storage_state(path=str(state_path))
            ua = page.evaluate("() => navigator.userAgent")
            print(f"  saved session -> {state_path.name}")
            if ua != UA:
                print("  NOTE: your browser UA differs from this script's UA.")
                print("  If requests fail, set UA in the script to:")
                print(f"    {ua}")
        else:
            print("  ! challenge did not clear - just run --login again")
        ctx.close()
    return ok


def load_session(state_path: Path) -> cr.Session:
    if not state_path.exists():
        sys.exit(f"No session file ({state_path.name}). Run:\n"
                 f"  python {Path(__file__).name} --login")
    st = json.loads(state_path.read_text(encoding="utf-8"))
    cookies = {c["name"]: c["value"] for c in st.get("cookies", [])
               if "exporthub" in c.get("domain", "")}
    if "cf_clearance" not in cookies:
        print("  ! no cf_clearance in session file; re-run --login if requests fail")
    s = cr.Session(impersonate="chrome", headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    s.cookies.update(cookies)
    return s


def say(msg: str = ""):
    """print() that survives non-UTF8 consoles.

    The Windows console is cp1252, so printing a company name containing e.g.
    Arabic characters raises UnicodeEncodeError. Never let logging kill a scrape.
    """
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode(enc, errors="replace").decode(enc, errors="replace"))


def jitter(a=0.6, b=1.6):
    time.sleep(random.uniform(a, b))


# Sentinel: profile page returns 404 (dead link on ExportHub, never retry).
GONE = "__GONE__"


class SessionExpired(Exception):
    """Cloudflare clearance is gone; nothing more can be fetched this run."""


def fetch(session, url, tries=3):
    """GET with retries.

    Raises SessionExpired if the Cloudflare challenge comes back, so callers can
    stop and leave the remaining work un-marked (resumable) instead of recording
    thousands of silently-empty rows.
    """
    for attempt in range(tries):
        try:
            r = session.get(url, timeout=60)
            if "Just a moment" in r.text:
                raise SessionExpired(url)
            if r.status_code == 404:
                # Some suppliers appear in search results but their profile page
                # is a dead link. Permanent - do not retry.
                return GONE
            if r.status_code == 200:
                return r.text
        except SessionExpired:
            raise
        except Exception as e:
            if attempt == tries - 1:
                print(f"      ! fetch failed: {str(e)[:70]}")
        time.sleep(2 * (attempt + 1))
    return None


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------

def token_from(html: str) -> str | None:
    """CSRF token lives in an inline script, with a hidden input as fallback."""
    m = re.search(r"_token:\s*'([^']+)'", html)
    if m:
        return m.group(1)
    m = re.search(r'name="_token"\s+value="([^"]+)"', html)
    return m.group(1) if m else None


def is_placeholder_name(name: str) -> bool:
    """True for junk listings: obfuscated emails, bare numbers, punctuation only."""
    n = name.strip()
    if not n:
        return True
    if "@" in n or "email" in n.lower() and "protected" in n.lower():
        return True
    # names that are only digits/asterisks/dots (e.g. "10", "*******.01")
    return bool(re.fullmatch(r"[\d\*\.\s\-_]+", n))


def parse_cards(html: str) -> list[dict]:
    """One row per supplier card in the result list."""
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for box in soup.select("div.prodList-box"):
        a = box.select_one("a.k-word-product__title")
        if not a or not a.get("href"):
            continue
        txt = box.get_text("\n", strip=True)

        def pick(label):
            m = re.search(rf"{label}\s*:?\s*\n?\s*([^\n]+)", txt)
            return m.group(1).strip() if m else ""

        # the line just before the action buttons holds "City,Country"
        loc = ""
        lm = re.search(r"([A-Za-z .'\-]+,\s*[A-Za-z .'\-]+)\s*\n?\s*"
                       r"(?:Inquiry Basket|Contact Now)", txt)
        if lm:
            loc = re.sub(r"\s*,\s*", ",", lm.group(1).strip())
        mp = re.search(r"Main Products:\s*([^\n]+)", txt)

        href = a["href"]
        name = a.get_text(strip=True)
        if not name:
            # A few listings have a genuinely blank name on ExportHub (empty <h1>
            # on the profile too). Fall back to the URL slug so the row is usable.
            slug = re.sub(r"-\d{5,}$", "", href.rstrip("/").rsplit("/", 1)[-1])
            name = slug.replace("-", " ").strip().title()
        if is_placeholder_name(name):
            continue  # junk listing, not a real company
        rows.append({
            "company_name": name,
            "source_url": href if href.startswith("http") else BASE + href,
            "contact_person": pick("Contact Person"),
            "year_established": pick("Established In"),
            "business_nature": pick("Business Type"),
            "no_employees": pick("Employees"),
            "main_products": mp.group(1).strip() if mp else "",
            "location": loc,
        })
    return rows


def parse_profile(html: str) -> dict:
    """Stat tiles, About description + facts, and the company's own products."""
    soup = BeautifulSoup(html, "html.parser")
    out = {"tiles": {}, "description": "", "facts": {}, "products": []}

    for box in soup.select("div.comp-dtl_rgticon"):
        k = box.select_one(".comp-dtl_rgtnm")
        v = box.select_one(".comp-dtl_rgtp")
        if k:
            out["tiles"][k.get_text(strip=True)] = v.get_text(strip=True) if v else ""

    desp = soup.select_one(".rmp-comp--desp_cont")
    if desp:
        full = desp.get_text("\n", strip=True)
        # Drop the "About <company>" heading. It is its own line, but the company
        # name can wrap, so strip the heading element's own text explicitly.
        hdr = desp.select_one(".rmp-comp--box_ttl")
        if hdr:
            htxt = hdr.get_text(strip=True)
            if full.startswith(htxt):
                full = full[len(htxt):]
        full = re.sub(r"^\s*About\b.*(?:\n|$)", "", full, count=1).strip()
        # the first block, before the "Facts" list, is the readable summary
        desc = re.split(r"\n\s*\n", full)[0].strip()
        # Emails are obfuscated by Cloudflare into "[email protected]" noise;
        # such a "description" carries no information, so drop it.
        if "email" in desc.lower() and "protected" in desc.lower():
            desc = ""
        out["description"] = re.sub(r"\s*\n\s*", " ", desc).strip()
        for label, col in FACT_MAP.items():
            m = re.search(rf"{re.escape(label)}:\s*([^\n]+)", full)
            if m:
                out["facts"][col] = m.group(1).strip().rstrip(".")
        m = re.search(r"Facts\s+Name:\s*([^\n]+)", full)
        if m:
            out["facts"]["contact_person"] = m.group(1).strip()

    # NOTE: /products.html lists *other* companies' products - the company's own
    # catalogue only appears on the profile home tab.
    seen = set()
    for e in soup.select(".prod-del_pdnm"):
        name = e.get_text(strip=True)
        if name and name not in seen:
            seen.add(name)
            out["products"].append(name)
    return out


def search_country(session, keyword: str, country: str, cid: int) -> list[dict]:
    """GET the search page, POST the country filter, return matching cards.

    Note: the CSRF token is reusable across keywords, so the GET could be
    skipped - but measured against the live site that is no faster (3.8s vs
    3.1s per keyword; the server, not the request count, is the bottleneck),
    so we keep the straightforward GET-then-POST flow.
    """
    url = f"{BASE}/search?type=1&keyword={keyword.replace(' ', '+')}"
    html = fetch(session, url)   # may raise SessionExpired
    if html is None:
        return []

    # NOTE: do NOT skip when the sidebar lacks this country's checkbox. The
    # sidebar is a partial list (it showed 62 countries for a 5,000-supplier
    # search, omitting Kuwait and Saudi Arabia), but POSTing the country id
    # anyway still returns that country's suppliers - verified: Kuwait (123)
    # on "Greenhouse Manufacturer" yields 40 Kuwaiti suppliers despite being
    # absent from the sidebar. Always attempt the filter POST.
    tok = token_from(html)
    if not tok:
        print("      ! no CSRF token found")
        return []

    try:
        r = session.post(
            url,
            data=[("_token", tok), ("filters_id", ""), ("filter[]", str(cid))],
            timeout=60,
            headers={"Referer": url, "Origin": BASE, "X-CSRF-TOKEN": tok,
                     "Content-Type": "application/x-www-form-urlencoded"},
        )
        if "Just a moment" in r.text:
            raise SessionExpired(url)
    except SessionExpired:
        raise
    except Exception as e:
        print(f"      ! filter POST failed: {str(e)[:70]}")
        return []

    cards = parse_cards(r.text)
    if not cards:
        print(f"      - no {country} suppliers")
        return []
    kept = [c for c in cards if country.lower() in c["location"].lower()]
    if not kept:
        # Filter silently didn't apply; drop rather than emit wrong-country rows.
        print(f"      ! filter not applied ({len(cards)} unfiltered) - skipped")
        return []
    print(f"      {len(kept)} {country} suppliers")
    return kept


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def write_csvs(companies: dict, comp_csv: Path, prod_csv: Path) -> tuple[int, int]:
    """Merge duplicate company names, assign ids, and write both CSVs.

    Safe to call at any time (e.g. --export-only against a checkpoint), not just
    at the end of a full run.
    """
    # ExportHub sometimes lists the same company under several profile URLs. We
    # key on URL while scraping (they are genuinely distinct pages), then merge
    # here so company_name is unique per row, as required.
    merged: dict[str, dict] = {}
    for url, rec in sorted(companies.items(), key=lambda kv: kv[1]["source_url"]):
        name = (rec.get("company_name") or "").strip()
        if not name:
            slug = re.sub(r"-\d{5,}$", "", url.rstrip("/").rsplit("/", 1)[-1])
            name = slug.replace("-", " ").strip().title()
            rec["company_name"] = name
        if is_placeholder_name(name):
            continue  # junk listing (also filtered in parse_cards for new runs)
        key = re.sub(r"\s+", " ", rec["company_name"]).strip().lower()
        if key not in merged:
            merged[key] = dict(rec)
            continue
        keep = merged[key]
        # prefer the richer record field-by-field
        for col in COMPANY_COLUMNS:
            if not keep.get(col) and rec.get(col):
                keep[col] = rec[col]
        for term in rec["search_term"].split(" | "):
            if term not in keep["search_term"].split(" | "):
                keep["search_term"] += f" | {term}"
        seen = set(keep.get("products") or [])
        for prod in rec.get("products") or []:
            if prod not in seen:
                seen.add(prod)
                keep.setdefault("products", []).append(prod)
        # keep both source URLs so nothing is silently lost
        if rec["source_url"] not in keep["source_url"]:
            keep["source_url"] += f" | {rec['source_url']}"

    comp_rows, prod_rows = [], []
    for n, rec in enumerate(
            sorted(merged.values(), key=lambda r: r["company_name"].lower()), 1):
        rec["id"] = n
        prods = rec.get("products") or []
        rec["product_count"] = len(prods)
        comp_rows.append(rec)
        for prod in prods:
            prod_rows.append({"id": n, "company_name": rec["company_name"],
                              "product_name": prod})

    with open(comp_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COMPANY_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(comp_rows)
    with open(prod_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=PRODUCT_COLUMNS)
        w.writeheader()
        w.writerows(prod_rows)
    return len(comp_rows), len(prod_rows)


def main():
    # Company names include Arabic/CJK text; the Windows console defaults to
    # cp1252, so reconfigure stdout rather than lose the run to a print().
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="ExportHub country-specific scraper")
    ap.add_argument("--country", default="United Arab Emirates")
    ap.add_argument("--keywords", default=str(KEYWORDS_CSV))
    ap.add_argument("--limit", type=int, help="only the first N keywords")
    ap.add_argument("--priority", type=int, choices=[1, 2])
    ap.add_argument("--group", help="product_goods | service_institution")
    ap.add_argument("--outdir", default=str(HERE))
    ap.add_argument("--state", default=str(STATE_FILE))
    ap.add_argument("--login", action="store_true", help="one-time session setup")
    ap.add_argument("--no-profiles", action="store_true",
                    help="skip profile pages (no description/products, much faster)")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--export-only", action="store_true",
                    help="write CSVs from the existing checkpoint and exit "
                         "(no scraping) - use this to inspect partial results")
    ap.add_argument("--list-countries", action="store_true")
    args = ap.parse_args()

    if args.list_countries:
        for n in sorted(COUNTRY_IDS):
            print(f"  {n}  (id={COUNTRY_IDS[n]})")
        return
    if args.login:
        do_login(Path(args.state))
        return

    country = args.country
    if country not in COUNTRY_IDS:
        near = [c for c in COUNTRY_IDS if country.lower() in c.lower()]
        if len(near) == 1:
            country = near[0]
        else:
            sys.exit(f"Unknown country '{country}'. Try --list-countries.")
    cid = COUNTRY_IDS[country]

    kdf = pd.read_csv(args.keywords)
    if args.priority:
        kdf = kdf[kdf["Priority"] == args.priority]
    if args.group:
        kdf = kdf[kdf["Group"] == args.group]
    if args.limit:
        kdf = kdf.head(args.limit)
    keywords = kdf.to_dict("records")

    slug = re.sub(r"\W+", "_", country).strip("_")
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    comp_csv = outdir / f"exporthub_companies_{slug}.csv"
    prod_csv = outdir / f"exporthub_products_{slug}.csv"
    ckpt = outdir / f".checkpoint_{slug}.json"

    companies: dict[str, dict] = {}
    done: set[str] = set()
    if (args.resume or args.export_only) and ckpt.exists():
        saved = json.loads(ckpt.read_text(encoding="utf-8"))
        companies = saved.get("companies", {})
        done = set(saved.get("done", []))
        print(f"Loaded checkpoint: {len(companies)} companies, "
              f"{len(done)} keywords done")

    if args.export_only:
        if not companies:
            sys.exit(f"Nothing to export - no checkpoint at {ckpt.name}")
        n_comp, n_prod = write_csvs(companies, comp_csv, prod_csv)
        n_prof = sum(1 for r in companies.values() if r.get("_profiled"))
        print(f"\n{n_comp} companies -> {comp_csv}")
        print(f"{n_prod} products  -> {prod_csv}")
        if n_prof < len(companies):
            print(f"\nNote: {len(companies) - n_prof} of {len(companies)} companies "
                  f"are not profiled yet, so their description/products columns "
                  f"are still empty.\nFinish the run (--resume) to fill them.")
        return

    session = load_session(Path(args.state))
    print(f"\nExportHub | country={country} (id={cid}) | keywords={len(keywords)}")
    print(f"  -> {comp_csv.name}\n  -> {prod_csv.name}\n")

    def save_ckpt():
        ckpt.write_text(json.dumps({"companies": companies, "done": sorted(done)}),
                        encoding="utf-8")

    def flush_csvs():
        """Refresh the CSVs mid-run so partial results are inspectable."""
        try:
            write_csvs(companies, comp_csv, prod_csv)
        except Exception as e:  # never let reporting kill the scrape
            print(f"      ! csv flush failed: {str(e)[:70]}")

    try:
        for i, row in enumerate(keywords, 1):
            kw = str(row["Keyword"]).strip()
            if kw in done:
                continue
            say(f"[{i}/{len(keywords)}] {kw}")
            for c in search_country(session, kw, country, cid):
                url = c["source_url"]
                if url in companies:
                    # already seen under an earlier keyword: record the extra term
                    rec = companies[url]
                    if kw not in rec["search_term"].split(" | "):
                        rec["search_term"] += f" | {kw}"
                    continue
                loc = c["location"]
                companies[url] = {
                    "company_name": c["company_name"],
                    "business_nature": c["business_nature"],
                    "no_employees": c["no_employees"],
                    "year_established": c["year_established"],
                    "annual_turnover": "",
                    "country_region": loc,
                    "main_products": c["main_products"],
                    "legal_status": "",
                    "payment_terms": "",
                    "contact_person": c["contact_person"],
                    "address": "",
                    "city": loc.split(",")[0].strip() if "," in loc else "",
                    "country": country,
                    "export_focus": "",
                    "registered_capital": "",
                    "ownership_status": "",
                    "export_percentage": "",
                    "factory_size": "",
                    "production_lines": "",
                    "research_team_size": "",
                    "description": "",
                    "source_url": url,
                    "search_term": kw,
                    "entity_role": row.get("Entities", ""),
                    "keyword_group": row.get("Group", ""),
                    "keyword_priority": row.get("Priority", ""),
                    "products": [],
                    "_profiled": False,
                }
            done.add(kw)
            save_ckpt()
            if len(done) % 10 == 0:
                flush_csvs()
            jitter()

        if not args.no_profiles:
            todo = [(u, r) for u, r in companies.items() if not r.get("_profiled")]
            print(f"\nFetching {len(todo)} company profiles...")
            for n, (url, rec) in enumerate(todo, 1):
                say(f"  [{n}/{len(todo)}] {rec['company_name'][:50]}")
                html = fetch(session, url, tries=2)
                if html is GONE:
                    # dead profile link; keep the search-derived fields we have
                    rec["_profiled"] = True
                    rec["_profile_missing"] = True
                    say("      - profile page missing (404)")
                elif html:
                    d = parse_profile(html)
                    for label, col in TILE_MAP.items():
                        if d["tiles"].get(label):
                            rec[col] = d["tiles"][label]
                    if d["description"]:
                        rec["description"] = d["description"]
                    for col, val in d["facts"].items():
                        if val and not rec.get(col):
                            rec[col] = val
                    rec["products"] = d["products"]
                    rec["_profiled"] = True
                else:
                    # leave _profiled False so --resume retries this company
                    say("      ! profile fetch returned nothing - will retry on --resume")
                if n % 10 == 0:
                    save_ckpt()
                    flush_csvs()
                jitter(0.4, 1.1)
    except SessionExpired:
        print("\n! Cloudflare clearance expired - stopping here so the remaining")
        print("  work stays resumable. Refresh the session and continue with:")
        print(f"    python {Path(__file__).name} --login")
        print(f"    python {Path(__file__).name} --resume --country \"{country}\"")
    except KeyboardInterrupt:
        print("\nInterrupted - writing partial output (rerun with --resume).")
    finally:
        save_ckpt()

    n_comp, n_prod = write_csvs(companies, comp_csv, prod_csv)
    print(f"\nDone. {n_comp} companies -> {comp_csv}")
    print(f"      {n_prod} products  -> {prod_csv}")


if __name__ == "__main__":
    main()
