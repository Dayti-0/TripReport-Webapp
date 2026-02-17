"""Scraper for PsychonautWiki experience reports."""

import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://psychonautwiki.org"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

REQUEST_DELAY = 1.5


def _fetch_page(url: str, timeout: int = 15) -> Optional[BeautifulSoup]:
    """Fetch a page and return parsed BeautifulSoup, or None on error."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=timeout)
        response.raise_for_status()
        return BeautifulSoup(response.text, "lxml")
    except requests.RequestException as e:
        print(f"[psychonautwiki] Error fetching {url}: {e}")
        return None


def _normalize_substance(name: str) -> str:
    """Normalize substance name for PsychonautWiki URL format."""
    return name.strip().replace(" ", "_")


def scrape_report_list(substance_name: str, callback=None) -> list[dict]:
    """Scrape the list of experience reports from PsychonautWiki.

    Args:
        substance_name: Name of the substance.
        callback: Optional progress callback.

    Returns:
        List of report metadata dicts.
    """
    normalized = _normalize_substance(substance_name)
    index_url = f"{BASE_URL}/wiki/Experience:{normalized}"

    print(f"[psychonautwiki] Fetching experience index: {index_url}")
    soup = _fetch_page(index_url)

    reports = []

    if not soup:
        # Try the general experience index
        index_url = f"{BASE_URL}/wiki/Experience_index"
        soup = _fetch_page(index_url)
        if not soup:
            return []

    # Find experience report links
    content = soup.find("div", id="mw-content-text")
    if not content:
        return []

    for link in content.find_all("a", href=True):
        href = link.get("href", "")
        if "/wiki/Experience:" not in href:
            continue

        title = link.text.strip()
        if not title or title == substance_name:
            continue

        full_url = BASE_URL + href if href.startswith("/") else href

        # Generate ID from URL
        page_name = href.split("Experience:")[-1] if "Experience:" in href else href
        report_id = re.sub(r"[^a-zA-Z0-9_-]", "_", page_name)

        reports.append({
            "id": f"psychonautwiki_{report_id}",
            "source": "psychonautwiki",
            "title": title,
            "author": "",
            "date": "",
            "url": full_url,
            "language": "en",
            "substances_text": substance_name,
        })

    print(f"[psychonautwiki] Found {len(reports)} reports for '{substance_name}'")
    return reports


def scrape_report(report_url: str, report_id: str) -> Optional[dict]:
    """Scrape an individual experience report from PsychonautWiki."""
    soup = _fetch_page(report_url)
    if not soup:
        return None

    # Title
    title_el = soup.find("h1", id="firstHeading")
    title = title_el.text.strip() if title_el else "Unknown"
    # Clean up "Experience:" prefix
    title = re.sub(r"^Experience:\s*", "", title)

    # Content
    content = soup.find("div", id="mw-content-text")
    body_text = ""
    if content:
        # Remove table of contents and edit sections
        for el in content.find_all(["div", "span"], class_=["toc", "mw-editsection"]):
            el.decompose()
        body_text = content.get_text(separator="\n").strip()

    return {
        "id": report_id,
        "source": "psychonautwiki",
        "title": title,
        "author": "",
        "date": "",
        "url": report_url,
        "language": "en",
        "substances": [],
        "body_weight": "",
        "gender": "",
        "age": "",
        "categories": "",
        "is_combo": False,
        "body_original": body_text,
        "body_translated": "",
    }
