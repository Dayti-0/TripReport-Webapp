"""Scraper for Psychonaut.fr trip reports."""

import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.psychonaut.fr"
CATEGORY_URL = f"{BASE_URL}/categories/trip-reports-vos-experiences-psychedeliques.148/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
}

REQUEST_DELAY = 1.5


def _fetch_page(url: str, timeout: int = 15) -> Optional[BeautifulSoup]:
    """Fetch a page and return parsed BeautifulSoup, or None on error."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=timeout)
        response.raise_for_status()
        return BeautifulSoup(response.text, "html.parser")
    except requests.RequestException as e:
        print(f"[psychonaut] Error fetching {url}: {e}")
        return None


def scrape_report_list(substance_name: str, callback=None) -> list[dict]:
    """Search Psychonaut.fr for trip reports mentioning the substance.

    Args:
        substance_name: Name of the substance to search for.
        callback: Optional progress callback.

    Returns:
        List of report metadata dicts.
    """
    print(f"[psychonaut] Searching for '{substance_name}' on Psychonaut.fr")

    search_url = f"{BASE_URL}/search/?q={requests.utils.quote(substance_name)}&t=post&c[forums]=43"
    soup = _fetch_page(search_url)
    if not soup:
        return []

    reports = []
    # Search results contain thread links
    for result in soup.find_all("li", class_="block-row"):
        title_el = result.find("h3", class_="contentRow-title")
        if not title_el:
            continue

        link = title_el.find("a")
        if not link:
            continue

        href = link.get("href", "")
        title = link.text.strip()

        # Only include if substance name appears in title
        if substance_name.lower() not in title.lower():
            continue

        full_url = BASE_URL + href if href.startswith("/") else href

        # Get author and date
        meta = result.find("ul", class_="listInline")
        author = ""
        date = ""
        if meta:
            author_link = meta.find("a", class_="username")
            if author_link:
                author = author_link.text.strip()
            time_el = meta.find("time")
            if time_el:
                date = time_el.get("datetime", time_el.text.strip())

        # Generate ID from URL
        thread_match = re.search(r"\.(\d+)", href)
        thread_id = thread_match.group(1) if thread_match else str(hash(href))

        reports.append({
            "id": f"psychonaut_{thread_id}",
            "source": "psychonaut",
            "title": title,
            "author": author,
            "date": date,
            "url": full_url,
            "language": "fr",
            "substances_text": substance_name,
        })

    print(f"[psychonaut] Found {len(reports)} reports for '{substance_name}'")
    return reports


def scrape_report(report_url: str, report_id: str) -> Optional[dict]:
    """Scrape an individual trip report thread from Psychonaut.fr.

    Extracts the first post content (the trip report itself).
    """
    soup = _fetch_page(report_url)
    if not soup:
        return None

    # Get thread title
    title_el = soup.find("h1", class_="p-title-value")
    title = title_el.text.strip() if title_el else "Sans titre"

    # Get first post
    first_post = soup.find("article", class_="message")
    if not first_post:
        return None

    # Author
    author_el = first_post.find("a", class_="username")
    author = author_el.text.strip() if author_el else "Anonyme"

    # Date
    date = ""
    time_el = first_post.find("time")
    if time_el:
        date = time_el.get("datetime", time_el.text.strip())

    # Body text
    body_el = first_post.find("div", class_="bbWrapper")
    body_text = ""
    if body_el:
        body_text = body_el.get_text(separator="\n").strip()

    return {
        "id": report_id,
        "source": "psychonaut",
        "title": title,
        "author": author,
        "date": date,
        "url": report_url,
        "language": "fr",
        "substances": [],
        "body_weight": "",
        "gender": "",
        "age": "",
        "categories": "",
        "is_combo": False,
        "body_original": body_text,
        "body_translated": body_text,  # Already in French
    }
