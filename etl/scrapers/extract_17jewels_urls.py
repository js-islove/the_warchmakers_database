"""
Step 2: Extract all movement URLs, summary table columns, and `index_row_hash`
fingerprints from the cached `17jewels_index.html` file using BeautifulSoup
(with regex fallback).

Output: data/processed/17jewels_movement_urls.json
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "etl"))
from algorithms.diff_engine import compute_fingerprint

INDEX_FILE = ROOT / "data" / "raw_html" / "17jewels_index_formatted.html"
if not INDEX_FILE.exists():
    INDEX_FILE = ROOT / "data" / "raw_html" / "17jewels_index.html"

OUTPUT_JSON = ROOT / "data" / "processed" / "17jewels_movement_urls.json"
BASE_URL = "https://17jewels.info"


def parse_fractional_ligne(raw_size: str) -> tuple[float | None, float | None]:
    """
    Converts fractional Swiss ligne strings like "11 1/2'''" or "7 3/4'''"
    into (ligne_float, diameter_mm).
    1 French ligne = 2.2558291 mm.
    """
    if not raw_size:
        return None, None

    cleaned = raw_size.replace("\xa0", " ").strip()

    # Rectangular movements e.g. "6 3/4 x 8'''" -> take the first dimension or skip round diameter
    if "x" in cleaned.lower():
        cleaned = cleaned.lower().split("x")[0].strip()

    # Match "11 1/2" or "7 3/4"
    frac_match = re.search(r"(\d+)\s+(\d+)/(\d+)", cleaned)
    if frac_match:
        whole = float(frac_match.group(1))
        num = float(frac_match.group(2))
        den = float(frac_match.group(3))
        if den != 0:
            ligne = round(whole + (num / den), 2)
            return ligne, round(ligne * 2.2558, 2)

    # Match simple decimal or integer e.g. "12'''" or "11.5'''"
    num_match = re.search(r"(\d+(?:[.,]\d+)?)", cleaned)
    if num_match:
        val = float(num_match.group(1).replace(",", "."))
        if "mm" in cleaned.lower():
            return round(val / 2.2558, 2), round(val, 2)
        return round(val, 2), round(val * 2.2558, 2)

    return None, None


def _build_movement_entry(
    rel_path: str,
    caliber_label: str,
    cells_text: list[str],
) -> dict:
    full_url = f"{BASE_URL}{rel_path}"
    parts = [p for p in rel_path.strip("/").split("/") if p]
    manufacturer_slug = parts[2] if len(parts) >= 3 else "unknown"
    movement_slug = parts[3] if len(parts) >= 4 else parts[-1]

    # Table columns after <th class=caliber>:
    # [0]=size, [1]=esc., [2]=jewels, [3]=shockprot., [4]=construction, [5]=features, [6]=condition
    size_raw = cells_text[0] if len(cells_text) > 0 else ""
    esc_code = cells_text[1] if len(cells_text) > 1 else ""
    jewels_raw = cells_text[2] if len(cells_text) > 2 else ""
    shock_raw = cells_text[3] if len(cells_text) > 3 else ""
    construction_raw = cells_text[4] if len(cells_text) > 4 else ""
    features_raw = cells_text[5] if len(cells_text) > 5 else ""
    condition_raw = cells_text[6] if len(cells_text) > 6 else ""

    ligne, diameter_mm = parse_fractional_ligne(size_raw)
    jewels = int(jewels_raw) if jewels_raw.isdigit() else None

    row_summary = {
        "caliber": caliber_label,
        "size_raw": size_raw,
        "escapement_code": esc_code,
        "jewels": jewels,
        "shock_protection": shock_raw,
        "construction": construction_raw,
        "features_code": features_raw,
        "condition": condition_raw,
    }

    return {
        "canonical_key": f"{manufacturer_slug}:{movement_slug.removeprefix(manufacturer_slug + '-')}",
        "manufacturer_slug": manufacturer_slug,
        "caliber": caliber_label,
        "movement_slug": movement_slug,
        "relative_path": rel_path,
        "url": full_url,
        "size_raw": size_raw,
        "ligne": ligne,
        "diameter_mm": diameter_mm,
        "jewels": jewels,
        "shock_protection": shock_raw if shock_raw.lower() != "none" else None,
        "construction": construction_raw or None,
        "features_code": features_raw or None,
        "index_row_hash": compute_fingerprint(row_summary),
    }


def extract_with_beautifulsoup(html: str) -> list[dict]:
    """Parse index rows using BeautifulSoup."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    movements: list[dict] = []
    seen_urls: set[str] = set()

    for tag in soup.find_all("a", class_="movement-available"):
        rel_path = tag.get("href")
        if not rel_path or not rel_path.startswith("/movements/"):
            continue

        full_url = f"{BASE_URL}{rel_path}"
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        caliber_label = tag.get_text(strip=True)
        tr = tag.find_parent("tr")
        cells_text: list[str] = []
        if tr:
            tds = tr.find_all("td")
            # First two <td> are before <th class=caliber>; remaining 7 <td> follow it
            cells_text = [
                td.get_text(" ", strip=True).replace("\xa0", " ") for td in tds[2:]
            ]

        movements.append(_build_movement_entry(rel_path, caliber_label, cells_text))

    return movements


def extract_with_regex(html: str) -> list[dict]:
    """Fast regex parser that extracts each <tr> containing a movement-available link."""
    tr_pattern = re.compile(r"<tr>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
    link_pattern = re.compile(
        r'<a\s+href=["\']?(/movements/[^"\'\s>]+)["\']?\s+[^>]*class=["\']?movement-available["\']?[^>]*>(.*?)</a>',
        re.IGNORECASE,
    )
    td_pattern = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL | re.IGNORECASE)
    tag_strip = re.compile(r"<[^>]+>")

    movements: list[dict] = []
    seen_urls: set[str] = set()

    for tr_match in tr_pattern.finditer(html):
        tr_html = tr_match.group(1)
        link_match = link_pattern.search(tr_html)
        if not link_match:
            continue

        rel_path = link_match.group(1).strip()
        caliber_label = link_match.group(2).strip()
        full_url = f"{BASE_URL}{rel_path}"
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        raw_tds = td_pattern.findall(tr_html)
        cleaned_tds = [
            tag_strip.sub("", td).replace("\xa0", " ").strip() for td in raw_tds[2:]
        ]

        movements.append(_build_movement_entry(rel_path, caliber_label, cleaned_tds))

    return movements


def extract_movement_urls() -> list[dict]:
    if not INDEX_FILE.exists():
        raise FileNotFoundError(
            f"Index HTML not found at {INDEX_FILE}. Run fetch_17jewels_index.py first."
        )

    html = INDEX_FILE.read_text(encoding="utf-8")

    try:
        movements = extract_with_beautifulsoup(html)
        print("[PARSER] Extracted index rows using BeautifulSoup (bs4)")
    except ImportError:
        movements = extract_with_regex(html)
        print("[PARSER] Extracted index rows using Regex fallback")

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(
        json.dumps(movements, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(
        f"[SUCCESS] Extracted {len(movements)} movements with index_row_hash fingerprints"
    )
    print(f"[SAVED] JSON file written to: {OUTPUT_JSON}")
    return movements


if __name__ == "__main__":
    extract_movement_urls()
