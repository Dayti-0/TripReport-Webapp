"""Scraper for Psychonaut.fr trip reports.

Browses the trip report subcategories on this XenForo forum
and filters threads by substance name.
"""

import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.psychonaut.fr"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
}

REQUEST_DELAY = 1.5

# Subcategory forum IDs under "Trip reports"
SUBCATEGORY_IDS = {
    149: "LSD et lysergamides",
    150: "Champignons, DMT et tryptamines",
    151: "Cactus et phényléthylamines",
    152: "Salvia Divinorum",
    153: "Dissociatifs",
    154: "Cannabinoïdes",
    155: "Combos",
    156: "Trips sobres",
    157: "Autres",
}

# Map common substance names / keywords to the subcategory IDs to search.
# A substance can match multiple subcategories (e.g. combo substances).
# If no match is found, all subcategories are searched.
SUBSTANCE_TO_SUBCATEGORIES: dict[str, list[int]] = {
    "lsd": [149, 155],
    "1p-lsd": [149, 155],
    "1cp-lsd": [149, 155],
    "al-lad": [149, 155],
    "lsa": [149, 155],
    "eth-lad": [149, 155],
    "lysergamide": [149],
    "champignons": [150, 155],
    "mushrooms": [150, 155],
    "psilocybin": [150, 155],
    "psilocybine": [150, 155],
    "dmt": [150, 155],
    "4-ho-met": [150, 155],
    "4-aco-dmt": [150, 155],
    "4-ho-mipt": [150, 155],
    "metocine": [150, 155],
    "métocine": [150, 155],
    "tryptamine": [150],
    "mescaline": [151, 155],
    "2c-b": [151, 155],
    "2c-e": [151, 155],
    "2c-i": [151, 155],
    "cactus": [151],
    "peyote": [151],
    "san pedro": [151],
    "salvia": [152, 155],
    "salvinorine": [152],
    "ketamine": [153, 155],
    "kétamine": [153, 155],
    "dxm": [153, 155],
    "mxe": [153, 155],
    "methoxetamine": [153, 155],
    "pcp": [153, 155],
    "dissociatif": [153],
    "cannabis": [154, 155],
    "thc": [154, 155],
    "weed": [154, 155],
    "mdma": [155, 157],
    "cocaine": [157, 155],
    "cocaïne": [157, 155],
    "amphétamine": [157, 155],
    "amphetamine": [157, 155],
    "speed": [157, 155],
    "heroin": [157, 155],
    "héroïne": [157, 155],
    "kratom": [157, 155],
    "ghb": [157, 155],
    "nbome": [151, 155],
    "ayahuasca": [150, 155],
}

# Maximum pages to browse per subcategory
MAX_PAGES_PER_SUBCATEGORY = 5


