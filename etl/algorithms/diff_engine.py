"""
Two-Level Diffing Engine for Watch Movement Sync & Cron Pipeline
================================================================
Level 1 (Index Fingerprint Diff):
    Compares the summary row hash (`index_row_hash`) of every movement on the
    main index page against our stored state (`17jewels_synced_movements.json`).
    - Unchanged rows are skipped immediately (0 network calls).
    - Only NEW URLs or CHANGED rows are queued for on-the-fly scraping.

Level 2 (Movement Record Field-by-Field Diff):
    Once a movement page is scraped in memory, compares the old movement record
    against the newly scraped movement record field-by-field and records exact
    `{"old": ..., "new": ...}` transitions for the audit changelog.
"""

import hashlib
import json
from typing import Any

# Fields compared during Level-2 movement record diffing
TRACKED_FIELDS = [
    "display_name",
    "manufacturer_name",
    "caliber",
    "ligne",
    "diameter_mm",
    "beat_rate_vph",
    "lift_angle_deg",
    "jewels",
    "winding",
    "escapement",
    "balance_type",
    "shock_protection",
    "hairspring_direction",
    "moveable_stud",
    "adjust_mechanism",
    "features",
]


def compute_fingerprint(payload: dict[str, Any] | str) -> str:
    """Computes a deterministic SHA-256 hex digest for a string or dict."""
    if isinstance(payload, dict):
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    else:
        raw = str(payload)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def diff_index_rows(
    existing_records_by_url: dict[str, dict[str, Any]],
    current_index_items: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """
    Level 1 Diff: Compares current index page rows against already-synced records.

    Returns:
    {
        "added": [...],      # Brand new movement URLs never scraped before
        "modified": [...],   # Existing URLs whose index row fingerprint changed
        "unchanged": [...],  # Existing URLs with identical index fingerprint (SKIP!)
    }
    """
    added: list[dict[str, Any]] = []
    modified: list[dict[str, Any]] = []
    unchanged: list[dict[str, Any]] = []

    for item in current_index_items:
        url = item["url"]
        new_row_hash = item.get("index_row_hash", "")
        existing = existing_records_by_url.get(url)

        if existing is None:
            added.append(item)
        elif existing.get("index_row_hash") != new_row_hash:
            modified.append(item)
        else:
            unchanged.append(item)

    return {
        "added": added,
        "modified": modified,
        "unchanged": unchanged,
    }


def diff_movement_records(
    old_record: dict[str, Any] | None,
    new_record: dict[str, Any],
) -> dict[str, Any]:
    """
    Level 2 Diff: Compares an existing movement record with a newly scraped record
    field-by-field.

    Returns:
    {
        "action": "ADDED" | "UPDATED" | "UNCHANGED",
        "changed_fields": {
            "jewels": {"old": 17, "new": 21},
            ...
        },
        "needs_substitute_recalc": bool,
    }
    """
    if old_record is None:
        return {
            "action": "ADDED",
            "changed_fields": {},
            "needs_substitute_recalc": True,
        }

    changed_fields: dict[str, dict[str, Any]] = {}
    for field in TRACKED_FIELDS:
        old_val = old_record.get(field)
        new_val = new_record.get(field)
        if old_val != new_val:
            changed_fields[field] = {"old": old_val, "new": new_val}

    if not changed_fields:
        return {
            "action": "UNCHANGED",
            "changed_fields": {},
            "needs_substitute_recalc": False,
        }

    envelope_fields = {"diameter_mm", "ligne", "height_mm", "stem_height_mm"}
    needs_sub_recalc = bool(envelope_fields & set(changed_fields.keys()))

    return {
        "action": "UPDATED",
        "changed_fields": changed_fields,
        "needs_substitute_recalc": needs_sub_recalc,
    }


