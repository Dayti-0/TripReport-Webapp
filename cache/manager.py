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
    """Get the set of report IDs already cached for a substance.

    Checks actual report files on disk for reliability, rather than
    relying solely on the index which could be out of sync if the
    script was interrupted.
    """
    slug = _slugify(substance_name)
    reports_dir = os.path.join(DATA_DIR, slug, "reports")
    if not os.path.isdir(reports_dir):
        return set()
    return {f[:-5] for f in os.listdir(reports_dir) if f.endswith(".json")}


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


def get_merge_suggestions(substances: list[dict]) -> list[dict]:
    """Detect substance pairs that are likely duplicates (one name is a substring of another).

    Returns a list of groups, each being a list of substance dicts that should be merged.
    The first element in each group is the longest-named substance (the merge target).
    """
    n = len(substances)
    merged_indices: set[int] = set()
    groups = []

    for i in range(n):
        if i in merged_indices:
            continue
        slug_i = _slugify(substances[i]["name"])
        group = [i]
        for j in range(n):
            if i == j or j in merged_indices:
                continue
            slug_j = _slugify(substances[j]["name"])
            # One slug is a prefix of the other (e.g. "lsd" vs "lsd-25" → merge,
            # but "lsd" vs "1cp-lsd" → do NOT merge because "lsd" is a suffix, not prefix)
            if slug_j.startswith(slug_i + "-") or slug_i.startswith(slug_j + "-"):
                group.append(j)

        if len(group) > 1:
            for idx in group:
                merged_indices.add(idx)
            # Sort by name length descending; longest name is the merge target
            group_subs = sorted([substances[k] for k in group], key=lambda s: len(s["name"]), reverse=True)
            groups.append(group_subs)

    return groups


def merge_substances(names: list[str]) -> str:
    """Merge multiple substance cache entries into the one with the longest name.

    Moves all report files from the shorter-named entries into the longest-named
    entry's directory, rebuilds the index, and removes the now-empty directories.

    Returns the slug of the merged (target) substance.
    """
    if len(names) < 2:
        raise ValueError("Need at least 2 substance names to merge.")

    # Longest name wins
    target_name = max(names, key=len)
    target_slug = _slugify(target_name)
    target_dir, target_reports_dir = _ensure_dirs(target_slug)

    # Load existing target index (if any)
    target_index_path = os.path.join(target_dir, "index.json")
    target_index: dict = {"substance_name": target_name, "reports": [], "last_scraped": ""}
    if os.path.isfile(target_index_path):
        try:
            with open(target_index_path, "r", encoding="utf-8") as f:
                target_index = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    target_index["substance_name"] = target_name

    existing_report_ids = {r["id"] for r in target_index["reports"]}

    for name in names:
        if name == target_name:
            continue
        slug = _slugify(name)
        src_dir = os.path.join(DATA_DIR, slug)
        src_reports_dir = os.path.join(src_dir, "reports")
        src_index_path = os.path.join(src_dir, "index.json")

        if not os.path.isdir(src_dir):
            continue

        # Load source index for metadata
        src_index: dict = {"reports": []}
        if os.path.isfile(src_index_path):
            try:
                with open(src_index_path, "r", encoding="utf-8") as f:
                    src_index = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

        src_meta_by_id = {r["id"]: r for r in src_index.get("reports", [])}

        # Move report files
        if os.path.isdir(src_reports_dir):
            for fname in os.listdir(src_reports_dir):
                if not fname.endswith(".json"):
                    continue
                report_id = fname[:-5]
                src_path = os.path.join(src_reports_dir, fname)
                dst_path = os.path.join(target_reports_dir, fname)

                # Move the file
                import shutil
                shutil.move(src_path, dst_path)

                # Add to target index if not already there
                if report_id not in existing_report_ids:
                    meta = src_meta_by_id.get(report_id)
                    if meta:
                        target_index["reports"].append(meta)
                    else:
                        # Build minimal meta from the report file itself
                        try:
                            with open(dst_path, "r", encoding="utf-8") as f:
                                rdata = json.load(f)
                            meta = {k: v for k, v in rdata.items()
                                    if k not in ("body_original", "body_translated")}
                            target_index["reports"].append(meta)
                        except (json.JSONDecodeError, IOError):
                            pass
                    existing_report_ids.add(report_id)

        # Remove source directory
        import shutil as _shutil
        _shutil.rmtree(src_dir, ignore_errors=True)

    # Write updated target index
    target_index["last_scraped"] = datetime.now(timezone.utc).isoformat()
    with open(target_index_path, "w", encoding="utf-8") as f:
        json.dump(target_index, f, ensure_ascii=False, indent=2)

    return target_slug
