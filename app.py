"""TripReport Webapp - Flask application with WebSocket support."""

import threading
import time

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit

from scraper import erowid, psychonaut, psychonautwiki
from translator.translate import translate_report, translate_text
from cache.manager import (
    get_cached_substances,
    get_index,
    get_report,
    save_report,
    is_report_cached,
    get_cached_report_ids,
)

app = Flask(__name__)
app.config["SECRET_KEY"] = "tripreport-secret-key"
socketio = SocketIO(app, async_mode="threading")

# Track active scraping tasks per substance to prevent duplicates.
# Maps substance_name (lowercase) -> {"thread": Thread, "subscribers": set of sids}
_active_tasks = {}
_active_tasks_lock = threading.Lock()

# All scraper modules with their display name
SCRAPERS = [
    {"module": erowid, "name": "erowid", "label": "Erowid"},
    {"module": psychonaut, "name": "psychonaut", "label": "Psychonaut.fr"},
    {"module": psychonautwiki, "name": "psychonautwiki", "label": "PsychonautWiki"},
]


# ─── Routes ─────────────────────────────────────────────────────────────────


@app.route("/")
def index():
    """Home page with search field and cached substances."""
    substances = get_cached_substances()
    return render_template("index.html", substances=substances)


@app.route("/substance/<name>")
def substance(name: str):
    """Substance dashboard page."""
    cached_index = get_index(name)
    return render_template("substance.html", substance_name=name, cached_index=cached_index)


@app.route("/report/<substance>/<report_id>")
def report(substance: str, report_id: str):
    """Individual report page."""
    report_data = get_report(substance, report_id)
    if not report_data:
        return render_template("report.html", report=None, substance_name=substance), 404

    # Auto-translate title if missing (for reports cached before title translation)
    if (
        not report_data.get("title_translated")
        and report_data.get("title")
        and report_data.get("language") != "fr"
    ):
        try:
            translated = translate_text(report_data["title"], source="en", target="fr")
            report_data["title_translated"] = translated if translated else report_data["title"]
            save_report(substance, report_data)
            print(f"[auto-translate] Title translated for {report_id}: '{report_data['title_translated']}'")
        except Exception as e:
            print(f"[auto-translate] Failed to translate title for {report_id}: {e}")
            report_data["title_translated"] = report_data["title"]

    return render_template("report.html", report=report_data, substance_name=substance)


@app.route("/api/substance/<name>")
def api_substance(name: str):
    """API endpoint to get cached reports for a substance."""
    cached_index = get_index(name)
    if cached_index:
        return jsonify(cached_index)
    return jsonify({"substance_name": name, "reports": [], "last_scraped": ""})


@app.route("/api/substances")
def api_substances():
    """API endpoint to list all cached substances."""
    return jsonify(get_cached_substances())


# ─── WebSocket Events ────────────────────────────────────────────────────────


def _emit_to_subscribers(event: str, data: dict, substance_key: str):
    """Emit a WebSocket event to all subscribers of a scraping task."""
    with _active_tasks_lock:
        task = _active_tasks.get(substance_key)
        if not task:
            return
        sids = list(task["subscribers"])
    for sid in sids:
        socketio.emit(event, data, to=sid)


