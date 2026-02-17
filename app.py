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


def _scrape_worker(substance_name: str, sid: str):
    """Background worker that scrapes, translates, and caches reports.

    Emits progress events via WebSocket.
    """
    # Step 1: Get the report list
    socketio.emit("scraping_status", {
        "message": f"Récupération de la liste des rapports pour '{substance_name}'...",
        "phase": "listing",
    }, to=sid)

    report_list = scrape_report_list(substance_name)
    if not report_list:
        socketio.emit("scraping_error", {
            "message": f"Aucun rapport trouvé pour '{substance_name}' sur Erowid.",
        }, to=sid)
        return

    # Filter out already cached reports
    cached_ids = get_cached_report_ids(substance_name)
    new_reports = [r for r in report_list if r["id"] not in cached_ids]
    already_cached = len(report_list) - len(new_reports)

    total = len(new_reports)
    socketio.emit("scraping_start", {
        "source": "erowid",
        "total": total,
        "total_with_cached": len(report_list),
        "already_cached": already_cached,
    }, to=sid)

    if total == 0:
        socketio.emit("scraping_complete", {
            "total_reports": len(report_list),
            "message": "Tous les rapports sont déjà en cache.",
        }, to=sid)
        return

    # Step 2: Scrape and translate each report
    import time

    for i, meta in enumerate(new_reports):
        socketio.emit("report_scraping", {
            "source": "erowid",
            "current": i + 1,
            "total": total,
            "title": meta["title"],
        }, to=sid)

        # Scrape individual report
        report_data = scrape_report(meta["url"], meta["id"])
        if not report_data:
            continue

        # Merge date from list if missing
        if not report_data.get("date") and meta.get("date"):
            report_data["date"] = meta["date"]

        # Translate
        socketio.emit("report_translating", {
            "current": i + 1,
            "total": total,
            "title": meta["title"],
        }, to=sid)

        translate_report(report_data)

        # Cache
        save_report(substance_name, report_data)

        # Notify frontend
        report_meta = {k: v for k, v in report_data.items()
                       if k not in ("body_original", "body_translated")}
        socketio.emit("report_scraped", {
            "source": "erowid",
            "current": i + 1,
            "total": total,
            "report": report_meta,
        }, to=sid)

        time.sleep(0.2)  # Small delay between WebSocket events

    # Step 3: Done
    final_index = get_index(substance_name)
    total_reports = len(final_index["reports"]) if final_index else 0
    socketio.emit("scraping_complete", {
        "total_reports": total_reports,
        "message": f"Scraping terminé ! {total_reports} rapports disponibles.",
    }, to=sid)


@socketio.on("start_scraping")
def handle_start_scraping(data):
    """Handle a scraping request from the client."""
    substance_name = data.get("substance", "").strip()
    if not substance_name:
        emit("scraping_error", {"message": "Nom de substance vide."})
        return

    sid = request.sid

    # Run scraping in a background thread
    thread = threading.Thread(
        target=_scrape_worker,
        args=(substance_name, sid),
        daemon=True,
    )
    thread.start()


@socketio.on("connect")
def handle_connect():
    print(f"[ws] Client connected: {request.sid}")


@socketio.on("disconnect")
def handle_disconnect():
    print(f"[ws] Client disconnected: {request.sid}")


# ─── Main ────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True)
