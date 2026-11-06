"""
Step 3: On-the-Fly Movement Scraper + Two-Level Diff Engine + Cron Scheduler
============================================================================
How this script works:
1. Level-1 Diff (Index Check):
   Compares `17jewels_movement_urls.json` (`index_row_hash`) against our stored
   database state (`data/processed/17jewels_synced_movements.json`).
   - Movements whose `index_row_hash` has NOT changed are SKIPPED (0 HTTP calls!).
   - Only NEW (`ADDED`) or CHANGED (`MODIFIED`) movements enter the scrape queue.

2. On-the-Fly Detail Scrape (In Memory with BeautifulSoup):
   Fetches each queued movement URL in memory (no `.html` files saved to disk),
   extracts the specification table with BeautifulSoup, and normalizes all numbers.

3. Level-2 Diff (Field-by-Field Comparison & Audit Changelog):
   Compares `old_record` vs `new_record` field-by-field (`diff_movement_records`),
   saves the updated records to `data/processed/17jewels_synced_movements.json`,
   and logs every addition or field change to `data/processed/17jewels_sync_changelog.json`.

Usage examples:
  # Scrape 5 Seiko movements on the fly:
  python etl/scrapers/sync_17jewels_cron.py --brand seiko --limit 5

  # Scrape the next 10 unsynced movements from any brand:
  python etl/scrapers/sync_17jewels_cron.py --limit 10

  # Test & see the Level-1 and Level-2 diff engine in action offline:
  python etl/scrapers/sync_17jewels_cron.py --simulate-diff

  # Run continuously as a scheduled cron job every 24 hours:
  python etl/scrapers/sync_17jewels_cron.py --cron-hours 24
"""

import argparse
from datetime import datetime, timezone
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
import httpx

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "etl"))
sys.path.insert(0, str(ROOT / "etl" / "scrapers"))

from algorithms.diff_engine import (
    compute_fingerprint,
    diff_index_rows,
    diff_movement_records,
)
from extract_17jewels_urls import extract_movement_urls, parse_fractional_ligne
from fetch_17jewels_index import fetch_movements_index