def _fetch_page(url: str, timeout: int = 15) -> Optional[BeautifulSoup]:
    """Fetch a page and return parsed BeautifulSoup, or None on error."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=timeout)
        response.raise_for_status()
        return BeautifulSoup(response.text, "html.parser")
    except requests.RequestException as e:
        print(f"[psychonaut] Error fetching {url}: {e}")
        return None


def _get_subcategories_for_substance(substance_name: str) -> list[int]:
    """Determine which subcategories to search for a given substance."""
    key = substance_name.lower().strip()

    # Direct match
    if key in SUBSTANCE_TO_SUBCATEGORIES:
        return SUBSTANCE_TO_SUBCATEGORIES[key]

    # Partial match
    for sub_key, cat_ids in SUBSTANCE_TO_SUBCATEGORIES.items():
        if sub_key in key or key in sub_key:
            return cat_ids

    # No match: search all subcategories
    return list(SUBCATEGORY_IDS.keys())


def _get_forum_slug(forum_id: int) -> str:
    """Get the URL slug for a forum subcategory by ID.

    XenForo requires the slug in the URL, but will redirect if wrong.
    We use known slugs for our mapped categories.
    """
    slug_map = {
        149: "trip-reports-lsd-et-lysergamides",
        150: "trip-reports-champignons-dmt-et-tryptamines",
        151: "trip-reports-cactus-et-phenylethylamines",
        152: "trip-reports-salvia-divinorum",
        153: "trip-reports-dissociatifs",
        154: "trip-reports-cannabinoides",
        155: "trip-reports-combos",
        156: "trip-reports-trips-sobres",
        157: "trip-reports-autres",
    }
    return slug_map.get(forum_id, f"forum.{forum_id}")


def _parse_thread_list(soup: BeautifulSoup, substance_name: str) -> list[dict]:
    """Parse a forum page and extract threads matching the substance name."""
    threads = []
    substance_lower = substance_name.lower()

    # XenForo uses structItem for thread rows
    for item in soup.find_all("div", class_="structItem"):
        # Thread title
        title_el = item.find("div", class_="structItem-title")
        if not title_el:
            continue

        link = title_el.find("a", href=lambda h: h and "/threads/" in h)
        if not link:
            continue

        title = link.text.strip()
        href = link.get("href", "")

        # Filter: substance name must appear in the title
        if substance_lower not in title.lower():
            continue

        full_url = BASE_URL + href if href.startswith("/") else href

        # Extract thread ID from URL: /threads/slug.12345/
        thread_match = re.search(r"\.(\d+)/?$", href)
        thread_id = thread_match.group(1) if thread_match else str(abs(hash(href)))

        # Author
        author = ""
        author_el = item.find("a", class_="username")
        if author_el:
            author = author_el.text.strip()

        # Date
        date = ""
        time_el = item.find("time")
        if time_el:
            date = time_el.get("datetime", time_el.text.strip())

        threads.append({
            "id": f"psychonaut_{thread_id}",
            "source": "psychonaut",
            "title": title,
            "author": author,
            "date": date,
            "url": full_url,
            "language": "fr",
            "substances_text": substance_name,
        })

    return threads


def scrape_report_list(substance_name: str, callback=None) -> list[dict]:
    """Search Psychonaut.fr for trip reports mentioning the substance.

    Browses relevant subcategories and filters threads by title.

    Args:
        substance_name: Name of the substance to search for.
        callback: Optional progress callback.

    Returns:
        List of report metadata dicts.
    """
    print(f"[psychonaut] Searching for '{substance_name}' on Psychonaut.fr")

    subcategory_ids = _get_subcategories_for_substance(substance_name)
    print(f"[psychonaut] Will search subcategories: {[SUBCATEGORY_IDS.get(i, i) for i in subcategory_ids]}")

    all_reports: dict[str, dict] = {}  # keyed by report ID to deduplicate

    for cat_id in subcategory_ids:
        slug = _get_forum_slug(cat_id)
        cat_name = SUBCATEGORY_IDS.get(cat_id, str(cat_id))

        for page_num in range(1, MAX_PAGES_PER_SUBCATEGORY + 1):
            if page_num == 1:
                url = f"{BASE_URL}/forums/{slug}.{cat_id}/"
            else:
                url = f"{BASE_URL}/forums/{slug}.{cat_id}/page-{page_num}"

            print(f"[psychonaut] Fetching {cat_name} page {page_num}: {url}")
            soup = _fetch_page(url)
            if not soup:
                break

            threads = _parse_thread_list(soup, substance_name)
            for t in threads:
                all_reports[t["id"]] = t

            # Check if there's a next page
            nav = soup.find("nav", class_="pageNavWrapper")
            if not nav:
                break
            next_link = nav.find("a", class_="pageNav-jump--next")
            if not next_link:
                break

            time.sleep(REQUEST_DELAY)

        time.sleep(REQUEST_DELAY)

    reports = list(all_reports.values())
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

    # Get first post - XenForo uses article.message for posts
    first_post = soup.find("article", class_="message")
    if not first_post:
        # Fallback: try finding any message content
        first_post = soup.find("div", class_="message-body")
        if not first_post:
            return None

    # Author
    author = ""
    author_el = first_post.find("a", class_="username")
    if not author_el:
        # Try data attribute
        author_el = first_post.find(attrs={"data-author": True})
        if author_el:
            author = author_el.get("data-author", "")
    if author_el and not author:
        author = author_el.text.strip()
    if not author:
        author = "Anonyme"

    # Date
    date = ""
    time_el = first_post.find("time")
    if time_el:
        date = time_el.get("datetime", time_el.text.strip())

    # Body text
    body_el = first_post.find("div", class_="bbWrapper")
    body_text = ""
    if body_el:
        # Remove quoted content (blockquotes from other users)
        for quote in body_el.find_all("blockquote"):
            quote.decompose()
        body_text = body_el.get_text(separator="\n").strip()

    if not body_text:
        return None

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
