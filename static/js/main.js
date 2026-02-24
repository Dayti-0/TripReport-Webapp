/**
 * TripReport - Frontend logic + Socket.IO client
 */

(function () {
    "use strict";

    // ─── State ───────────────────────────────────────────────────────────────
    let allReports = [];
    let socket = null;
    let isScraping = false;
    let readReports = JSON.parse(localStorage.getItem("readReports") || "[]");

    // Source labels for display
    var SOURCE_LABELS = {
        "erowid": "Erowid",
        "psychonaut": "Psychonaut.fr",
        "psychonautwiki": "PsychonautWiki"
    };

    // ─── DOM Elements ────────────────────────────────────────────────────────
    const reportsGrid = document.getElementById("reportsGrid");
    const progressContainer = document.getElementById("progressContainer");
    const progressBar = document.getElementById("progressBar");
    const progressText = document.getElementById("progressText");
    const statsBar = document.getElementById("statsBar");
    const sidebarToggle = document.getElementById("sidebarToggle");
    const sidebarContent = document.getElementById("sidebarContent");
    const filterSearch = document.getElementById("filterSearch");
    const filterLang = document.getElementById("filterLang");
    const filterSolo = document.getElementById("filterSolo");
    const filterCombo = document.getElementById("filterCombo");
    const filterSource = document.getElementById("filterSource");
    const filterReset = document.getElementById("filterReset");

    // ─── Initialization ──────────────────────────────────────────────────────

    function init() {
        // Load cached reports if available
        if (typeof CACHED_INDEX !== "undefined" && CACHED_INDEX && CACHED_INDEX.reports) {
            allReports = CACHED_INDEX.reports;
            renderReports();
            updateStats();
        }

        // Always start scraping to check for new/missing reports.
        // The backend skips already-cached reports and will quickly finish
        // if everything is already downloaded.
        startScraping();

        // Setup event listeners
        setupFilters();
        setupSidebar();
    }

    // ─── Socket.IO ───────────────────────────────────────────────────────────

    function startScraping() {
        if (isScraping) return;
        isScraping = true;

        // Disconnect any previous socket before creating a new one
        if (socket) {
            socket.disconnect();
            socket = null;
        }

        socket = io();

        socket.on("connect", function () {
            console.log("[ws] Connected");
            socket.emit("start_scraping", { substance: SUBSTANCE_NAME });
        });

        socket.on("scraping_status", function (data) {
            showProgress(data.message);
        });

        socket.on("scraping_start", function (data) {
            var label = SOURCE_LABELS[data.source] || data.source;
            showProgress(
                "Scraping " + label + "... 0/" + data.total +
                (data.already_cached ? " (" + data.already_cached + " en cache)" : "")
            );
            progressBar.style.width = "5%";
        });

        socket.on("report_scraping", function (data) {
            var label = SOURCE_LABELS[data.source] || data.source;
            var pct = Math.max(5, Math.round((data.current / data.total) * 80));
            progressBar.style.width = pct + "%";
            showProgress(
                label + " " + data.current + "/" + data.total +
                " : " + truncate(data.title, 40)
            );
        });

        socket.on("report_translating", function (data) {
            var label = SOURCE_LABELS[data.source] || data.source;
            var pct = Math.max(5, Math.round((data.current / data.total) * 80));
            progressBar.style.width = pct + "%";
            showProgress(label + " - Traduction " + data.current + "/" + data.total + "...");
        });

        socket.on("report_scraped", function (data) {
            // Add new report to the list
            var report = data.report;
            // Check if already in the list
            var exists = allReports.some(function (r) { return r.id === report.id; });
            if (!exists) {
                allReports.push(report);
            }
            renderReports();
            updateStats();
        });

        socket.on("scraping_complete", function (data) {
            isScraping = false;
            progressBar.style.width = "100%";
            showProgress(data.message);
            setTimeout(function () {
                progressContainer.style.display = "none";
            }, 3000);
            // Reload full index from API
            fetch("/api/substance/" + encodeURIComponent(SUBSTANCE_NAME))
                .then(function (r) { return r.json(); })
                .then(function (index) {
                    if (index.reports && index.reports.length > 0) {
                        allReports = index.reports;
                        renderReports();
                        updateStats();
                    }
                })
                .catch(function (e) { console.error("Failed to reload index:", e); });
        });

        socket.on("scraping_error", function (data) {
            isScraping = false;
            showProgress("Erreur : " + data.message);
            progressBar.style.width = "0%";
            setTimeout(function () {
                progressContainer.style.display = "none";
            }, 5000);
        });
    }

    function showProgress(text) {
        progressContainer.style.display = "block";
        progressText.textContent = text;
    }

    // ─── Rendering ───────────────────────────────────────────────────────────

    function renderReports() {
        var filtered = applyFilters(allReports);
        reportsGrid.innerHTML = "";

        if (filtered.length === 0 && allReports.length > 0) {
            reportsGrid.innerHTML = '<p style="color: var(--text-muted); padding: 2rem;">Aucun rapport ne correspond aux filtres.</p>';
        } else if (filtered.length === 0) {
            reportsGrid.innerHTML = '<p style="color: var(--text-muted); padding: 2rem;">Aucun rapport disponible. Lancement du scraping...</p>';
        }

        filtered.forEach(function (report) {
            reportsGrid.appendChild(createCard(report));
        });

        // Update displayed count
        var statDisplayed = document.getElementById("statDisplayed");
        if (statDisplayed) statDisplayed.textContent = filtered.length;
    }

    function createCard(report) {
        var card = document.createElement("div");
        card.className = "report-card";

        // Substances text
        var substancesHtml = "";
        if (report.substances && report.substances.length > 0) {
            substancesHtml = report.substances.map(function (s) {
                return '<span class="substance-tag">' + escapeHtml(s.name) + '</span>';
            }).join("");
        } else if (report.substances_text) {
            substancesHtml = '<span class="substance-tag">' + escapeHtml(report.substances_text) + '</span>';
        }

        // Type badge
        var isCombo = report.is_combo ||
            (report.substances && report.substances.length > 1) ||
            (report.substances_text && report.substances_text.indexOf("&") !== -1);
        var typeBadge = isCombo
            ? '<span class="card-type-badge badge-combo">combo</span>'
            : '<span class="card-type-badge badge-solo">solo</span>';

        // Read badge
        var isRead = readReports.indexOf(report.id) !== -1;
        if (isRead) {
            card.classList.add("report-read");
        }

        card.innerHTML =
            (isRead ? '<span class="card-read-badge">D\u00e9j\u00e0 lu</span>' : '') +
            '<div class="card-title">' + escapeHtml(report.title_translated || report.title) + '</div>' +
            '<div class="card-meta">' +
                escapeHtml(report.author || "Anonyme") +
                (report.date ? ' &middot; ' + escapeHtml(report.date) : '') +
            '</div>' +
            '<div class="card-substances">' + substancesHtml + '</div>' +
            (report.body_weight_kg || report.body_weight
                ? '<div class="card-weight">' + escapeHtml(report.body_weight_kg || report.body_weight) +
                  (report.gender_fr || report.gender ? ' &middot; ' + escapeHtml(report.gender_fr || report.gender) : '') +
                  '</div>'
                : '') +
            (report.categories
                ? '<div class="card-categories">' + escapeHtml(report.categories) + '</div>'
                : '') +
            '<div class="card-footer">' +
                '<span class="card-source">' + escapeHtml(report.source) + ' ' + typeBadge + '</span>' +
                '<a href="/report/' + encodeURIComponent(SUBSTANCE_NAME) + '/' +
                    encodeURIComponent(report.id) + '" class="card-link">Lire &rarr;</a>' +
            '</div>';

        return card;
    }

    function updateStats() {
        var total = allReports.length;
        var solo = 0;
        var combo = 0;

        allReports.forEach(function (r) {
            var isCombo = r.is_combo ||
                (r.substances && r.substances.length > 1) ||
                (r.substances_text && r.substances_text.indexOf("&") !== -1);
            if (isCombo) combo++;
            else solo++;
        });

        document.getElementById("statTotal").textContent = total;
        document.getElementById("statSolo").textContent = solo;
        document.getElementById("statCombo").textContent = combo;
        document.getElementById("statDisplayed").textContent = total;
    }

    // ─── Filters ─────────────────────────────────────────────────────────────

    function setupFilters() {
        filterSearch.addEventListener("input", renderReports);
        filterLang.addEventListener("change", renderReports);
        filterSolo.addEventListener("change", renderReports);
        filterCombo.addEventListener("change", renderReports);
        filterSource.addEventListener("change", renderReports);
        filterReset.addEventListener("click", function () {
            filterSearch.value = "";
            filterLang.value = "all";
            filterSolo.checked = false;
            filterCombo.checked = false;
            filterSource.value = "all";
            renderReports();
        });
    }

    function applyFilters(reports) {
        var searchTerm = filterSearch.value.toLowerCase().trim();
        var lang = filterLang.value;
        var onlySolo = filterSolo.checked;
        var onlyCombo = filterCombo.checked;
        var source = filterSource.value;

        return reports.filter(function (r) {
            // Search filter
            if (searchTerm) {
                var searchIn = (
                    (r.title_translated || "") + " " +
                    (r.title || "") + " " +
                    (r.author || "") + " " +
                    (r.substances_text || "") + " " +
                    (r.substances ? r.substances.map(function (s) { return s.name; }).join(" ") : "")
                ).toLowerCase();
                if (searchIn.indexOf(searchTerm) === -1) return false;
            }

            // Language filter
            if (lang !== "all" && r.language && r.language !== lang) return false;

            // Solo/Combo filter
            var isCombo = r.is_combo ||
                (r.substances && r.substances.length > 1) ||
                (r.substances_text && r.substances_text.indexOf("&") !== -1);

            if (onlySolo && !onlyCombo && isCombo) return false;
            if (onlyCombo && !onlySolo && !isCombo) return false;

            // Source filter
            if (source !== "all" && r.source !== source) return false;

            return true;
        });
    }

    // ─── Sidebar ─────────────────────────────────────────────────────────────

    function setupSidebar() {
        sidebarToggle.addEventListener("click", function () {
            sidebarContent.classList.toggle("open");
        });
    }

    // ─── Utilities ───────────────────────────────────────────────────────────

    function escapeHtml(str) {
        if (!str) return "";
        var div = document.createElement("div");
        div.textContent = str;
        return div.innerHTML;
    }

    function truncate(str, maxLen) {
        if (!str) return "";
        return str.length > maxLen ? str.substring(0, maxLen) + "..." : str;
    }

    // ─── Cleanup ──────────────────────────────────────────────────────────────

    window.addEventListener("beforeunload", function () {
        if (socket) {
            socket.disconnect();
            socket = null;
        }
    });

    // ─── Start ───────────────────────────────────────────────────────────────

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
