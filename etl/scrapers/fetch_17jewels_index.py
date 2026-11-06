"""
Step 1: Download the main 17jewels.info movements index page once and save it locally.
URL: https://17jewels.info/movements/
Saved to: data/raw_html/17jewels_index.html
"""

from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parent.parent.parent
RAW_HTML_DIR = ROOT / "data" / "raw_html"
INDEX_URL = "https://17jewels.info/movements/"
INDEX_FILE = RAW_HTML_DIR / "17jewels_index.html"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def fetch_movements_index(refresh: bool = False) -> Path:
    """Downloads https://17jewels.info/movements/ and caches it locally."""
    RAW_HTML_DIR.mkdir(parents=True, exist_ok=True)

    if INDEX_FILE.exists() and not refresh:
        print(f"[CACHE] Index page already exists at: {INDEX_FILE}")
        print(f"[INFO] File size: {INDEX_FILE.stat().st_size:,} bytes")
        return INDEX_FILE

    print(f"[FETCH] Downloading main movements index: {INDEX_URL} ...")
    with httpx.Client(
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        response = client.get(INDEX_URL)
        response.raise_for_status()

    html = response.text
    INDEX_FILE.write_text(html, encoding="utf-8")

    print(f"[SAVED] Saved main index HTML to: {INDEX_FILE}")
    print(f"[INFO] HTTP status: {response.status_code}")
    print(f"[INFO] Total size: {len(html):,} characters")
    return INDEX_FILE


if __name__ == "__main__":
    fetch_movements_index()
