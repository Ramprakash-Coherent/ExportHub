"""
Combine `agri_keywords_master.csv` with the role-based terms in `listings/*.xlsx`
into one deduplicated keyword file for the scraper.

The two sources are complementary:
  * master   - product/goods terms ("Vertical Farming Rack", "Hydroponic Tower System")
  * listings - role/entity terms   ("Fertilizer Supplier", "Coco Peat Exporter")
Only 101 of ~7,000 terms overlap, so merging gives ~10x more search coverage.

Output: agri_keywords_combined.csv with the same schema the scraper expects
(Keyword, Entities, Group, Priority) plus a `Source` column for traceability.

Usage
-----
    python build_keywords.py                 # write agri_keywords_combined.csv
    python build_keywords.py --stats         # just report, write nothing
    python build_keywords.py --out other.csv
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
MASTER = HERE / "agri_keywords_master.csv"
LISTINGS = HERE / "listings"
OUT = HERE / "agri_keywords_combined.csv"

# Listings rows carry only Entity+Listing. Priority/Group come from the master
# row for the same entity; these are the fallbacks when an entity is new.
DEFAULT_GROUP = "role_listing"
DEFAULT_PRIORITY = 3


def norm(s: str) -> str:
    """Normalise a term for duplicate detection (case/space/punctuation-insensitive)."""
    s = str(s).strip().lower()
    s = re.sub(r"[^\w\s&/-]", "", s)
    return re.sub(r"\s+", " ", s)


def norm_entity(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower())


def load_master() -> pd.DataFrame:
    m = pd.read_csv(MASTER)
    for c in ("Keyword", "Entities", "Group"):
        m[c] = m[c].astype(str).str.strip()
    m["Source"] = "master"
    return m


def load_listings() -> pd.DataFrame:
    files = sorted(glob.glob(str(LISTINGS / "*.xlsx")))
    if not files:
        sys.exit(f"No .xlsx files found in {LISTINGS}")
    frames = []
    for f in files:
        try:
            d = pd.read_excel(f)
        except Exception as e:
            print(f"  ! skipped {os.path.basename(f)}: {str(e)[:60]}")
            continue
        if not {"Entity", "Listing"} <= set(d.columns):
            print(f"  ! skipped {os.path.basename(f)}: unexpected columns "
                  f"{d.columns.tolist()}")
            continue
        d = d[["Entity", "Listing"]].copy()
        d.columns = ["Entities", "Keyword"]
        d["Source"] = os.path.basename(f)
        frames.append(d)
    L = pd.concat(frames, ignore_index=True)
    for c in ("Keyword", "Entities"):
        L[c] = L[c].astype(str).str.strip()
    # drop blanks / literal NaN text
    L = L[L.Keyword.ne("") & ~L.Keyword.str.lower().isin({"nan", "none"})]
    return L


def build(stats_only: bool = False, out_path: Path = OUT) -> pd.DataFrame:
    m = load_master()
    L = load_listings()

    # Map entity -> (Group, Priority) from master so listing terms inherit them.
    # Master has two compound entities ("A; B"); index each part separately so
    # listing entities resolve against them too.
    meta: dict[str, tuple[str, int]] = {}
    for _, r in m.iterrows():
        g, p = r["Group"], r["Priority"]
        for part in str(r["Entities"]).split(";"):
            meta.setdefault(norm_entity(part), (g, p))

    L["Group"] = [meta.get(norm_entity(e), (DEFAULT_GROUP, DEFAULT_PRIORITY))[0]
                  for e in L.Entities]
    L["Priority"] = [meta.get(norm_entity(e), (DEFAULT_GROUP, DEFAULT_PRIORITY))[1]
                     for e in L.Entities]

    combined = pd.concat([m[["Keyword", "Entities", "Group", "Priority", "Source"]],
                          L[["Keyword", "Entities", "Group", "Priority", "Source"]]],
                         ignore_index=True)

    # Dedupe on the normalised keyword, keeping the first occurrence. Master is
    # concatenated first, so its Group/Priority/Entities win on a collision.
    combined["_k"] = combined.Keyword.map(norm)
    before = len(combined)
    combined = combined.drop_duplicates("_k", keep="first").drop(columns="_k")

    combined = combined.sort_values(["Priority", "Entities", "Keyword"],
                                    kind="stable").reset_index(drop=True)

    print(f"master keywords     : {len(m)}")
    print(f"listing rows        : {len(L)}  (from {L.Source.nunique()} files)")
    print(f"raw concatenated    : {before}")
    print(f"after dedupe        : {len(combined)}")
    print(f"  new vs master     : {len(combined) - len(m)}")
    print(f"entities            : {combined.Entities.nunique()}")
    print(f"\nby Group:\n{combined.Group.value_counts().to_string()}")
    print(f"\nby Priority:\n{combined.Priority.value_counts().sort_index().to_string()}")

    if not stats_only:
        combined.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"\nwrote {len(combined)} keywords -> {out_path}")
    return combined


def main():
    ap = argparse.ArgumentParser(description="Merge master + listings keywords")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--stats", action="store_true", help="report only, write nothing")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    build(stats_only=args.stats, out_path=Path(args.out))


if __name__ == "__main__":
    main()
