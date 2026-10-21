"""
Watchmaker Caliber ETL & Normalization Pipeline
===============================================
What this script does:
1. Demonstrates cleaning messy website + PDF table data (`data/raw_samples/messy_scraped_and_pdf_extract.json`).
2. Loads all clean YAML movement files from `data/fixtures/`.
3. Builds the 5 core tables in `data/processed/` as clean CSV files you can open in VS Code or Excel:
   - 1_calibers.csv                 (All watch movements & normalized measurements)
   - 2_family_tree_relations.csv    (Parent / Child / Clone arrows)
   - 3_interchangeable_parts.csv    (Parts inside each movement + their shared Storage Bin / part_class)
   - 4_donor_movement_rankings.csv  (Ranked donor movements calculated using donor_weight!)
   - 5_drop_in_substitutes.csv      (Whole-movement swap compatibility based on case & hand sizes)
"""

import csv
import json
import re
import sys
import unicodedata
from pathlib import Path

import yaml

# Ensure etl modules can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent))
from algorithms import calculate_donor_rankings, calculate_movement_substitutes

ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = ROOT / "data" / "fixtures"
RAW_SAMPLES_DIR = ROOT / "data" / "raw_samples"
PROCESSED_DIR = ROOT / "data" / "processed"

# Universal Swiss CS Part Number -> Our internal part_type slot name
CS_CODE_TO_SLOT = {
    "401": "winding_stem",
    "407": "sliding_pinion",
    "410": "winding_pinion",
    "443": "setting_lever",
    "445": "setting_lever_jumper",
    "705": "escape_wheel",
    "710": "pallet_fork",
    "721": "balance_complete",
    "723": "balance_staff",
    "770": "mainspring",
    "240": "cannon_pinion",
    "206": "center_wheel",
    "220": "fourth_wheel",
    "1488": "reversing_wheel",
    "2557": "date_indicator",
}


# ─────────────────────────────────────────────────────────────
# STEP 1: Normalization Functions (Fixes messy text & units)
# ─────────────────────────────────────────────────────────────
_DASHES = re.compile(r"[\u2010-\u2015\u2212]")
_NOISE = re.compile(r"\b(cal(iber|ibre)?|kal(iber)?|mvt|movement)\b\.?", re.I)
_VARIANT = re.compile(r"(?<=\d)[/_ ](?=\d{1,2}[a-z]?\b)")


def fold_name(raw: str) -> str:
    """Cleans up messy movement strings: 'Cal. ETA 2824/2' -> 'eta 2824-2'"""
    s = unicodedata.normalize("NFKD", raw)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = _DASHES.sub("-", s).casefold()
    s = _NOISE.sub(" ", s)
    s = re.sub(r"\s*\(.*?\)", "", s)  # strip parenthetical notes like '(also called...)'
    s = re.sub(r"\s+", " ", s).strip(" .")
    return _VARIANT.sub("-", s)


def parse_mm_or_ligne(raw_text: str) -> float | None:
    """Extracts mm from strings like "11.5''' (25,60 mm)" or converts lignes to mm."""
    if not raw_text:
        return None
    text = raw_text.replace(",", ".")
    mm_match = re.search(r"(\d+(?:\.\d+)?)\s*mm", text, re.I)
    if mm_match:
        return round(float(mm_match.group(1)), 2)
    ligne_match = re.search(r"(\d+(?:\.\d+)?)\s*'''", text)
    if ligne_match:
        return round(float(ligne_match.group(1)) * 2.2558, 2)
    return None


def parse_vph_or_hz(raw_text: str) -> int | None:
    """Converts '4 Hz (28.800 A/h)' -> 28800 vph."""
    if not raw_text:
        return None
    vph_match = re.search(r"(\d{2})[.,]?(\d{3})\s*(?:a/h|vph|bph)", raw_text, re.I)
    if vph_match:
        return int(vph_match.group(1) + vph_match.group(2))
    hz_match = re.search(r"(\d+(?:\.\d+)?)\s*hz", raw_text, re.I)
    if hz_match:
        return int(round(float(hz_match.group(1)) * 7200))
    return None


def demo_raw_normalization() -> None:
    """Demonstrates how a messy webpage + PDF parts table gets normalized."""
    sample_file = RAW_SAMPLES_DIR / "messy_scraped_and_pdf_extract.json"
    if not sample_file.exists():
        return
    raw_items = json.loads(sample_file.read_text(encoding="utf-8"))
    cleaned_demo = []
    for item in raw_items:
        cleaned_Name = fold_name(item["raw_caliber_name"])
        diam_mm = parse_mm_or_ligne(item["raw_diameter"])
        height_mm = parse_mm_or_ligne(item["raw_height"])
        vph = parse_vph_or_hz(item["raw_frequency"])
        hands = [float(x) for x in re.findall(r"\d+\.\d+", item.get("raw_hands", ""))]

        # Convert PDF CS numbers (401, 710, 721...) into standardized part_class bins!
        extracted_parts = []
        for row in item.get("raw_pdf_parts_table", []):
            cs = row["cs_code"]
            base_ref = row["base_caliber_ref"].lower().replace("-", "_")
            slot = CS_CODE_TO_SLOT.get(cs, f"cs_{cs}")
            extracted_parts.append(
                {
                    "cs_code": cs,
                    "slot": slot,
                    "interchange_group_bin": f"grp:eta{base_ref}_{slot}_{cs}",
                }
            )

        cleaned_demo.append(
            {
                "normalized_name": cleaned_Name,
                "diameter_mm": diam_mm,
                "ligne_calculated": round(diam_mm / 2.2558, 1) if diam_mm else None,
                "height_mm": height_mm,
                "beat_rate_vph": vph,
                "hour_hand_mm": hands[0] if len(hands) > 0 else None,
                "minute_hand_mm": hands[1] if len(hands) > 1 else None,
                "seconds_hand_mm": hands[2] if len(hands) > 2 else None,
                "normalized_parts_from_pdf": extracted_parts,
            }
        )

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PROCESSED_DIR / "0_demo_cleaned_from_raw.json"
    out_path.write_text(json.dumps(cleaned_demo, indent=2), encoding="utf-8")


