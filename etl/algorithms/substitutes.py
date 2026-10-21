"""
Parametric Movement Substitutes Algorithm (Whole Movement Drop-in Swaps)
========================================================================
Checks physical tolerances to see if a candidate movement can physically fit
into the same watch case, dial, and hands as a target movement.

Checks performed:
- Diameter tolerance (within 0.05 mm)
- Height bounds (thinner is fine, slightly thicker checked for caseback clearance)
- Crown position (must match e.g. 3 o'clock)
- Stem height (within 0.10 mm)
- Hand hole posts (hour, minute within 0.03 mm)
- Date window position (e.g. 3 o'clock vs 4 o'clock)
"""

from typing import Any


def calculate_movement_substitutes(
    calibers: list[dict[str, Any]],
    tol_diam_mm: float = 0.05,
    max_extra_height_mm: float = 0.50,
    tol_stem_mm: float = 0.10,
    tol_hand_mm: float = 0.03,
) -> list[dict[str, Any]]:
    """
    Evaluates every pair of movements and classifies compatibility into:
    - 'drop_in': Exact case, stem, dial & hand match
    - 'check_caseback_clearance': Fits case diameter & stem, but candidate is thicker
    - 'needs_hands': Fits case & stem, but hand hole sizes differ
    - 'needs_dial_or_no_date': Fits case & stem, but date position differs
    """
    sub_rows: list[dict[str, Any]] = []

    for target in calibers:
        for cand in calibers:
            if target["canonical_key"] == cand["canonical_key"]:
                continue

            # Pre-filter 1: Diameter
            if abs(cand["diameter_mm"] - target["diameter_mm"]) > tol_diam_mm:
                continue

            # Pre-filter 2: Height bound
            if cand["height_mm"] > target["height_mm"] + max_extra_height_mm:
                continue

            # Hard Check 1: Crown position (e.g. 3 o'clock vs 4 o'clock)
            if cand.get("crown_oclock") != target.get("crown_oclock"):
                continue

            # Hard Check 2: Stem height (distance from dial side to center of stem)
            if (
                cand.get("stem_height_mm") is not None
                and target.get("stem_height_mm") is not None
            ):
                if abs(cand["stem_height_mm"] - target["stem_height_mm"]) > tol_stem_mm:
                    continue

            # Soft checks: clearances, hands, date
            notes: list[str] = []
            fit_status = "drop_in"

            if cand["height_mm"] > target["height_mm"]:
                fit_status = "check_caseback_clearance"
                diff = round(cand["height_mm"] - target["height_mm"], 2)
                notes.append(f"Taller by {diff}mm")

            if (
                abs(cand.get("hour_hand_mm", 0) - target.get("hour_hand_mm", 0)) > tol_hand_mm
                or abs(cand.get("minute_hand_mm", 0) - target.get("minute_hand_mm", 0)) > tol_hand_mm
            ):
                fit_status = "needs_hands"
                notes.append("Hand hole sizes differ")

            if cand.get("date_oclock") != target.get("date_oclock"):
                fit_status = "needs_dial_or_no_date"
                notes.append("Date window differs")

            sub_rows.append(
                {
                    "original_movement": target["display_name"],
                    "substitute_movement": cand["display_name"],
                    "fit_classification": fit_status,
                    "diameter_mm": f"{cand['diameter_mm']} mm",
                    "height_comparison": f"{target['height_mm']}mm -> {cand['height_mm']}mm",
                    "stem_height_mm": f"{cand.get('stem_height_mm', '')} mm",
                    "hand_sizes_mm": f"{cand.get('hour_hand_mm')}/{cand.get('minute_hand_mm')}/{cand.get('seconds_hand_mm')}",
                    "fitment_notes": "; ".join(notes) if notes else "Exact case, stem, dial & hand match",
                }
            )

    return sub_rows
