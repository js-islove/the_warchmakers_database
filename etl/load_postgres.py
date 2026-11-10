"""
PostgreSQL Database Loader (etl/load_postgres.py)
-------------------------------------------------
Loads both:
  1. Curated Horological YAML Fixtures (`data/fixtures/`)
     - Manufacturers, Architecture Families, Calibers, Parts, Interchange Classes, Family Relations
  2. Scraped 17jewels Movements (`data/processed/17jewels_synced_movements.json`)
     - 1,039 movements with physical specs, JSONB `raw_specs`, and automatic `caliber base` -> `DERIVED_FROM` lineage edges
  3. Precomputed Donor Movement Rankings (`horo.caliber_similarity`)

Usage:
  python etl/load_postgres.py             # Connects to PostgreSQL & loads everything
  python etl/load_postgres.py --dry-run   # Validates & summarizes all data without a DB connection
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from etl.algorithms import calculate_donor_rankings

FIXTURES_DIR = ROOT_DIR / "data" / "fixtures"
PROCESSED_DIR = ROOT_DIR / "data" / "processed"
MIGRATION_FILE = ROOT_DIR / "packages" / "db" / "migrations" / "001_init_horo_schema.sql"
SCRAPED_JSON_FILE = PROCESSED_DIR / "17jewels_synced_movements.json"

DEFAULT_DB_URL = "postgresql://watchmaker:watchmaker_secret@127.0.0.1:5435/watchmaker_db"


def get_db_connection(db_url: str):
    """Connect using psycopg2 or psycopg (v3), whichever is installed."""
    try:
        import psycopg2
        conn = psycopg2.connect(db_url)
        return conn
    except ImportError:
        import psycopg
        conn = psycopg.connect(db_url)
        return conn


# ---------------------------------------------------------------------------
# Normalization Helpers for Scraped 17jewels Fields
# ---------------------------------------------------------------------------
def parse_height_mm(raw_table: Dict[str, Any]) -> Optional[float]:
    """Extract numeric height in mm from strings like '3,50mm' or '4.6 mm'."""
    val = raw_table.get("height")
    if not val or not isinstance(val, str):
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*mm", val.lower())
    if m:
        try:
            num = float(m.group(1).replace(",", "."))
            if 0.5 <= num <= 30.0:
                return round(num, 2)
        except ValueError:
            pass
    return None


def parse_production_years(raw_table: Dict[str, Any]) -> Tuple[Optional[int], Optional[int]]:
    """Extract (start_year, end_year) from 'production period' or 'mentioning in literature (years)'."""
    raw = raw_table.get("production period") or raw_table.get("mentioning in literature (years)") or ""
    if not raw or not isinstance(raw, str):
        return None, None
    years = [int(y) for y in re.findall(r"\b(1[89]\d{2}|20[0-2]\d)\b", raw)]
    if not years:
        return None, None
    if len(years) == 1:
        return years[0], None
    return min(years), max(years)


def parse_features_list(features_str: Optional[str]) -> List[str]:
    """Convert comma/newline separated features string into clean list of tokens."""
    if not features_str:
        return []
    parts = re.split(r"[,;/\n]+", features_str)
    return [p.strip() for p in parts if p.strip()]


def load_curated_data() -> Tuple[List[Dict], List[Dict], List[Dict], List[Dict]]:
    """Read curated YAML fixtures from data/fixtures/."""
    with open(FIXTURES_DIR / "manufacturers.yaml", "r", encoding="utf-8") as f:
        manufacturers = yaml.safe_load(f)["manufacturers"]

    with open(FIXTURES_DIR / "part_types.yaml", "r", encoding="utf-8") as f:
        part_types = yaml.safe_load(f)["part_types"]

    families = []
    calibers = []
    for path in sorted(glob.glob(str(FIXTURES_DIR / "calibers" / "*.yaml"))):
        with open(path, "r", encoding="utf-8") as f:
            doc = yaml.safe_load(f)
            fam = doc["family"]
            families.append(fam)
            for cal in doc["calibers"]:
                cal["family_slug"] = fam["slug"]
                calibers.append(cal)

    return manufacturers, part_types, families, calibers


def load_scraped_data() -> List[Dict[str, Any]]:
    """Read scraped 17jewels movements JSON if present."""
    if not SCRAPED_JSON_FILE.exists():
        print(f"[WARN] {SCRAPED_JSON_FILE} not found; loading only curated YAML fixtures.")
        return []
    with open(SCRAPED_JSON_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_scraped_base_relations(
    scraped_movements: List[Dict[str, Any]],
    all_known_keys_by_display: Dict[str, str],
) -> List[Dict[str, Any]]:
    """
    Match `raw_table['caliber base']` (e.g., 'AS 1525' or ' ETA 2824 ') against known movements
    to automatically create DERIVED_FROM lineage edges for scraped 17jewels movements.
    """
    inferred_relations: List[Dict[str, Any]] = []
    seen_pairs = set()

    for rec in scraped_movements:
        from_key = rec["canonical_key"]
        raw_table = rec.get("raw_table") or {}
        base_str = raw_table.get("caliber base")
        if not base_str or not isinstance(base_str, str):
            continue

        # Normalize base string to lookup canonical_key
        norm_base = re.sub(r"[^a-z0-9]+", "", base_str.lower())
        to_key = all_known_keys_by_display.get(norm_base)
        if not to_key:
            # Also try prefixing with same manufacturer slug if base_str is just caliber number
            maker_slug = rec.get("manufacturer_slug", "")
            candidate_norm = re.sub(r"[^a-z0-9]+", "", f"{maker_slug}{base_str}".lower())
            to_key = all_known_keys_by_display.get(candidate_norm)

        if to_key and to_key != from_key and (from_key, to_key) not in seen_pairs:
            seen_pairs.add((from_key, to_key))
            inferred_relations.append({
                "from_key": from_key,
                "to_key": to_key,
                "kind": "DERIVED_FROM",
                "subtype": "base_caliber",
                "modification_degree": 2,
                "confidence": 0.90,
                "notes": f"17jewels documented caliber base: {base_str}",
            })

    return inferred_relations


def run_loader(db_url: str, dry_run: bool = False) -> None:
    manufacturers, part_types, families, curated_calibers = load_curated_data()
    scraped_movements = load_scraped_data()

    # Build normalized display name -> canonical_key lookup for base-caliber resolution
    display_lookup: Dict[str, str] = {}
    for cal in curated_calibers:
        norm = re.sub(r"[^a-z0-9]+", "", cal["display_name"].lower())
        display_lookup[norm] = cal["canonical_key"]
        norm_key = re.sub(r"[^a-z0-9]+", "", cal["canonical_key"].lower())
        display_lookup[norm_key] = cal["canonical_key"]
    for rec in scraped_movements:
        norm = re.sub(r"[^a-z0-9]+", "", rec["display_name"].lower())
        display_lookup.setdefault(norm, rec["canonical_key"])
        norm_key = re.sub(r"[^a-z0-9]+", "", rec["canonical_key"].lower())
        display_lookup.setdefault(norm_key, rec["canonical_key"])

    inferred_relations = resolve_scraped_base_relations(scraped_movements, display_lookup)

    # Compute donor rankings from curated part lists
    part_type_by_code = {pt["code"]: pt for pt in part_types}
    flat_parts = []
    for cal in curated_calibers:
        for p in cal.get("parts", []):
            slot_meta = part_type_by_code[p["slot"]]
            flat_parts.append({
                "caliber_key": cal["canonical_key"],
                "part_slot": p["slot"],
                "cs_number": slot_meta["cs_number"],
                "part_name": slot_meta["name"],
                "part_number": p["part_number"],
                "shared_storage_bin_part_class": p["interchange_group"],
                "compatibility": p.get("compatibility", "direct"),
                "donor_weight": slot_meta["donor_weight"],
                "notes": p.get("notes", ""),
            })
    donor_rankings = calculate_donor_rankings(curated_calibers, flat_parts)

    heights_found = sum(1 for r in scraped_movements if parse_height_mm(r.get("raw_table") or {}) is not None)
    years_found = sum(1 for r in scraped_movements if parse_production_years(r.get("raw_table") or {})[0] is not None)

    print("=" * 72)
    print(" HOROLOGICAL DATABASE LOADER SUMMARY")
    print("=" * 72)
    print(f"  - Curated Manufacturers     : {len(manufacturers)}")
    print(f"  - Universal Part Slots (CS) : {len(part_types)}")
    print(f"  - Curated Families          : {len(families)}")
    print(f"  - Curated Calibers (YAML)   : {len(curated_calibers)}")
    print(f"  - Scraped Calibers (JSON)   : {len(scraped_movements)}")
    print(f"      * With parsed height_mm : {heights_found}")
    print(f"      * With production years : {years_found}")
    print(f"      * Base caliber edges    : {len(inferred_relations)}")
    print(f"  - Precomputed Donor Pairs   : {len(donor_rankings)}")
    print("=" * 72)

    if dry_run:
        print("[DRY-RUN] Validation complete! Omit --dry-run once PostgreSQL is running.")
        return

    print(f"\nConnecting to PostgreSQL...")
    conn = get_db_connection(db_url)
    conn.autocommit = False

    try:
        # 1. Execute schema migration and commit so new enum values are registered in pg_enum
        print(f"Applying migration: {MIGRATION_FILE.name} ...")
        sql_schema = MIGRATION_FILE.read_text(encoding="utf-8")
        with conn.cursor() as cur:
            cur.execute(sql_schema)
        conn.commit()

        with conn.cursor() as cur:
            # 2. Upsert Manufacturers (Curated + Scraped)
            print("Loading manufacturers...")
            maker_id_by_slug: Dict[str, int] = {}
            for m in manufacturers:
                cur.execute(
                    """
                    INSERT INTO horo.manufacturer (slug, name, aliases, country_code, founded_year, roles)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (slug) DO UPDATE SET
                        name = EXCLUDED.name,
                        aliases = EXCLUDED.aliases,
                        country_code = COALESCE(EXCLUDED.country_code, horo.manufacturer.country_code),
                        founded_year = COALESCE(EXCLUDED.founded_year, horo.manufacturer.founded_year),
                        roles = EXCLUDED.roles
                    RETURNING id;
                    """,
                    (
                        m["slug"],
                        m["name"],
                        m.get("aliases", []),
                        m.get("country_code"),
                        m.get("founded_year"),
                        m.get("roles", []),
                    ),
                )
                maker_id_by_slug[m["slug"]] = cur.fetchone()[0]

            for rec in scraped_movements:
                m_slug = rec["manufacturer_slug"]
                m_name = rec["manufacturer_name"]
                if m_slug not in maker_id_by_slug:
                    cur.execute(
                        """
                        INSERT INTO horo.manufacturer (slug, name, roles)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (slug) DO UPDATE SET name = horo.manufacturer.name
                        RETURNING id;
                        """,
                        (m_slug, m_name, ["ebauche_maker"]),
                    )
                    maker_id_by_slug[m_slug] = cur.fetchone()[0]

            # 3. Upsert Architecture Families
            print("Loading architecture families...")
            family_id_by_slug: Dict[str, int] = {}
            for fam in families:
                cur.execute(
                    """
                    INSERT INTO horo.architecture_family (slug, name, origin_year)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (slug) DO UPDATE SET
                        name = EXCLUDED.name,
                        origin_year = EXCLUDED.origin_year
                    RETURNING id;
                    """,
                    (fam["slug"], fam["name"], fam.get("origin_year")),
                )
                family_id_by_slug[fam["slug"]] = cur.fetchone()[0]

            # 4. Upsert Part Types
            print("Loading universal part types (CS dictionary codes)...")
            part_type_id_by_code: Dict[str, int] = {}
            for pt in part_types:
                cur.execute(
                    """
                    INSERT INTO horo.part_type (code, cs_number, name, category, donor_weight, is_wear_item)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (code) DO UPDATE SET
                        cs_number = EXCLUDED.cs_number,
                        name = EXCLUDED.name,
                        category = EXCLUDED.category,
                        donor_weight = EXCLUDED.donor_weight,
                        is_wear_item = EXCLUDED.is_wear_item
                    RETURNING id;
                    """,
                    (
                        pt["code"],
                        str(pt["cs_number"]),
                        pt["name"],
                        pt["category"],
                        pt["donor_weight"],
                        pt.get("is_wear_item", False),
                    ),
                )
                part_type_id_by_code[pt["code"]] = cur.fetchone()[0]

            # 5. Upsert Curated YAML Calibers
            print("Loading curated YAML calibers...")
            valid_statuses = {"current", "discontinued", "vintage", "obscure", "parts_scarce"}
            caliber_id_by_key: Dict[str, int] = {}
            for cal in curated_calibers:
                env = cal.get("envelope", {})
                perf = cal.get("performance", {})
                maker_id = maker_id_by_slug[cal["manufacturer"]]
                family_id = family_id_by_slug.get(cal.get("family_slug", ""))
                cal_status = cal.get("status", "vintage")
                if cal_status not in valid_statuses:
                    cal_status = "vintage"

                cur.execute(
                    """
                    INSERT INTO horo.caliber (
                        canonical_key, manufacturer_id, family_id, reference, display_name,
                        winding, functions,
                        diameter_mm, height_mm, stem_height_mm, crown_position_oclock,
                        hour_hand_hole_mm, minute_hand_post_mm, seconds_hand_post_mm,
                        date_position_oclock,
                        beat_rate_vph, jewels, power_reserve_h, lift_angle_deg, shock_protection,
                        production_start, production_end, status, accessibility_score,
                        source
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s::horo.winding_type, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s::horo.production_status, %s,
                        'curated_yaml'
                    )
                    ON CONFLICT (canonical_key) DO UPDATE SET
                        manufacturer_id = EXCLUDED.manufacturer_id,
                        family_id = EXCLUDED.family_id,
                        reference = EXCLUDED.reference,
                        display_name = EXCLUDED.display_name,
                        winding = EXCLUDED.winding,
                        functions = EXCLUDED.functions,
                        diameter_mm = EXCLUDED.diameter_mm,
                        height_mm = EXCLUDED.height_mm,
                        stem_height_mm = EXCLUDED.stem_height_mm,
                        crown_position_oclock = EXCLUDED.crown_position_oclock,
                        hour_hand_hole_mm = EXCLUDED.hour_hand_hole_mm,
                        minute_hand_post_mm = EXCLUDED.minute_hand_post_mm,
                        seconds_hand_post_mm = EXCLUDED.seconds_hand_post_mm,
                        date_position_oclock = EXCLUDED.date_position_oclock,
                        beat_rate_vph = EXCLUDED.beat_rate_vph,
                        jewels = EXCLUDED.jewels,
                        power_reserve_h = EXCLUDED.power_reserve_h,
                        lift_angle_deg = EXCLUDED.lift_angle_deg,
                        shock_protection = EXCLUDED.shock_protection,
                        production_start = EXCLUDED.production_start,
                        production_end = EXCLUDED.production_end,
                        status = EXCLUDED.status,
                        accessibility_score = EXCLUDED.accessibility_score,
                        source = 'curated_yaml',
                        updated_at = now()
                    RETURNING id;
                    """,
                    (
                        cal["canonical_key"],
                        maker_id,
                        family_id,
                        str(cal["reference"]),
                        cal["display_name"],
                        cal["winding"],
                        cal.get("functions", []),
                        env.get("diameter_mm"),
                        env.get("height_mm"),
                        env.get("stem_height_mm"),
                        env.get("crown_position_oclock", 3.0),
                        env.get("hour_hand_hole_mm"),
                        env.get("minute_hand_post_mm"),
                        env.get("seconds_hand_post_mm"),
                        env.get("date_position_oclock"),
                        perf.get("beat_rate_vph"),
                        perf.get("jewels"),
                        perf.get("power_reserve_h"),
                        perf.get("lift_angle_deg"),
                        perf.get("shock_protection"),
                        cal.get("production_start"),
                        cal.get("production_end"),
                        cal_status,
                        cal.get("accessibility_score", 0.5),
                    ),
                )
                cal_id = cur.fetchone()[0]
                caliber_id_by_key[cal["canonical_key"]] = cal_id

                # Aliases
                for al in cal.get("aliases", []):
                    cur.execute(
                        """
                        INSERT INTO horo.caliber_alias (caliber_id, alias, kind)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (caliber_id, alias) DO NOTHING;
                        """,
                        (cal_id, al["alias"], al.get("kind", "official")),
                    )

            # 6. Upsert Scraped 17jewels Movements
            print(f"Loading {len(scraped_movements)} scraped movements from 17jewels...")
            for rec in scraped_movements:
                c_key = rec["canonical_key"]
                maker_id = maker_id_by_slug[rec["manufacturer_slug"]]
                raw_table = rec.get("raw_table") or {}
                height_mm = parse_height_mm(raw_table)
                prod_start, prod_end = parse_production_years(raw_table)
                funcs = parse_features_list(rec.get("features"))
                winding = rec.get("winding") if rec.get("winding") in ("manual", "automatic", "quartz") else "manual"

                cur.execute(
                    """
                    INSERT INTO horo.caliber (
                        canonical_key, manufacturer_id, reference, display_name,
                        winding, functions,
                        ligne, size_raw, diameter_mm, height_mm,
                        beat_rate_vph, lift_angle_deg, jewels, shock_protection,
                        escapement, balance_type, hairspring_direction, moveable_stud, adjust_mechanism,
                        production_start, production_end, status, accessibility_score,
                        source, source_url, index_row_hash, record_hash, raw_specs
                    )
                    VALUES (
                        %s, %s, %s, %s,
                        %s::horo.winding_type, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, 'vintage'::horo.production_status, 0.45,
                        '17jewels', %s, %s, %s, %s::jsonb
                    )
                    ON CONFLICT (canonical_key) DO UPDATE SET
                        -- Preserve curated_yaml primary specs if already present, but enrich with 17jewels metadata
                        ligne = COALESCE(horo.caliber.ligne, EXCLUDED.ligne),
                        size_raw = COALESCE(horo.caliber.size_raw, EXCLUDED.size_raw),
                        diameter_mm = COALESCE(horo.caliber.diameter_mm, EXCLUDED.diameter_mm),
                        height_mm = COALESCE(horo.caliber.height_mm, EXCLUDED.height_mm),
                        beat_rate_vph = COALESCE(horo.caliber.beat_rate_vph, EXCLUDED.beat_rate_vph),
                        lift_angle_deg = COALESCE(horo.caliber.lift_angle_deg, EXCLUDED.lift_angle_deg),
                        jewels = COALESCE(horo.caliber.jewels, EXCLUDED.jewels),
                        shock_protection = COALESCE(horo.caliber.shock_protection, EXCLUDED.shock_protection),
                        escapement = COALESCE(horo.caliber.escapement, EXCLUDED.escapement),
                        balance_type = COALESCE(horo.caliber.balance_type, EXCLUDED.balance_type),
                        hairspring_direction = COALESCE(horo.caliber.hairspring_direction, EXCLUDED.hairspring_direction),
                        moveable_stud = COALESCE(horo.caliber.moveable_stud, EXCLUDED.moveable_stud),
                        adjust_mechanism = COALESCE(horo.caliber.adjust_mechanism, EXCLUDED.adjust_mechanism),
                        production_start = COALESCE(horo.caliber.production_start, EXCLUDED.production_start),
                        production_end = COALESCE(horo.caliber.production_end, EXCLUDED.production_end),
                        source_url = EXCLUDED.source_url,
                        index_row_hash = EXCLUDED.index_row_hash,
                        record_hash = EXCLUDED.record_hash,
                        raw_specs = EXCLUDED.raw_specs,
                        updated_at = now()
                    RETURNING id;
                    """,
                    (
                        c_key,
                        maker_id,
                        str(rec.get("caliber") or c_key),
                        rec["display_name"],
                        winding,
                        funcs,
                        rec.get("ligne"),
                        rec.get("size_raw"),
                        rec.get("diameter_mm"),
                        height_mm,
                        rec.get("beat_rate_vph"),
                        rec.get("lift_angle_deg"),
                        rec.get("jewels"),
                        rec.get("shock_protection"),
                        rec.get("escapement"),
                        rec.get("balance_type"),
                        rec.get("hairspring_direction"),
                        rec.get("moveable_stud"),
                        rec.get("adjust_mechanism"),
                        prod_start,
                        prod_end,
                        rec.get("url"),
                        rec.get("index_row_hash"),
                        rec.get("record_hash"),
                        json.dumps(raw_table),
                    ),
                )
                cal_id = cur.fetchone()[0]
                caliber_id_by_key[c_key] = cal_id

                # Add official display_name alias for fast search
                cur.execute(
                    """
                    INSERT INTO horo.caliber_alias (caliber_id, alias, kind)
                    VALUES (%s, %s, 'official')
                    ON CONFLICT (caliber_id, alias) DO NOTHING;
                    """,
                    (cal_id, rec["display_name"]),
                )

            # 7. Upsert Part Classes, Parts, and Caliber-Part Compatibility Links
            print("Loading interchangeable parts & equivalence classes...")
            part_class_id_by_code: Dict[str, int] = {}
            for cal in curated_calibers:
                cal_id = caliber_id_by_key[cal["canonical_key"]]
                maker_id = maker_id_by_slug[cal["manufacturer"]]
                for p in cal.get("parts", []):
                    pt_id = part_type_id_by_code[p["slot"]]
                    cls_code = p["interchange_group"]
                    if cls_code not in part_class_id_by_code:
                        cur.execute(
                            """
                            INSERT INTO horo.part_class (part_type_id, class_code)
                            VALUES (%s, %s)
                            ON CONFLICT (class_code) DO UPDATE SET part_type_id = EXCLUDED.part_type_id
                            RETURNING id;
                            """,
                            (pt_id, cls_code),
                        )
                        part_class_id_by_code[cls_code] = cur.fetchone()[0]
                    cls_id = part_class_id_by_code[cls_code]

                    cur.execute(
                        """
                        INSERT INTO horo.part (part_type_id, part_class_id, manufacturer_id, part_number)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (manufacturer_id, part_number) DO UPDATE SET
                            part_class_id = EXCLUDED.part_class_id
                        RETURNING id;
                        """,
                        (pt_id, cls_id, maker_id, p["part_number"]),
                    )
                    part_id = cur.fetchone()[0]

                    cur.execute(
                        """
                        INSERT INTO horo.caliber_part (
                            caliber_id, part_id, part_type_id, part_class_id, compatibility, notes
                        )
                        VALUES (%s, %s, %s, %s, %s::horo.part_compatibility, %s)
                        ON CONFLICT (caliber_id, part_id) DO UPDATE SET
                            part_class_id = EXCLUDED.part_class_id,
                            compatibility = EXCLUDED.compatibility,
                            notes = EXCLUDED.notes;
                        """,
                        (
                            cal_id,
                            part_id,
                            pt_id,
                            cls_id,
                            p.get("compatibility", "direct"),
                            p.get("notes"),
                        ),
                    )

            # 8. Upsert Lineage Relations (Curated YAML + Inferred 17jewels Base Calibers)
            print("Loading lineage graph relations...")
            for cal in curated_calibers:
                from_id = caliber_id_by_key[cal["canonical_key"]]
                for rel in cal.get("relations", []):
                    to_id = caliber_id_by_key.get(rel["to"])
                    if not to_id or from_id == to_id:
                        continue
                    cur.execute(
                        """
                        INSERT INTO horo.caliber_relation (
                            from_caliber_id, to_caliber_id, kind, subtype,
                            modification_degree, confidence, notes
                        )
                        VALUES (%s, %s, %s::horo.relation_kind, %s, %s, %s, %s)
                        ON CONFLICT (from_caliber_id, to_caliber_id, kind) DO UPDATE SET
                            subtype = EXCLUDED.subtype,
                            modification_degree = EXCLUDED.modification_degree,
                            confidence = EXCLUDED.confidence,
                            notes = EXCLUDED.notes;
                        """,
                        (
                            from_id,
                            to_id,
                            rel["kind"],
                            rel.get("subtype"),
                            rel.get("modification_degree"),
                            rel.get("confidence", 0.95),
                            rel.get("notes"),
                        ),
                    )

            for rel in inferred_relations:
                from_id = caliber_id_by_key.get(rel["from_key"])
                to_id = caliber_id_by_key.get(rel["to_key"])
                if not from_id or not to_id or from_id == to_id:
                    continue
                cur.execute(
                    """
                    INSERT INTO horo.caliber_relation (
                        from_caliber_id, to_caliber_id, kind, subtype,
                        modification_degree, confidence, notes
                    )
                    VALUES (%s, %s, %s::horo.relation_kind, %s, %s, %s, %s)
                    ON CONFLICT (from_caliber_id, to_caliber_id, kind) DO NOTHING;
                    """,
                    (
                        from_id,
                        to_id,
                        rel["kind"],
                        rel["subtype"],
                        rel["modification_degree"],
                        rel["confidence"],
                        rel["notes"],
                    ),
                )

            # 9. Upsert Precomputed Donor Similarity Rankings
            print("Loading precomputed donor movement rankings...")
            for row in donor_rankings:
                target_id = caliber_id_by_key.get(row["target_key"])
                donor_id = caliber_id_by_key.get(row["donor_key"])
                if not target_id or not donor_id:
                    continue
                top_shared = [
                    s.strip() for s in row["swappable_parts_list"].split(",") if s.strip()
                ]
                cur.execute(
                    """
                    INSERT INTO horo.caliber_similarity (
                        target_caliber_id, donor_caliber_id,
                        shared_direct_cnt, shared_caveat_cnt,
                        weighted_coverage, jaccard_score, donor_rank_score, top_shared_types
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (target_caliber_id, donor_caliber_id) DO UPDATE SET
                        shared_direct_cnt = EXCLUDED.shared_direct_cnt,
                        shared_caveat_cnt = EXCLUDED.shared_caveat_cnt,
                        weighted_coverage = EXCLUDED.weighted_coverage,
                        jaccard_score = EXCLUDED.jaccard_score,
                        donor_rank_score = EXCLUDED.donor_rank_score,
                        top_shared_types = EXCLUDED.top_shared_types;
                    """,
                    (
                        target_id,
                        donor_id,
                        row["shared_part_count"],
                        0,
                        row["weighted_coverage"],
                        row["jaccard_score"],
                        row["final_donor_score"],
                        top_shared,
                    ),
                )

        conn.commit()
        print("\n[SUCCESS] All curated and scraped movements loaded into PostgreSQL!")
    except Exception as exc:
        conn.rollback()
        raise exc
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Load Horological YAML & 17jewels JSON into PostgreSQL")
    parser.add_argument(
        "--db-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_DB_URL),
        help="PostgreSQL connection URL",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and summarize data without connecting to PostgreSQL",
    )
    args = parser.parse_args()
    run_loader(db_url=args.db_url, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
