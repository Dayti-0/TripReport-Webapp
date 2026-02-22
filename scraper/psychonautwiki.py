"""Scraper for PsychonautWiki experience reports.

Uses the MediaWiki API to search for experience report pages,
then scrapes individual wiki pages for the full report content.
"""

import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://psychonautwiki.org"
API_URL = f"{BASE_URL}/w/api.php"

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
        return BeautifulSoup(response.text, "html.parser")
    except requests.RequestException as e:
        print(f"[psychonautwiki] Error fetching {url}: {e}")
        return None


def _search_api(substance_name: str, limit: int = 50) -> list[dict]:
    """Search for experience reports using the MediaWiki API.

    Returns a list of search result dicts with 'title' and 'pageid'.
    """
    results = []
    offset = 0

    while True:
        params = {
            "action": "query",
            "list": "search",
            "srsearch": f"intitle:Experience {substance_name}",
            "srnamespace": "0",
            "srlimit": str(min(limit - len(results), 50)),
            "sroffset": str(offset),
            "format": "json",
        }

        try:
            response = requests.get(API_URL, params=params, headers=HEADERS, timeout=15)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as e:
            print(f"[psychonautwiki] API error: {e}")
            break

        search_results = data.get("query", {}).get("search", [])
        if not search_results:
            break

        for item in search_results:
            title = item.get("title", "")
            # Only include pages that start with "Experience:"
            if not title.startswith("Experience:"):
                continue
            results.append({
                "title": title,
                "pageid": item.get("pageid", 0),
            })

        # Check if we have enough or if there are more results
        if len(results) >= limit:
            break

        cont = data.get("continue", {})
        if "sroffset" not in cont:
            break
        offset = cont["sroffset"]
        time.sleep(0.5)

    return results


def scrape_report_list(substance_name: str, callback=None) -> list[dict]:
    """Search PsychonautWiki for experience reports mentioning the substance.

    Uses the MediaWiki API to find pages with "Experience:" prefix.

    Args:
        substance_name: Name of the substance.
        callback: Optional progress callback.

    Returns:
        List of report metadata dicts.
    """
    print(f"[psychonautwiki] Searching API for '{substance_name}' experience reports")

    api_results = _search_api(substance_name)

    reports = []
    for item in api_results:
        title = item["title"]
        # Remove "Experience:" prefix for display
        display_title = re.sub(r"^Experience:\s*", "", title)

        # Build wiki URL from page title
        page_slug = title.replace(" ", "_")
        full_url = f"{BASE_URL}/wiki/{requests.utils.quote(page_slug, safe='/:_')}"

        # Generate a clean ID from the page title
        clean_id = re.sub(r"[^a-zA-Z0-9_-]", "_", title.replace("Experience:", "").strip())
        report_id = f"psychonautwiki_{clean_id}"

        reports.append({
            "id": report_id,
            "source": "psychonautwiki",
            "title": display_title,
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
        # Remove navigation boxes
        for el in content.find_all("div", class_=["navbox", "noprint"]):
            el.decompose()
        body_text = content.get_text(separator="\n").strip()

    if not body_text:
        return None

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
