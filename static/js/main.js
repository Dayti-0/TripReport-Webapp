/**
 * TripReport - Frontend logic + Socket.IO client (v2)
 */

(function () {
    "use strict";

    // ─── State ───────────────────────────────────────────────────────────────
    var allReports = [];
    var socket = null;
    var isScraping = false;
    var readReports = JSON.parse(localStorage.getItem("readReports") || "[]");
    var favorites = JSON.parse(localStorage.getItem("tripReportFavorites") || "[]");
    var currentSort = { field: "date", dir: "desc" };

    // Source labels for display
    var SOURCE_LABELS = {
        "erowid": "Erowid",
        "psychonaut": "Psychonaut.fr",
        "psychonautwiki": "PsychonautWiki"
    };

    // Rating categories mapped to sentiment
    var POSITIVE_RATINGS = [
        "glowing experiences", "very positive", "positive", "highly recommended",
        "recommended", "favorable"
    ];
    var NEGATIVE_RATINGS = [
        "bad trips", "train wrecks & trip disasters", "difficult experiences",
        "very negative", "negative", "health problems", "addiction & habituation",
        "not recommended"
    ];

    // ─── DOM Elements ────────────────────────────────────────────────────────
    var reportsGrid = document.getElementById("reportsGrid");
    var progressContainer = document.getElementById("progressContainer");
    var progressBar = document.getElementById("progressBar");
    var progressText = document.getElementById("progressText");
    var sidebarToggle = document.getElementById("sidebarToggle");
    var sidebarContent = document.getElementById("sidebarContent");
    var filterSearch = document.getElementById("filterSearch");
    var filterLang = document.getElementById("filterLang");
    var filterSolo = document.getElementById("filterSolo");
    var filterCombo = document.getElementById("filterCombo");
    var filterSource = document.getElementById("filterSource");
    var filterRouteGroup = document.getElementById("filterRouteGroup");
    var filterRouteContainer = document.getElementById("filterRouteContainer");
    var filterReset = document.getElementById("filterReset");
    var scrollTopBtn = document.getElementById("scrollTopBtn");

    // ─── Initialization ──────────────────────────────────────────────────────

    function init() {
        // Load cached reports if available
        if (typeof CACHED_INDEX !== "undefined" && CACHED_INDEX && CACHED_INDEX.reports) {
            allReports = CACHED_INDEX.reports;
            buildRouteCheckboxes();
            renderReports();
            updateStats();
        }

        // Always start scraping to check for new/missing reports.
        startScraping();

        // Setup event listeners
        setupFilters();
        setupSidebar();
        setupSorting();
        setupScrollToTop();
    }

    // ─── Socket.IO ───────────────────────────────────────────────────────────

    function startScraping() {
        if (isScraping) return;
        isScraping = true;

        if (socket) {
            socket.disconnect();
            socket = null;
        }

        socket = io();

        socket.on("connect", function () {
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
            var report = data.report;
            var exists = allReports.some(function (r) { return r.id === report.id; });
            if (!exists) {
                allReports.push(report);
            }
            buildRouteCheckboxes();
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
                        buildRouteCheckboxes();
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

    // ─── Sorting ─────────────────────────────────────────────────────────────

    function setupSorting() {
        var sortBtns = document.querySelectorAll(".sort-btn");
        for (var i = 0; i < sortBtns.length; i++) {
            sortBtns[i].addEventListener("click", function () {
                var field = this.getAttribute("data-sort");
                var dir = this.getAttribute("data-dir");

                // Toggle direction if same field clicked
                if (currentSort.field === field) {
                    dir = currentSort.dir === "asc" ? "desc" : "asc";
                }

                currentSort = { field: field, dir: dir };
                this.setAttribute("data-dir", dir);

                // Update UI
                var allBtns = document.querySelectorAll(".sort-btn");
                for (var j = 0; j < allBtns.length; j++) {
                    allBtns[j].classList.remove("active");
                    var arrow = allBtns[j].querySelector(".sort-arrow");
                    if (arrow) arrow.textContent = "";
                }
                this.classList.add("active");
                var myArrow = this.querySelector(".sort-arrow");
                if (!myArrow) {
                    myArrow = document.createElement("span");
                    myArrow.className = "sort-arrow";
                    this.appendChild(myArrow);
                }
                myArrow.innerHTML = dir === "asc" ? "&uarr;" : "&darr;";

                renderReports();
            });
        }
    }

    function sortReports(reports) {
        var field = currentSort.field;
        var dir = currentSort.dir;
        var mult = dir === "asc" ? 1 : -1;

        return reports.slice().sort(function (a, b) {
            var va, vb;
            switch (field) {
                case "date":
                    va = a.date || "";
                    vb = b.date || "";
                    break;
                case "title":
                    va = (a.title_translated || a.title || "").toLowerCase();
                    vb = (b.title_translated || b.title || "").toLowerCase();
                    break;
                case "source":
                    va = a.source || "";
                    vb = b.source || "";
                    break;
                case "rating":
                    va = getRatingSortValue(a);
                    vb = getRatingSortValue(b);
                    break;
                default:
                    va = a.date || "";
                    vb = b.date || "";
            }
            if (va < vb) return -1 * mult;
            if (va > vb) return 1 * mult;
            return 0;
        });
    }

    function getRatingSortValue(report) {
        var rating = (report.rating || "").toLowerCase();
        if (!rating) return "1_none";
        for (var i = 0; i < POSITIVE_RATINGS.length; i++) {
            if (rating.indexOf(POSITIVE_RATINGS[i]) !== -1) return "0_positive";
        }
        for (var j = 0; j < NEGATIVE_RATINGS.length; j++) {
            if (rating.indexOf(NEGATIVE_RATINGS[j]) !== -1) return "2_negative";
        }
        return "1_neutral";
    }

    // ─── Rendering ───────────────────────────────────────────────────────────

    function renderReports() {
        var filtered = applyFilters(allReports);
        filtered = sortReports(filtered);
        reportsGrid.innerHTML = "";

        if (filtered.length === 0 && allReports.length > 0) {
            reportsGrid.innerHTML =
                '<div class="no-results">' +
                '<div class="no-results-icon">&#128269;</div>' +
                '<p>Aucun rapport ne correspond aux filtres.</p>' +
                '</div>';
        } else if (filtered.length === 0) {
            reportsGrid.innerHTML =
                '<div class="no-results">' +
                '<div class="no-results-icon">&#9203;</div>' +
                '<p>Aucun rapport disponible. Lancement du scraping...</p>' +
                '</div>';
        }

        // Stagger animation
        filtered.forEach(function (report, index) {
            var card = createCard(report);
            card.style.animationDelay = Math.min(index * 30, 500) + "ms";
            reportsGrid.appendChild(card);
        });

        // Update displayed count
        var statDisplayed = document.getElementById("statDisplayed");
        if (statDisplayed) statDisplayed.textContent = filtered.length;
    }

    function createCard(report) {
        var card = document.createElement("div");
        card.className = "report-card";

        // Substances text (with dosage info)
        var substancesHtml = "";
        if (report.substances && report.substances.length > 0) {
            substancesHtml = report.substances.map(function (s) {
                var label = s.name;
                var doseInfo = "";
                if (s.dose) doseInfo += s.dose;
                if (s.route) doseInfo += (doseInfo ? ", " : "") + s.route;
                if (doseInfo) {
                    return '<span class="substance-tag">' + escapeHtml(label) +
                        ' <span class="substance-dose">' + escapeHtml(doseInfo) + '</span></span>';
                }
                return '<span class="substance-tag">' + escapeHtml(label) + '</span>';
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
        if (isRead) card.classList.add("report-read");

        // Favorite state
        var isFav = favorites.indexOf(report.id) !== -1;

        // Rating badge
        var ratingHtml = "";
        if (report.rating) {
            var ratingClass = getRatingClass(report.rating);
            ratingHtml = '<span class="card-rating ' + ratingClass + '">' +
                escapeHtml(truncate(report.rating, 35)) + '</span>';
        }

        card.innerHTML =
            '<div class="card-header">' +
                '<div>' +
                    (isRead ? '<span class="card-read-badge" title="Cliquer pour retirer" data-report-id="' + escapeHtml(report.id) + '">D\u00e9j\u00e0 lu &times;</span>' : '') +
                    '<div class="card-title">' + escapeHtml(report.title_translated || report.title) + '</div>' +
                '</div>' +
                '<button class="card-favorite' + (isFav ? ' favorited' : '') + '" data-report-id="' + escapeHtml(report.id) + '" title="' + (isFav ? 'Retirer des favoris' : 'Ajouter aux favoris') + '">' +
                    (isFav ? '\u2605' : '\u2606') +
                '</button>' +
            '</div>' +
            '<div class="card-meta">' +
                escapeHtml(report.author || "Anonyme") +
                (report.date ? ' \u00b7 ' + escapeHtml(report.date) : '') +
            '</div>' +
            '<div class="card-substances">' + substancesHtml + '</div>' +
            (report.body_weight_kg || report.body_weight
                ? '<div class="card-weight">' + escapeHtml(report.body_weight_kg || report.body_weight) +
                  (report.gender_fr || report.gender ? ' \u00b7 ' + escapeHtml(report.gender_fr || report.gender) : '') +
                  '</div>'
                : '') +
            ratingHtml +
            (report.categories
                ? '<div class="card-categories">' + escapeHtml(report.categories) + '</div>'
                : '') +
            '<div class="card-footer">' +
                '<span class="card-source">' + escapeHtml(SOURCE_LABELS[report.source] || report.source) + ' ' + typeBadge + '</span>' +
                '<a href="/report/' + encodeURIComponent(SUBSTANCE_NAME) + '/' +
                    encodeURIComponent(report.id) + '" class="card-link">Lire &rarr;</a>' +
            '</div>';

        // Read badge click handler
        if (isRead) {
            var badge = card.querySelector(".card-read-badge");
            if (badge) {
                badge.addEventListener("click", function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    var rid = this.getAttribute("data-report-id");
                    var idx = readReports.indexOf(rid);
                    if (idx !== -1) {
                        readReports.splice(idx, 1);
                        localStorage.setItem("readReports", JSON.stringify(readReports));
                    }
                    this.parentElement.parentElement.parentElement.classList.remove("report-read");
                    this.remove();
                });
            }
        }

        // Favorite button handler
        var favBtn = card.querySelector(".card-favorite");
        if (favBtn) {
            favBtn.addEventListener("click", function (e) {
                e.preventDefault();
                e.stopPropagation();
                var rid = this.getAttribute("data-report-id");
                var idx = favorites.indexOf(rid);
                if (idx !== -1) {
                    favorites.splice(idx, 1);
                    this.classList.remove("favorited");
                    this.textContent = "\u2606";
                    this.title = "Ajouter aux favoris";
                } else {
                    favorites.push(rid);
                    this.classList.add("favorited");
                    this.textContent = "\u2605";
                    this.title = "Retirer des favoris";
                }
                localStorage.setItem("tripReportFavorites", JSON.stringify(favorites));
            });
        }

        return card;
    }

    function getRatingClass(rating) {
        var r = rating.toLowerCase();
        for (var i = 0; i < POSITIVE_RATINGS.length; i++) {
            if (r.indexOf(POSITIVE_RATINGS[i]) !== -1) return "rating-positive";
        }
        for (var j = 0; j < NEGATIVE_RATINGS.length; j++) {
            if (r.indexOf(NEGATIVE_RATINGS[j]) !== -1) return "rating-negative";
        }
        return "rating-neutral";
    }

    function updateStats() {
        var total = allReports.length;
        var solo = 0;
        var combo = 0;
        var fr = 0;

        allReports.forEach(function (r) {
            var isCombo = r.is_combo ||
                (r.substances && r.substances.length > 1) ||
                (r.substances_text && r.substances_text.indexOf("&") !== -1);
            if (isCombo) combo++;
            else solo++;
            if (r.language === "fr") fr++;
        });

        animateStatValue("statTotal", total);
        animateStatValue("statSolo", solo);
        animateStatValue("statCombo", combo);
        animateStatValue("statFr", fr);
        document.getElementById("statDisplayed").textContent = total;

        renderDosageStats();
    }

    // Animate stat numbers counting up
    function animateStatValue(elementId, targetValue) {
        var el = document.getElementById(elementId);
        if (!el) return;
        var current = parseInt(el.textContent) || 0;
        if (current === targetValue) return;

        var diff = targetValue - current;
        var steps = Math.min(Math.abs(diff), 20);
        var stepSize = diff / steps;
        var step = 0;

        function tick() {
            step++;
            if (step >= steps) {
                el.textContent = targetValue;
                return;
            }
            el.textContent = Math.round(current + stepSize * step);
            requestAnimationFrame(tick);
        }
        requestAnimationFrame(tick);
    }

    // ─── Dosage Stats ─────────────────────────────────────────────────────────

    function parseDose(doseStr) {
        if (!doseStr) return null;
        var match = doseStr.match(/^[\s]*([\d]+(?:[.,]\d+)?)\s*(mg|g|ug|µg|ml|mcg)\b/i);
        if (match) {
            var value = parseFloat(match[1].replace(",", "."));
            if (isNaN(value) || value <= 0) return null;
            var unit = match[2].toLowerCase();
            if (unit === "µg" || unit === "mcg") unit = "ug";
            return { value: value, unit: unit };
        }
        var countMatch = doseStr.match(/^[\s]*([\d]+(?:[.,]\d+)?)\s*(seeds?|hits?|caps?|capsules?|tablets?|tabs?|drops?|pills?|blotters?|stamps?|joints?|bowls?|bumps?|lines?|sprays?|puffs?|pieces?|slices?|scoops?|spoons?|tablespoons?|teaspoons?|bags?|cups?|leaves?|flowers?|pods?)\b/i);
        if (countMatch) {
            var countValue = parseFloat(countMatch[1].replace(",", "."));
            if (isNaN(countValue) || countValue <= 0) return null;
            var countUnit = countMatch[2].toLowerCase();
            if (countUnit === "leaves") {
                countUnit = "leaf";
            } else {
                countUnit = countUnit.replace(/s$/, "");
            }
            if (countUnit === "capsule") countUnit = "cap";
            if (countUnit === "tablet") countUnit = "tab";
            if (countUnit === "blotter" || countUnit === "stamp") countUnit = "hit";
            if (countUnit === "tablespoon") countUnit = "tbsp";
            if (countUnit === "teaspoon") countUnit = "tsp";
            return { value: countValue, unit: countUnit };
        }
        return null;
    }

    function isMatchingSubstance(substanceName, searchedName) {
        if (!substanceName || !searchedName) return false;
        var a = substanceName.toLowerCase().trim();
        var b = searchedName.toLowerCase().trim();
        if (a === b) return true;
        if (a.indexOf(b) !== -1 || b.indexOf(a) !== -1) return true;
        var normA = a.replace(/[-\s.()]/g, "");
        var normB = b.replace(/[-\s.()]/g, "");
        if (normA === normB) return true;
        if (normA.indexOf(normB) !== -1 || normB.indexOf(normA) !== -1) return true;
        return false;
    }

    function normalizeRoute(routeStr) {
        var ROUTE_ALIASES = {
            "insufflated": "insufflated",
            "snorted": "insufflated",
            "nasal": "insufflated",
            "intranasal": "insufflated",
            "oral": "oral",
            "eaten": "oral",
            "swallowed": "oral",
            "smoked": "smoked",
            "inhaled": "inhaled",
            "vapourized": "inhaled",
            "vaporized": "inhaled",
            "sublingual": "sublingual",
            "buccal": "sublingual",
            "im": "IM",
            "intramuscular": "IM",
            "iv": "IV",
            "intravenous": "IV",
            "iv drip": "IV",
            "rectal": "rectal",
            "plugged": "rectal",
            "transdermal": "transdermal",
            "topical": "transdermal",
            "subcutaneous": "subcutaneous"
        };
        var route = routeStr.trim().toLowerCase();
        return ROUTE_ALIASES[route] || route;
    }

    var COUNT_UNITS = ["seed", "hit", "cap", "tab", "drop", "pill", "joint", "bowl",
        "bump", "line", "spray", "puff", "piece", "slice", "scoop", "spoon",
        "tbsp", "tsp", "bag", "cup", "leaf", "flower", "pod"];

    function convertToMg(value, unit) {
        if (COUNT_UNITS.indexOf(unit) !== -1) {
            return { value_mg: value, unit_type: "count", count_unit: unit };
        }
        switch (unit) {
            case "g":  return { value_mg: value * 1000, unit_type: "weight" };
            case "mg": return { value_mg: value,        unit_type: "weight" };
            case "ug": return { value_mg: value / 1000, unit_type: "weight" };
            case "ml": return { value_mg: value,        unit_type: "volume" };
            default:   return { value_mg: value,        unit_type: "weight" };
        }
    }

    function chooseBestUnit(values_mg) {
        if (values_mg.length === 0) return "mg";
        var median = values_mg.slice().sort(function (a, b) { return a - b; })[Math.floor(values_mg.length / 2)];
        if (median >= 1000) return "g";
        if (median < 1) return "ug";
        return "mg";
    }

    function convertFromMg(value_mg, targetUnit) {
        switch (targetUnit) {
            case "g":  return value_mg / 1000;
            case "ug": return value_mg * 1000;
            default:   return value_mg;
        }
    }

    function computeDosageStats() {
        var groups = {};
        var targetSubstance = (typeof SUBSTANCE_NAME !== "undefined") ? SUBSTANCE_NAME : "";

        allReports.forEach(function (r) {
            if (!r.substances || r.substances.length === 0) return;

            var reportDoses = {};
            r.substances.forEach(function (s) {
                if (targetSubstance && !isMatchingSubstance(s.name, targetSubstance)) return;

                var rawRoute = (s.route || "").trim().toLowerCase();
                if (!rawRoute) return;
                var parsed = parseDose(s.dose);
                if (!parsed) return;

                var converted = convertToMg(parsed.value, parsed.unit);

                var routeParts = rawRoute.split(/[\n\r]+/).map(function (p) { return p.trim(); }).filter(Boolean);
                routeParts.forEach(function (part) {
                    var route = normalizeRoute(part);
                    var unitKey = converted.unit_type === "count"
                        ? "count:" + converted.count_unit
                        : converted.unit_type;
                    var key = route + "|" + unitKey;
                    if (!reportDoses[key]) {
                        reportDoses[key] = {
                            route: route,
                            unit_type: converted.unit_type,
                            count_unit: converted.count_unit || null,
                            value_mg: 0
                        };
                    }
                    reportDoses[key].value_mg += converted.value_mg;
                });
            });

            Object.keys(reportDoses).forEach(function (key) {
                var rd = reportDoses[key];
                if (!groups[key]) {
                    groups[key] = {
                        route: rd.route,
                        unit_type: rd.unit_type,
                        count_unit: rd.count_unit,
                        values: []
                    };
                }
                groups[key].values.push(rd.value_mg);
            });
        });

        var results = [];
        Object.keys(groups).forEach(function (key) {
            var g = groups[key];
            var vals = g.values;
            vals.sort(function (a, b) { return a - b; });
            var sum = vals.reduce(function (acc, v) { return acc + v; }, 0);

            var displayUnit;
            if (g.unit_type === "count") {
                displayUnit = g.count_unit;
            } else if (g.unit_type === "volume") {
                displayUnit = "ml";
            } else {
                displayUnit = chooseBestUnit(vals);
            }

            var minVal = g.unit_type === "count" ? vals[0] : convertFromMg(vals[0], displayUnit);
            var maxVal = g.unit_type === "count" ? vals[vals.length - 1] : convertFromMg(vals[vals.length - 1], displayUnit);
            var avgVal = g.unit_type === "count" ? sum / vals.length : convertFromMg(sum / vals.length, displayUnit);

            results.push({
                route: g.route,
                unit: displayUnit,
                count: vals.length,
                min: minVal,
                max: maxVal,
                avg: avgVal
            });
        });

        results.sort(function (a, b) { return b.count - a.count; });
        return results;
    }

    function formatDose(value, unit) {
        var str;
        if (value >= 100) {
            str = Math.round(value).toString();
        } else if (value >= 10) {
            str = value.toFixed(1).replace(/\.0$/, "");
        } else {
            str = value.toFixed(2).replace(/\.?0+$/, "");
        }
        var displayUnit = unit;
        if (COUNT_UNITS.indexOf(unit) !== -1 && value > 1) {
            if (unit === "leaf") {
                displayUnit = "leaves";
            } else {
                displayUnit = unit + "s";
            }
        }
        return str + " " + displayUnit;
    }

    function renderDosageStats() {
        var container = document.getElementById("dosageStats");
        var grid = document.getElementById("dosageStatsGrid");
        if (!container || !grid) return;

        var stats = computeDosageStats();
        if (stats.length === 0) {
            container.style.display = "none";
            return;
        }

        container.style.display = "block";
        grid.innerHTML = "";

        stats.forEach(function (s) {
            var row = document.createElement("div");
            row.className = "dosage-row";
            row.innerHTML =
                '<span class="dosage-route">' + escapeHtml(s.route) + '</span>' +
                '<span class="dosage-detail">' +
                    '<span class="dosage-label">min</span> ' +
                    '<span class="dosage-value">' + escapeHtml(formatDose(s.min, s.unit)) + '</span>' +
                '</span>' +
                '<span class="dosage-detail">' +
                    '<span class="dosage-label">moy</span> ' +
                    '<span class="dosage-value">' + escapeHtml(formatDose(s.avg, s.unit)) + '</span>' +
                '</span>' +
                '<span class="dosage-detail">' +
                    '<span class="dosage-label">max</span> ' +
                    '<span class="dosage-value">' + escapeHtml(formatDose(s.max, s.unit)) + '</span>' +
                '</span>' +
                '<span class="dosage-count">(' + s.count + ')</span>';
            grid.appendChild(row);
        });
    }

    // ─── Dosage toggle ────────────────────────────────────────────────────────

    var dosageToggle = document.getElementById("dosageStatsToggle");
    if (dosageToggle) {
        dosageToggle.addEventListener("click", function () {
            var container = document.getElementById("dosageStats");
            if (container) {
                container.classList.toggle("open");
            }
        });
    }

    // ─── Filters ─────────────────────────────────────────────────────────────

    function buildRouteCheckboxes() {
        if (!filterRouteContainer || !filterRouteGroup) return;

        var targetSub = (typeof SUBSTANCE_NAME !== "undefined") ? SUBSTANCE_NAME : "";
        var routeSet = {};
        allReports.forEach(function (r) {
            if (!r.substances) return;
            r.substances.forEach(function (s) {
                if (!s.route) return;
                if (targetSub && !isMatchingSubstance(s.name, targetSub)) return;
                var parts = s.route.split(/[\n\r]+/).map(function (p) { return p.trim(); }).filter(Boolean);
                parts.forEach(function (part) {
                    var normalized = normalizeRoute(part);
                    if (normalized) routeSet[normalized] = true;
                });
            });
        });

        var routes = Object.keys(routeSet).sort();
        if (routes.length === 0) {
            filterRouteGroup.style.display = "none";
            return;
        }

        var previouslyChecked = {};
        var existing = filterRouteContainer.querySelectorAll("input[type=checkbox]");
        for (var i = 0; i < existing.length; i++) {
            if (existing[i].checked) previouslyChecked[existing[i].value] = true;
        }

        filterRouteGroup.style.display = "block";
        filterRouteContainer.innerHTML = "";

        routes.forEach(function (route) {
            var label = document.createElement("label");
            var cb = document.createElement("input");
            cb.type = "checkbox";
            cb.value = route;
            cb.className = "filter-route-cb";
            if (previouslyChecked[route]) cb.checked = true;
            cb.addEventListener("change", renderReports);
            label.appendChild(cb);
            label.appendChild(document.createTextNode(" " + route));
            filterRouteContainer.appendChild(label);
        });
    }

    function getSelectedRoutes() {
        if (!filterRouteContainer) return [];
        var checked = filterRouteContainer.querySelectorAll("input.filter-route-cb:checked");
        var routes = [];
        for (var i = 0; i < checked.length; i++) {
            routes.push(checked[i].value);
        }
        return routes;
    }

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
            if (filterRouteContainer) {
                var cbs = filterRouteContainer.querySelectorAll("input.filter-route-cb");
                for (var i = 0; i < cbs.length; i++) {
                    cbs[i].checked = false;
                }
            }
            renderReports();
        });
    }

    function applyFilters(reports) {
        var searchTerm = filterSearch.value.toLowerCase().trim();
        var lang = filterLang.value;
        var onlySolo = filterSolo.checked;
        var onlyCombo = filterCombo.checked;
        var source = filterSource.value;
        var selectedRoutes = getSelectedRoutes();

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

            // Route of administration filter
            if (selectedRoutes.length > 0) {
                if (!r.substances || r.substances.length === 0) return false;
                var targetSub = (typeof SUBSTANCE_NAME !== "undefined") ? SUBSTANCE_NAME : "";
                var reportRoutes = [];
                r.substances.forEach(function (s) {
                    if (!s.route) return;
                    if (targetSub && !isMatchingSubstance(s.name, targetSub)) return;
                    var parts = s.route.split(/[\n\r]+/).map(function (p) { return p.trim(); }).filter(Boolean);
                    parts.forEach(function (part) {
                        var normalized = normalizeRoute(part);
                        if (normalized) reportRoutes.push(normalized);
                    });
                });
                var hasMatch = selectedRoutes.some(function (sr) {
                    return reportRoutes.indexOf(sr) !== -1;
                });
                if (!hasMatch) return false;
            }

            return true;
        });
    }

    // ─── Sidebar ─────────────────────────────────────────────────────────────

    function setupSidebar() {
        sidebarToggle.addEventListener("click", function () {
            var isOpen = sidebarContent.classList.toggle("open");
            sidebarToggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
            sidebarToggle.textContent = isOpen ? "Masquer les filtres" : "Filtres";
        });
    }

    // ─── Scroll to Top ──────────────────────────────────────────────────────

    function setupScrollToTop() {
        if (!scrollTopBtn) return;

        window.addEventListener("scroll", function () {
            if (window.scrollY > 400) {
                scrollTopBtn.classList.add("visible");
            } else {
                scrollTopBtn.classList.remove("visible");
            }
        }, { passive: true });

        scrollTopBtn.addEventListener("click", function () {
            window.scrollTo({ top: 0, behavior: "smooth" });
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
        return str.length > maxLen ? str.substring(0, maxLen) + "\u2026" : str;
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
