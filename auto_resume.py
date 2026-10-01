"""
Wait out a Cloudflare rate-limit, then resume a scrape automatically.

After a few hours of sustained scraping exporthub.com stops clearing the JS
challenge for a while. Retrying immediately just prolongs it, so this script
polls at a slow interval and only launches the resume once the site actually
serves real content again.

Usage
-----
    python auto_resume.py --country "Saudi Arabia" --keywords agri_keywords_extended.csv

    # tune the wait
    python auto_resume.py --country "Saudi Arabia" --interval 900 --max-wait 6

Notes
-----
* Probing uses ONE request per attempt - deliberately gentle.
* The probe needs a valid cf_clearance cookie in eh_state.json. If the cookie
  itself has expired (as opposed to being rate-limited), refresh it first with
  `python exporthub_scraper.py --login`.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from curl_cffi import requests as cr

HERE = Path(__file__).resolve().parent
STATE = HERE / "eh_state.json"
PROBE_URL = "https://www.exporthub.com/superior-technologies/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36")


def stamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def probe() -> bool:
    """One gentle request. True when the site serves real content again."""
    if not STATE.exists():
        print(f"[{stamp()}] no eh_state.json - run --login first")
        return False
    st = json.loads(STATE.read_text(encoding="utf-8"))
    ck = {c["name"]: c["value"] for c in st.get("cookies", [])
          if "exporthub" in c.get("domain", "")}
    s = cr.Session(impersonate="chrome", headers={"User-Agent": UA})
    s.cookies.update(ck)
    try:
        r = s.get(PROBE_URL, timeout=60)
    except Exception as e:
        print(f"[{stamp()}] probe error: {str(e)[:60]}")
        return False
    ok = r.status_code == 200 and "Just a moment" not in r.text
    print(f"[{stamp()}] probe: status={r.status_code} "
          f"challenge={'Just a moment' in r.text} -> {'CLEAR' if ok else 'blocked'}")
    return ok


def main():
    ap = argparse.ArgumentParser(description="Wait out a block, then resume")
    ap.add_argument("--country", required=True)
    ap.add_argument("--keywords", default="agri_keywords_extended.csv")
    ap.add_argument("--interval", type=int, default=900,
                    help="seconds between probes (default 900 = 15 min)")
    ap.add_argument("--max-wait", type=float, default=8,
                    help="give up after this many hours (default 8)")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    deadline = time.time() + args.max_wait * 3600
    print(f"[{stamp()}] waiting for exporthub.com to unblock "
          f"(probe every {args.interval}s, up to {args.max_wait}h)")

    while time.time() < deadline:
        if probe():
            print(f"[{stamp()}] site is reachable - resuming {args.country}")
            cmd = [sys.executable, "-u", str(HERE / "exporthub_scraper.py"),
                   "--keywords", args.keywords,
                   "--country", args.country, "--resume"]
            rc = subprocess.call(cmd, cwd=str(HERE))
            print(f"[{stamp()}] scraper exited with code {rc}")
            return rc
        time.sleep(args.interval)

    print(f"[{stamp()}] still blocked after {args.max_wait}h - giving up.")
    print("  Try: python exporthub_scraper.py --login   (then --resume)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
