"""Scraper for Erowid Experience Vaults."""

import re
import time
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.erowid.org/experiences/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Mapping of common substance names to Erowid URL slugs
SUBSTANCE_SLUG_MAP: dict[str, str] = {
    "4-ho-met": "4HOMET",
    "4-aco-dmt": "4AcODMT",
    "4-ho-mipt": "4HOMiPT",
    "4-aco-mipt": "4AcOMiPT",
    "lsd": "LSD",
    "cannabis": "Cannabis",
    "mdma": "MDMA",
    "psilocybin": "Psilocybin",
    "mushrooms": "Mushrooms",
    "dmt": "DMT",
    "ketamine": "Ketamine",
    "mescaline": "Mescaline",
    "salvia": "Salvia",
    "dxm": "DXM",
    "cocaine": "Cocaine",
    "amphetamines": "Amphetamines",
    "2c-b": "2CB",
    "2c-e": "2CE",
    "2c-i": "2CI",
    "nbome": "NBOMe",
    "methoxetamine": "Methoxetamine",
    "mxe": "Methoxetamine",
    "nitrous oxide": "NitrousOxide",
    "ayahuasca": "Ayahuasca",
    "ibogaine": "Ibogaine",
    "kratom": "Kratom",
    "heroin": "Heroin",
    "oxycodone": "Oxycodone",
    "ghb": "GHB",
    "alcohol": "Alcohol",
}

REQUEST_DELAY = 1.5  # seconds between requests


def _get_substance_slug(substance_name: str) -> str:
    """Convert a substance name to its Erowid URL slug."""
    key = substance_name.lower().strip()
    if key in SUBSTANCE_SLUG_MAP:
        return SUBSTANCE_SLUG_MAP[key]
    # Fallback: remove hyphens and spaces, capitalize each word
    slug = re.sub(r"[^a-zA-Z0-9]", "", substance_name.title())
    return slug


