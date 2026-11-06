"""
Database & Repository Layer (apps/api/db.py)
--------------------------------------------
Provides data access for the FastAPI backend:
  1. Primary Mode ("postgresql"):
     Connects to the PostgreSQL 16 container (`horo` schema) and executes
     trigram searches, recursive CTE graph traversals (`horo.lineage_up` / `horo.lineage_down`),
     donor part-sharing queries (`horo.donor_matches`), and envelope substitute queries (`horo.substitutes`).
  2. Automatic Fallback Mode ("memory_fallback"):
     If PostgreSQL is not currently reachable (e.g. Docker container stopped),
     loads the curated YAML fixtures + 1,039 scraped 17jewels movements into memory
     so the API and Frontend remain 100% functional at all times.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from etl.algorithms import calculate_donor_rankings, calculate_movement_substitutes
from etl.load_postgres import (
    DEFAULT_DB_URL,
    load_curated_data,
    load_scraped_data,
    parse_features_list,
    parse_height_mm,
    parse_production_years,
    resolve_scraped_base_relations,
)


class HorologyRepository:
    def __init__(self, db_url: Optional[str] = None) -> None:
        self.db_url = db_url or os.environ.get("DATABASE_URL", DEFAULT_DB_URL)
        self._memory_loaded = False
        self.calibers_by_key: Dict[str, Dict[str, Any]] = {}
        self.manufacturers_by_slug: Dict[str, Dict[str, Any]] = {}
        self.part_types_by_code: Dict[str, Dict[str, Any]] = {}
        self.relations: List[Dict[str, Any]] = []
        self.donor_rankings: List[Dict[str, Any]] = []
        self.substitutes_list: List[Dict[str, Any]] = []

    def get_pg_conn(self):
        """Try connecting to PostgreSQL with a fast timeout."""
        import psycopg2
        from psycopg2.extras import RealDictCursor

        return psycopg2.connect(self.db_url, connect_timeout=2, cursor_factory=RealDictCursor)

    def is_pg_available(self) -> bool:
        try:
            conn = self.get_pg_conn()
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM horo.caliber LIMIT 1;")
            conn.close()
            return True
        except Exception:
            return False

    # -----------------------------------------------------------------------
    # Fallback In-Memory Loader (Mirrors PostgreSQL Schema)
    # -----------------------------------------------------------------------
    def ensure_memory_loaded(self) -> None:
        if self._memory_loaded:
            return

        manufacturers, part_types, families, curated_calibers = load_curated_data()
        scraped_movements = load_scraped_data()

        self.part_types_by_code = {pt["code"]: pt for pt in part_types}
        for m in manufacturers:
            self.manufacturers_by_slug[m["slug"]] = {
                "slug": m["slug"],
                "name": m["name"],
                "country_code": m.get("country_code"),
                "founded_year": m.get("founded_year"),
                "roles": m.get("roles", []),
            }

        display_lookup: Dict[str, str] = {}

        # 1. Load Curated YAML Calibers
        for cal in curated_calibers:
            env = cal.get("envelope", {})
            perf = cal.get("performance", {})
            c_key = cal["canonical_key"]
            m_slug = cal["manufacturer"]
            m_name = self.manufacturers_by_slug.get(m_slug, {}).get("name", m_slug.upper())

            parts_detailed = []
            for p in cal.get("parts", []):
                pt = self.part_types_by_code.get(p["slot"], {})
                parts_detailed.append({
                    "slot": p["slot"],
                    "name": pt.get("name", p["slot"]),
                    "cs_number": str(pt.get("cs_number", "")),
                    "category": pt.get("category", ""),
                    "part_number": p["part_number"],
                    "interchange_group": p["interchange_group"],
                    "compatibility": p.get("compatibility", "direct"),
                    "donor_weight": pt.get("donor_weight", 0.5),
                    "notes": p.get("notes"),
                })

            self.calibers_by_key[c_key] = {
                "canonical_key": c_key,
                "display_name": cal["display_name"],
                "reference": str(cal["reference"]),
                "manufacturer_slug": m_slug,
                "manufacturer_name": m_name,
                "family_slug": cal.get("family_slug"),
                "winding": cal["winding"],
                "functions": cal.get("functions", []),
                "ligne": None,
                "size_raw": None,
                "diameter_mm": env.get("diameter_mm"),
                "height_mm": env.get("height_mm"),
                "stem_height_mm": env.get("stem_height_mm"),
                "crown_position_oclock": env.get("crown_position_oclock", 3.0),
                "hour_hand_hole_mm": env.get("hour_hand_hole_mm"),
                "minute_hand_post_mm": env.get("minute_hand_post_mm"),
                "seconds_hand_post_mm": env.get("seconds_hand_post_mm"),
                "date_position_oclock": env.get("date_position_oclock"),
                "beat_rate_vph": perf.get("beat_rate_vph"),
                "jewels": perf.get("jewels"),
                "power_reserve_h": perf.get("power_reserve_h"),
                "lift_angle_deg": perf.get("lift_angle_deg"),
                "shock_protection": perf.get("shock_protection"),
                "escapement": None,
                "balance_type": None,
                "hairspring_direction": None,
                "moveable_stud": None,
                "adjust_mechanism": None,
                "production_start": cal.get("production_start"),
                "production_end": cal.get("production_end"),
                "status": cal.get("status", "vintage"),
                "accessibility_score": cal.get("accessibility_score", 0.5),
                "source": "curated_yaml",
                "source_url": None,
                "raw_specs": {},
                "aliases": [a["alias"] for a in cal.get("aliases", [])],
                "parts": parts_detailed,
                # Keep nested envelope for Python substitute helper
                "envelope": env,
            }

            display_lookup[re.sub(r"[^a-z0-9]+", "", cal["display_name"].lower())] = c_key
            display_lookup[re.sub(r"[^a-z0-9]+", "", c_key.lower())] = c_key

            for rel in cal.get("relations", []):
                self.relations.append({
                    "from_key": c_key,
                    "to_key": rel["to"],
                    "kind": rel["kind"],
                    "subtype": rel.get("subtype"),
                    "modification_degree": rel.get("modification_degree", 1),
                    "confidence": rel.get("confidence", 0.95),
                    "notes": rel.get("notes", ""),
                })

        # 2. Load Scraped 17jewels Movements
        for rec in scraped_movements:
            c_key = rec["canonical_key"]
            m_slug = rec["manufacturer_slug"]
            m_name = rec["manufacturer_name"]
            if m_slug not in self.manufacturers_by_slug:
                self.manufacturers_by_slug[m_slug] = {
                    "slug": m_slug,
                    "name": m_name,
                    "country_code": None,
                    "founded_year": None,
                    "roles": ["ebauche_maker"],
                }

            raw_table = rec.get("raw_table") or {}
            height_mm = parse_height_mm(raw_table)
            prod_start, prod_end = parse_production_years(raw_table)
            funcs = parse_features_list(rec.get("features"))

            display_lookup.setdefault(re.sub(r"[^a-z0-9]+", "", rec["display_name"].lower()), c_key)
            display_lookup.setdefault(re.sub(r"[^a-z0-9]+", "", c_key.lower()), c_key)

            if c_key in self.calibers_by_key:
                # Enrich existing curated caliber with 17jewels metadata
                existing = self.calibers_by_key[c_key]
                existing["ligne"] = existing["ligne"] or rec.get("ligne")
                existing["size_raw"] = existing["size_raw"] or rec.get("size_raw")
                existing["source_url"] = rec.get("url")
                existing["raw_specs"] = raw_table
                continue

            self.calibers_by_key[c_key] = {
                "canonical_key": c_key,
                "display_name": rec["display_name"],
                "reference": str(rec.get("caliber") or c_key),
                "manufacturer_slug": m_slug,
                "manufacturer_name": m_name,
                "family_slug": None,
                "winding": rec.get("winding") or "manual",
                "functions": funcs,
                "ligne": rec.get("ligne"),
                "size_raw": rec.get("size_raw"),
                "diameter_mm": rec.get("diameter_mm"),
                "height_mm": height_mm,
                "stem_height_mm": None,
                "crown_position_oclock": 3.0,
                "hour_hand_hole_mm": None,
                "minute_hand_post_mm": None,
                "seconds_hand_post_mm": None,
                "date_position_oclock": None,
                "beat_rate_vph": rec.get("beat_rate_vph"),
                "jewels": rec.get("jewels"),
                "power_reserve_h": None,
                "lift_angle_deg": rec.get("lift_angle_deg"),
                "shock_protection": rec.get("shock_protection"),
                "escapement": rec.get("escapement"),
                "balance_type": rec.get("balance_type"),
                "hairspring_direction": rec.get("hairspring_direction"),
                "moveable_stud": rec.get("moveable_stud"),
                "adjust_mechanism": rec.get("adjust_mechanism"),
                "production_start": prod_start,
                "production_end": prod_end,
                "status": "vintage",
                "accessibility_score": 0.45,
                "source": "17jewels",
                "source_url": rec.get("url"),
                "raw_specs": raw_table,
                "aliases": [rec["display_name"]],
                "parts": [],
                "envelope": {
                    "diameter_mm": rec.get("diameter_mm"),
                    "height_mm": height_mm,
                    "crown_position_oclock": 3.0,
                },
            }

        # 3. Resolve scraped base caliber relations
        inferred = resolve_scraped_base_relations(scraped_movements, display_lookup)
        self.relations.extend(inferred)

        # 4. Precompute donor rankings for curated calibers
        flat_parts = []
        for cal in curated_calibers:
            for p in cal.get("parts", []):
                pt = self.part_types_by_code[p["slot"]]
                flat_parts.append({
                    "caliber_key": cal["canonical_key"],
                    "part_slot": p["slot"],
                    "cs_number": pt["cs_number"],
                    "part_name": pt["name"],
                    "part_number": p["part_number"],
                    "shared_storage_bin_part_class": p["interchange_group"],
                    "compatibility": p.get("compatibility", "direct"),
                    "donor_weight": pt["donor_weight"],
                    "notes": p.get("notes", ""),
                })
        self.donor_rankings = calculate_donor_rankings(curated_calibers, flat_parts)
        self._memory_loaded = True

    # -----------------------------------------------------------------------
    # Endpoint Implementations
    # -----------------------------------------------------------------------
    def get_health_stats(self) -> Dict[str, Any]:
        if self.is_pg_available():
            conn = self.get_pg_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) AS cnt FROM horo.caliber;")
                    cal_cnt = cur.fetchone()["cnt"]
                    cur.execute("SELECT COUNT(*) AS cnt FROM horo.manufacturer;")
                    mfr_cnt = cur.fetchone()["cnt"]
                    cur.execute("SELECT COUNT(*) AS cnt FROM horo.caliber_relation;")
                    rel_cnt = cur.fetchone()["cnt"]
                    cur.execute("SELECT COUNT(*) AS cnt FROM horo.caliber_part;")
                    part_cnt = cur.fetchone()["cnt"]
                return {
                    "status": "ok",
                    "engine": "postgresql",
                    "counts": {
                        "calibers": cal_cnt,
                        "manufacturers": mfr_cnt,
                        "lineage_relations": rel_cnt,
                        "caliber_parts": part_cnt,
                    },
                }
            finally:
                conn.close()

        self.ensure_memory_loaded()
        part_cnt = sum(len(c.get("parts", [])) for c in self.calibers_by_key.values())
        return {
            "status": "ok",
            "engine": "memory_fallback",
            "counts": {
                "calibers": len(self.calibers_by_key),
                "manufacturers": len(self.manufacturers_by_slug),
                "lineage_relations": len(self.relations),
                "caliber_parts": part_cnt,
            },
        }

    def list_manufacturers(self) -> List[Dict[str, Any]]:
        if self.is_pg_available():
            conn = self.get_pg_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT m.slug, m.name, m.country_code, m.founded_year,
                               COUNT(c.id)::INT AS caliber_count
                        FROM horo.manufacturer m
                        LEFT JOIN horo.caliber c ON c.manufacturer_id = m.id
                        GROUP BY m.id
                        ORDER BY caliber_count DESC, m.name ASC;
                        """
                    )
                    return [dict(r) for r in cur.fetchall()]
            finally:
                conn.close()

        self.ensure_memory_loaded()
        counts: Dict[str, int] = {}
        for c in self.calibers_by_key.values():
            counts[c["manufacturer_slug"]] = counts.get(c["manufacturer_slug"], 0) + 1
        result = []
        for slug, m in self.manufacturers_by_slug.items():
            result.append({
                **m,
                "caliber_count": counts.get(slug, 0),
            })
        result.sort(key=lambda r: (-r["caliber_count"], r["name"]))
        return result

    def search_calibers(
        self,
        q: Optional[str] = None,
        brand: Optional[str] = None,
        winding: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        if self.is_pg_available():
            conn = self.get_pg_conn()
            try:
                with conn.cursor() as cur:
                    where_clauses = ["1=1"]
                    params: List[Any] = []

                    if q and q.strip():
                        q_clean = q.strip()
                        where_clauses.append(
                            "(c.display_name ILIKE %s OR c.canonical_key ILIKE %s OR c.reference ILIKE %s)"
                        )
                        like_pat = f"%{q_clean}%"
                        params.extend([like_pat, like_pat, like_pat])

                    if brand:
                        where_clauses.append("m.slug = %s")
                        params.append(brand.lower())

                    if winding:
                        where_clauses.append("c.winding::TEXT = %s")
                        params.append(winding.lower())

                    if source:
                        where_clauses.append("c.source = %s")
                        params.append(source)

                    where_sql = " AND ".join(where_clauses)
                    cur.execute(
                        f"""
                        SELECT COUNT(*)::INT AS total
                        FROM horo.caliber c
                        JOIN horo.manufacturer m ON m.id = c.manufacturer_id
                        WHERE {where_sql};
                        """,
                        params,
                    )
                    total = cur.fetchone()["total"]

                    cur.execute(
                        f"""
                        SELECT
                            c.canonical_key,
                            c.display_name,
                            c.reference,
                            m.slug AS manufacturer_slug,
                            m.name AS manufacturer_name,
                            c.winding::TEXT AS winding,
                            c.ligne::FLOAT AS ligne,
                            c.diameter_mm::FLOAT AS diameter_mm,
                            c.height_mm::FLOAT AS height_mm,
                            c.beat_rate_vph,
                            c.jewels,
                            c.shock_protection,
                            c.status::TEXT AS status,
                            c.source,
                            c.source_url
                        FROM horo.caliber c
                        JOIN horo.manufacturer m ON m.id = c.manufacturer_id
                        WHERE {where_sql}
                        ORDER BY
                            CASE WHEN c.source = 'curated_yaml' THEN 0 ELSE 1 END,
                            c.display_name ASC
                        LIMIT %s OFFSET %s;
                        """,
                        params + [limit, offset],
                    )
                    items = [dict(r) for r in cur.fetchall()]
                    return {"total": total, "limit": limit, "offset": offset, "items": items}
            finally:
                conn.close()

        self.ensure_memory_loaded()
        q_lower = q.strip().lower() if q else None
        filtered = []
        for c in self.calibers_by_key.values():
            if brand and c["manufacturer_slug"] != brand.lower():
                continue
            if winding and c["winding"] != winding.lower():
                continue
            if source and c["source"] != source:
                continue
            if q_lower:
                haystack = f"{c['display_name']} {c['canonical_key']} {c['reference']} {' '.join(c.get('aliases', []))}".lower()
                if q_lower not in haystack:
                    continue
            filtered.append({
                "canonical_key": c["canonical_key"],
                "display_name": c["display_name"],
                "reference": c["reference"],
                "manufacturer_slug": c["manufacturer_slug"],
                "manufacturer_name": c["manufacturer_name"],
                "winding": c["winding"],
                "ligne": c["ligne"],
                "diameter_mm": c["diameter_mm"],
                "height_mm": c["height_mm"],
                "beat_rate_vph": c["beat_rate_vph"],
                "jewels": c["jewels"],
                "shock_protection": c["shock_protection"],
                "status": c["status"],
                "source": c["source"],
                "source_url": c["source_url"],
            })

        filtered.sort(key=lambda r: (0 if r["source"] == "curated_yaml" else 1, r["display_name"]))
        return {
            "total": len(filtered),
            "limit": limit,
            "offset": offset,
            "items": filtered[offset : offset + limit],
        }

    def get_caliber_detail(self, canonical_key: str) -> Optional[Dict[str, Any]]:
        if self.is_pg_available():
            conn = self.get_pg_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT
                            c.id,
                            c.canonical_key,
                            c.display_name,
                            c.reference,
                            m.slug AS manufacturer_slug,
                            m.name AS manufacturer_name,
                            af.slug AS family_slug,
                            af.name AS family_name,
                            c.winding::TEXT AS winding,
                            c.functions,
                            c.ligne::FLOAT AS ligne,
                            c.size_raw,
                            c.diameter_mm::FLOAT AS diameter_mm,
                            c.height_mm::FLOAT AS height_mm,
                            c.stem_height_mm::FLOAT AS stem_height_mm,
                            c.crown_position_oclock::FLOAT AS crown_position_oclock,
                            c.hour_hand_hole_mm::FLOAT AS hour_hand_hole_mm,
                            c.minute_hand_post_mm::FLOAT AS minute_hand_post_mm,
                            c.seconds_hand_post_mm::FLOAT AS seconds_hand_post_mm,
                            c.date_position_oclock,
                            c.beat_rate_vph,
                            c.jewels,
                            c.power_reserve_h::FLOAT AS power_reserve_h,
                            c.lift_angle_deg::FLOAT AS lift_angle_deg,
                            c.shock_protection,
                            c.escapement,
                            c.balance_type,
                            c.hairspring_direction,
                            c.moveable_stud,
                            c.adjust_mechanism,
                            c.production_start,
                            c.production_end,
                            c.status::TEXT AS status,
                            c.accessibility_score::FLOAT AS accessibility_score,
                            c.source,
                            c.source_url,
                            c.raw_specs
                        FROM horo.caliber c
                        JOIN horo.manufacturer m ON m.id = c.manufacturer_id
                        LEFT JOIN horo.architecture_family af ON af.id = c.family_id
                        WHERE c.canonical_key = %s;
                        """,
                        (canonical_key,),
                    )
                    row = cur.fetchone()
                    if not row:
                        return None
                    cal = dict(row)
                    cal_id = cal.pop("id")

                    cur.execute(
                        """
                        SELECT
                            pt.code AS slot,
                            pt.name,
                            pt.cs_number,
                            pt.category,
                            p.part_number,
                            pc.class_code AS interchange_group,
                            cp.compatibility::TEXT AS compatibility,
                            pt.donor_weight::FLOAT AS donor_weight,
                            cp.notes
                        FROM horo.caliber_part cp
                        JOIN horo.part p ON p.id = cp.part_id
                        JOIN horo.part_type pt ON pt.id = cp.part_type_id
                        JOIN horo.part_class pc ON pc.id = cp.part_class_id
                        WHERE cp.caliber_id = %s
                        ORDER BY pt.donor_weight DESC;
                        """,
                        (cal_id,),
                    )
                    cal["parts"] = [dict(r) for r in cur.fetchall()]
                    return cal
            finally:
                conn.close()

        self.ensure_memory_loaded()
        cal = self.calibers_by_key.get(canonical_key)
        if not cal:
            return None
        out = dict(cal)
        out.pop("envelope", None)
        return out

    def get_lineage_graph(self, canonical_key: str, depth: int = 5) -> Optional[Dict[str, Any]]:
        if self.is_pg_available():
            conn = self.get_pg_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id FROM horo.caliber WHERE canonical_key = %s;",
                        (canonical_key,),
                    )
                    root = cur.fetchone()
                    if not root:
                        return None
                    root_id = root["id"]

                    cur.execute(
                        """
                        SELECT from_id, to_id, kind::TEXT AS kind, subtype, mod_degree, confidence, notes
                        FROM horo.lineage_up(%s, %s)
                        UNION
                        SELECT from_id, to_id, kind::TEXT AS kind, subtype, mod_degree, confidence, notes
                        FROM horo.lineage_down(%s, %s);
                        """,
                        (root_id, depth, root_id, depth),
                    )
                    raw_edges = [dict(r) for r in cur.fetchall()]

                    node_ids = {root_id}
                    for e in raw_edges:
                        node_ids.add(e["from_id"])
                        node_ids.add(e["to_id"])

                    cur.execute(
                        """
                        SELECT
                            c.id,
                            c.canonical_key,
                            c.display_name,
                            m.name AS manufacturer_name,
                            c.winding::TEXT AS winding,
                            c.diameter_mm::FLOAT AS diameter_mm,
                            c.height_mm::FLOAT AS height_mm,
                            c.beat_rate_vph,
                            c.jewels,
                            c.production_start,
                            c.status::TEXT AS status,
                            c.source
                        FROM horo.caliber c
                        JOIN horo.manufacturer m ON m.id = c.manufacturer_id
                        WHERE c.id = ANY(%s);
                        """,
                        (list(node_ids),),
                    )
                    nodes_by_id = {r["id"]: dict(r) for r in cur.fetchall()}

                    nodes = []
                    for nid, n in nodes_by_id.items():
                        nodes.append({
                            "id": n["canonical_key"],
                            "display_name": n["display_name"],
                            "manufacturer": n["manufacturer_name"],
                            "winding": n["winding"],
                            "diameter_mm": n["diameter_mm"],
                            "height_mm": n["height_mm"],
                            "beat_rate_vph": n["beat_rate_vph"],
                            "jewels": n["jewels"],
                            "production_start": n["production_start"],
                            "status": n["status"],
                            "is_focus": nid == root_id,
                        })

                    edges = []
                    for e in raw_edges:
                        f_node = nodes_by_id.get(e["from_id"])
                        t_node = nodes_by_id.get(e["to_id"])
                        if f_node and t_node:
                            edges.append({
                                "id": f"{f_node['canonical_key']}->{t_node['canonical_key']}:{e['kind']}",
                                "source": f_node["canonical_key"],
                                "target": t_node["canonical_key"],
                                "kind": e["kind"],
                                "subtype": e["subtype"],
                                "modification_degree": e["mod_degree"],
                                "confidence": round(float(e["confidence"] or 0.95), 3),
                                "notes": e["notes"],
                            })

                    return {
                        "focus": canonical_key,
                        "nodes": nodes,
                        "edges": edges,
                        "meta": {
                            "node_count": len(nodes),
                            "edge_count": len(edges),
                            "max_depth": depth,
                        },
                    }
            finally:
                conn.close()

        self.ensure_memory_loaded()
        if canonical_key not in self.calibers_by_key:
            return None

        # BFS upstream & downstream in memory
        visited_nodes = {canonical_key}
        collected_edges = []
        seen_edge_ids = set()

        frontier = {canonical_key}
        for _ in range(depth):
            next_frontier = set()
            for rel in self.relations:
                fk, tk = rel["from_key"], rel["to_key"]
                if fk in frontier or tk in frontier:
                    edge_id = f"{fk}->{tk}:{rel['kind']}"
                    if edge_id not in seen_edge_ids and fk in self.calibers_by_key and tk in self.calibers_by_key:
                        seen_edge_ids.add(edge_id)
                        collected_edges.append({
                            "id": edge_id,
                            "source": fk,
                            "target": tk,
                            "kind": rel["kind"],
                            "subtype": rel.get("subtype"),
                            "modification_degree": rel.get("modification_degree"),
                            "confidence": rel.get("confidence", 0.95),
                            "notes": rel.get("notes"),
                        })
                    if fk not in visited_nodes and fk in self.calibers_by_key:
                        visited_nodes.add(fk)
                        next_frontier.add(fk)
                    if tk not in visited_nodes and tk in self.calibers_by_key:
                        visited_nodes.add(tk)
                        next_frontier.add(tk)
            if not next_frontier:
                break
            frontier = next_frontier

        nodes = []
        for nk in sorted(visited_nodes):
            c = self.calibers_by_key[nk]
            nodes.append({
                "id": c["canonical_key"],
                "display_name": c["display_name"],
                "manufacturer": c["manufacturer_name"],
                "winding": c["winding"],
                "diameter_mm": c["diameter_mm"],
                "height_mm": c["height_mm"],
                "beat_rate_vph": c["beat_rate_vph"],
                "jewels": c["jewels"],
                "production_start": c["production_start"],
                "status": c["status"],
                "is_focus": nk == canonical_key,
            })

        return {
            "focus": canonical_key,
            "nodes": nodes,
            "edges": collected_edges,
            "meta": {
                "node_count": len(nodes),
                "edge_count": len(collected_edges),
                "max_depth": depth,
            },
        }

    def get_donor_matches(self, canonical_key: str, part_slot: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if self.is_pg_available():
            conn = self.get_pg_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, display_name FROM horo.caliber WHERE canonical_key = %s;",
                        (canonical_key,),
                    )
                    target = cur.fetchone()
                    if not target:
                        return None

                    slot_filter = [part_slot] if part_slot else None
                    cur.execute(
                        """
                        SELECT
                            donor_key,
                            donor_name,
                            accessibility::FLOAT AS accessibility,
                            shared_direct_cnt,
                            shared_caveat_cnt,
                            ROUND((weighted_coverage * 100)::NUMERIC, 1)::FLOAT AS coverage_pct,
                            ROUND(donor_score::NUMERIC, 3)::FLOAT AS donor_score,
                            shared_parts
                        FROM horo.donor_matches(%s, %s, 25);
                        """,
                        (target["id"], slot_filter),
                    )
                    donors = [dict(r) for r in cur.fetchall()]
                    return {
                        "target_caliber": canonical_key,
                        "target_display_name": target["display_name"],
                        "part_filter": part_slot,
                        "donors": donors,
                    }
            finally:
                conn.close()

        self.ensure_memory_loaded()
        target = self.calibers_by_key.get(canonical_key)
        if not target:
            return None

        target_parts_by_group = {
            p["interchange_group"]: p for p in target.get("parts", [])
            if (not part_slot or p["slot"] == part_slot)
        }

        donors_out = []
        for row in self.donor_rankings:
            if row["target_key"] != canonical_key:
                continue
            donor_cal = self.calibers_by_key.get(row["donor_key"])
            if not donor_cal:
                continue

            shared_details = []
            for dp in donor_cal.get("parts", []):
                grp = dp["interchange_group"]
                if grp in target_parts_by_group:
                    tp = target_parts_by_group[grp]
                    shared_details.append({
                        "slot": tp["slot"],
                        "name": tp["name"],
                        "cs_number": tp["cs_number"],
                        "target_part": tp["part_number"],
                        "donor_part": dp["part_number"],
                        "compat": dp["compatibility"],
                        "notes": dp.get("notes") or tp.get("notes"),
                    })

            if part_slot and not shared_details:
                continue

            donors_out.append({
                "donor_key": row["donor_key"],
                "donor_name": row["recommended_donor_caliber"],
                "accessibility": row["donor_accessibility"],
                "shared_direct_cnt": len(shared_details),
                "shared_caveat_cnt": 0,
                "coverage_pct": float(row["part_coverage_pct"].replace("%", "")),
                "donor_score": row["final_donor_score"],
                "shared_parts": shared_details,
            })

        return {
            "target_caliber": canonical_key,
            "target_display_name": target["display_name"],
            "part_filter": part_slot,
            "donors": donors_out,
        }

    def get_substitutes(self, canonical_key: str) -> Optional[Dict[str, Any]]:
        if self.is_pg_available():
            conn = self.get_pg_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, display_name, diameter_mm::FLOAT, height_mm::FLOAT FROM horo.caliber WHERE canonical_key = %s;",
                        (canonical_key,),
                    )
                    target = cur.fetchone()
                    if not target:
                        return None

                    cur.execute(
                        """
                        SELECT
                            candidate_key,
                            candidate_name,
                            winding::TEXT AS winding,
                            fit_class,
                            ROUND(compatibility_score::NUMERIC, 3)::FLOAT AS compatibility_score,
                            delta_diameter_mm::FLOAT AS delta_diameter_mm,
                            delta_height_mm::FLOAT AS delta_height_mm,
                            delta_stem_mm::FLOAT AS delta_stem_mm,
                            hands_compatible,
                            date_aligned,
                            modifications
                        FROM horo.substitutes(%s);
                        """,
                        (target["id"],),
                    )
                    subs = [dict(r) for r in cur.fetchall()]
                    return {
                        "target_caliber": canonical_key,
                        "target_display_name": target["display_name"],
                        "target_diameter_mm": target["diameter_mm"],
                        "target_height_mm": target["height_mm"],
                        "substitutes": subs,
                    }
            finally:
                conn.close()

        self.ensure_memory_loaded()
        target = self.calibers_by_key.get(canonical_key)
        if not target:
            return None

        subs_out = []
        t_diam = target.get("diameter_mm")
        t_height = target.get("height_mm")

        if t_diam is not None:
            for c_key, cand in self.calibers_by_key.items():
                if c_key == canonical_key:
                    continue
                c_diam = cand.get("diameter_mm")
                c_height = cand.get("height_mm")
                if c_diam is None:
                    continue
                if abs(c_diam - t_diam) > 0.30:
                    continue
                if t_height is not None and c_height is not None:
                    if abs(c_height - t_height) > 0.60:
                        continue
                elif not (target.get("family_slug") and target.get("family_slug") == cand.get("family_slug")):
                    continue

                d_diam = round(c_diam - t_diam, 2)
                d_height = round(c_height - t_height, 2) if (c_height is not None and t_height is not None) else None
                t_stem = target.get("stem_height_mm")
                c_stem = cand.get("stem_height_mm")
                d_stem = round(c_stem - t_stem, 2) if (c_stem is not None and t_stem is not None) else None

                hands_ok = (
                    (cand.get("hour_hand_hole_mm") == target.get("hour_hand_hole_mm") or cand.get("hour_hand_hole_mm") is None)
                    and (cand.get("minute_hand_post_mm") == target.get("minute_hand_post_mm") or cand.get("minute_hand_post_mm") is None)
                )
                date_ok = cand.get("date_position_oclock") == target.get("date_position_oclock")

                mods = []
                if abs(d_diam) > 0.05:
                    mods.append(f"Movement spacer ring adjustment ({d_diam:+.2f} mm diameter delta)")
                if d_height is not None and abs(d_height) > 0.15:
                    mods.append(f"Caseback clearance check ({d_height:+.2f} mm height delta)")
                if not hands_ok:
                    mods.append(
                        f"Hour/minute hand holes differ ({cand.get('hour_hand_hole_mm')}/{cand.get('minute_hand_post_mm')} mm "
                        f"vs {target.get('hour_hand_hole_mm')}/{target.get('minute_hand_post_mm')} mm)"
                    )

                score = max(
                    0.0,
                    round(
                        1.0
                        - 0.8 * abs(d_diam)
                        - 0.4 * abs(d_height or 0.0)
                        - 1.2 * abs(d_stem or 0.0)
                        - (0.0 if hands_ok else 0.15),
                        3,
                    ),
                )
                fit_class = (
                    "direct_swap"
                    if abs(d_diam) <= 0.05 and abs(d_height or 0.0) <= 0.15 and hands_ok
                    else ("minor_mod" if abs(d_diam) <= 0.15 and abs(d_height or 0.0) <= 0.35 else "case_mod")
                )

                subs_out.append({
                    "candidate_key": c_key,
                    "candidate_name": cand["display_name"],
                    "winding": cand["winding"],
                    "fit_class": fit_class,
                    "compatibility_score": score,
                    "delta_diameter_mm": d_diam,
                    "delta_height_mm": d_height,
                    "delta_stem_mm": d_stem,
                    "hands_compatible": hands_ok,
                    "date_aligned": date_ok,
                    "modifications": mods,
                })

        subs_out.sort(key=lambda r: -r["compatibility_score"])
        return {
            "target_caliber": canonical_key,
            "target_display_name": target["display_name"],
            "target_diameter_mm": t_diam,
            "target_height_mm": t_height,
            "substitutes": subs_out[:25],
        }
