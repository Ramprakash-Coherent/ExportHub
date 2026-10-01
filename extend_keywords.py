"""
Extend `agri_keywords_master.csv` with new keywords in the SAME pattern, to
cover more of global agriculture.

Why this instead of the 7,485-keyword `agri_keywords_combined.csv`
------------------------------------------------------------------
The listings/*.xlsx dump produced thousands of mechanical role variants
("Agri Equipment B2B", "Agri Equipment B2C"). Measured on the finished UAE run
those variants overlap heavily. The master file is different in kind: concrete,
real-world business and facility terms ("Broiler Poultry Farm", "Shrimp
Hatchery", "Veterinary Diagnostic Lab"), 2-4 words, specific not generic.

This script keeps that style and fills the real gaps:
  * thin entities - many entities had only 4-10 keywords vs 20-47 for the
    strongest ones;
  * whole topics absent from the master (beekeeping, mushrooms, date palm,
    camel dairy, post-harvest cold chain, sericulture, ...);
  * region-specific agriculture (Gulf/MENA, Asia, Africa, Latin America) so the
    same file works for any --country, not just UAE.

Spot-checked against live UAE search before writing: of 10 candidate keywords in
this style, 5 returned results and together surfaced 38 companies that the
entire 697-keyword run had missed (e.g. "Beekeeping Apiary Supplies" -> 13 new).

Usage
-----
    python extend_keywords.py             # -> agri_keywords_extended.csv
    python extend_keywords.py --stats     # report only, write nothing
    python extend_keywords.py --verify    # probe each NEW keyword against the
                                          # live site and keep only productive
                                          # ones (slow: ~3s per keyword)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
MASTER = HERE / "agri_keywords_master.csv"
OUT = HERE / "agri_keywords_extended.csv"
STATE = HERE / "eh_state.json"

# New keywords per entity, matching the master's style: concrete business or
# facility terms, 2-4 words, globally applicable with some regional specificity.
NEW: dict[str, list[str]] = {
    "Seeds, crop protection, fertilizers & biologicals suppliers": [
        "Hybrid Seed Producer", "Vegetable Seed Company", "Seed Treatment Plant",
        "Seed Testing Laboratory", "Cover Crop Seed Supplier",
        "Forage Seed Supplier", "Rootstock Nursery Supplier",
    ],
    "Fertilizers and crop nutrition supplier": [
        "Compost Production Plant", "Vermicompost Producer",
        "Humic Acid Manufacturer", "Seaweed Extract Fertilizer",
        "Calcium Nitrate Supplier", "Sulphur Fertilizer Supplier",
        "Foliar Nutrition Supplier",
    ],
    "Crop protection & agrochemicals supplier": [
        "Pheromone Trap Supplier", "Neem Oil Pesticide Supplier",
        "Bio Control Agent Supplier", "Seed Dressing Chemical Supplier",
        "Sticky Trap Manufacturer",
    ],
    "Farm machinery & heavy equipment OEMs": [
        "Combine Harvester Dealer", "Rice Transplanter Supplier",
        "Sugarcane Harvester Supplier", "Laser Land Leveller",
        "Rotavator Manufacturer", "Baler Machine Supplier",
        "Date Palm Harvesting Equipment",
    ],
    "Feed mill operators & nutrition managers": [
        "Cattle Feed Plant", "Poultry Feed Mill", "Feed Pellet Plant",
        "Silage Production Unit", "Total Mixed Ration Supplier",
        "Feed Premix Manufacturer",
    ],
    "Water management & irrigation technology providers": [
        "Drip Irrigation Installer", "Sprinkler Irrigation Supplier",
        "Pivot Irrigation System", "Solar Water Pump Irrigation",
        "Desalination Irrigation Solution", "Treated Wastewater Irrigation",
        "Rainwater Harvesting Agriculture", "Fertigation System Supplier",
    ],
    "Coco peat / substrate supplier": [
        "Perlite Substrate Supplier", "Rockwool Growing Media",
        "Peat Moss Importer", "Vermiculite Supplier",
        "Rice Husk Substrate Supplier",
    ],
    "Aquaculture products & services provider": [
        "Shrimp Feed Supplier", "Fish Fingerling Supplier",
        "Aquaculture Consultancy Service", "Seafood Processing Plant",
        "Ornamental Fish Exporter", "Seaweed Farming Company",
    ],
    "Vertical farming / racking systems provider": [
        "Container Vertical Farm", "Plant Factory Equipment",
        "Grow Light LED Supplier", "Vertical Farm Automation",
    ],
    "Agri input / equipment manufacturer": [
        "Knapsack Sprayer Manufacturer", "Farm Tool Manufacturer",
        "Milking Machine Manufacturer", "Egg Incubator Manufacturer",
        "Grain Dryer Manufacturer",
    ],
    "Plastics & infrastructure components": [
        "Greenhouse Shade Net Supplier", "Mulch Film Manufacturer",
        "Insect Net Supplier", "Silage Wrap Film Supplier",
        "HDPE Pond Liner Supplier", "Plant Nursery Pot Manufacturer",
    ],
    "Aquaculture input & technology suppliers": [
        "Aquaculture Aerator Supplier", "Water Quality Monitoring Aquaculture",
        "Biofloc Tank Supplier", "Fish Pond Liner Supplier",
    ],
    "Agri-tech, IoT, drones & robotics providers": [
        "Agricultural Drone Spraying Service", "Farm Robot Supplier",
        "Soil Moisture Sensor Supplier", "Weather Station Agriculture",
        "Livestock Ear Tag RFID", "Crop Scouting Drone Service",
    ],
    "Livestock nutrition & veterinary suppliers": [
        "Cattle Mineral Block Supplier", "Veterinary Vaccine Distributor",
        "Animal Feed Additive Supplier", "Livestock Dewormer Supplier",
        "Poultry Vitamin Premix",
    ],
    "Greenhouse construction & hydroponics providers": [
        "Polyhouse Construction Company", "Glass Greenhouse Builder",
        "Screen House Construction", "Hydroponic Farm Turnkey Project",
        "Greenhouse Cooling Pad System", "Net House Construction",
    ],
    "Poultry farms and integrators": [
        "Quail Farming", "Poultry Processing Plant", "Poultry Feed Integrator",
        "Ostrich Farm", "Guinea Fowl Farm",
    ],
    "Fish and shrimp farm operators": [
        "Cage Fish Farming", "Crab Farming Operation", "Oyster Farm",
        "Mussel Farming", "Sea Bass Farm", "Tuna Aquaculture",
    ],
    "Livestock farm operators (beef, dairy, sheep)": [
        "Camel Dairy Farm", "Goat Dairy Farm", "Feedlot Cattle Operation",
        "Sheep Fattening Farm", "Buffalo Dairy Farm", "Cattle Breeding Ranch",
    ],
    "Organic / regenerative farming operators": [
        "Certified Organic Farm", "Biodynamic Farm", "Permaculture Farm",
        "Agroforestry Plantation", "Organic Date Farm",
    ],
    "Large-scale farm owners & agribusiness groups": [
        "Date Palm Plantation", "Banana Plantation Company",
        "Oil Palm Plantation", "Tea Estate Company", "Coffee Plantation Company",
        "Sugarcane Estate", "Rice Milling Company",
    ],
    "Nurseries & landscaping firms": [
        "Ornamental Plant Nursery", "Turf Grass Supplier",
        "Landscape Contracting Company", "Fruit Tree Nursery",
        "Palm Tree Supplier", "Indoor Plant Supplier",
    ],
    "Supply chain & logistics decision-makers": [
        "Reefer Container Logistics", "Cold Storage Warehouse Agriculture",
        "Grain Silo Operator", "Agri Commodity Freight Forwarder",
        "Perishable Cargo Handling",
    ],
    "Exporters & trading companies": [
        "Fresh Produce Exporter", "Grain Trading Company",
        "Spice Exporter", "Pulses Exporter", "Dried Fruit Exporter",
        "Livestock Exporter",
    ],
    "Alternative protein & circular economy ventures": [
        "Insect Protein Producer", "Black Soldier Fly Farming",
        "Algae Protein Producer", "Plant Based Protein Manufacturer",
        "Agricultural Waste Recycling",
    ],
    "Renewable energy in agriculture adopters": [
        "Solar Powered Greenhouse", "Biogas Plant Farm",
        "Agrivoltaics Project", "Biomass Energy Agriculture",
    ],
    "Aquaponics & RAS operators": [
        "Recirculating Aquaculture System Farm", "Aquaponics Greenhouse Farm",
        "Fish Vegetable Integrated Farm",
    ],
    "Veterinary hospitals & clinics": [
        "Camel Veterinary Clinic", "Equine Veterinary Hospital",
        "Veterinary Pharmacy", "Artificial Insemination Center Livestock",
    ],
    "Certification bodies, labs & standards organisations": [
        "Organic Certification Body", "GlobalGAP Certification Body",
        "Food Safety Testing Laboratory", "Soil Testing Laboratory",
        "Pesticide Residue Testing Lab", "Halal Certification Body",
    ],
    "Market intelligence & consulting firm": [
        "Agriculture Market Research Firm", "Commodity Price Analytics",
        "Agribusiness Advisory Firm",
    ],
    "Agriculture & food security authorities": [
        "Ministry Of Agriculture", "Food Security Authority",
        "Plant Quarantine Department", "Agricultural Extension Service",
    ],
    "Agri-focused investors & VCs": [
        "Agriculture Private Equity", "Food Security Investment Fund",
        "Aquaculture Investment Company",
    ],
    "Banks & DFIs": [
        "Agricultural Insurance Company", "Crop Insurance Provider",
        "Microfinance Agriculture", "Islamic Agriculture Finance",
    ],
    "Water & irrigation authorities": [
        "Groundwater Authority", "Water Users Association",
        "Wastewater Reuse Authority",
    ],
    "Farm management software & SaaS users": [
        "Farm ERP Software", "Livestock Management Software",
        "Traceability Software Agriculture", "Greenhouse Climate Software",
    ],
    "Precision ag, drone & sensing users": [
        "Satellite Crop Monitoring", "NDVI Mapping Service",
        "Yield Mapping Service", "Soil Sampling Service",
    ],
    "Smart greenhouse & livestock monitoring adopters": [
        "Dairy Herd Monitoring System", "Poultry House Climate Controller",
        "Greenhouse Sensor Network",
    ],
    "Sustainability & impact platform": [
        "Carbon Farming Platform", "Agriculture Carbon Credit",
        "Regenerative Agriculture Program",
    ],
    "Tech / digital solutions provider": [
        "Agri E Commerce Platform", "Farmer Advisory Mobile App",
        "Agri Fintech Platform", "Digital Crop Marketplace",
    ],
    "Greenhouse & controlled-environment farming operators": [
        "Tomato Greenhouse Grower", "Cucumber Greenhouse Farm",
        "Strawberry Greenhouse Farm", "Leafy Greens Greenhouse",
        "Flower Greenhouse Grower",
    ],
    "Urban / vertical farming companies": [
        "Rooftop Farming Company", "Indoor Microgreens Farm",
        "Community Urban Farm",
    ],
    "Dealers, distributors & importers": [
        "Tractor Dealership", "Agrochemical Distributor",
        "Seed Distribution Company", "Veterinary Products Importer",
    ],
    "Regional agri trading / distribution company": [
        "Fruit Vegetable Wholesale Market", "Agri Commodity Trading House",
        "Feed Ingredient Trader",
    ],
    "Sustainable & regenerative agriculture solution providers": [
        "Soil Health Solution Provider", "Water Saving Agriculture Technology",
        "Desert Agriculture Solution",
    ],
    "Agri inputs & solutions supplier": [
        "Greenhouse Input Supplier", "Turnkey Farm Solution Provider",
    ],
    "Innovative agri solutions supplier": [
        "Hydroponic Fodder Unit", "Desert Greening Technology",
        "Saline Agriculture Solution",
    ],
    "Liquid / fertilizer storage solutions provider": [
        "Fertilizer Storage Tank", "Liquid Fertilizer Tank Supplier",
        "Water Storage Tank Farm",
    ],
    "Agriculture strategy & CEA advisory": [
        "CEA Feasibility Study", "Agriculture Investment Advisory",
    ],
    "Greenhouse sustainability consulting & design firm": [
        "Greenhouse Design Consultant", "Greenhouse Energy Audit",
    ],
    "Regional agricultural development authorities": [
        "Agricultural Development Authority", "Rural Development Agency",
    ],
    "Agri input / equipment distributor": [
        "Irrigation Equipment Distributor", "Greenhouse Equipment Distributor",
    ],
    "Greenhouse / CEA solutions consortium": [
        "CEA Industry Association", "Hydroponics Growers Association",
    ],
    # Topics absent from the master file entirely.
    "Beekeeping & apiculture suppliers": [
        "Beekeeping Equipment Supplier", "Beekeeping Apiary Supplies",
        "Honey Processing Company", "Queen Bee Breeder", "Beehive Manufacturer",
    ],
    "Mushroom & specialty crop growers": [
        "Mushroom Growing Farm", "Mushroom Spawn Supplier",
        "Truffle Cultivation", "Sprouts Growing Facility",
    ],
    "Post-harvest & processing equipment suppliers": [
        "Post Harvest Cold Chain", "Fruit Grading Machine Supplier",
        "Grain Cleaning Machine", "Fruit Ripening Chamber",
        "Vacuum Cooling Equipment", "Date Processing Plant",
    ],
    "Sericulture & fibre crop operators": [
        "Sericulture Farm", "Cotton Ginning Company", "Jute Processing Mill",
    ],
}

DEFAULT_GROUP = "product_goods"
DEFAULT_PRIORITY = 1
# Groups/priorities for the entities that are new to the master file.
NEW_ENTITY_META = {
    "Beekeeping & apiculture suppliers": ("product_goods", 1),
    "Mushroom & specialty crop growers": ("product_goods", 1),
    "Post-harvest & processing equipment suppliers": ("product_goods", 1),
    "Sericulture & fibre crop operators": ("product_goods", 1),
}


def norm(s: str) -> str:
    s = str(s).strip().lower()
    s = re.sub(r"[^\w\s&/-]", "", s)
    return re.sub(r"\s+", " ", s)


def build(stats_only=False, verify=False, out_path=OUT) -> pd.DataFrame:
    m = pd.read_csv(MASTER)
    for c in ("Keyword", "Entities", "Group"):
        m[c] = m[c].astype(str).str.strip()

    # entity -> (Group, Priority) taken from the master itself
    meta = {}
    for _, r in m.iterrows():
        for part in str(r["Entities"]).split(";"):
            meta.setdefault(part.strip(), (r["Group"], r["Priority"]))
    meta.update(NEW_ENTITY_META)

    have = set(m.Keyword.map(norm))
    rows, skipped = [], 0
    for entity, kws in NEW.items():
        g, p = meta.get(entity, (DEFAULT_GROUP, DEFAULT_PRIORITY))
        for kw in kws:
            if norm(kw) in have:
                skipped += 1
                continue
            have.add(norm(kw))
            rows.append({"Keyword": kw, "Entities": entity,
                         "Group": g, "Priority": p})
    new = pd.DataFrame(rows)

    if verify and len(new):
        new = verify_live(new)

    out = pd.concat([m[["Keyword", "Entities", "Group", "Priority"]], new],
                    ignore_index=True)
    out["_k"] = out.Keyword.map(norm)
    out = out.drop_duplicates("_k", keep="first").drop(columns="_k")
    out = out.sort_values(["Priority", "Entities", "Keyword"],
                          kind="stable").reset_index(drop=True)

    print(f"master keywords    : {len(m)}")
    print(f"new keywords added : {len(new)}"
          + (f"  ({skipped} already present, skipped)" if skipped else ""))
    print(f"extended total     : {len(out)}")
    print(f"entities           : {out.Entities.nunique()} "
          f"(was {m.Entities.nunique()})")
    thin = out.groupby("Entities").size()
    print(f"keywords/entity    : min {thin.min()}, median {int(thin.median())}, "
          f"max {thin.max()}")

    if not stats_only:
        out.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"\nwrote {len(out)} keywords -> {out_path}")
    return out


def verify_live(new: pd.DataFrame, country_id: int = 2) -> pd.DataFrame:
    """Probe each new keyword; keep only those with results for the country."""
    from bs4 import BeautifulSoup
    from curl_cffi import requests as cr

    if not STATE.exists():
        print("  ! no eh_state.json - skipping --verify")
        return new
    st = json.loads(STATE.read_text(encoding="utf-8"))
    ck = {c["name"]: c["value"] for c in st.get("cookies", [])
          if "exporthub" in c.get("domain", "")}
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")
    s = cr.Session(impersonate="chrome", headers={"User-Agent": ua})
    s.cookies.update(ck)

    keep = []
    print(f"verifying {len(new)} new keywords against live search...")
    for i, kw in enumerate(new.Keyword, 1):
        url = f"https://www.exporthub.com/search?type=1&keyword={kw.replace(' ', '+')}"
        try:
            h = s.get(url, timeout=60).text
            ok = f'id="sidebar-filter-{country_id}"' in h
        except Exception:
            ok = False
        keep.append(ok)
        if i % 20 == 0:
            print(f"  {i}/{len(new)}")
        time.sleep(0.4)
    new = new[pd.Series(keep, index=new.index)]
    print(f"  kept {len(new)} productive keywords")
    return new


def main():
    ap = argparse.ArgumentParser(description="Extend master keywords in-pattern")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--verify", action="store_true",
                    help="probe new keywords live and drop unproductive ones")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    build(stats_only=args.stats, verify=args.verify, out_path=Path(args.out))


if __name__ == "__main__":
    main()
