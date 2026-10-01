"""
Prune the combined keyword list without losing supplier coverage.

Why this is needed
------------------
`agri_keywords_combined.csv` has 7,485 keywords, which is a very long scrape.
But not all keywords are worth the request. Measurements taken against the
completed 697-keyword UAE run and live probes of exporthub.com search:

1. Only 281 of the 697 keywords that ran (40%) were needed to reach 100% of the
   3,225 companies found. The rest contributed no unique company.
2. Role suffixes are the PRODUCTIVE part, not redundancy. "Greenhouse Supplier"
   (36 results) and "Greenhouse Manufacturer" (40) had ZERO overlap, and the
   bare "Greenhouse" returned only 3, missing all 76. So never strip roles, and
   never reduce a core to its bare noun.
3. Single-word keywords are the weakest class: 19% hit rate (7/36) in the real
   run, because ExportHub matches phrases, not concepts.
4. Long modifier variants on a shared head overlap heavily. The three
   "Agri Equipment {B2B, Cold Storage, Agency}" each returned 35 UAE results
   for a union of 39 - so ~1-2 unique companies per extra variant.

The strategy therefore keeps every distinct concept and every role variant, and
only thins the deep modifier tails plus the weakest keyword classes.

Usage
-----
    python prune_keywords.py                 # write agri_keywords_pruned.csv
    python prune_keywords.py --stats         # report only
    python prune_keywords.py --tail 2        # keep 2 modifier variants per head
    python prune_keywords.py --keep-single   # don't drop 1-word keywords
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
COMBINED = HERE / "agri_keywords_combined.csv"
OUT = HERE / "agri_keywords_pruned.csv"

# Trailing words that denote a business role. These are high-value: ExportHub
# returns a materially different supplier set per role, so all are kept.
ROLES = {
    "supplier", "manufacturer", "dealer", "distributor", "exporter", "importer",
    "provider", "company", "agency", "vendor", "trader", "wholesaler",
    "retailer", "producer", "maker", "firm", "contractor", "consultant",
    "specialist", "partner", "source", "sourcing", "trading", "seller",
    "manufacturers", "suppliers", "exporters", "distributors",
}

# Suffix classes that were unproductive in the real UAE run (n>=4 observed).
# 'pump' 0/4, 'film' 1/4. Kept conservative on purpose - only clear losers.
WEAK_SUFFIXES = {"pump", "film"}


def role_of(kw: str) -> str | None:
    w = str(kw).split()
    return w[-1].lower() if len(w) > 1 and w[-1].lower() in ROLES else None


def head_of(kw: str, n: int = 2) -> str:
    """The leading concept phrase, used to group modifier variants."""
    return " ".join(str(kw).split()[:n]).lower()


def productive_from_checkpoint() -> set[str]:
    """Keywords already proven to yield companies (any completed run)."""
    proven: set[str] = set()
    for f in HERE.glob(".checkpoint_*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for rec in d.get("companies", {}).values():
            for t in str(rec.get("search_term", "")).split(" | "):
                t = t.strip()
                if t:
                    proven.add(t.lower())
    return proven


def prune(tail: int = 3, drop_single: bool = True, stats_only: bool = False,
          out_path: Path = OUT) -> pd.DataFrame:
    c = pd.read_csv(COMBINED)
    n0 = len(c)
    c["_role"] = c.Keyword.map(role_of)
    c["_head"] = c.Keyword.map(head_of)
    c["_nw"] = c.Keyword.astype(str).str.split().str.len()
    c["_last"] = c.Keyword.astype(str).str.split().str[-1].str.lower()

    proven = productive_from_checkpoint()
    c["_proven"] = c.Keyword.astype(str).str.strip().str.lower().isin(proven)

    # Never drop a curated master keyword. Zero UAE results does not mean zero
    # results for another country, and this file is reused across countries.
    if "Source" in c.columns:
        c["_proven"] |= c.Source.eq("master")

    keep = pd.Series(True, index=c.index)
    reasons: dict[str, int] = collections.Counter()

    # 1. Drop single-word keywords (19% hit rate) unless already proven.
    if drop_single:
        m = (c._nw == 1) & ~c._proven
        keep &= ~m
        reasons["single-word"] = int(m.sum())

    # 2. Drop suffix classes that produced (almost) nothing, unless proven.
    m = c._last.isin(WEAK_SUFFIXES) & ~c._proven
    keep &= ~m
    reasons["weak-suffix"] = int(m.sum())

    # 3. Thin deep modifier tails: for non-role keywords sharing a 2-word head,
    #    keep the shortest `tail` variants (shortest = most general = widest
    #    result set). Role keywords and proven keywords are never thinned.
    cand = c[keep & c._role.isna() & ~c._proven].copy()
    cand = cand.sort_values(["_head", "_nw", "Keyword"], kind="stable")
    over = cand.groupby("_head").cumcount() >= tail
    drop_idx = cand.index[over]
    keep.loc[drop_idx] = False
    reasons[f"modifier-tail(>{tail}/head)"] = len(drop_idx)

    out = c[keep].drop(columns=[x for x in c.columns if x.startswith("_")])
    out = out.sort_values(["Priority", "Entities", "Keyword"],
                          kind="stable").reset_index(drop=True)

    print(f"combined keywords : {n0}")
    for r, n in reasons.items():
        print(f"  dropped {r:26} {n}")
    print(f"pruned keywords   : {len(out)}  ({100*len(out)/n0:.0f}% of combined)")
    print(f"  proven-productive kept : {int(c[keep]._proven.sum())} "
          f"(of {int(c._proven.sum())} known)")
    print(f"  entities retained      : {out.Entities.nunique()} / {c.Entities.nunique()}")
    print(f"  concept heads retained : {out.Keyword.map(head_of).nunique()} / "
          f"{c._head.nunique()}")
    print(f"  role variants retained : {out.Keyword.map(role_of).notna().sum()} / "
          f"{int(c._role.notna().sum())}")

    if not stats_only:
        out.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"\nwrote {len(out)} keywords -> {out_path}")
    return out


def main():
    ap = argparse.ArgumentParser(description="Prune keywords, preserving coverage")
    ap.add_argument("--tail", type=int, default=3,
                    help="modifier variants to keep per concept head (default 3)")
    ap.add_argument("--keep-single", action="store_true",
                    help="keep single-word keywords (default: drop, 19%% hit rate)")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    prune(tail=args.tail, drop_single=not args.keep_single,
          stats_only=args.stats, out_path=Path(args.out))


if __name__ == "__main__":
    main()
