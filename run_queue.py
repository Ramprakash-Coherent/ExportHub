"""
Wait out a Cloudflare block, then run a queue of countries back to back.

Each country is run to completion (search + profiles) before the next starts.
If the site blocks mid-run the scraper stops cleanly, and this script goes back
to probing and then resumes that same country with --resume.

Usage
-----
    python run_queue.py --countries "Oman" "Qatar"
    python run_queue.py --countries "Oman" --interval 900 --max-wait 12
"""
from __future__ import annotations
import argparse, json, subprocess, sys, time
from datetime import datetime
from pathlib import Path
from curl_cffi import requests as cr

HERE = Path(__file__).resolve().parent
STATE = HERE / "eh_state.json"
PROBE = "https://www.exporthub.com/superior-technologies/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36")

def stamp(): return datetime.now().strftime("%H:%M:%S")

def clear() -> bool:
    if not STATE.exists(): return False
    st = json.loads(STATE.read_text(encoding="utf-8"))
    ck = {c["name"]: c["value"] for c in st.get("cookies", [])
          if "exporthub" in c.get("domain", "")}
    s = cr.Session(impersonate="chrome", headers={"User-Agent": UA})
    s.cookies.update(ck)
    try:
        r = s.get(PROBE, timeout=60)
    except Exception as e:
        print(f"[{stamp()}] probe error: {str(e)[:50]}", flush=True); return False
    ok = r.status_code == 200 and "Just a moment" not in r.text
    print(f"[{stamp()}] probe: {r.status_code} -> {'CLEAR' if ok else 'blocked'}", flush=True)
    return ok

def slug(c): return c.replace(" ", "_")

def done(country) -> bool:
    """True when every company for this country has been profiled."""
    f = HERE / f".checkpoint_{slug(country)}.json"
    if not f.exists(): return False
    try: d = json.loads(f.read_text(encoding="utf-8"))
    except Exception: return False
    comps = d.get("companies", {})
    return bool(comps) and all(r.get("_profiled") for r in comps.values())

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--countries", nargs="+", required=True)
    ap.add_argument("--keywords", default="agri_keywords_extended.csv")
    ap.add_argument("--interval", type=int, default=900)
    ap.add_argument("--max-wait", type=float, default=12)
    a = ap.parse_args()
    try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

    for country in a.countries:
        print(f"\n[{stamp()}] === {country} ===", flush=True)
        deadline = time.time() + a.max_wait * 3600
        while not done(country):
            if time.time() > deadline:
                print(f"[{stamp()}] gave up waiting for {country}", flush=True); break
            if not clear():
                time.sleep(a.interval); continue
            ck = HERE / f".checkpoint_{slug(country)}.json"
            cmd = [sys.executable, "-u", str(HERE / "exporthub_scraper.py"),
                   "--keywords", a.keywords, "--country", country]
            if ck.exists(): cmd.append("--resume")
            log = HERE / f"scrape_{slug(country).lower()}.log"
            print(f"[{stamp()}] running: {' '.join(cmd[-4:])}", flush=True)
            with open(log, "a", encoding="utf-8") as fh:
                subprocess.call(cmd, cwd=str(HERE), stdout=fh, stderr=subprocess.STDOUT)
            if not done(country):
                print(f"[{stamp()}] stopped early (likely blocked) - will retry", flush=True)
                time.sleep(a.interval)
        if done(country):
            print(f"[{stamp()}] {country} COMPLETE", flush=True)

if __name__ == "__main__":
    sys.exit(main())
