"""
Adapt an external keyword CSV to the schema exporthub_scraper.py expects.

The scraper needs: Keyword, Entities, Group, Priority
GrowIQX file provides: keyword, sub_category, main_group

Mapping:
  Keyword   <- keyword
  Entities  <- sub_category   (the finer-grained role, mirrors how `Entities`
                               was used before: one role label per keyword)
  Group     <- main_group     (the coarse grouping)
  Priority  <- 1              (no priority column in the source; the scraper
                               only uses Priority for optional --priority
                               filtering, so a constant is harmless)

Usage
-----
    python adapt_keywords.py GrowIQX_master_keywords_G1toG7.csv
    python adapt_keywords.py <in.csv> --out <out.csv>
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent


def norm(s: str) -> str:
    s = str(s).strip().lower()
    s = re.sub(r"[^\w\s&/-]", "", s)
    return re.sub(r"\s+", " ", s)


def main():
    ap = argparse.ArgumentParser(description="Adapt a keyword CSV for the scraper")
    ap.add_argument("infile")
    ap.add_argument("--out", help="default: <infile stem>_adapted.csv")
    ap.add_argument("--keyword-col", default="keyword")
    ap.add_argument("--entity-col", default="sub_category")
    ap.add_argument("--group-col", default="main_group")
    ap.add_argument("--priority", type=int, default=1)
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    src = Path(args.infile)
    if not src.is_absolute():
        src = HERE / src
    d = pd.read_csv(src)

    missing = [c for c in (args.keyword_col, args.entity_col, args.group_col)
               if c not in d.columns]
    if missing:
        sys.exit(f"missing columns {missing}; file has {d.columns.tolist()}")

    out = pd.DataFrame({
        "Keyword": d[args.keyword_col].astype(str).str.strip(),
        "Entities": d[args.entity_col].astype(str).str.strip(),
        "Group": d[args.group_col].astype(str).str.strip(),
        "Priority": args.priority,
    })
    out = out[out.Keyword.ne("") & ~out.Keyword.str.lower().isin({"nan", "none"})]

    before = len(out)
    out["_k"] = out.Keyword.map(norm)
    out = out.drop_duplicates("_k", keep="first").drop(columns="_k")
    out = out.sort_values(["Group", "Entities", "Keyword"],
                          kind="stable").reset_index(drop=True)

    dest = Path(args.out) if args.out else HERE / f"{src.stem}_adapted.csv"
    if not dest.is_absolute():
        dest = HERE / dest
    out.to_csv(dest, index=False, encoding="utf-8-sig")

    print(f"source      : {src.name}  ({len(d)} rows)")
    print(f"deduplicated: {before} -> {len(out)}")
    print(f"entities    : {out.Entities.nunique()}")
    print(f"groups      : {out.Group.nunique()}")
    print(f"wrote       : {dest.name}")


if __name__ == "__main__":
    main()