INDEX_URLS_JSON = ROOT / "data" / "processed" / "17jewels_movement_urls.json"
SYNCED_DB_JSON = ROOT / "data" / "processed" / "17jewels_synced_movements.json"
CHANGELOG_JSON = ROOT / "data" / "processed" / "17jewels_sync_changelog.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def parse_17jewels_detail_html(html: str, index_entry: dict[str, Any]) -> dict[str, Any]:
    """
    Parses a single 17jewels movement HTML page in memory using BeautifulSoup
    and returns a normalized movement record.
    """
    soup = BeautifulSoup(html, "html.parser")
    raw_table: dict[str, str] = {}

    # 17jewels movement pages store specs in <tr> rows with 2 cells (label, value)
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if len(cells) >= 2:
            label = (
                cells[0]
                .get_text(" ", strip=True)
                .replace("\xa0", " ")
                .rstrip(":")
                .strip()
                .lower()
            )
            val = cells[1].get_text(" ", strip=True).replace("\xa0", " ").strip()
            if label and val:
                raw_table[label] = val

    mfr_name = raw_table.get("manufacturer") or index_entry["manufacturer_slug"].upper()
    caliber = raw_table.get("caliber") or index_entry["caliber"]
    size_str = raw_table.get("size") or index_entry.get("size_raw") or ""
    ligne, diameter_mm = parse_fractional_ligne(size_str)

    # Parse A/h (beat rate vph) e.g. "21600"
    ah_str = raw_table.get("a/h", "")
    ah_match = re.search(r"(\d{4,6})", ah_str.replace(".", "").replace(",", ""))
    beat_rate_vph = int(ah_match.group(1)) if ah_match else None

    # Parse lift angle e.g. "49°" or "50.5°"
    lift_str = raw_table.get("lift angle", "")
    lift_match = re.search(r"(\d+(?:[.,]\d+)?)", lift_str)
    lift_angle_deg = (
        float(lift_match.group(1).replace(",", ".")) if lift_match else None
    )

    # Parse jewels e.g. "17"
    jewels_str = raw_table.get("number of jewels", "")
    jewels_match = re.search(r"(\d+)", jewels_str)
    jewels = (
        int(jewels_match.group(1))
        if jewels_match
        else index_entry.get("jewels")
    )

    # Parse features & winding type
    features_raw = raw_table.get("features", "") or index_entry.get("features_code") or ""
    winding = (
        "automatic"
        if ("aut" in features_raw.lower() or "selfwinding" in features_raw.lower())
        else "manual"
    )

    record = {
        "canonical_key": index_entry["canonical_key"],
        "display_name": f"{mfr_name} {caliber}".strip(),
        "manufacturer_slug": index_entry["manufacturer_slug"],
        "manufacturer_name": mfr_name,
        "caliber": caliber,
        "url": index_entry["url"],
        "size_raw": size_str,
        "ligne": ligne if ligne is not None else index_entry.get("ligne"),
        "diameter_mm": (
            diameter_mm if diameter_mm is not None else index_entry.get("diameter_mm")
        ),
        "beat_rate_vph": beat_rate_vph,
        "lift_angle_deg": lift_angle_deg,
        "jewels": jewels,
        "winding": winding,
        "escapement": raw_table.get("escapement"),
        "balance_type": raw_table.get("balance types"),
        "shock_protection": raw_table.get("shock protection(s)")
        or index_entry.get("shock_protection"),
        "hairspring_direction": raw_table.get(
            "balance bearing / direction hairspring"
        ),
        "moveable_stud": raw_table.get("moveable stud"),
        "adjust_mechanism": raw_table.get("adjust mechanism"),
        "features": features_raw,
        "raw_table": raw_table,
        "index_row_hash": index_entry["index_row_hash"],
    }
    record["record_hash"] = compute_fingerprint(
        {k: record.get(k) for k in ["ligne", "diameter_mm", "beat_rate_vph", "lift_angle_deg", "jewels", "winding", "escapement", "shock_protection", "features"]}
    )
    return record


def load_synced_db() -> dict[str, dict[str, Any]]:
    """Loads existing synced movements keyed by URL."""
    if not SYNCED_DB_JSON.exists():
        return {}
    items = json.loads(SYNCED_DB_JSON.read_text(encoding="utf-8"))
    return {item["url"]: item for item in items}


