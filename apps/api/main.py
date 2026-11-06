"""
FastAPI Backend Service (apps/api/main.py)
------------------------------------------
Horological Caliber Lineage & Compatibility Graph Engine API.

Run locally with:
  uvicorn apps.api.main:app --reload --port 8000

Interactive Swagger UI Docs:
  http://localhost:8000/docs
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from apps.api.db import HorologyRepository

app = FastAPI(
    title="Horological Caliber Lineage & Compatibility API",
    description=(
        "REST & Graph Traversal API for Watch Movement Family Trees, "
        "Part Scavenging Donor Rankings, and Case/Hand Swap Substitutes."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

repo = HorologyRepository()


@app.get("/api/health", tags=["System"])
def health_check() -> Dict[str, Any]:
    """Return API status, active database engine ('postgresql' or 'memory_fallback'), and record counts."""
    return repo.get_health_stats()


@app.get("/api/manufacturers", tags=["Catalog"])
def get_manufacturers() -> List[Dict[str, Any]]:
    """List all watch movement manufacturers ordered by caliber count."""
    return repo.list_manufacturers()


@app.get("/api/search", tags=["Catalog"])
@app.get("/api/calibers", tags=["Catalog"])
def search_calibers(
    q: Optional[str] = Query(default=None, description="Search query (e.g. '2824', 'SW200', '7750', 'AS 1525')"),
    brand: Optional[str] = Query(default=None, description="Manufacturer slug filter (e.g. 'eta', 'sellita', 'seiko', 'as')"),
    winding: Optional[str] = Query(default=None, description="Winding type filter ('manual', 'automatic', 'quartz')"),
    source: Optional[str] = Query(default=None, description="Data source filter ('curated_yaml' or '17jewels')"),
    limit: int = Query(default=50, ge=1, le=250),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    """Search and filter across all curated and scraped watch movements."""
    return repo.search_calibers(
        q=q,
        brand=brand,
        winding=winding,
        source=source,
        limit=limit,
        offset=offset,
    )


@app.get("/api/calibers/{canonical_key:path}/lineage", tags=["Graph & Compatibility"])
def get_caliber_lineage(
    canonical_key: str,
    depth: int = Query(default=5, ge=1, le=10, description="Max traversal hops upstream & downstream"),
) -> Dict[str, Any]:
    """
    Return the upstream & downstream family tree DAG (`{ focus, nodes, edges, meta }`)
    for rendering in React Flow / Cytoscape.
    """
    graph = repo.get_lineage_graph(canonical_key=canonical_key, depth=depth)
    if not graph:
        raise HTTPException(status_code=404, detail=f"Caliber '{canonical_key}' not found")
    return graph


@app.get("/api/calibers/{canonical_key:path}/donors", tags=["Graph & Compatibility"])
def get_caliber_donors(
    canonical_key: str,
    part_slot: Optional[str] = Query(
        default=None,
        description="Optional part slot code filter (e.g. 'balance_complete', 'mainspring', 'winding_stem')",
    ),
) -> Dict[str, Any]:
    """
    Return ranked donor movements that share interchangeable parts with the target caliber,
    along with the exact CS dictionary part numbers and compatibility notes.
    """
    result = repo.get_donor_matches(canonical_key=canonical_key, part_slot=part_slot)
    if not result:
        raise HTTPException(status_code=404, detail=f"Caliber '{canonical_key}' not found")
    return result


@app.get("/api/calibers/{canonical_key:path}/substitutes", tags=["Graph & Compatibility"])
def get_caliber_substitutes(canonical_key: str) -> Dict[str, Any]:
    """
    Return drop-in movement substitutes based on physical envelope dimensions
    (diameter, height, stem height, crown position, hand hole diameters, and date window).
    """
    result = repo.get_substitutes(canonical_key=canonical_key)
    if not result:
        raise HTTPException(status_code=404, detail=f"Caliber '{canonical_key}' not found")
    return result


@app.get("/api/calibers/{canonical_key:path}", tags=["Catalog"])
def get_caliber_details(canonical_key: str) -> Dict[str, Any]:
    """Return full specifications, envelope dimensions, interchangeable parts, and raw 17jewels specs."""
    cal = repo.get_caliber_detail(canonical_key=canonical_key)
    if not cal:
        raise HTTPException(status_code=404, detail=f"Caliber '{canonical_key}' not found")
    return cal