def _scrape_source(scraper_info: dict, substance_name: str, substance_key: str,
                   cached_ids: set[str]) -> int:
    """Scrape a single source: list reports, scrape + translate new ones, cache them.

    Returns the number of new reports scraped from this source.
    """
    source_name = scraper_info["name"]
    source_label = scraper_info["label"]
    module = scraper_info["module"]

    _emit_to_subscribers("scraping_status", {
        "message": f"Récupération de la liste des rapports sur {source_label}...",
        "phase": "listing",
        "source": source_name,
    }, substance_key)

    try:
        report_list = module.scrape_report_list(substance_name)
    except Exception as e:
        print(f"[{source_name}] Error during list scraping: {e}")
        _emit_to_subscribers("scraping_status", {
            "message": f"Erreur lors du scraping de {source_label}: {e}",
            "phase": "error",
            "source": source_name,
        }, substance_key)
        return 0

    if not report_list:
        _emit_to_subscribers("scraping_status", {
            "message": f"Aucun rapport trouvé sur {source_label}.",
            "phase": "empty",
            "source": source_name,
        }, substance_key)
        return 0

    # Filter out already cached reports
    new_reports = [r for r in report_list if r["id"] not in cached_ids]
    already_cached = len(report_list) - len(new_reports)
    total = len(new_reports)

    _emit_to_subscribers("scraping_start", {
        "source": source_name,
        "total": total,
        "total_with_cached": len(report_list),
        "already_cached": already_cached,
    }, substance_key)

    if total == 0:
        _emit_to_subscribers("scraping_status", {
            "message": f"{source_label} : {already_cached} rapports déjà en cache.",
            "phase": "cached",
            "source": source_name,
        }, substance_key)
        return 0

    scraped_count = 0

    for i, meta in enumerate(new_reports):
        # Skip if another thread already cached this report
        if is_report_cached(substance_name, meta["id"]):
            cached_ids.add(meta["id"])
            continue

        _emit_to_subscribers("report_scraping", {
            "source": source_name,
            "current": i + 1,
            "total": total,
            "title": meta["title"],
        }, substance_key)

        # Scrape individual report
        try:
            report_data = module.scrape_report(meta["url"], meta["id"])
        except Exception as e:
            print(f"[{source_name}] Error scraping report {meta['id']}: {e}")
            continue

        if not report_data:
            continue

        # Merge date from list if missing
        if not report_data.get("date") and meta.get("date"):
            report_data["date"] = meta["date"]

        # Translate if needed (skip French reports from psychonaut.fr)
        if report_data.get("language") != "fr" and report_data.get("body_original"):
            _emit_to_subscribers("report_translating", {
                "source": source_name,
                "current": i + 1,
                "total": total,
                "title": meta["title"],
            }, substance_key)

            try:
                translate_report(report_data)
            except Exception as e:
                print(f"[{source_name}] Translation error for {meta['id']}: {e}")
                # Keep the report even if translation fails
                report_data["body_translated"] = report_data.get("body_original", "")

        # Cache
        save_report(substance_name, report_data)
        cached_ids.add(report_data["id"])
        scraped_count += 1

        # Notify frontend
        report_meta = {k: v for k, v in report_data.items()
                       if k not in ("body_original", "body_translated")}
        _emit_to_subscribers("report_scraped", {
            "source": source_name,
            "current": i + 1,
            "total": total,
            "report": report_meta,
        }, substance_key)

        time.sleep(0.2)  # Small delay between WebSocket events

    return scraped_count


def _scrape_worker(substance_name: str, substance_key: str):
    """Background worker that scrapes all sources, translates, and caches reports.

    Emits progress events via WebSocket to all subscribers.
    """
    try:
        cached_ids = get_cached_report_ids(substance_name)
        total_new = 0

        for scraper_info in SCRAPERS:
            new_count = _scrape_source(
                scraper_info, substance_name, substance_key, cached_ids
            )
            total_new += new_count

        # Done
        final_index = get_index(substance_name)
        total_reports = len(final_index["reports"]) if final_index else 0

        if total_new == 0 and total_reports > 0:
            message = f"Tous les rapports sont déjà en cache ({total_reports} rapports)."
        elif total_new == 0:
            message = f"Aucun rapport trouvé pour '{substance_name}'."
        else:
            message = f"Scraping terminé ! {total_new} nouveaux rapports, {total_reports} au total."

        _emit_to_subscribers("scraping_complete", {
            "total_reports": total_reports,
            "message": message,
        }, substance_key)
    finally:
        # Clean up the task entry
        with _active_tasks_lock:
            _active_tasks.pop(substance_key, None)


@socketio.on("start_scraping")
def handle_start_scraping(data):
    """Handle a scraping request from the client."""
    substance_name = data.get("substance", "").strip()
    if not substance_name:
        emit("scraping_error", {"message": "Nom de substance vide."})
        return

    sid = request.sid
    substance_key = substance_name.lower().replace(" ", "-")

    with _active_tasks_lock:
        if substance_key in _active_tasks:
            # A scraping task is already running for this substance.
            # Subscribe this client to receive progress updates too.
            _active_tasks[substance_key]["subscribers"].add(sid)
            emit("scraping_status", {
                "message": f"Scraping déjà en cours pour '{substance_name}'...",
                "phase": "already_running",
            })
            return

        # Register new task
        _active_tasks[substance_key] = {
            "subscribers": {sid},
        }

    # Run scraping in a background thread
    thread = threading.Thread(
        target=_scrape_worker,
        args=(substance_name, substance_key),
        daemon=True,
    )
    thread.start()


@socketio.on("connect")
def handle_connect():
    print(f"[ws] Client connected: {request.sid}")


@socketio.on("disconnect")
def handle_disconnect():
    sid = request.sid
    print(f"[ws] Client disconnected: {sid}")
    # Remove this client from all active task subscriber lists
    with _active_tasks_lock:
        for task in _active_tasks.values():
            task["subscribers"].discard(sid)


# ─── Main ────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True)
