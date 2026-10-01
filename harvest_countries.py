"""
Harvest the country -> filter-id map from ExportHub's search sidebar.

The sidebar only lists countries that have suppliers for the *current* keyword,
so no single search shows them all (one keyword showed 60, another 98). This
probes several broad keywords and unions the results.

Prints a ready-to-paste COUNTRY_IDS block and writes country_ids.json.

Usage
-----
    python harvest_countries.py
    python harvest_countries.py --update   # rewrite COUNTRY_IDS in the scraper
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup
from curl_cffi import requests as cr

HERE = Path(__file__).resolve().parent
STATE = HERE / "eh_state.json"
OUT = HERE / "country_ids.json"
SCRAPER = HERE / "exporthub_scraper.py"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36")

# Broad, high-volume keywords so the sidebar lists as many countries as possible.
PROBE_KEYWORDS = [
    "Date Palm Plantation", "Fertilizer Supplier", "Greenhouse Manufacturer",
    "Agricultural Equipment", "Tractor Dealership", "Fish Farming Pond",
    "Poultry Feed Mill", "Irrigation Equipment Distributor", "Seed Supplier",
    "Animal Feed Supplier",
]


def harvest() -> dict[str, str]:
    if not STATE.exists():
        sys.exit("No eh_state.json - run: python exporthub_scraper.py --login")
    st = json.loads(STATE.read_text(encoding="utf-8"))
    ck = {c["name"]: c["value"] for c in st.get("cookies", [])
          if "exporthub" in c.get("domain", "")}
    s = cr.Session(impersonate="chrome", headers={"User-Agent": UA})
    s.cookies.update(ck)

    seen: dict[str, str] = {}
    for kw in PROBE_KEYWORDS:
        url = f"https://www.exporthub.com/search?type=1&keyword={kw.replace(' ', '+')}"
        try:
            r = s.get(url, timeout=60)
            if "Just a moment" in r.text:
                print(f"  ! challenge on '{kw}' - session expired")
                break
            soup = BeautifulSoup(r.text, "html.parser")
            before = len(seen)
            for i in soup.select('input[name="filter[]"]'):
                lbl = i.find_parent("label") or i.parent
                nm = re.sub(r"\s+", " ", lbl.get_text(strip=True)) if lbl else ""
                if nm and i.get("value"):
                    seen.setdefault(nm, i["value"])
            print(f"  {kw:34} +{len(seen)-before:3} (total {len(seen)})")
        except Exception as e:
            print(f"  ! {kw}: {str(e)[:50]}")
    return seen


def render(seen: dict[str, str]) -> str:
    lines, row = ["COUNTRY_IDS = {"], " "
    for name, cid in sorted(seen.items()):
        piece = f' "{name}": {cid},'
        if len(row) + len(piece) > 78:
            lines.append(row)
            row = " "
        row += piece
    if row.strip():
        lines.append(row)
    lines.append("}")
    return "\n".join(lines)


def harvest_full() -> dict[str, str]:
    """Pull the complete country list from the homepage's <select name="country">.

    This is authoritative - unlike the search sidebar (which only lists
    countries with results for the *current* keyword and is missing ~100
    countries, e.g. Bahrain), the signup/RFQ form dropdown lists every country
    ExportHub knows, in the same id space (verified against 7 known sidebar
    ids - all matched).
    """
    if not STATE.exists():
        sys.exit("No eh_state.json - run: python exporthub_scraper.py --login")
    st = json.loads(STATE.read_text(encoding="utf-8"))
    ck = {c["name"]: c["value"] for c in st.get("cookies", [])
          if "exporthub" in c.get("domain", "")}
    s = cr.Session(impersonate="chrome", headers={"User-Agent": UA})
    s.cookies.update(ck)
    r = s.get("https://www.exporthub.com/", timeout=60)
    if "Just a moment" in r.text:
        sys.exit("Cloudflare challenge - refresh eh_state.json first")
    soup = BeautifulSoup(r.text, "html.parser")
    sel = soup.find("select", {"name": "country"})
    if not sel:
        sys.exit("country <select> not found on homepage")
    opts = {}
    for o in sel.find_all("option"):
        name = re.sub(r"\s+", " ", o.get_text(strip=True))
        val = o.get("value")
        if name and val and name not in ("Other", "Select Country"):
            opts[name] = val
    return opts


def main():
    ap = argparse.ArgumentParser(description="Harvest ExportHub country ids")
    ap.add_argument("--update", action="store_true",
                    help="rewrite COUNTRY_IDS inside exporthub_scraper.py")
    ap.add_argument("--full", action="store_true",
                    help="use the homepage country dropdown (complete, ~250 "
                         "countries) instead of probing search sidebars "
                         "(partial, ~150 countries)")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    seen = harvest_full() if args.full else harvest()
    if not seen:
        sys.exit("harvested nothing")
    OUT.write_text(json.dumps(seen, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\n{len(seen)} countries -> {OUT.name}")

    if args.update:
        s = SCRAPER.read_text(encoding="utf-8")
        start = s.index("COUNTRY_IDS = {")
        end = s.index("}", start) + 1
        SCRAPER.write_text(s[:start] + render(seen) + s[end:], encoding="utf-8")
        print(f"updated COUNTRY_IDS in {SCRAPER.name}")
    else:
        print("\n(pass --update to write this into the scraper)")


if __name__ == "__main__":
    main()
