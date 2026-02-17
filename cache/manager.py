"""Cache manager for storing scraped and translated reports as JSON files."""

import json
import os
import re
from datetime import datetime, timezone
from typing import Optional

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def _slugify(name: str) -> str:
    """Convert a substance name to a filesystem-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug


def _ensure_dirs(substance_slug: str) -> tuple[str, str]:
    """Ensure the cache directories exist for a substance. Returns (substance_dir, reports_dir)."""
    substance_dir = os.path.join(DATA_DIR, substance_slug)
    reports_dir = os.path.join(substance_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    return substance_dir, reports_dir


def get_cached_substances() -> list[dict]:
    """List all substances that have been cached.

    Returns:
        List of dicts with 'name', 'slug', 'report_count', 'last_scraped'.
    """
    if not os.path.exists(DATA_DIR):
        return []

    substances = []
    for entry in sorted(os.listdir(DATA_DIR)):
        index_path = os.path.join(DATA_DIR, entry, "index.json")
        if os.path.isfile(index_path):
            try:
                with open(index_path, "r", encoding="utf-8") as f:
                    index = json.load(f)
                substances.append({
                    "name": index.get("substance_name", entry),
                    "slug": entry,
                    "report_count": len(index.get("reports", [])),
                    "last_scraped": index.get("last_scraped", ""),
                })
            except (json.JSONDecodeError, IOError):
                continue
    return substances


def get_index(substance_name: str) -> Optional[dict]:
    """Get the cached index for a substance.

    Returns:
        The index dict, or None if not cached.
    """
    slug = _slugify(substance_name)
    index_path = os.path.join(DATA_DIR, slug, "index.json")
    if not os.path.isfile(index_path):
        return None
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def get_cached_report_ids(substance_name: str) -> set[str]:
    """Get the set of report IDs already cached for a substance."""
    index = get_index(substance_name)
    if not index:
        return set()
    return {r["id"] for r in index.get("reports", [])}


def save_report(substance_name: str, report: dict) -> None:
    """Save a single report to the cache.

    Also updates the index with the report's metadata.
    """
    slug = _slugify(substance_name)
    substance_dir, reports_dir = _ensure_dirs(slug)

    report_id = report["id"]
    report_path = os.path.join(reports_dir, f"{report_id}.json")

    # Save full report
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Update index
    index_path = os.path.join(substance_dir, "index.json")
    index = {"substance_name": substance_name, "reports": [], "last_scraped": ""}
    if os.path.isfile(index_path):
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                index = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    # Build metadata (report without body texts)
    meta = {k: v for k, v in report.items() if k not in ("body_original", "body_translated")}

    # Replace or add in index
    existing_ids = {r["id"]: i for i, r in enumerate(index["reports"])}
    if report_id in existing_ids:
        index["reports"][existing_ids[report_id]] = meta
    else:
        index["reports"].append(meta)

    index["last_scraped"] = datetime.now(timezone.utc).isoformat()

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def get_report(substance_name: str, report_id: str) -> Optional[dict]:
    """Load a single report from the cache.

    Returns:
        The full report dict, or None if not cached.
    """
    slug = _slugify(substance_name)
    report_path = os.path.join(DATA_DIR, slug, "reports", f"{report_id}.json")
    if not os.path.isfile(report_path):
        return None
    try:
        with open(report_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def is_report_cached(substance_name: str, report_id: str) -> bool:
    """Check if a specific report is already cached."""
    slug = _slugify(substance_name)
    report_path = os.path.join(DATA_DIR, slug, "reports", f"{report_id}.json")
    return os.path.isfile(report_path)
