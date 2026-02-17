"""TripReport Webapp - Flask application with WebSocket support."""

import threading

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit

from scraper.erowid import scrape_report_list, scrape_report
from translator.translate import translate_report
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


def _scrape_worker(substance_name: str, substance_key: str):
    """Background worker that scrapes, translates, and caches reports.

    Emits progress events via WebSocket to all subscribers.
    """
    try:
        # Step 1: Get the report list
        _emit_to_subscribers("scraping_status", {
            "message": f"Récupération de la liste des rapports pour '{substance_name}'...",
            "phase": "listing",
        }, substance_key)

        report_list = scrape_report_list(substance_name)
        if not report_list:
            _emit_to_subscribers("scraping_error", {
                "message": f"Aucun rapport trouvé pour '{substance_name}' sur Erowid.",
            }, substance_key)
            return

        # Filter out already cached reports
        cached_ids = get_cached_report_ids(substance_name)
        new_reports = [r for r in report_list if r["id"] not in cached_ids]
        already_cached = len(report_list) - len(new_reports)

        total = len(new_reports)
        _emit_to_subscribers("scraping_start", {
            "source": "erowid",
            "total": total,
            "total_with_cached": len(report_list),
            "already_cached": already_cached,
        }, substance_key)

        if total == 0:
            _emit_to_subscribers("scraping_complete", {
                "total_reports": len(report_list),
                "message": "Tous les rapports sont déjà en cache.",
            }, substance_key)
            return

        # Step 2: Scrape and translate each report
        import time

        for i, meta in enumerate(new_reports):
            # Skip if another thread already cached this report
            if is_report_cached(substance_name, meta["id"]):
                continue

            _emit_to_subscribers("report_scraping", {
                "source": "erowid",
                "current": i + 1,
                "total": total,
                "title": meta["title"],
            }, substance_key)

            # Scrape individual report
            report_data = scrape_report(meta["url"], meta["id"])
            if not report_data:
                continue

            # Merge date from list if missing
            if not report_data.get("date") and meta.get("date"):
                report_data["date"] = meta["date"]

            # Translate
            _emit_to_subscribers("report_translating", {
                "current": i + 1,
                "total": total,
                "title": meta["title"],
            }, substance_key)

            translate_report(report_data)

            # Cache
            save_report(substance_name, report_data)

            # Notify frontend
            report_meta = {k: v for k, v in report_data.items()
                           if k not in ("body_original", "body_translated")}
            _emit_to_subscribers("report_scraped", {
                "source": "erowid",
                "current": i + 1,
                "total": total,
                "report": report_meta,
            }, substance_key)

            time.sleep(0.2)  # Small delay between WebSocket events

        # Step 3: Done
        final_index = get_index(substance_name)
        total_reports = len(final_index["reports"]) if final_index else 0
        _emit_to_subscribers("scraping_complete", {
            "total_reports": total_reports,
            "message": f"Scraping terminé ! {total_reports} rapports disponibles.",
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