def _fetch_page(url: str, timeout: int = 15) -> Optional[BeautifulSoup]:
    """Fetch a page and return parsed BeautifulSoup, or None on error."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=timeout)
        response.raise_for_status()
        return BeautifulSoup(response.text, "lxml")
    except requests.RequestException as e:
        print(f"[erowid] Error fetching {url}: {e}")
        return None


def _parse_category_page(url: str) -> list[dict]:
    """Parse a category page (main or 'more') and extract report metadata."""
    soup = _fetch_page(url)
    if not soup:
        return []

    reports = []
    # Find all report links
    links = soup.find_all("a", href=lambda h: h and "exp.php?ID=" in h)

    for link in links:
        href = link.get("href", "")
        id_match = re.search(r"ID=(\d+)", href)
        if not id_match:
            continue

        report_id = id_match.group(1)
        title = link.text.strip()
        full_url = urljoin(BASE_URL, href)

        # Get the parent row
        tr = link.find_parent("tr")
        if not tr:
            continue

        tds = tr.find_all("td")
        author = ""
        substances_text = ""
        date = ""

        if len(tds) == 3:
            # Main substance page format: title | author | substances
            author = tds[1].text.strip()
            substances_text = tds[2].text.strip()
        elif len(tds) >= 6:
            # 'More' page format: empty | empty | title | author | substances | date
            author = tds[3].text.strip()
            substances_text = tds[4].text.strip()
            date = tds[5].text.strip()

        reports.append({
            "id": f"erowid_{report_id}",
            "source": "erowid",
            "title": title,
            "author": author,
            "date": date,
            "url": full_url,
            "substances_text": substances_text,
        })

    return reports


def scrape_report_list(substance_name: str, callback=None) -> list[dict]:
    """Scrape the list of reports for a given substance from Erowid.

    Args:
        substance_name: Name of the substance to search for.
        callback: Optional function called after each page is scraped,
                  with signature callback(source, current, total, message).

    Returns:
        List of report metadata dicts.
    """
    slug = _get_substance_slug(substance_name)
    main_url = f"{BASE_URL}subs/exp_{slug}.shtml"

    print(f"[erowid] Fetching main page: {main_url}")
    soup = _fetch_page(main_url)
    if not soup:
        print(f"[erowid] Could not fetch main page for '{substance_name}' (slug: {slug})")
        return []

    # Collect all reports from the main page (limited view)
    all_reports: dict[str, dict] = {}

    # Find all 'more' links for full category listings
    more_links = []
    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        if href.startswith(f"exp_{slug}_") and href.endswith(".shtml"):
            full_url = urljoin(main_url, href)
            if full_url not in more_links:
                more_links.append(full_url)

    # If there are 'more' pages, scrape those for complete listings
    if more_links:
        for i, more_url in enumerate(more_links):
            print(f"[erowid] Fetching category page {i+1}/{len(more_links)}: {more_url}")
            reports = _parse_category_page(more_url)
            for r in reports:
                all_reports[r["id"]] = r

            if callback:
                callback("erowid", i + 1, len(more_links),
                         f"Scraping category pages... {i+1}/{len(more_links)}")

            time.sleep(REQUEST_DELAY)
    else:
        # No 'more' links — just parse the main page directly
        reports = _parse_category_page(main_url)
        for r in reports:
            all_reports[r["id"]] = r

    # Also grab any reports from the main page that might not be in 'more' pages
    # (categories without 'more' links)
    main_reports = _parse_category_page(main_url)
    for r in main_reports:
        if r["id"] not in all_reports:
            all_reports[r["id"]] = r

    result = list(all_reports.values())
    print(f"[erowid] Found {len(result)} unique reports for '{substance_name}'")
    return result


def scrape_report(report_url: str, report_id: str) -> Optional[dict]:
    """Scrape an individual report page from Erowid.

    Args:
        report_url: Full URL of the report page.
        report_id: The report ID (e.g., 'erowid_63399').

    Returns:
        Dict with full report data, or None on error.
    """
    soup = _fetch_page(report_url)
    if not soup:
        return None

    # Title
    title_div = soup.find("div", class_="title")
    title = title_div.text.strip() if title_div else "Unknown Title"

    # Substance name (header)
    sub_div = soup.find("div", class_="substance")
    substance_header = sub_div.text.strip() if sub_div else ""

    # Author
    author_tag = soup.find("a", href=lambda h: h and "ShowAuthor" in str(h))
    author = author_tag.text.strip() if author_tag else "Anonymous"

    # Dosage table
    substances = []
    dose_table = soup.find("table", class_="dosechart")
    if dose_table:
        for row in dose_table.find_all("tr"):
            tds = row.find_all("td")
            if len(tds) >= 4:
                dose = tds[1].text.strip()
                route = tds[2].text.strip()
                name = tds[3].text.strip()
                form = tds[4].text.strip() if len(tds) > 4 else ""
                substances.append({
                    "name": name,
                    "dose": dose,
                    "route": route,
                    "form": form,
                })

    # Body weight
    bw_amount = soup.find("td", class_="bodyweight-amount")
    body_weight = bw_amount.text.strip() if bw_amount else ""

    # Metadata from footdata (extract BEFORE decomposing tables)
    date = ""
    gender = ""
    age = ""
    categories = ""

    pub_td = soup.find("td", class_="footdata-pubdate")
    if pub_td:
        match = re.search(r"Published:\s*(.+)", pub_td.text)
        if match:
            date = match.group(1).strip()

    gender_td = soup.find("td", class_="footdata-gender")
    if gender_td:
        match = re.search(r"Gender:\s*(.+)", gender_td.text)
        if match:
            gender = match.group(1).strip()

    age_td = soup.find("td", class_="footdata-ageofexp")
    if age_td:
        match = re.search(r"Age.*?:\s*(.+)", age_td.text)
        if match:
            age = match.group(1).strip()

    cat_td = soup.find("td", class_="footdata-topic-list")
    if cat_td:
        categories = cat_td.text.strip()

    # Report text (extract AFTER footdata, because decompose is destructive)
    report_div = soup.find("div", class_="report-text-surround")
    body_text = ""
    if report_div:
        # Remove all tables (dosechart, bodyweight, footdata) before extracting text
        for table in report_div.find_all("table"):
            table.decompose()
        body_text = report_div.get_text(separator="\n").strip()

    # Determine if solo or combo
    is_combo = len(substances) > 1

    return {
        "id": report_id,
        "source": "erowid",
        "title": title,
        "author": author,
        "date": date,
        "url": report_url,
        "language": "en",
        "substances": substances,
        "body_weight": body_weight,
        "gender": gender,
        "age": age,
        "categories": categories,
        "is_combo": is_combo,
        "body_original": body_text,
        "body_translated": "",
    }


def scrape_substance(substance_name: str, callback=None,
                     max_reports: Optional[int] = None) -> list[dict]:
    """Scrape all reports for a substance: list + individual pages.

    Args:
        substance_name: Name of the substance.
        callback: Optional progress callback(source, current, total, message).
        max_reports: Optional limit on number of reports to scrape individually.

    Returns:
        List of fully scraped report dicts.
    """
    report_list = scrape_report_list(substance_name, callback=callback)

    if max_reports:
        report_list = report_list[:max_reports]

    total = len(report_list)
    full_reports = []

    for i, meta in enumerate(report_list):
        print(f"[erowid] Scraping report {i+1}/{total}: {meta['title'][:60]}")

        report = scrape_report(meta["url"], meta["id"])
        if report:
            # Merge list-level metadata (date from list if not found in report)
            if not report["date"] and meta.get("date"):
                report["date"] = meta["date"]
            full_reports.append(report)

        if callback:
            callback("erowid", i + 1, total, meta["title"])

        time.sleep(REQUEST_DELAY)

    print(f"[erowid] Successfully scraped {len(full_reports)}/{total} reports")
    return full_reports