# ─────────────────────────────────────────────────────────────
# STEP 2: Load YAML Fixtures & Compute Graph / Donor / Swap Tables
# ─────────────────────────────────────────────────────────────
def run_pipeline() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    demo_raw_normalization()

    # 1. Load part_types and their donor_weight scores
    part_types_data = yaml.safe_load(
        (FIXTURES_DIR / "part_types.yaml").read_text(encoding="utf-8")
    )
    slot_weights: dict[str, float] = {}
    slot_cs: dict[str, str] = {}
    for pt in part_types_data["part_types"]:
        slot_weights[pt["code"]] = float(pt["donor_weight"])
        slot_cs[pt["code"]] = pt["cs_number"]

    # 2. Load all caliber family YAML files
    calibers: list[dict] = []
    relations: list[dict] = []
    caliber_parts: list[dict] = []

    for yaml_path in sorted((FIXTURES_DIR / "calibers").glob("*.yaml")):
        doc = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        family_slug = doc["family"]["slug"]
        for c in doc["calibers"]:
            env = c.get("envelope", {})
            perf = c.get("performance", {})
            diam = env.get("diameter_mm")
            calibers.append(
                {
                    "canonical_key": c["canonical_key"],
                    "display_name": c["display_name"],
                    "manufacturer": c["manufacturer"],
                    "family": family_slug,
                    "winding": c.get("winding", ""),
                    "diameter_mm": diam,
                    "ligne": round(diam / 2.2558, 1) if diam else "",
                    "height_mm": env.get("height_mm"),
                    "stem_height_mm": env.get("stem_height_mm"),
                    "crown_oclock": env.get("crown_position_oclock"),
                    "hour_hand_mm": env.get("hour_hand_hole_mm"),
                    "minute_hand_mm": env.get("minute_hand_post_mm"),
                    "seconds_hand_mm": env.get("seconds_hand_post_mm"),
                    "date_oclock": env.get("date_position_oclock"),
                    "beat_rate_vph": perf.get("beat_rate_vph"),
                    "jewels": perf.get("jewels"),
                    "power_reserve_h": perf.get("power_reserve_h"),
                    "status": c.get("status", "unknown"),
                    "accessibility_score": float(c.get("accessibility_score", 0.5)),
                }
            )

            for rel in c.get("relations", []):
                relations.append(
                    {
                        "from_caliber": c["canonical_key"],
                        "from_name": c["display_name"],
                        "relationship_kind": rel["kind"],
                        "subtype": rel["subtype"],
                        "to_caliber": rel["to"],
                        "modification_degree": rel["modification_degree"],
                        "confidence": rel["confidence"],
                        "notes": rel.get("notes", ""),
                    }
                )

            for p in c.get("parts", []):
                slot = p["slot"]
                caliber_parts.append(
                    {
                        "caliber_key": c["canonical_key"],
                        "caliber_name": c["display_name"],
                        "cs_code": slot_cs.get(slot, ""),
                        "part_slot": slot,
                        "part_number": p["part_number"],
                        "shared_storage_bin_part_class": p["interchange_group"],
                        "donor_weight": slot_weights.get(slot, 0.5),
                    }
                )

    # 3. Write 1_calibers.csv
    with (PROCESSED_DIR / "1_calibers.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(calibers[0].keys()))
        writer.writeheader()
        writer.writerows(calibers)

    # 4. Write 2_family_tree_relations.csv
    with (PROCESSED_DIR / "2_family_tree_relations.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.DictWriter(f, fieldnames=list(relations[0].keys()))
        writer.writeheader()
        writer.writerows(relations)

    # 5. Write 3_interchangeable_parts.csv
    with (PROCESSED_DIR / "3_interchangeable_parts.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.DictWriter(f, fieldnames=list(caliber_parts[0].keys()))
        writer.writeheader()
        writer.writerows(caliber_parts)

    # 6. Calculate & Write 4_donor_movement_rankings.csv
    donor_rows = calculate_donor_rankings(calibers, caliber_parts)
    with (PROCESSED_DIR / "4_donor_movement_rankings.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.DictWriter(f, fieldnames=list(donor_rows[0].keys()))
        writer.writeheader()
        writer.writerows(donor_rows)

    # 7. Calculate & Write 5_drop_in_substitutes.csv (Whole Movement Case/Hand Swap)
    sub_rows = calculate_movement_substitutes(calibers)
    with (PROCESSED_DIR / "5_drop_in_substitutes.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.DictWriter(f, fieldnames=list(sub_rows[0].keys()))
        writer.writeheader()
        writer.writerows(sub_rows)

    print(f"Successfully processed {len(calibers)} calibers, {len(relations)} family tree links, and {len(caliber_parts)} part mappings!")
    print(f"Generated 5 CSV tables in: {PROCESSED_DIR}")


if __name__ == "__main__":
    run_pipeline()
