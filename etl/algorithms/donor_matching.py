"""
Donor Matching Algorithm (Part Scavenging Engine)
=================================================
Calculates how well candidate donor movements can supply parts for a broken target movement.

Ranking Signals:
1. Coverage (Containment):
   W(shared) / W(target)
   Asymmetric: "How much of what I need can this donor supply?"
2. Weighted Jaccard:
   W(shared) / (W(target) + W(donor) - W(shared))
   Symmetric: "How similar are the two movements overall?"
3. Market Accessibility:
   Accessibility score (0.0 to 1.0) of the donor movement.

Composite Score Formula:
   Score = (0.45 * Coverage) + (0.25 * Weighted_Jaccard) + (0.30 * Accessibility)
"""

from typing import Any


def group_parts_by_caliber(
    caliber_parts: list[dict[str, Any]],
) -> dict[str, dict[str, tuple[str, float]]]:
    """
    Groups parts by caliber key into a lookup map:
    {
        "caliber_key": {
            "interchange_group_bin": ("part_slot", donor_weight)
        }
    }
    """
    parts_by_caliber: dict[str, dict[str, tuple[str, float]]] = {}
    for cp in caliber_parts:
        parts_by_caliber.setdefault(cp["caliber_key"], {})[
            cp["shared_storage_bin_part_class"]
        ] = (cp["part_slot"], cp["donor_weight"])
    return parts_by_caliber


def calculate_donor_rankings(
    calibers: list[dict[str, Any]],
    caliber_parts: list[dict[str, Any]],
    weight_coverage: float = 0.45,
    weight_jaccard: float = 0.25,
    weight_access: float = 0.30,
) -> list[dict[str, Any]]:
    """
    Compares all movements against each other and returns ranked donor pairings.

    Returns a list of dicts suitable for CSV export or API payloads:
    [
        {
            "broken_target_caliber": "ETA 2824-2",
            "recommended_donor_caliber": "Sellita SW200-1",
            "final_donor_score": 0.722,
            "part_coverage_pct": "66.3%",
            "shared_part_count": 8,
            "donor_accessibility": 0.95,
            "swappable_parts_list": "balance_complete, mainspring, ...",
        },
        ...
    ]
    """
    parts_by_caliber = group_parts_by_caliber(caliber_parts)
    cal_by_key = {c["canonical_key"]: c for c in calibers}
    donor_rows: list[dict[str, Any]] = []

    for target_key, target_bins in parts_by_caliber.items():
        w_target = sum(w for _, w in target_bins.values())
        if w_target == 0:
            continue

        for donor_key, donor_bins in parts_by_caliber.items():
            if donor_key == target_key:
                continue

            # Set intersection on interchange storage bins
            shared_bins = set(target_bins.keys()) & set(donor_bins.keys())
            if not shared_bins:
                continue

            w_donor = sum(w for _, w in donor_bins.values())
            w_shared = sum(target_bins[b][1] for b in shared_bins)
            shared_slot_names = sorted(target_bins[b][0] for b in shared_bins)

            # 1. Coverage (Containment)
            coverage = w_shared / w_target

            # 2. Weighted Jaccard
            denominator = w_target + w_donor - w_shared
            jaccard = (w_shared / denominator) if denominator > 0 else 0.0

            # 3. Market Accessibility
            access = cal_by_key[donor_key].get("accessibility_score", 0.5)

            # Composite rank
            final_score = (
                (weight_coverage * coverage)
                + (weight_jaccard * jaccard)
                + (weight_access * access)
            )

            donor_rows.append(
                {
                    "broken_target_caliber": cal_by_key[target_key]["display_name"],
                    "recommended_donor_caliber": cal_by_key[donor_key]["display_name"],
                    "final_donor_score": round(final_score, 3),
                    "part_coverage_pct": f"{round(coverage * 100, 1)}%",
                    "shared_part_count": len(shared_bins),
                    "donor_accessibility": access,
                    "swappable_parts_list": ", ".join(shared_slot_names),
                }
            )

    # Sort grouped by broken target, then highest score first
    donor_rows.sort(
        key=lambda r: (r["broken_target_caliber"], -r["final_donor_score"])
    )
    return donor_rows