def save_synced_db(records_by_url: dict[str, dict[str, Any]]) -> None:
    SYNCED_DB_JSON.parent.mkdir(parents=True, exist_ok=True)
    sorted_items = sorted(
        records_by_url.values(), key=lambda r: r.get("canonical_key", "")
    )
    SYNCED_DB_JSON.write_text(
        json.dumps(sorted_items, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def append_changelog(entry: dict[str, Any]) -> None:
    history: list[dict[str, Any]] = []
    if CHANGELOG_JSON.exists():
        history = json.loads(CHANGELOG_JSON.read_text(encoding="utf-8"))
    history.append(entry)
    CHANGELOG_JSON.write_text(
        json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def run_sync(
    brand: str | None = None,
    limit: int | None = 5,
    scrape_all: bool = False,
    refresh_index: bool = False,
) -> None:
    """Runs the 2-level diff and scrapes new/modified movement pages on the fly."""
    if refresh_index:
        fetch_movements_index(refresh=True)
        extract_movement_urls()
    elif not INDEX_URLS_JSON.exists():
        extract_movement_urls()

    index_items: list[dict[str, Any]] = json.loads(
        INDEX_URLS_JSON.read_text(encoding="utf-8")
    )
    if brand:
        index_items = [
            x
            for x in index_items
            if x["manufacturer_slug"].lower() == brand.lower()
        ]
        print(f"[FILTER] Filtered index to brand='{brand}': {len(index_items)} movements")

    existing_by_url = load_synced_db()

    # ── STEP 1: Level-1 Index Diff ──
    diff_result = diff_index_rows(existing_by_url, index_items)
    added_queue = diff_result["added"]
    modified_queue = diff_result["modified"]
    unchanged_list = diff_result["unchanged"]

    print(
        f"\n[LEVEL-1 INDEX DIFF] Checked {len(index_items)} movements:"
        f"\n  - New (ADDED):        {len(added_queue)}"
        f"\n  - Changed (MODIFIED): {len(modified_queue)}"
        f"\n  - Already Synced:     {len(unchanged_list)} (0 network requests needed!)"
    )

    full_queue = modified_queue + added_queue
    if scrape_all or limit is None or limit <= 0:
        scrape_queue = full_queue
    else:
        scrape_queue = full_queue[:limit]

    if not scrape_queue:
        print("[SYNC COMPLETE] Everything is up to date! Nothing to fetch.")
        return

    print(f"\n[ON-THE-FLY SCRAPER] Fetching {len(scrape_queue)} movement page(s) in memory...\n")

    changes_logged: list[dict[str, Any]] = []
    start_time = time.time()

    with httpx.Client(
        timeout=25.0,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        for idx, item in enumerate(scrape_queue, start=1):
            url = item["url"]
            pct = round((idx / len(scrape_queue)) * 100, 1)
            elapsed = time.time() - start_time
            avg_per_item = elapsed / idx if idx > 0 else 1.5
            remaining_sec = int(avg_per_item * (len(scrape_queue) - idx))
            eta_str = f"{remaining_sec // 60}m {remaining_sec % 60}s"

            print(f"  [{idx}/{len(scrape_queue)}] ({pct}%) ETA: {eta_str} | {url}")

            # Fetch with 1 retry on transient network errors
            response = None
            for attempt in range(2):
                try:
                    response = client.get(url)
                    response.raise_for_status()
                    break
                except httpx.HTTPError as err:
                    if attempt == 0:
                        print(f"         [RETRY] Error: {err}. Retrying in 2s...")
                        time.sleep(2.0)
                    else:
                        print(f"         [SKIP] Failed after 2 attempts: {err}")

            if response is None or response.status_code != 200:
                continue

            # Parse HTML in memory without saving .html to disk
            new_record = parse_17jewels_detail_html(response.text, item)
            old_record = existing_by_url.get(url)

            # ── STEP 2: Level-2 Field-by-Field Diff ──
            record_diff = diff_movement_records(old_record, new_record)
            action = record_diff["action"]

            existing_by_url[url] = new_record
            save_synced_db(existing_by_url)

            print(
                f"         -> Parsed: {new_record['display_name']} | "
                f"{new_record['diameter_mm']} mm | {new_record['beat_rate_vph']} vph | "
                f"{new_record['jewels']}J | Status: {action}"
            )

            if action in ("ADDED", "UPDATED"):
                changes_logged.append(
                    {
                        "canonical_key": new_record["canonical_key"],
                        "display_name": new_record["display_name"],
                        "url": url,
                        "action": action,
                        "changed_fields": record_diff["changed_fields"],
                    }
                )

            if idx < len(scrape_queue):
                time.sleep(1.2)  # Polite delay between requests

    append_changelog(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "checked_count": len(index_items),
            "scraped_count": len(scrape_queue),
            "skipped_unchanged_count": len(unchanged_list),
            "changes": changes_logged,
        }
    )

    print(f"\n[SAVED] Synced movements stored at: {SYNCED_DB_JSON}")
    print(f"[SAVED] Audit changelog updated at: {CHANGELOG_JSON}")


def run_offline_diff_simulation() -> None:
    """
    Demonstrates the Level-1 and Level-2 Diff Engine offline using sample data
    (including the Seiko 4206B example) so you can verify how diffing works immediately.
    """
    print("=== RUNNING OFFLINE TWO-LEVEL DIFF SIMULATION ===\n")
    sample_html = """
    <table>
      <tr><td>Manufacturer:</td><td>Seiko</td></tr>
      <tr><td>Caliber:</td><td>4206B</td></tr>
      <tr><td>Size:</td><td>7 3/4'''</td></tr>
      <tr><td>A/h:</td><td>21600</td></tr>
      <tr><td>lift angle:</td><td>49°</td></tr>
      <tr><td>Number of jewels:</td><td>17</td></tr>
      <tr><td>Escapement:</td><td>Pallet lever</td></tr>
      <tr><td>Balance types:</td><td>Glucydur anular balance</td></tr>
      <tr><td>Shock protection(s):</td><td>Diashock (Seiko)</td></tr>
      <tr><td>Features:</td><td>SC? QG JG RDR AUT (selfwinding)</td></tr>
    </table>
    """
    index_entry = {
        "canonical_key": "seiko:4206b",
        "manufacturer_slug": "seiko",
        "caliber": "4206B",
        "url": "https://17jewels.info/movements/s/seiko/seiko-4206b/",
        "size_raw": "7 3/4'''",
        "ligne": 7.75,
        "diameter_mm": 17.48,
        "jewels": 17,
        "shock_protection": "Diashock",
        "features_code": "SC,QG,JG,RDR,AUT",
        "index_row_hash": "hash_v1_4206b",
    }

    # 1. First sync (Movement is brand new -> ADDED)
    rec_v1 = parse_17jewels_detail_html(sample_html, index_entry)
    diff_1 = diff_movement_records(None, rec_v1)
    print(f"1. First Scrape of {rec_v1['display_name']}:")
    print(f"   Action: {diff_1['action']} | Diameter: {rec_v1['diameter_mm']} mm | Beat: {rec_v1['beat_rate_vph']} vph | Winding: {rec_v1['winding']}")

    # 2. Second sync when nothing changed -> SKIPPED at Level 1
    l1_diff = diff_index_rows({rec_v1["url"]: rec_v1}, [index_entry])
    print(f"\n2. Next Cron Run (No changes on website):")
    print(f"   Level-1 Diff -> Added: {len(l1_diff['added'])}, Modified: {len(l1_diff['modified'])}, Skipped (Unchanged): {len(l1_diff['unchanged'])}")

    # 3. Third sync when website updates jewels from 17 -> 21 and lift angle 49° -> 50°
    rec_v2 = dict(rec_v1)
    rec_v2["jewels"] = 21
    rec_v2["lift_angle_deg"] = 50.0
    diff_2 = diff_movement_records(rec_v1, rec_v2)
    print(f"\n3. Cron Run When Website Updates Specs:")
    print(f"   Action: {diff_2['action']}")
    print(f"   Exact Field Diff Detected: {json.dumps(diff_2['changed_fields'])}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="On-the-fly 17jewels scraper with 2-level diffing & cron scheduler."
    )
    parser.add_argument("--brand", help="Filter by manufacturer slug (e.g. seiko, eta, citizen)")
    parser.add_argument("--limit", type=int, default=5, help="Max movement pages to scrape in this run (default: 5)")
    parser.add_argument("--all", action="store_true", help="Scrape all remaining unsynced movements")
    parser.add_argument("--refresh-index", action="store_true", help="Re-download the main 17jewels index page first")
    parser.add_argument("--simulate-diff", action="store_true", help="Run an offline demonstration of the 2-level diff engine")
    parser.add_argument("--cron-hours", type=float, help="Run continuously on a recurring interval (in hours)")

    args = parser.parse_args()

    if args.simulate_diff:
        run_offline_diff_simulation()
    elif args.cron_hours:
        interval_sec = int(args.cron_hours * 3600)
        print(f"[CRON SCHEDULER] Started! Running sync every {args.cron_hours} hour(s)...")
        while True:
            run_sync(
                brand=args.brand,
                limit=args.limit,
                scrape_all=args.all,
                refresh_index=True,
            )
            print(f"[CRON SCHEDULER] Sleeping for {args.cron_hours} hour(s)...")
            time.sleep(interval_sec)
    else:
        run_sync(
            brand=args.brand,
            limit=args.limit,
            scrape_all=args.all,
            refresh_index=args.refresh_index,
        )
