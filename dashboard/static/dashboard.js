// =========================================================
// SEO AUTOMATION DASHBOARD
// Context-aware Website / YouTube dashboard
// =========================================================

"use strict";


/* =========================================================
   STATE
   ========================================================= */

let state = {
    data: null,
    overview: null,
    charts: {},
    runs: [],
    automation: "SEARCH",
    activeView: "overview",

    // Live Logs state
    selectedLogRunId: "",
    liveLogs: [],
    logsLoading: false
};


/* =========================================================
   DOM HELPERS
   ========================================================= */

function $(id) {
    return document.getElementById(id);
}


function setText(id, value) {
    const element = $(id);

    if (element) {
        element.textContent = value ?? "";
    }
}


function escapeHtml(value) {
    if (value === null || value === undefined) {
        return "";
    }

    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}


/* =========================================================
   AUTOMATION HELPERS
   ========================================================= */

function getAutomationName(mode = state.automation) {
    return String(mode || "").toUpperCase() === "SEARCH"
        ? "Website"
        : "YouTube";
}


function getApiAutomation(mode = state.automation) {
    return String(mode || "").toUpperCase() === "SEARCH"
        ? "SEARCH"
        : "YOUTUBE";
}


function modeApiName() {
    return getApiAutomation(state.automation);
}


function isWebsite() {
    return state.automation === "SEARCH";
}


function isYouTube() {
    return state.automation === "YOUTUBE";
}


/* =========================================================
   AUTOMATION TOGGLE
   ========================================================= */

function updateAutomationToggle() {
    const current =
        getApiAutomation(state.automation);

    document
        .querySelectorAll(".automation-switch-btn")
        .forEach(button => {
            const buttonMode =
                String(
                    button.dataset.automation ||
                    button.dataset.mode ||
                    ""
                ).toUpperCase();

            const active =
                buttonMode === current;

            button.classList.toggle(
                "active",
                active
            );

            button.setAttribute(
                "aria-selected",
                active ? "true" : "false"
            );
        });
}


/* =========================================================
   HEADER
   ========================================================= */

function updateHeader() {
    const name =
        getAutomationName();

    const title =
        $("pageTitle");

    const subtitle =
        $("pageSubtitle");

    if (title) {
        if (state.activeView === "overview") {
            title.textContent =
                `${name} Automation Overview`;
        }
        else {
            title.textContent =
                name;
        }
    }

    if (subtitle) {
        if (state.activeView === "overview") {
            subtitle.textContent =
                `Performance overview for ${name} automation`;
        }
        else {
            subtitle.textContent =
                `${name} automation activity`;
        }
    }

    setText(
        "automationTitle",
        name
    );

    setText(
        "heroTitle",
        `${name} automation is under control.`
    );
}


/* =========================================================
   SIDEBAR
   ========================================================= */

function updateSidebar() {
    /*
     * Website and YouTube are now equal-priority contexts.
     *
     * The sidebar itself stays common:
     *
     * Overview
     * Automation Runs
     * Live Logs
     * Search Engines
     * Performance
     *
     * Therefore we DO NOT hide Website/YouTube navigation
     * items here.
     */

    document
        .querySelectorAll(".nav-item")
        .forEach(button => {
            const automation =
                button.dataset.automation;

            if (!automation) {
                return;
            }

            const active =
                String(automation).toUpperCase() ===
                getApiAutomation();

            button.classList.toggle(
                "active-automation",
                active
            );
        });
}

/* =========================================================
   AUTOMATION LOADER
   ========================================================= */

function showAutomationLoader() {

    const loader =
        $("automationLoader");

    if (loader) {
        loader.hidden = false;
        loader.classList.add("is-visible");
    }

    document
        .querySelectorAll(
            ".automation-switch-btn"
        )
        .forEach(button => {

            button.disabled = true;

            button.classList.add(
                "is-loading"
            );
        });
}


function hideAutomationLoader() {

    const loader =
        $("automationLoader");

    if (loader) {
        loader.classList.remove(
            "is-visible"
        );

        loader.hidden = true;
    }

    document
        .querySelectorAll(
            ".automation-switch-btn"
        )
        .forEach(button => {

            button.disabled = false;

            button.classList.remove(
                "is-loading"
            );
        });
}


/* =========================================================
   AUTOMATION SWITCH
   ========================================================= */

async function setAutomation(mode, view = null) {
    const normalized =
        String(mode || "").toUpperCase() === "SEARCH"
            ? "SEARCH"
            : "YOUTUBE";

    state.automation = normalized;

    if (view) {
        state.activeView = view;

        document
            .querySelectorAll(".view")
            .forEach(viewElement => {
                viewElement.classList.remove("active");
            });

        const activeViewElement = $(view);

        if (activeViewElement) {
            activeViewElement.classList.add("active");
        }

        document
            .querySelectorAll(".nav-item[data-view]")
            .forEach(button => {
                button.classList.toggle(
                    "active",
                    button.dataset.view === view
                );
            });
    }

    rememberAutomation();

    updateAutomationToggle();
    updateSidebar();
    updateHeader();

    showAutomationLoader();

    try {
        await loadAutomationData(normalized);
    }
    finally {
        hideAutomationLoader();
    }

    // renderDashboardView();
}


/* =========================================================
   VIEW HANDLING
   ========================================================= */

function showView(viewId) {
    const target = $(viewId);

    if (!target) {
        console.warn("[DASHBOARD] View not found:", viewId);
        return;
    }

    document.querySelectorAll(".view").forEach(view => view.classList.remove("active"));
    target.classList.add("active");

    state.activeView = viewId === "dashboard" ? "overview" : viewId;

    document.querySelectorAll(".nav-item[data-view]").forEach(button => {
        button.classList.toggle("active", button.dataset.view === state.activeView);
    });

    if (viewId === "website" || viewId === "youtube") {
        state.automation = viewId === "website" ? "SEARCH" : "YOUTUBE";
        state.activeView = "overview";
        const overview = $("overview");
        if (overview) {
            document.querySelectorAll(".view").forEach(view => view.classList.remove("active"));
            overview.classList.add("active");
        }
        updateAutomationToggle();
        updateSidebar();
        updateHeader();
        loadSelectedAutomation();
        return;
    }

    updateHeader();
    updateSidebar();
    updateAutomationToggle();

    /* Critical: changing a sidebar view must render the already-loaded data. */
    if (state.data) {
        renderDashboardView();
    }
}


/* =========================================================
   NAVIGATION
   ========================================================= */

function nav() {
    document
        .querySelectorAll(".nav-item")
        .forEach(button => {

            /*
             * Avoid duplicate listeners.
             */
            if (
                button.dataset.dashboardNavBound === "true"
            ) {
                return;
            }

            button.dataset.dashboardNavBound =
                "true";

            button.addEventListener(
                "click",
                () => {

                    const automation =
                        button.dataset.automation;

                    const view =
                        button.dataset.view;

                    /*
                     * If the sidebar item explicitly has an
                     * automation, change context.
                     */
                    if (automation) {
                        setAutomation(
                            automation,
                            view || state.activeView
                        );
                    }

                    /*
                     * Common sidebar navigation.
                     */
                    if (view) {
                        showView(view);
                    }
                }
            );
        });


    document
        .querySelectorAll(
            "[data-view-target]"
        )
        .forEach(button => {

            if (
                button.dataset.dashboardTargetBound ===
                "true"
            ) {
                return;
            }

            button.dataset.dashboardTargetBound =
                "true";

            button.addEventListener(
                "click",
                () => {
                    showView(
                        button.dataset.viewTarget
                    );
                }
            );
        });


    /*
     * Website / YouTube top toggle.
     */
    document
        .querySelectorAll(
            ".automation-switch-btn"
        )
        .forEach(button => {

            if (
                button.dataset.dashboardAutomationBound ===
                "true"
            ) {
                return;
            }

            button.dataset.dashboardAutomationBound =
                "true";

            button.addEventListener(
                "click",
                async () => {

                    const automation =
                        button.dataset.automation ||
                        button.dataset.mode ||
                        "YOUTUBE";

                    await setAutomation(
                        automation,
                        state.activeView
                    );

                    window.scrollTo({
                        top: 0,
                        behavior: "smooth"
                    });
                }
            );
        });
}


/* =========================================================
   DATABASE HEALTH
   ========================================================= */

async function health() {
    try {
        const response = await fetch(
            "/api/health",
            {
                cache: "no-store"
            }
        );

        let data = {};

        try {
            data = await response.json();
        } catch (jsonError) {
            data = {};
        }

        if (data.status === "connected") {
            setText("dbStatus", "Connected");
            return;
        }

        if (data.status === "disconnected") {
            setText("dbStatus", "Disconnected");
            return;
        }

        setText("dbStatus", "Unavailable");

    } catch (error) {
        setText("dbStatus", "Unavailable");

        console.error(
            "Database health error:",
            error
        );
    }
}


/* =========================================================
   API
   ========================================================= */

async function fetchDashboard(
    days,
    automation
) {

    const response =
        await fetch(
            `/api/dashboard?days=${encodeURIComponent(days)}&automation=${encodeURIComponent(automation)}`,
            {
                cache: "no-store"
            }
        );

    if (!response.ok) {
        throw new Error(
            `Dashboard API failed: ${response.status}`
        );
    }

    return response.json();
}


/* =========================================================
   EMPTY DATA
   ========================================================= */

function emptyDashboardData(
    automation = modeApiName()
) {

    return {
        automation,
        generated_at: null,

        summary: {
            total_runs: 0,
            successful_runs: 0,
            failed_runs: 0,
            running_runs: 0,
            interrupted_runs: 0,
            total_retries: 0,
            unique_keywords: 0,
            success_rate: 0
        },

        daily: [],
        engines: [],
        recent: []
    };
}


/* =========================================================
   MAIN LOAD
   ========================================================= */

async function load() {

    const range =
        $("range");

    const days =
        range?.value || "7";

    const generated =
        $("generated");

    const automation =
        getApiAutomation();

    console.log(
        "[DASHBOARD] Loading selected automation:",
        automation
    );

    try {

        /*
         * IMPORTANT:
         *
         * Load ONLY the currently selected automation.
         *
         * SEARCH  = Website
         * YOUTUBE = YouTube
         */

        const data =
            await fetchDashboard(
                days,
                automation
            );

        /*
         * Store ONLY selected automation.
         */

        state.data = data;

        state.runs =
            data.recent || [];

        /*
         * Keep overview data pointing
         * to the selected automation only.
         */

        state.overview = {
            youtube:
                automation === "YOUTUBE"
                    ? data
                    : null,

            website:
                automation === "SEARCH"
                    ? data
                    : null
        };

        /*
         * Render selected automation.
         */

        renderCurrentMode();

        renderOverview();

        /*
         * Database refresh time.
         */

        if (
            generated &&
            data.generated_at
        ) {

            generated.textContent =
                `Last database refresh: ${
                    new Date(
                        data.generated_at
                    ).toLocaleString("en-IN")
                }`;
        }

        console.log(
            "[DASHBOARD] Loaded selected automation:",
            automation,
            data
        );

    } catch (error) {

        console.error(
            "[DASHBOARD] Dashboard load failed:",
            automation,
            error
        );

        state.data = {
            automation,

            summary: {
                total_runs: 0,
                successful_runs: 0,
                failed_runs: 0,
                running_runs: 0,
                interrupted_runs: 0,
                total_retries: 0,
                unique_keywords: 0,
                success_rate: 0
            },

            daily: [],
            engines: [],
            recent: []
        };

        state.runs = [];

        state.overview = {
            youtube:
                automation === "YOUTUBE"
                    ? state.data
                    : null,

            website:
                automation === "SEARCH"
                    ? state.data
                    : null
        };

        renderCurrentMode();

        renderOverview();

        if (generated) {
            generated.textContent =
                "Unable to load database data. Check PostgreSQL connection.";
        }
    }

    health();
}


/* =========================================================
   LOAD SELECTED AUTOMATION
   ========================================================= */

async function loadSelectedAutomation() {

    const range =
        $("range");

    const days =
        range
            ? range.value
            : "7";

    const automation =
        modeApiName();

    console.log(
        "[DASHBOARD] Loading:",
        automation
    );

    try {

        const data =
            await fetchDashboard(
                days,
                automation
            );

        /*
         * Store ONLY selected automation.
         */
        state.data =
            data || emptyDashboardData(
                automation
            );

        state.overview =
            state.data;

        state.runs =
            state.data.recent || [];

        /*
         * Render selected context.
         */
        renderCurrentMode();

        if (
            state.activeView ===
            "overview"
        ) {
            renderOverview();
        }

        const generated =
            $("generated");

        if (
            generated &&
            state.data.generated_at
        ) {
            generated.textContent =
                `Last database refresh: ${
                    new Date(
                        state.data.generated_at
                    ).toLocaleString(
                        "en-IN"
                    )
                }`;
        }

        console.log(
            "[DASHBOARD] Loaded:",
            automation,
            data
        );

    }
    catch (error) {

        console.error(
            "[DASHBOARD] Failed loading",
            automation,
            error
        );

        state.data =
            emptyDashboardData(
                automation
            );

        state.overview =
            state.data;

        state.runs = [];

        renderCurrentMode();

        if (
            state.activeView ===
            "overview"
        ) {
            renderOverview();
        }
    }
}


/* =========================================================
   OVERVIEW
   ========================================================= */

/* =========================================================
   OVERVIEW
   ========================================================= */

function renderOverview() {

    /*
     * Overview always represents ONLY the
     * currently selected automation.
     */

    if (!state.data) {
        return;
    }

    const data =
        state.data || {};

    const summary =
        data.summary || {};

    const totalRuns =
        Number(
            summary.total_runs || 0
        );

    const successful =
        Number(
            summary.successful_runs || 0
        );

    const failed =
        Number(
            summary.failed_runs || 0
        );

    const retries =
        Number(
            summary.total_retries || 0
        );

    const keywords =
        Number(
            summary.unique_keywords || 0
        );

    const running =
        Number(
            summary.running_runs || 0
        );

    const interrupted =
        Number(
            summary.interrupted_runs || 0
        );

    const successRate =
        Number(
            summary.success_rate || 0
        );

    /*
     * Selected automation KPI
     */

    setText(
        "totalRuns",
        totalRuns
    );

    setText(
        "successRuns",
        successful
    );

    setText(
        "failedRuns",
        failed
    );

    setText(
        "retries",
        retries
    );

    setText(
        "keywords",
        keywords
    );

    setText(
        "heroRate",
        `${successRate.toFixed(1)}%`
    );

    setText(
        "donutRate",
        `${successRate.toFixed(1)}%`
    );

    /*
     * Daily activity
     *
     * IMPORTANT:
     * Do NOT merge YouTube + Website.
     * Use only selected automation.
     */

    renderActivity(
        data.daily || []
    );

    /*
     * Health
     *
     * IMPORTANT:
     * Do NOT combine both automations.
     */

    renderHealth({

        successful_runs:
            successful,

        failed_runs:
            failed,

        running_runs:
            running,

        interrupted_runs:
            interrupted
    });

    /*
     * Remove old comparison UI
     * if it exists from an earlier render.
     */

    const comparison =
        $("typeBars");

    if (comparison) {
        comparison.innerHTML = "";
    }

    const automationCards =
        $("overviewAutomationCards");

    if (automationCards) {
        automationCards.remove();
    }
}


/* =========================================================
   LEGACY FUNCTION
   ========================================================= */

/* =========================================================
   OVERVIEW AUTOMATION CARDS
   DISABLED
   ========================================================= */

function ensureOverviewAutomationCards() {

    const container =
        $("overviewAutomationCards");

    if (container) {
        container.remove();
    }

    /*
     * Intentionally empty.
     *
     * Overview must NOT show
     * Website vs YouTube comparison cards.
     */
}


/* =========================================================
   LEGACY RENDER TYPES
   ========================================================= */

function renderTypes() {

    /*
     * No-op by design.
     *
     * The dashboard should not show a Website-vs-YouTube
     * comparison anymore.
     */
}


/* =========================================================
   DAILY DATA MERGE
   ========================================================= */

function mergeDaily(
    first = [],
    second = []
) {

    /*
     * Kept for backwards compatibility.
     *
     * New Overview does NOT use this to combine
     * Website and YouTube.
     */

    const map =
        new Map();

    [...first, ...second]
        .forEach(item => {

            const date =
                item.date ||
                item.day ||
                item.label;

            if (!date) {
                return;
            }

            if (!map.has(date)) {

                map.set(
                    date,
                    {
                        ...item
                    }
                );

                return;
            }

            const existing =
                map.get(date);

            Object.keys(item)
                .forEach(key => {

                    if (
                        key === "date" ||
                        key === "day" ||
                        key === "label"
                    ) {
                        return;
                    }

                    const current =
                        Number(
                            existing[key] || 0
                        );

                    const incoming =
                        Number(
                            item[key] || 0
                        );

                    if (
                        !Number.isNaN(
                            incoming
                        )
                    ) {
                        existing[key] =
                            current +
                            incoming;
                    }
                });
        });

    return Array.from(
        map.values()
    );
}


/* =========================================================
   CHART HELPERS
   ========================================================= */

function destroyChart(
    key
) {

    if (
        state.charts &&
        state.charts[key]
    ) {

        try {
            state.charts[key].destroy();
        }
        catch (error) {
            console.warn(
                "Chart destroy error:",
                key,
                error
            );
        }

        state.charts[key] =
            null;
    }
}


function getCanvas(
    id
) {
    const element =
        $(id);

    if (!element) {
        return null;
    }

    return element.getContext(
        "2d"
    );
}


/* =========================================================
   ACTIVITY CHART
   ========================================================= */

function renderActivity(
    daily = []
) {

    const canvas =
        $("activityChart");

    if (!canvas) {
        return;
    }

    destroyChart(
        "activity"
    );

    if (
        typeof Chart ===
        "undefined"
    ) {
        console.warn(
            "Chart.js is not loaded."
        );

        return;
    }

    const labels =
        daily.map(
            item =>
                item.date ||
                item.day ||
                item.label ||
                ""
        );

    const totals =
        daily.map(
            item =>
                Number(
                    item.total_runs ??
                    item.total ??
                    item.runs ??
                    0
                )
        );

    const successful =
        daily.map(
            item =>
                Number(
                    item.successful_runs ??
                    item.success ??
                    item.successful ??
                    0
                )
        );

    const failed =
        daily.map(
            item =>
                Number(
                    item.failed_runs ??
                    item.failed ??
                    0
                )
        );

    const running =
        daily.map(
            item =>
                Number(
                    item.running_runs ??
                    item.running ??
                    0
                )
        );

    const datasets = [
        {
            label: "Total",
            data: totals,
            borderColor: "#5b8cff",
            backgroundColor: "#5b8cff",
            tension: 0.35,
            fill: false
        },
        {
            label: "Successful",
            data: successful,
            borderColor: "#35d39a",
            backgroundColor: "#35d39a",
            tension: 0.35,
            fill: false
        },
        {
            label: "Failed",
            data: failed,
            borderColor: "#ff6577",
            backgroundColor: "#ff6577",
            tension: 0.35,
            fill: false
        }
    ];

    /*
     * Only add Running when data actually exists.
     */
    if (
        running.some(
            value => value > 0
        )
    ) {
        datasets.push({
            label: "Running",
            data: running,
            tension: 0.35,
            fill: false
        });
    }

    state.charts.activity =
        new Chart(
            canvas,
            {
                type: "line",

                data: {
                    labels,
                    datasets
                },

                options: {
                    responsive: true,
                    maintainAspectRatio: false,

                    interaction: {
                        intersect: false,
                        mode: "index"
                    },

                    plugins: {
                        legend: {
                            display: true
                        },

                        tooltip: {
                            enabled: true
                        }
                    },

                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: {
                                precision: 0
                            }
                        }
                    }
                }
            }
        );
}


/* =========================================================
   HEALTH CHART
   ========================================================= */

function renderHealth(
    summary = {}
) {

    const canvas =
        $("healthChart") ||
        $("healthDonut");

    if (!canvas) {
        return;
    }

    destroyChart(
        "health"
    );

    if (
        typeof Chart ===
        "undefined"
    ) {
        return;
    }

    const successful =
        Number(
            summary.successful_runs || 0
        );

    const failed =
        Number(
            summary.failed_runs || 0
        );

    const running =
        Number(
            summary.running_runs || 0
        );

    const interrupted =
        Number(
            summary.interrupted_runs || 0
        );

    const total =
        successful +
        failed +
        running +
        interrupted;

    /*
     * If backend supplies total_runs and it is larger than
     * status components, preserve that total by treating
     * remaining runs as other.
     */
    const suppliedTotal =
        Number(
            summary.total_runs || 0
        );

    const actualTotal =
        Math.max(
            total,
            suppliedTotal
        );

    const other =
        Math.max(
            0,
            actualTotal -
            total
        );

    const labels = [
        "Successful",
        "Failed",
        "Running",
        "Interrupted"
    ];

    const values = [
        successful,
        failed,
        running,
        interrupted
    ];

    if (other > 0) {
        labels.push(
            "Other"
        );

        values.push(
            other
        );
    }

    state.charts.health =
        new Chart(
            canvas,
            {
                type: "doughnut",

                data: {
                    labels,
                    datasets: [
                        {
                            data: values,
                            backgroundColor: [
                                "#35d39a", // Successful - GREEN
                                "#ff6577", // Failed - RED
                                "#f4bd54", // Running - AMBER
                                "#ffd45c"  // Interrupted - YELLOW
                            ]
                        }
                    ]
                },

                options: {
                    responsive: true,
                    maintainAspectRatio: false,

                    cutout: "70%",

                    plugins: {
                        legend: {
                            display: true,
                            position: "bottom"
                        }
                    }
                }
            }
        );
}


function updateEngineVisibility() {
    const canvas = $("engineChart");

    if (!canvas) {
        return;
    }

    const panel =
        canvas.closest(".panel") ||
        canvas.parentElement?.closest(".panel");

    if (!panel) {
        return;
    }

    // Search-engine analytics is available
    // for both Website and YouTube automation.
    panel.hidden = false;
}


/* =========================================================
   SEARCH ENGINE PERFORMANCE
   ========================================================= */

function renderEngines(engines = []) {

    const filteredEngines =
        engines.filter(engine => {

            const name =
                String(
                    engine.engine ??
                    engine.search_engine ??
                    engine.name ??
                    ""
                )
                    .trim()
                    .toUpperCase();

            /*
             * YouTube is NOT a search engine.
             * Hide it from Search Engine Performance.
             */
            return !(
                state.automation === "YOUTUBE" &&
                name === "YOUTUBE"
            );
        });

    engines = filteredEngines;


    /*
     * SEARCH ENGINE PERFORMANCE CHART
     *
     * Only TOTAL RUNS are shown here.
     *
     * Successful / Failed are intentionally
     * NOT included because they are shown
     * in the detailed Search Engines page.
     */

    const canvas =
        $("searchEnginePerformanceChart");

    if (
        !canvas ||
        typeof Chart === "undefined"
    ) {
        return;
    }


    /*
     * No data
     */

    if (
        !Array.isArray(engines) ||
        engines.length === 0
    ) {

        destroyChart(
            "searchEnginePerformance"
        );

        return;
    }


    /*
     * Labels
     */

    const labels =
        engines.map(
            item =>
                item.engine ??
                item.search_engine ??
                item.name ??
                "Unknown"
        );


    /*
     * Total runs only
     */

    const totals =
        engines.map(
            item =>
                toNumber(
                    item.total ??
                    item.total_runs ??
                    item.runs ??
                    item.count ??
                    0
                )
        );


    /*
     * Destroy previous chart
     */

    destroyChart(
        "searchEnginePerformance"
    );


    /*
     * Vertical bar chart
     */

    state.charts.searchEnginePerformance =
        new Chart(
            canvas,
            {
                type: "bar",

                data: {

                    labels,

                    datasets: [
                        {
                            label: "Total Runs",

                            data: totals,

                            backgroundColor:
                                "#5b8cff",

                            borderColor:
                                "#5b8cff",

                            borderWidth: 0,

                            borderRadius: 6,

                            barPercentage: 0.55,

                            categoryPercentage: 0.65
                        }
                    ]
                },


                options: {

                    responsive: true,

                    maintainAspectRatio: false,


                    plugins: {

                        legend: {
                            display: false
                        },

                        tooltip: {

                            enabled: true,

                            backgroundColor:
                                "#101827",

                            borderColor:
                                "#243249",

                            borderWidth: 1,

                            titleColor:
                                "#ffffff",

                            bodyColor:
                                "#aebbd0",

                            padding: 12,

                            displayColors: false,

                            callbacks: {

                                label: context =>
                                    ` ${formatNumber(
                                        context.raw
                                    )} runs`
                            }
                        }
                    },


                    scales: {

                        x: {

                            grid: {
                                display: false
                            },

                            ticks: {

                                color:
                                    "#8b98aa",

                                font: {
                                    size: 11
                                }
                            }
                        },


                        y: {

                            beginAtZero: true,

                            grid: {

                                color:
                                    "rgba(139,152,170,0.08)"
                            },

                            ticks: {

                                color:
                                    "#707d91",

                                precision: 0,

                                font: {
                                    size: 10
                                }
                            }
                        }
                    }
                }
            }
        );
}


    /* =========================================================
    YOUTUBE PERFORMANCE
    ========================================================= */

    function renderYoutubePerformance(
    youtube = null
) {
    const section =
        $("youtubePerformanceSection");

    const container =
        $("youtubePerformanceBars");

    if (!section || !container) {
        return;
    }

    /*
     * Show this panel only for YouTube automation.
     */
    if (state.automation !== "YOUTUBE") {
        section.hidden = true;
        container.innerHTML = "";
        return;
    }

    section.hidden = false;

    /*
     * YouTube performance data comes
     * directly from state.data.youtube
     */
    const youtubeData =
        youtube || {
            total: 0,
            success: 0,
            failed: 0,
            success_rate: 0
        };

    const total =
        toNumber(
            youtubeData.total ??
            youtubeData.total_runs ??
            youtubeData.runs ??
            youtubeData.count ??
            0
        );

    const successful =
        toNumber(
            youtubeData.success ??
            youtubeData.successful_runs ??
            youtubeData.successful ??
            0
        );

    const failed =
        toNumber(
            youtubeData.failed ??
            youtubeData.failed_runs ??
            0
        );

    const rate =
        youtubeData.success_rate !== undefined
            ? toNumber(
                youtubeData.success_rate
            )
            : total
                ? (
                    successful /
                    total
                ) * 100
                : 0;

    container.innerHTML = `
        <div class="bar-row">

            <div class="bar-label">
                <span>
                    Total
                </span>

                <strong>
                    ${formatNumber(total)}
                </strong>
            </div>

            <div class="bar-track">
                <div
                    class="bar-fill youtube-total"
                    style="width:100%"
                ></div>
            </div>

        </div>


        <div class="bar-row">

            <div class="bar-label">
                <span>
                    Successful
                </span>

                <strong>
                    ${formatNumber(successful)}
                </strong>
            </div>

            <div class="bar-track">
                <div
                    class="bar-fill youtube-success"
                    style="
                        width:${
                            total
                                ? (
                                    successful /
                                    total *
                                    100
                                ).toFixed(1)
                                : 0
                        }%
                    "
                ></div>
            </div>

        </div>


        <div class="bar-row">

            <div class="bar-label">
                <span>
                    Failed
                </span>

                <strong>
                    ${formatNumber(failed)}
                </strong>
            </div>

            <div class="bar-track">
                <div
                    class="bar-fill youtube-failed"
                    style="
                        width:${
                            total
                                ? (
                                    failed /
                                    total *
                                    100
                                ).toFixed(1)
                                : 0
                        }%
                    "
                ></div>
            </div>

        </div>


        <div class="bar-row">

            <div class="bar-label">
                <span>
                    Success Rate
                </span>

                <strong>
                    ${formatPercent(rate)}
                </strong>
            </div>

            <div class="bar-track">
                <div
                    class="bar-fill youtube-rate"
                    style="
                        width:${rate.toFixed(1)}%
                    "
                ></div>
            </div>

        </div>
    `;
}


/* =========================================================
   CURRENT MODE
   ========================================================= */

function renderCurrentMode() {
    if (!state.data) return;

    switch (state.activeView) {
        case "overview":
            renderOverview();

            renderEngines(
                state.data?.engines || []
            );

            renderYoutubePerformance(
                state.data?.youtube || null
            );

            break;

        case "runs":
        case "automation-runs":
            renderRunsView();
            break;

        case "logs":
        case "live-logs":
            renderLogsView();
            break;

        case "engines":
        case "search-engines":
            renderEnginesView();
            break;

        case "performance":
            renderPerformanceView();
            break;

        default:
            renderOverview();
            renderEngines(state.data?.engines || []);
            renderYoutubePerformance(
                state.data?.youtube || null
            );
            break;
    }
}


/* =========================================================
   RUNS VIEW
   ========================================================= */

function renderRunsView() {

    /*
     * Existing dashboard implementations may already have
     * specialized run-table functions.
     *
     * Prefer those functions if available.
     */

    if (
        typeof renderRuns ===
        "function"
    ) {
        renderRuns(
            state.runs || []
        );

        return;
    }

    if (
        typeof renderAutomationRuns ===
        "function"
    ) {
        renderAutomationRuns(
            state.runs || []
        );
    }
}


/* =========================================================
   LOGS VIEW
   ========================================================= */

function renderLogsView() {
    populateLogRunSelect();

    renderLogs(
        state.liveLogs || []
    );
}


/* =========================================================
   ENGINES VIEW
   ========================================================= */

function renderEnginesView() {
    const canvas = $("engineChart");

    if (!canvas) {
        return;
    }

    const panel =
        canvas.closest(".panel") ||
        canvas.parentElement?.closest(".panel");

    if (panel) {
        panel.hidden = false;
    }

    canvas.style.display = "";

    renderSearchEnginesPage(
        state.data?.engines || []
    );
}

function renderSearchEnginesPage(engines = []) {

    const canvas = $("engineChart");

    if (
        !canvas ||
        typeof Chart === "undefined"
    ) {
        return;
    }

    /*
     * Search Engines page should show
     * actual search-engine performance.
     *
     * YouTube is NOT a search engine.
     */
    const filteredEngines =
        (Array.isArray(engines) ? engines : [])
            .filter(engine => {

                const name =
                    String(
                        engine.engine ??
                        engine.search_engine ??
                        engine.name ??
                        ""
                    )
                        .trim()
                        .toUpperCase();

                return name !== "YOUTUBE";
            });

    destroyChart("enginePerformance");

    if (filteredEngines.length === 0) {
        return;
    }

    const labels =
        filteredEngines.map(
            engine =>
                engine.engine ??
                engine.search_engine ??
                engine.name ??
                "Unknown"
        );

    const total =
        filteredEngines.map(
            engine =>
                toNumber(
                    engine.total ??
                    engine.total_runs ??
                    engine.runs ??
                    engine.count ??
                    0
                )
        );

    const successful =
        filteredEngines.map(
            engine =>
                toNumber(
                    engine.success ??
                    engine.successful_runs ??
                    engine.successful ??
                    0
                )
        );

    const failed =
        filteredEngines.map(
            engine =>
                toNumber(
                    engine.failed ??
                    engine.failed_runs ??
                    0
                )
        );

    state.charts.enginePerformance =
        new Chart(
            canvas,
            {
                type: "bar",

                data: {
                    labels,

                    datasets: [
                        {
                            label: "Total Runs",
                            data: total,

                            backgroundColor:
                                "#5b8cff",

                            borderWidth: 0,

                            borderRadius: 6,

                            barPercentage: 0.7,

                            categoryPercentage: 0.7
                        },

                        {
                            label: "Successful",
                            data: successful,

                            backgroundColor:
                                "#35d39a",

                            borderWidth: 0,

                            borderRadius: 6,

                            barPercentage: 0.7,

                            categoryPercentage: 0.7
                        },

                        {
                            label: "Failed",
                            data: failed,

                            backgroundColor:
                                "#ff6577",

                            borderWidth: 0,

                            borderRadius: 6,

                            barPercentage: 0.7,

                            categoryPercentage: 0.7
                        }
                    ]
                },

                options: {
                    responsive: true,

                    maintainAspectRatio: false,

                    interaction: {
                        intersect: false,
                        mode: "index"
                    },

                    plugins: {
                        legend: {
                            display: true,
                            position: "top"
                        },

                        tooltip: {
                            enabled: true,

                            callbacks: {
                                label: context => {
                                    return ` ${
                                        context.dataset.label
                                    }: ${
                                        formatNumber(
                                            context.raw
                                        )
                                    } runs`;
                                }
                            }
                        }
                    },

                    scales: {
                        x: {
                            grid: {
                                display: false
                            },

                            ticks: {
                                color: "#8b98aa",
                                font: {
                                    size: 11
                                }
                            }
                        },

                        y: {
                            beginAtZero: true,

                            ticks: {
                                precision: 0,
                                color: "#707d91"
                            },

                            grid: {
                                color:
                                    "rgba(139,152,170,0.08)"
                            }
                        }
                    }
                }
            }
        );
}


/* =========================================================
   PERFORMANCE VIEW
   ========================================================= */

function renderPerformanceView() {

    const summary =
        state.data?.summary || {};

    if (
        typeof renderPerformance ===
        "function"
    ) {
        renderPerformance(
            state.data
        );

        return;
    }

    /*
     * Fallback values for standard performance fields.
     */

    setText(
        "performanceTotal",
        Number(
            summary.total_runs || 0
        )
    );

    setText(
        "performanceSuccess",
        Number(
            summary.successful_runs || 0
        )
    );

    setText(
        "performanceFailed",
        Number(
            summary.failed_runs || 0
        )
    );

    setText(
        "performanceRate",
        `${Number(
            summary.success_rate || 0
        ).toFixed(1)}%`
    );
}


/* =========================================================
   RECENT RUNS
   ========================================================= */

function renderRecentRuns(
    runs = []
) {

    const container =
        $("recentRuns");

    if (!container) {
        return;
    }

    if (
        !Array.isArray(runs) ||
        runs.length === 0
    ) {

        container.innerHTML = `
            <div class="empty-state">
                No recent runs available.
            </div>
        `;

        return;
    }

    container.innerHTML =
        runs.map(
            run => {

                const status =
                    String(
                        run.status ||
                        "UNKNOWN"
                    ).toUpperCase();

                const keyword =
                    run.keyword ||
                    run.search_keyword ||
                    run.title ||
                    "—";

                const started =
                    run.started_at ||
                    run.created_at ||
                    "";

                return `
                    <div class="recent-run-row">

                        <div class="recent-run-main">

                            <div class="recent-run-keyword">
                                ${escapeHtml(
                                    keyword
                                )}
                            </div>

                            <div class="recent-run-time">
                                ${escapeHtml(
                                    formatDateTime(
                                        started
                                    )
                                )}
                            </div>

                        </div>

                        <div class="recent-run-status status-${status.toLowerCase()}">
                            ${escapeHtml(
                                status
                            )}
                        </div>

                    </div>
                `;
            }
        )
        .join("");
}


/* =========================================================
   DATE FORMATTER
   ========================================================= */

function formatDateTime(
    value
) {

    if (!value) {
        return "—";
    }

    const date =
        new Date(value);

    if (
        Number.isNaN(
            date.getTime()
        )
    ) {
        return String(value);
    }

    return date.toLocaleString(
        "en-IN",
        {
            dateStyle: "medium",
            timeStyle: "short"
        }
    );
}


/* =========================================================
   RANGE CHANGE
   ========================================================= */

function setupRange() {

    const range =
        $("range");

    if (!range) {
        return;
    }

    if (
        range.dataset.rangeBound ===
        "true"
    ) {
        return;
    }

    range.dataset.rangeBound =
        "true";

    range.addEventListener(
        "change",
        async () => {

            await loadSelectedAutomation();

            if (
                state.activeView ===
                "overview"
            ) {
                renderOverview();
            }
        }
    );
}


/* =========================================================
   REFRESH BUTTON
   ========================================================= */

function setupRefresh() {

    const selectors = [
        "#refresh",
        "#refreshBtn",
        "[data-refresh]"
    ];

    let button = null;

    for (
        const selector of selectors
    ) {
        button =
            document.querySelector(
                selector
            );

        if (button) {
            break;
        }
    }

    if (!button) {
        return;
    }

    if (
        button.dataset.refreshBound ===
        "true"
    ) {
        return;
    }

    button.dataset.refreshBound =
        "true";

    button.addEventListener(
        "click",
        async () => {

            button.disabled =
                true;

            try {
                await loadSelectedAutomation();
            }
            finally {
                button.disabled =
                    false;
            }
        }
    );
}


/* =========================================================
   INITIALIZATION
   ========================================================= */

/* Legacy startup intentionally disabled. FINAL STARTUP below is the only startup. */
async function initializeDashboard() {
    return;
}

// =========================================================
// DASHBOARD.JS — PART 2/3
// =========================================================


/* =========================================================
   NUMBER HELPERS
   ========================================================= */

function toNumber(
    value,
    fallback = 0
) {

    const number =
        Number(value);

    return Number.isFinite(number)
        ? number
        : fallback;
}


function formatNumber(
    value
) {

    return toNumber(
        value
    ).toLocaleString(
        "en-IN"
    );
}


function formatPercent(
    value
) {

    return `${toNumber(
        value
    ).toFixed(1)}%`;
}


/* =========================================================
   STATUS HELPERS
   ========================================================= */

function normalizeStatus(
    status
) {

    return String(
        status || "UNKNOWN"
    )
        .trim()
        .toUpperCase();
}


function statusClass(
    status
) {

    return normalizeStatus(
        status
    )
        .toLowerCase()
        .replace(
            /[^a-z0-9_-]/g,
            "-"
        );
}


function statusLabel(
    status
) {

    const normalized =
        normalizeStatus(
            status
        );

    switch (
        normalized
    ) {

        case "SUCCESS":
        case "COMPLETED":
        case "SUCCESSFUL":
            return "Success";

        case "FAILED":
        case "FAILURE":
            return "Failed";

        case "RUNNING":
            return "Running";

        case "INTERRUPTED":
            return "Interrupted";

        case "PENDING":
            return "Pending";

        default:
            return normalized
                .toLowerCase()
                .replace(
                    /\b\w/g,
                    char =>
                        char.toUpperCase()
                );
    }
}


/* =========================================================
   RUN FIELD HELPERS
   ========================================================= */

function getRunId(
    run
) {

    return (
        run.run_id ??
        run.id ??
        run.automation_run_id ??
        "—"
    );
}

/* =========================================================
   LIVE LOGS — RUN SELECTION
   ========================================================= */

function populateLogRunSelect() {
    const select = $("runSelect");

    if (!select) {
        return;
    }

    const runs =
        Array.isArray(state.runs)
            ? state.runs
            : [];

    const currentValue =
        state.selectedLogRunId || "";

    select.innerHTML = `
        <option value="">
            Select a recent run...
        </option>
    `;

    runs.forEach(run => {
        const runId =
            getRunId(run);

        if (
            !runId ||
            runId === "—"
        ) {
            return;
        }

        const keyword =
            run.original_keyword ??
            run.search_keyword ??
            run.keyword ??
            "—";

        const status =
            String(
                run.status ??
                "UNKNOWN"
            ).toUpperCase();

        const started =
            run.started_at
                ? formatDateTime(
                    run.started_at
                )
                : "—";

        const option =
            document.createElement(
                "option"
            );

        option.value =
            String(runId);

        option.textContent =
            `${keyword} · ${status} · ${started}`;

        select.appendChild(option);
    });

    if (
        currentValue &&
        runs.some(
            run =>
                String(
                    getRunId(run)
                ) ===
                String(currentValue)
        )
    ) {
        select.value =
            currentValue;
    } else {
        select.value = "";

        state.selectedLogRunId =
            "";
    }
}


/* =========================================================
   LIVE LOGS — API
   ========================================================= */

async function loadRunLogs(runId) {
    if (!runId) {
        state.selectedLogRunId = "";
        state.liveLogs = [];

        renderLogs([]);

        return;
    }

    state.selectedLogRunId =
        String(runId);

    state.logsLoading = true;

    const container =
        $("logTimeline");

    if (container) {
        container.classList.remove(
            "empty"
        );

        container.innerHTML = `
            <div class="empty-state">
                Loading logs...
            </div>
        `;
    }

    try {
        const response =
            await fetch(
                `/api/logs/${encodeURIComponent(
                    runId
                )}`,
                {
                    cache: "no-store"
                }
            );

        if (!response.ok) {
            throw new Error(
                `Logs API failed: ${response.status}`
            );
        }

        const logs =
            await response.json();

        if (
            state.selectedLogRunId !==
            String(runId)
        ) {
            return;
        }

        state.liveLogs =
            Array.isArray(logs)
                ? logs
                : [];

        renderLogs(
            state.liveLogs
        );

    } catch (error) {
        console.error(
            "[DASHBOARD] Failed to load run logs:",
            error
        );

        if (
            state.selectedLogRunId !==
            String(runId)
        ) {
            return;
        }

        state.liveLogs = [];

        if (container) {
            container.classList.add(
                "empty"
            );

            container.innerHTML = `
                <div class="empty-state">
                    Unable to load logs for this run.
                </div>
            `;
        }

    } finally {
        state.logsLoading = false;
    }
}

function selectAndLoadLatestLogRun() {
    const select = $("runSelect");

    const runs =
        Array.isArray(state.runs)
            ? state.runs
            : [];

    if (!select || runs.length === 0) {
        state.selectedLogRunId = "";
        state.liveLogs = [];
        renderLogs([]);
        return;
    }

    /*
     * Prefer an actively RUNNING run.
     * Otherwise use the newest run.
     */
    const activeRun =
        runs.find(
            run =>
                normalizeStatus(run.status) === "RUNNING"
        ) || runs[0];

    const runId =
        getRunId(activeRun);

    if (!runId || runId === "—") {
        state.selectedLogRunId = "";
        state.liveLogs = [];
        renderLogs([]);
        return;
    }

    state.selectedLogRunId =
        String(runId);

    populateLogRunSelect();

    select.value =
        String(runId);

    loadRunLogs(runId);
}


/* =========================================================
   LIVE LOGS — UI EVENTS
   ========================================================= */

function initializeLiveLogs() {
    const select =
        $("runSelect");

    const button =
        $("loadLogs");

    if (!select || !button) {
        console.warn(
            "[DASHBOARD] Live Logs controls not found."
        );

        return;
    }

    if (
        select.dataset.liveLogsBound ===
        "true"
    ) {
        return;
    }

    select.dataset.liveLogsBound =
        "true";

    button.dataset.liveLogsBound =
        "true";

    select.addEventListener(
        "change",
        () => {
            state.selectedLogRunId =
                select.value;

            state.liveLogs = [];

            renderLogs([]);
        }
    );

    button.addEventListener(
        "click",
        async event => {
            event.preventDefault();

            const runId =
                select.value;

            if (!runId) {
                state.selectedLogRunId =
                    "";

                state.liveLogs = [];

                renderLogs([]);

                return;
            }

            await loadRunLogs(
                runId
            );
        }
    );
}


function getRunKeyword(
    run
) {

    return (
        run.keyword ??
        run.search_keyword ??
        run.query ??
        run.title ??
        run.video_title ??
        "—"
    );
}


function getRunStatus(
    run
) {

    return normalizeStatus(
        run.status ??
        run.run_status ??
        "UNKNOWN"
    );
}


function getRunAutomation(
    run
) {

    return String(
        run.automation_type ??
        run.automation ??
        state.automation
    ).toUpperCase();
}


function getRunStartedAt(
    run
) {

    return (
        run.started_at ??
        run.start_time ??
        run.created_at ??
        run.timestamp ??
        null
    );
}


function getRunFinishedAt(
    run
) {

    return (
        run.finished_at ??
        run.completed_at ??
        run.end_time ??
        run.updated_at ??
        null
    );
}


/* =========================================================
   RUN TABLE
   ========================================================= */

function renderRuns(
    runs = state.runs || []
) {
    const containers = [
        $("runsTable"),
        $("runsTableBody"),
        $("automationRunsBody"),
        $("runsBody")
    ];

    const tbody =
        containers.find(
            element => Boolean(element)
        );

    if (!tbody) {
        return;
    }

    if (
        !Array.isArray(runs) ||
        runs.length === 0
    ) {
        tbody.innerHTML = `
            <tr>
                <td
                    colspan="9"
                    class="empty-state"
                >
                    No ${escapeHtml(
                        getAutomationName()
                    )} automation runs found.
                </td>
            </tr>
        `;

        return;
    }

    tbody.innerHTML =
        runs
            .map(
                run => {

                    /*
                     * -----------------------------------------
                     * STATUS
                     * -----------------------------------------
                     */
                    const status =
                        getRunStatus(run);


                    /*
                     * -----------------------------------------
                     * AUTOMATION TYPE
                     * SEARCH  -> Website
                     * YOUTUBE -> YouTube
                     * -----------------------------------------
                     */
                    const automation =
                        getRunAutomation(run);

                    const typeLabel =
                        automation === "SEARCH"
                            ? "Website"
                            : automation === "YOUTUBE"
                                ? "YouTube"
                                : "—";


                    /*
                     * -----------------------------------------
                     * KEYWORD
                     *
                     * original_keyword = actual user keyword
                     * search_keyword   = processed/search keyword
                     *
                     * Table should show original keyword.
                     * -----------------------------------------
                     */
                    const keyword =
                        run.original_keyword ??
                        run.keyword ??
                        run.search_keyword ??
                        "—";


                    /*
                     * -----------------------------------------
                     * TARGET
                     * -----------------------------------------
                     */
                    const target =
                        run.target ??
                        "—";


                    /*
                     * -----------------------------------------
                     * ENGINE
                     *
                     * search_engine belongs to SEARCH runs.
                     * -----------------------------------------
                     */
                    const engine =
                        run.search_engine ??
                        "—";


                    /*
                     * -----------------------------------------
                     * BROWSER
                     * -----------------------------------------
                     */
                    const browser =
                        run.browser_mode ??
                        run.browser ??
                        "—";


                    /*
                     * -----------------------------------------
                     * STARTED
                     * -----------------------------------------
                     */
                    const started =
                        getRunStartedAt(run);


                    /*
                     * -----------------------------------------
                     * DURATION
                     *
                     * Prefer backend-calculated duration_seconds.
                     * Fallback to start/finish calculation for
                     * compatibility with older API data.
                     * -----------------------------------------
                     */
                    const duration =
                        run.duration_seconds !== undefined &&
                        run.duration_seconds !== null
                            ? formatDurationSeconds(
                                run.duration_seconds
                            )
                            : getDuration(
                                started,
                                getRunFinishedAt(run)
                            );


                    /*
                     * -----------------------------------------
                     * RETRIES
                     * -----------------------------------------
                     */
                    const retries =
                        run.retry_count ??
                        run.retries ??
                        0;


                    return `
                        <tr>

                            <!-- STATUS -->
                            <td>
                                <span
                                    class="status-badge status-${statusClass(
                                        status
                                    )}"
                                >
                                    ${escapeHtml(
                                        statusLabel(status)
                                    )}
                                </span>
                            </td>


                            <!-- TYPE -->
                            <td>
                                ${escapeHtml(
                                    typeLabel
                                )}
                            </td>


                            <!-- KEYWORD -->
                            <td>
                                ${escapeHtml(
                                    keyword
                                )}
                            </td>


                            <!-- TARGET -->
                            <td>
                                ${escapeHtml(
                                    target
                                )}
                            </td>


                            <!-- ENGINE -->
                            <td>
                                ${escapeHtml(
                                    engine
                                )}
                            </td>


                            <!-- BROWSER -->
                            <td>
                                ${escapeHtml(
                                    browser
                                )}
                            </td>


                            <!-- STARTED -->
                            <td>
                                ${escapeHtml(
                                    formatDateTime(
                                        started
                                    )
                                )}
                            </td>


                            <!-- DURATION -->
                            <td>
                                ${escapeHtml(
                                    duration
                                )}
                            </td>


                            <!-- RETRIES -->
                            <td>
                                ${escapeHtml(
                                    formatNumber(
                                        retries
                                    )
                                )}
                            </td>

                        </tr>
                    `;
                }
            )
            .join("");
}


/* =========================================================
   RUN DETAILS
   ========================================================= */

function attachRunDetailsEvents() {

    document
        .querySelectorAll(
            ".run-details-btn"
        )
        .forEach(button => {

            if (
                button.dataset.bound ===
                "true"
            ) {
                return;
            }

            button.dataset.bound =
                "true";

            button.addEventListener(
                "click",
                () => {

                    const id =
                        button.dataset.runId;

                    showRunDetails(
                        id
                    );
                }
            );
        });
}


function showRunDetails(
    runId
) {

    const run =
        (state.runs || [])
            .find(
                item =>
                    String(
                        getRunId(item)
                    ) === String(runId)
            );

    if (!run) {
        return;
    }

    /*
     * Use an existing modal if the page provides one.
     */
    const modal =
        $("runDetailsModal");

    if (!modal) {

        console.log(
            "[DASHBOARD] Run details:",
            run
        );

        return;
    }

    const content =
        modal.querySelector(
            ".modal-content"
        ) ||
        modal.querySelector(
            "[data-modal-content]"
        );

    if (content) {

        content.innerHTML = `
            <div class="run-detail-grid">

                <div>
                    <strong>Run ID</strong>
                    <span>
                        ${escapeHtml(
                            getRunId(run)
                        )}
                    </span>
                </div>

                <div>
                    <strong>Automation</strong>
                    <span>
                        ${escapeHtml(
                            getAutomationName(
                                getRunAutomation(
                                    run
                                )
                            )
                        )}
                    </span>
                </div>

                <div>
                    <strong>Status</strong>
                    <span>
                        ${escapeHtml(
                            statusLabel(
                                getRunStatus(
                                    run
                                )
                            )
                        )}
                    </span>
                </div>

                <div>
                    <strong>Keyword</strong>
                    <span>
                        ${escapeHtml(
                            getRunKeyword(
                                run
                            )
                        )}
                    </span>
                </div>

                <div>
                    <strong>Started</strong>
                    <span>
                        ${escapeHtml(
                            formatDateTime(
                                getRunStartedAt(
                                    run
                                )
                            )
                        )}
                    </span>
                </div>

                <div>
                    <strong>Finished</strong>
                    <span>
                        ${escapeHtml(
                            formatDateTime(
                                getRunFinishedAt(
                                    run
                                )
                            )
                        )}
                    </span>
                </div>

            </div>
        `;
    }

    modal.classList.add(
        "active"
    );

    modal.hidden =
        false;
}


/* =========================================================
   DURATION
   ========================================================= */

function getDuration(
    start,
    end
) {

    if (!start) {
        return "—";
    }

    const startDate =
        new Date(start);

    if (
        Number.isNaN(
            startDate.getTime()
        )
    ) {
        return "—";
    }

    const endDate =
        end
            ? new Date(end)
            : new Date();

    if (
        Number.isNaN(
            endDate.getTime()
        )
    ) {
        return "—";
    }

    const milliseconds =
        Math.max(
            0,
            endDate.getTime() -
            startDate.getTime()
        );

    const seconds =
        Math.floor(
            milliseconds /
            1000
        );

    const hours =
        Math.floor(
            seconds /
            3600
        );

    const minutes =
        Math.floor(
            (seconds % 3600) /
            60
        );

    const remainingSeconds =
        seconds % 60;

    if (hours > 0) {

        return `${hours}h ${minutes}m`;
    }

    if (minutes > 0) {

        return `${minutes}m ${remainingSeconds}s`;
    }

    return `${remainingSeconds}s`;
}


/* =========================================================
   LIVE LOGS
   ========================================================= */

function renderLogs(logs = []) {
    const container = $("logTimeline");

    if (!container) {
        return;
    }

    container.classList.remove("empty");

    if (
        !Array.isArray(logs) ||
        logs.length === 0
    ) {
        container.classList.add("empty");

        if (state.selectedLogRunId) {
            container.innerHTML = `
                <div class="empty-state">
                    No logs found for the selected run.
                </div>
            `;
        } else {
            container.innerHTML = `
                <div class="empty-state">
                    Choose a run to inspect its logs.
                </div>
            `;
        }

        return;
    }

    container.innerHTML =
        logs
            .map(log => {
                const timestamp =
                    log.timestamp ?? "";

                const level =
                    String(
                        log.level ?? "INFO"
                    ).toUpperCase();

                const message =
                    log.message ?? "";

                const action =
                    log.action ?? "";

                const eventStatus =
                    log.event_status ?? "";

                const keyword =
                    log.keyword ?? "";

                const searchEngine =
                    log.search_engine ?? "";

                const url =
                    log.url ?? "";

                const errorMessage =
                    log.error_message ?? "";

                return `
                    <div class="log-entry log-${escapeHtml(
                        level.toLowerCase()
                    )}">

                        <div class="log-time">
                            ${escapeHtml(
                                formatDateTime(
                                    timestamp
                                )
                            )}
                        </div>

                        <div class="log-level">
                            ${escapeHtml(level)}
                        </div>

                        <div class="log-message">
                            ${escapeHtml(message)}
                        </div>

                        ${
                            action
                                ? `
                                    <div class="log-meta">
                                        Action:
                                        ${escapeHtml(action)}
                                    </div>
                                `
                                : ""
                        }

                        ${
                            eventStatus
                                ? `
                                    <div class="log-meta">
                                        Status:
                                        ${escapeHtml(eventStatus)}
                                    </div>
                                `
                                : ""
                        }

                        ${
                            keyword
                                ? `
                                    <div class="log-meta">
                                        Keyword:
                                        ${escapeHtml(keyword)}
                                    </div>
                                `
                                : ""
                        }

                        ${
                            searchEngine
                                ? `
                                    <div class="log-meta">
                                        Engine:
                                        ${escapeHtml(
                                            searchEngine
                                        )}
                                    </div>
                                `
                                : ""
                        }

                        ${
                            url
                                ? `
                                    <div class="log-meta">
                                        URL:
                                        ${escapeHtml(url)}
                                    </div>
                                `
                                : ""
                        }

                        ${
                            errorMessage
                                ? `
                                    <div class="log-error">
                                        ${escapeHtml(
                                            errorMessage
                                        )}
                                    </div>
                                `
                                : ""
                        }

                    </div>
                `;
            })
            .join("");
}

/* =========================================================
   LIVE LOGS — RUN SELECTION
   ========================================================= */

function populateLogRunSelect() {
    const select = $("runSelect");

    if (!select) {
        return;
    }

    const runs =
        Array.isArray(state.runs)
            ? state.runs
            : [];

    const currentValue =
        state.selectedLogRunId || "";

    select.innerHTML = `
        <option value="">
            Select a recent run...
        </option>
    `;

    runs.forEach(run => {
        const runId =
            getRunId(run);

        if (
            !runId ||
            runId === "—"
        ) {
            return;
        }

        const keyword =
            run.original_keyword ??
            run.search_keyword ??
            run.keyword ??
            "—";

        const status =
            String(
                run.status ??
                "UNKNOWN"
            ).toUpperCase();

        const started =
            run.started_at
                ? formatDateTime(
                    run.started_at
                )
                : "—";

        const option =
            document.createElement(
                "option"
            );

        option.value =
            String(runId);

        option.textContent =
            `${keyword} · ${status} · ${started}`;

        select.appendChild(option);
    });

    if (
        currentValue &&
        runs.some(
            run =>
                String(getRunId(run)) ===
                String(currentValue)
        )
    ) {
        select.value =
            currentValue;
    } else {
        select.value = "";
        state.selectedLogRunId = "";
    }
}


/* =========================================================
   LIVE LOGS — API
   ========================================================= */

async function loadRunLogs(runId) {
    if (!runId) {
        state.selectedLogRunId = "";
        state.liveLogs = [];

        renderLogs([]);

        return;
    }

    state.selectedLogRunId =
        String(runId);

    state.logsLoading = true;

    const container =
        $("logTimeline");

    if (container) {
        container.classList.remove(
            "empty"
        );

        container.innerHTML = `
            <div class="empty-state">
                Loading logs...
            </div>
        `;
    }

    try {
        const response =
            await fetch(
                `/api/logs/${encodeURIComponent(runId)}`,
                {
                    cache: "no-store"
                }
            );

        if (!response.ok) {
            throw new Error(
                `Logs API failed: ${response.status}`
            );
        }

        const logs =
            await response.json();

        /*
         * Ignore the response if the user
         * selected another run while this
         * request was in progress.
         */
        if (
            state.selectedLogRunId !==
            String(runId)
        ) {
            return;
        }

        state.liveLogs =
            Array.isArray(logs)
                ? logs
                : [];

        renderLogs(
            state.liveLogs
        );

    } catch (error) {
        console.error(
            "[DASHBOARD] Failed to load run logs:",
            error
        );

        if (
            state.selectedLogRunId !==
            String(runId)
        ) {
            return;
        }

        state.liveLogs = [];

        if (container) {
            container.classList.add(
                "empty"
            );

            container.innerHTML = `
                <div class="empty-state">
                    Unable to load logs for this run.
                </div>
            `;
        }

    } finally {
        state.logsLoading = false;
    }
}


/* =========================================================
   LIVE LOGS — UI EVENTS
   ========================================================= */

function initializeLiveLogs() {
    const select =
        $("runSelect");

    const button =
        $("loadLogs");

    if (!select || !button) {
        console.warn(
            "[DASHBOARD] Live Logs controls not found."
        );

        return;
    }

    if (
        select.dataset.liveLogsBound ===
        "true"
    ) {
        return;
    }

    select.dataset.liveLogsBound =
        "true";

    button.dataset.liveLogsBound =
        "true";

    select.addEventListener(
        "change",
        () => {
            state.selectedLogRunId =
                select.value;

            state.liveLogs = [];

            renderLogs([]);
        }
    );

    button.addEventListener(
        "click",
        async event => {
            event.preventDefault();

            const runId =
                select.value;

            if (!runId) {
                state.selectedLogRunId =
                    "";

                state.liveLogs = [];

                renderLogs([]);

                return;
            }

            await loadRunLogs(
                runId
            );
        }
    );
}


/* =========================================================
   SEARCH ENGINES TABLE
   ========================================================= */

function renderSearchEngines(
    engines = []
) {

    const container =
        $("searchEnginesBody") ||
        $("enginesTableBody");

    if (!container) {
        return;
    }

    if (
        !Array.isArray(engines) ||
        engines.length === 0
    ) {

        container.innerHTML = `
            <tr>
                <td
                    colspan="6"
                    class="empty-state"
                >
                    No search-engine data available.
                </td>
            </tr>
        `;

        return;
    }

    container.innerHTML =
        engines
            .map(
                engine => {

                    const name =
                        engine.search_engine ??
                        engine.engine ??
                        engine.name ??
                        "Unknown";

                    const total =
                        toNumber(
                            engine.total_runs ??
                            engine.runs ??
                            engine.count
                        );

                    const successful =
                        toNumber(
                            engine.successful_runs ??
                            engine.success ??
                            engine.successful
                        );

                    const failed =
                        toNumber(
                            engine.failed_runs ??
                            engine.failed
                        );

                    const rate =
                        engine.success_rate !==
                        undefined
                            ? toNumber(
                                engine.success_rate
                            )
                            : total
                                ? (
                                    successful /
                                    total *
                                    100
                                )
                                : 0;

                    return `
                        <tr>

                            <td>
                                ${escapeHtml(
                                    name
                                )}
                            </td>

                            <td>
                                ${formatNumber(
                                    total
                                )}
                            </td>

                            <td>
                                ${formatNumber(
                                    successful
                                )}
                            </td>

                            <td>
                                ${formatNumber(
                                    failed
                                )}
                            </td>

                            <td>
                                ${formatPercent(
                                    rate
                                )}
                            </td>

                        </tr>
                    `;
                }
            )
            .join("");
}


function formatDurationSeconds(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value <= 0) return "—";
    const totalSeconds = Math.round(value);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const remainingSeconds = totalSeconds % 60;
    if (hours > 0) return `${hours}h ${minutes}m`;
    if (minutes > 0) return `${minutes}m ${remainingSeconds}s`;
    return `${remainingSeconds}s`;
}

/* =========================================================
   PERFORMANCE DATA
   ========================================================= */

function renderPerformance(data = state.data || {}) {
    const summary = data.summary || {};
    const total = toNumber(summary.total_runs);
    const success = toNumber(summary.successful_runs);
    const retries = toNumber(summary.total_retries);
    const rate = total > 0 ? (success / total) * 100 : 0;

    const recent = Array.isArray(data.recent) ? data.recent : [];
    let durationTotal = 0;
    let durationCount = 0;

    recent.forEach(run => {
        const started = getRunStartedAt(run);
        const finished = getRunFinishedAt(run);
        if (!started || !finished) return;
        const startDate = new Date(started);
        const endDate = new Date(finished);
        if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) return;
        durationTotal += Math.max(0, endDate.getTime() - startDate.getTime()) / 1000;
        durationCount += 1;
    });

    const averageDuration = durationCount ? durationTotal / durationCount : 0;
    const days = getSelectedDays();
    const runsPerDay = days > 0 ? total / days : total;
    const retryRate = total > 0 ? (retries / total) * 100 : 0;

    setText("avgDuration", averageDuration > 0 ? formatDurationSeconds(averageDuration) : "—");
    setText("retryRate", formatPercent(retryRate));
    setText("runsPerDay", runsPerDay.toFixed(1));
    setText("perfRate", formatPercent(rate));

    const insights = $("insights");
    if (insights) {
        insights.innerHTML = `
            <div class="insight-item">
                <strong>${formatNumber(total)}</strong>
                <span>Total ${escapeHtml(getAutomationName())} runs in the selected period.</span>
            </div>
            <div class="insight-item">
                <strong>${formatPercent(rate)}</strong>
                <span>Overall success rate for the selected automation.</span>
            </div>
            <div class="insight-item">
                <strong>${formatNumber(retries)}</strong>
                <span>Retry attempts recorded in the selected period.</span>
            </div>`;
    }
}


/* =========================================================
   PERFORMANCE CHART
   ========================================================= */

function renderPerformanceChart(
    daily = []
) {

    const canvas =
        $("performanceChart");

    if (!canvas) {
        return;
    }

    destroyChart(
        "performance"
    );

    if (
        typeof Chart ===
        "undefined"
    ) {
        return;
    }

    const labels =
        daily.map(
            item =>
                item.date ||
                item.day ||
                item.label ||
                ""
        );

    const successRates =
        daily.map(
            item => {

                const supplied =
                    item.success_rate;

                if (
                    supplied !==
                    undefined &&
                    supplied !== null
                ) {
                    return toNumber(
                        supplied
                    );
                }

                const total =
                    toNumber(
                        item.total_runs ??
                        item.total
                    );

                const success =
                    toNumber(
                        item.successful_runs ??
                        item.success
                    );

                return total
                    ? success /
                        total *
                        100
                    : 0;
            }
        );

    state.charts.performance =
        new Chart(
            canvas,
            {
                type: "line",

                data: {
                    labels,

                    datasets: [
                        {
                            label:
                                "Success Rate",

                            data:
                                successRates,

                            tension:
                                0.35,

                            fill:
                                false
                        }
                    ]
                },

                options: {
                    responsive: true,
                    maintainAspectRatio: false,

                    scales: {
                        y: {
                            beginAtZero: true,
                            max: 100,

                            ticks: {
                                callback:
                                    value =>
                                        `${value}%`
                            }
                        }
                    }
                }
            }
        );
}


/* =========================================================
   KPI ANIMATION
   ========================================================= */

function animateNumber(
    element,
    target,
    duration = 500
) {

    if (!element) {
        return;
    }

    const finalValue =
        toNumber(
            target
        );

    const start =
        performance.now();

    function update(
        now
    ) {

        const progress =
            Math.min(
                1,
                (
                    now -
                    start
                ) /
                duration
            );

        const eased =
            1 -
            Math.pow(
                1 - progress,
                3
            );

        const value =
            Math.round(
                finalValue *
                eased
            );

        element.textContent =
            value.toLocaleString(
                "en-IN"
            );

        if (
            progress <
            1
        ) {
            requestAnimationFrame(
                update
            );
        }
    }

    requestAnimationFrame(
        update
    );
}


function animateDashboardKPIs() {

    const summary =
        state.data?.summary;

    if (!summary) {
        return;
    }

    const mappings = [
        [
            "totalRuns",
            summary.total_runs
        ],

        [
            "successRuns",
            summary.successful_runs
        ],

        [
            "failedRuns",
            summary.failed_runs
        ],

        [
            "retries",
            summary.total_retries
        ],

        [
            "keywords",
            summary.unique_keywords
        ],

        [
            "runningRuns",
            summary.running_runs
        ],

        [
            "interruptedRuns",
            summary.interrupted_runs
        ]
    ];

    mappings.forEach(
        ([id, value]) => {

            const element =
                $(id);

            if (element) {

                animateNumber(
                    element,
                    value
                );
            }
        }
    );
}


/* =========================================================
   SEARCH ENGINE FILTER
   ========================================================= */

function setupEngineFilter() {

    const input =
        $("engineSearch") ||
        $("searchEngineFilter");

    if (!input) {
        return;
    }

    if (
        input.dataset.engineFilterBound ===
        "true"
    ) {
        return;
    }

    input.dataset.engineFilterBound =
        "true";

    input.addEventListener(
        "input",
        () => {

            const query =
                String(
                    input.value || ""
                )
                    .trim()
                    .toLowerCase();

            document
                .querySelectorAll(
                    "#searchEnginesBody tr, #enginesTableBody tr"
                )
                .forEach(row => {

                    const text =
                        String(
                            row.textContent ||
                            ""
                        )
                            .toLowerCase();

                    row.hidden =
                        query &&
                        !text.includes(
                            query
                        );
                });
        }
    );
}


/* =========================================================
   RUN SEARCH / FILTER
   ========================================================= */

function setupRunFilter() {

    const input =
        $("runSearch") ||
        $("runsSearch") ||
        $("searchRuns");

    if (!input) {
        return;
    }

    if (
        input.dataset.runFilterBound ===
        "true"
    ) {
        return;
    }

    input.dataset.runFilterBound =
        "true";

    input.addEventListener(
        "input",
        () => {

            const query =
                String(
                    input.value || ""
                )
                    .trim()
                    .toLowerCase();

            document
                .querySelectorAll(
                    "#runsTableBody tr, #automationRunsBody tr, #runsBody tr"
                )
                .forEach(row => {

                    const text =
                        String(
                            row.textContent ||
                            ""
                        )
                            .toLowerCase();

                    row.hidden =
                        query &&
                        !text.includes(
                            query
                        );
                });
        }
    );
}


/* =========================================================
   MODAL CLOSE
   ========================================================= */

function setupModal() {

    document
        .querySelectorAll(
            "[data-close-modal], .modal-close"
        )
        .forEach(button => {

            if (
                button.dataset.modalBound ===
                "true"
            ) {
                return;
            }

            button.dataset.modalBound =
                "true";

            button.addEventListener(
                "click",
                () => {

                    const modal =
                        button.closest(
                            ".modal"
                        );

                    if (!modal) {
                        return;
                    }

                    modal.classList.remove(
                        "active"
                    );

                    modal.hidden =
                        true;
                }
            );
        });


    document
        .querySelectorAll(
            ".modal"
        )
        .forEach(modal => {

            if (
                modal.dataset.modalBackgroundBound ===
                "true"
            ) {
                return;
            }

            modal.dataset.modalBackgroundBound =
                "true";

            modal.addEventListener(
                "click",
                event => {

                    if (
                        event.target ===
                        modal
                    ) {

                        modal.classList.remove(
                            "active"
                        );

                        modal.hidden =
                            true;
                    }
                }
            );
        });


    document.addEventListener(
        "keydown",
        event => {

            if (
                event.key !==
                "Escape"
            ) {
                return;
            }

            document
                .querySelectorAll(
                    ".modal.active"
                )
                .forEach(modal => {

                    modal.classList.remove(
                        "active"
                    );

                    modal.hidden =
                        true;
                });
        }
    );
}


/* =========================================================
   SIDEBAR MOBILE
   ========================================================= */

function setupMobileSidebar() {

    const menuButton =
        $("menuButton") ||
        $("sidebarToggle") ||
        document.querySelector(
            "[data-sidebar-toggle]"
        );

    const sidebar =
        $("sidebar");

    if (
        !menuButton ||
        !sidebar
    ) {
        return;
    }

    if (
        menuButton.dataset.mobileSidebarBound ===
        "true"
    ) {
        return;
    }

    menuButton.dataset.mobileSidebarBound =
        "true";

    menuButton.addEventListener(
        "click",
        () => {

            sidebar.classList.toggle(
                "open"
            );
        }
    );


    document
        .querySelectorAll(
            ".nav-item"
        )
        .forEach(item => {

            item.addEventListener(
                "click",
                () => {

                    sidebar.classList.remove(
                        "open"
                    );
                }
            );
        });
}


/* =========================================================
   AUTOMATION CONTEXT INDICATORS
   ========================================================= */

function updateContextLabels() {

    const name =
        getAutomationName();

    const apiName =
        modeApiName();

    document
        .querySelectorAll(
            "[data-automation-context]"
        )
        .forEach(element => {

            element.textContent =
                name;
        });


    document
        .querySelectorAll(
            "[data-automation-api]"
        )
        .forEach(element => {

            element.textContent =
                apiName;
        });


    document
        .querySelectorAll(
            "[data-automation-badge]"
        )
        .forEach(element => {

            element.textContent =
                name;
        });
}


/* =========================================================
   UPDATE EVERYTHING
   ========================================================= */

function updateDashboardContext() {

    updateAutomationToggle();
    updateSidebar();
    updateHeader();
    updateContextLabels();
}


/* =========================================================
   AUTOMATION TOGGLE FALLBACK
   ========================================================= */

function createAutomationToggleIfMissing() {

    /*
     * We do not force-create a new toggle if index.html
     * already contains one.
     *
     * This function only supports pages where the toggle
     * container exists but the buttons are missing.
     */

    const container =
        document.querySelector(
            "[data-automation-toggle]"
        );

    if (!container) {
        return;
    }

    const existingButtons =
        container.querySelectorAll(
            ".automation-switch-btn"
        );

    if (
        existingButtons.length > 0
    ) {
        return;
    }

    container.innerHTML = `
        <button
            type="button"
            class="automation-switch-btn"
            data-automation="SEARCH"
            data-mode="SEARCH"
            aria-selected="false"
        >
            Website
        </button>

        <button
            type="button"
            class="automation-switch-btn"
            data-automation="YOUTUBE"
            data-mode="YOUTUBE"
            aria-selected="false"
        >
            YouTube
        </button>
    `;
}


/* =========================================================
   DATA VALIDATION
   ========================================================= */

function validateDashboardData(
    data
) {

    if (
        !data ||
        typeof data !==
        "object"
    ) {
        return false;
    }

    if (
        !data.summary ||
        typeof data.summary !==
        "object"
    ) {
        data.summary = {};
    }

    if (
        !Array.isArray(
            data.daily
        )
    ) {
        data.daily = [];
    }

    if (
        !Array.isArray(
            data.engines
        )
    ) {
        data.engines = [];
    }

    if (
        !Array.isArray(
            data.recent
        )
    ) {
        data.recent = [];
    }

    return true;
}


/* =========================================================
   NORMALIZE DASHBOARD DATA
   ========================================================= */

function normalizeDashboardData(
    data
) {

    if (
        !validateDashboardData(
            data
        )
    ) {
        return emptyDashboardData(
            modeApiName()
        );
    }

    const summary =
        data.summary;

    summary.total_runs =
        toNumber(
            summary.total_runs
        );

    summary.successful_runs =
        toNumber(
            summary.successful_runs
        );

    summary.failed_runs =
        toNumber(
            summary.failed_runs
        );

    summary.running_runs =
        toNumber(
            summary.running_runs
        );

    summary.interrupted_runs =
        toNumber(
            summary.interrupted_runs
        );

    summary.total_retries =
        toNumber(
            summary.total_retries
        );

    summary.unique_keywords =
        toNumber(
            summary.unique_keywords
        );

    if (
        summary.success_rate ===
        undefined ||
        summary.success_rate ===
        null
    ) {

        summary.success_rate =
            summary.total_runs
                ? (
                    summary.successful_runs /
                    summary.total_runs *
                    100
                )
                : 0;
    }
    else {

        summary.success_rate =
            toNumber(
                summary.success_rate
            );
    }

    return data;
}


/* =========================================================
   PATCH SELECTED DATA
   ========================================================= */

function setSelectedData(
    data
) {

    const normalized =
        normalizeDashboardData(
            data
        );

    /*
     * Force the automation context to match the current
     * toggle. This prevents stale Website/YouTube data from
     * being rendered after a toggle click.
     */
    normalized.automation =
        modeApiName();

    state.data =
        normalized;

    state.overview =
        normalized;

    state.runs =
        normalized.recent || [];
}


/* =========================================================
   SAFE LOAD SELECTED AUTOMATION
   ========================================================= */

async function refreshSelectedAutomation() {

    const range =
        $("range");

    const days =
        range?.value || "7";

    const automation =
        modeApiName();

    try {

        const response =
            await fetchDashboard(
                days,
                automation
            );

        setSelectedData(
            response
        );

        updateDashboardContext();

        renderCurrentMode();

        animateDashboardKPIs();

        return response;

    }
    catch (error) {

        console.error(
            "[DASHBOARD] Refresh failed:",
            error
        );

        setSelectedData(
            emptyDashboardData(
                automation
            )
        );

        renderCurrentMode();

        return null;
    }
}


/* =========================================================
   LIVE DATA POLLING
   ========================================================= */

let liveRefreshTimer =
    null;


function stopLiveRefresh() {

    if (
        liveRefreshTimer
    ) {

        clearInterval(
            liveRefreshTimer
        );

        liveRefreshTimer =
            null;
    }
}


function startLiveRefresh(
    interval = 30000
) {
    stopLiveRefresh();

    liveRefreshTimer =
        setInterval(
            async () => {

                /*
                 * Refresh dashboard data.
                 */
                await refreshSelectedAutomation();

                /*
                 * If user is watching Live Logs,
                 * refresh the currently selected run's logs too.
                 */
                if (
                    state.activeView === "logs" ||
                    state.activeView === "live-logs"
                ) {

                    const runId =
                        state.selectedLogRunId;

                    if (runId) {
                        await loadRunLogs(
                            runId
                        );
                    }
                }

            },
            interval
        );
}


/* =========================================================
   AUTO REFRESH SETUP
   ========================================================= */

function setupAutoRefresh() {

    /*
     * 30-second refresh keeps dashboard current while
     * avoiding unnecessary API calls.
     */

    startLiveRefresh(
        30000
    );
}


/* =========================================================
   VISIBILITY HANDLING
   ========================================================= */

function setupVisibilityRefresh() {

    document.addEventListener(
        "visibilitychange",
        async () => {

            if (
                document.hidden
            ) {

                stopLiveRefresh();

                return;
            }

            await refreshSelectedAutomation();

            startLiveRefresh(
                30000
            );
        }
    );
}


/* =========================================================
   ERROR DISPLAY
   ========================================================= */

function showDashboardError(
    message
) {

    const candidates = [
        $("dashboardError"),
        $("errorMessage"),
        $("loadError")
    ];

    const element =
        candidates.find(
            item => Boolean(item)
        );

    if (!element) {
        return;
    }

    element.textContent =
        message || "Something went wrong.";

    element.hidden =
        false;
}


function clearDashboardError() {

    document
        .querySelectorAll(
            "#dashboardError, #errorMessage, #loadError"
        )
        .forEach(element => {

            element.hidden =
                true;

            element.textContent =
                "";
        });
}


/* =========================================================
   ENHANCED SET AUTOMATION
   ========================================================= */

const originalSetAutomation =
    setAutomation;


/*
 * Rebind through a wrapper only when the original function
 * is already defined. This keeps the main behaviour above
 * while ensuring all context-dependent UI is refreshed.
 */

async function switchAutomationContext(
    mode
) {

    const normalized =
        String(
            mode || ""
        ).toUpperCase() ===
        "SEARCH"
            ? "SEARCH"
            : "YOUTUBE";

    state.automation =
        normalized;

    state.activeView =
        "overview";

    clearDashboardError();

    updateDashboardContext();

    await loadSelectedAutomation();

    if (
        state.activeView ===
        "overview"
    ) {
        renderOverview();
    }

    window.scrollTo({
        top: 0,
        behavior: "smooth"
    });
}


/* =========================================================
   TOGGLE REBIND
   ========================================================= */

function rebindAutomationToggle() {

    document
        .querySelectorAll(
            ".automation-switch-btn"
        )
        .forEach(button => {

            /*
             * Remove the possibility of duplicate clicks
             * by cloning the button.
             */
            if (
                button.dataset.contextRebound ===
                "true"
            ) {
                return;
            }

            button.dataset.contextRebound =
                "true";

            button.addEventListener(
                "click",
                async event => {

                    event.preventDefault();
                    event.stopPropagation();

                    const mode =
                        button.dataset.automation ||
                        button.dataset.mode;

                    await switchAutomationContext(
                        mode
                    );
                }
            );
        });

    updateAutomationToggle();
}


/* =========================================================
   FINAL UI INITIALIZATION
   ========================================================= */

function initializeAdditionalUI() {

    createAutomationToggleIfMissing();

    updateDashboardContext();

    setupEngineFilter();

    setupRunFilter();

    setupModal();

    setupMobileSidebar();

    initializeLiveLogs();

    setupAutoRefresh();

    setupVisibilityRefresh();

    rebindAutomationToggle();
}


/* =========================================================
   SAFE BOOTSTRAP
   ========================================================= */

function bootDashboardEnhancements() {

    try {

        initializeAdditionalUI();

        console.log(
            "[DASHBOARD] Context-aware dashboard initialized.",
            {
                automation:
                    state.automation,

                view:
                    state.activeView
            }
        );

    }
    catch (error) {

        console.error(
            "[DASHBOARD] UI initialization error:",
            error
        );
    }
}

// =========================================================
// DASHBOARD.JS — PART 3/3
// Final initialization + compatibility helpers
// =========================================================


/* =========================================================
   LEGACY COMPATIBILITY
   ========================================================= */

function refreshDashboard() {

    clearDashboardError();

    return refreshSelectedAutomation();
}


function reloadDashboard() {

    clearDashboardError();

    return loadSelectedAutomation();
}


/* =========================================================
   AUTOMATION BUTTON STATE
   ========================================================= */

function setAutomationButtonState() {

    const current =
        modeApiName();

    document
        .querySelectorAll(
            ".automation-switch-btn"
        )
        .forEach(button => {

            const mode =
                String(
                    button.dataset.automation ||
                    button.dataset.mode ||
                    ""
                ).toUpperCase();

            const active =
                mode === current;

            button.classList.toggle(
                "active",
                active
            );

            button.classList.toggle(
                "selected",
                active
            );

            button.setAttribute(
                "aria-pressed",
                active
                    ? "true"
                    : "false"
            );
        });
}


/* =========================================================
   CONTEXT BADGES
   ========================================================= */

function renderAutomationContext() {

    const name =
        getAutomationName();

    const apiName =
        modeApiName();

    document
        .querySelectorAll(
            ".automation-context-name"
        )
        .forEach(element => {

            element.textContent =
                name;
        });

    document
        .querySelectorAll(
            ".automation-context-code"
        )
        .forEach(element => {

            element.textContent =
                apiName;
        });
}


/* =========================================================
   OVERVIEW EMPTY STATE
   ========================================================= */

function renderOverviewEmptyState() {

    const data =
        state.data;

    if (!data) {
        return;
    }

    const summary =
        data.summary || {};

    const total =
        toNumber(
            summary.total_runs
        );

    const empty =
        total === 0 &&
        (!data.recent ||
            data.recent.length === 0);

    document
        .querySelectorAll(
            "[data-dashboard-empty]"
        )
        .forEach(element => {

            element.hidden =
                !empty;
        });
}


/* =========================================================
   FINAL OVERVIEW RENDER
   ========================================================= */

function renderSelectedOverview() {

    if (
        state.activeView !==
        "overview"
    ) {
        return;
    }

    if (!state.data) {
        return;
    }

    /*
     * Critical rule:
     *
     * state.data contains ONE automation only.
     *
     * Therefore all Overview values come from one source.
     */
    renderOverview();

    renderEngines(
        state.data?.engines || []
    );

    renderYoutubePerformance(
        state.data?.youtube || null
    );

    renderOverviewEmptyState();

    animateDashboardKPIs();

    renderAutomationContext();

    updateEngineVisibility();

    setAutomationButtonState();
}


/* =========================================================
   PATCH RENDER CURRENT MODE
   ========================================================= */

function renderDashboardView() {

    updateDashboardContext();

    if (
        state.activeView ===
        "overview"
    ) {

        renderSelectedOverview();

        return;
    }

    renderCurrentMode();
}


/* =========================================================
   RANGE SELECTOR
   ========================================================= */

function getSelectedDays() {

    const range =
        $("range");

    if (!range) {
        return 7;
    }

    const value =
        parseInt(
            range.value,
            10
        );

    if (
        !Number.isFinite(
            value
        ) ||
        value <= 0
    ) {
        return 7;
    }

    return value;
}


/* =========================================================
   MANUAL DATA LOAD
   ========================================================= */

async function loadAutomationData(automation = state.automation) {
    const requestedAutomation = String(automation || "").toUpperCase() === "SEARCH" ? "SEARCH" : "YOUTUBE";
    state.automation = requestedAutomation;
    const days = getSelectedDays();
    const apiAutomation = requestedAutomation;
    clearDashboardError();
    updateDashboardContext();

    state.loadSequence = (state.loadSequence || 0) + 1;
    const sequence = state.loadSequence;

    try {
        const data = await fetchDashboard(days, apiAutomation);
        if (sequence !== state.loadSequence || state.automation !== requestedAutomation) {
            console.warn("[DASHBOARD] Ignoring stale response:", requestedAutomation);
            return null;
        }
        setSelectedData(data);
        renderDashboardView();
        return data;
    } catch (error) {
        if (sequence !== state.loadSequence || state.automation !== requestedAutomation) return null;
        console.error("[DASHBOARD] Unable to load automation:", apiAutomation, error);
        showDashboardError(`Unable to load ${getAutomationName()} automation data.`);
        setSelectedData(emptyDashboardData(apiAutomation));
        renderDashboardView();
        return null;
    }
}


/* =========================================================
   TOP TOGGLE INITIALIZATION
   ========================================================= */

function initializeAutomationToggle() {

    const buttons =
        document.querySelectorAll(
            ".automation-switch-btn"
        );

    if (
        !buttons.length
    ) {
        return;
    }

    buttons.forEach(
        button => {

            button.removeAttribute(
                "aria-current"
            );

            button.setAttribute(
                "role",
                "tab"
            );
        }
    );

    setAutomationButtonState();
}


/* =========================================================
   COMMON NAVIGATION INITIALIZATION
   ========================================================= */

function initializeNavigation() {

    /*
     * Overview
     */
    document
        .querySelectorAll(
            '[data-view="overview"], [data-view-target="overview"]'
        )
        .forEach(button => {

            if (
                button.dataset.commonNavBound ===
                "true"
            ) {
                return;
            }

            button.dataset.commonNavBound =
                "true";

            button.addEventListener(
                "click",
                async event => {

                    event.preventDefault();

                    showView(
                        "overview"
                    );

                    updateDashboardContext();

                    renderOverview();

                    window.scrollTo({
                        top: 0,
                        behavior: "smooth"
                    });
                }
            );
        });
}


/* =========================================================
   RANGE + REFRESH EVENTS
   ========================================================= */

function initializeDataControls() {

    const range =
        $("range");

    if (range) {

        range.addEventListener(
            "change",
            async () => {

                await loadAutomationData(
                    state.automation
                );
            }
        );
    }


    const refreshButtons =
        document.querySelectorAll(
            "#refresh, #refreshBtn, [data-refresh]"
        );

    refreshButtons.forEach(
        button => {

            if (
                button.dataset.finalRefreshBound ===
                "true"
            ) {
                return;
            }

            button.dataset.finalRefreshBound =
                "true";

            button.addEventListener(
                "click",
                async event => {

                    event.preventDefault();

                    const oldText =
                        button.textContent;

                    button.disabled =
                        true;

                    button.classList.add(
                        "loading"
                    );

                    try {

                        await loadAutomationData(
                            state.automation
                        );

                    }
                    finally {

                        button.disabled =
                            false;

                        button.classList.remove(
                            "loading"
                        );

                        if (
                            oldText
                        ) {
                            button.textContent =
                                oldText;
                        }
                    }
                }
            );
        }
    );
}


/* =========================================================
   SELECTED AUTOMATION STORAGE
   ========================================================= */

function rememberAutomation() {

    try {

        sessionStorage.setItem(
            "dashboardAutomation",
            state.automation
        );

    }
    catch (error) {

        /*
         * Session storage may be unavailable in some
         * browser/privacy configurations.
         */
        console.warn(
            "[DASHBOARD] Could not save automation context."
        );
    }
}


function restoreAutomation() {

    try {

        const saved =
            sessionStorage.getItem(
                "dashboardAutomation"
            );

        if (
            saved === "SEARCH" ||
            saved === "YOUTUBE"
        ) {

            state.automation =
                saved;
        }

    }
    catch (error) {

        /*
         * Keep default context.
         */
    }
}


/* =========================================================
   PATCH CONTEXT SWITCH
   ========================================================= */

async function changeAutomation(
    mode
) {
    const normalized =
        String(
            mode || ""
        ).toUpperCase() ===
        "SEARCH"
            ? "SEARCH"
            : "YOUTUBE";

    /*
     * Remember whether the user is currently
     * watching Live Logs.
     */
    const wasViewingLogs =
        state.activeView === "logs" ||
        state.activeView === "live-logs";

    /*
     * Ignore clicks on the already selected context.
     */
    if (
        state.automation === normalized &&
        state.data
    ) {

        if (wasViewingLogs) {
            state.activeView = "logs";

            updateDashboardContext();

            renderLogsView();

            if (
                !state.selectedLogRunId
            ) {
                selectAndLoadLatestLogRun();
            }

        } else {

            state.activeView =
                "overview";

            updateDashboardContext();

            renderSelectedOverview();
        }

        return;
    }

    /*
     * Change automation context.
     */
    state.automation =
        normalized;

    /*
     * Clear the old automation's selected logs.
     */
    state.selectedLogRunId =
        "";

    state.liveLogs =
        [];

    /*
     * IMPORTANT:
     * If user was already on Live Logs,
     * stay on Live Logs.
     *
     * Otherwise use the normal Overview.
     */
    state.activeView =
        wasViewingLogs
            ? "logs"
            : "overview";

    rememberAutomation();

    updateDashboardContext();

    /*
     * Load the newly selected automation.
     */
    await loadAutomationData(
        normalized
    );

    /*
     * If we switched while watching Live Logs,
     * automatically select the latest run and
     * load its logs.
     */
    if (wasViewingLogs) {

        state.activeView =
            "logs";

        updateDashboardContext();

        renderLogsView();

        selectAndLoadLatestLogRun();

    } else {

        renderSelectedOverview();
    }

    window.scrollTo({
        top: 0,
        behavior: "smooth"
    });
}


/* =========================================================
   FINAL TOGGLE EVENT BINDING
   ========================================================= */

function bindFinalAutomationToggle() {

    document
        .querySelectorAll(
            ".automation-switch-btn"
        )
        .forEach(button => {

            if (
                button.dataset.finalAutomationBound ===
                "true"
            ) {
                return;
            }

            button.dataset.finalAutomationBound =
                "true";

            button.addEventListener(
                "click",
                async event => {

                    event.preventDefault();

                    event.stopPropagation();

                    const mode =
                        button.dataset.automation ||
                        button.dataset.mode ||
                        "YOUTUBE";

                    await changeAutomation(
                        mode
                    );
                }
            );
        });

    setAutomationButtonState();
}


/* =========================================================
   PERIODIC CONTEXT VALIDATION
   ========================================================= */

function validateCurrentContext() {

    const expected =
        modeApiName();

    if (
        !state.data
    ) {
        return;
    }

    const dataAutomation =
        String(
            state.data.automation ||
            ""
        ).toUpperCase();

    /*
     * If backend returned an automation identifier,
     * make sure it matches the selected context.
     */
    if (
        dataAutomation &&
        dataAutomation !==
        expected
    ) {

        console.warn(
            "[DASHBOARD] Context mismatch detected.",
            {
                selected:
                    expected,

                received:
                    dataAutomation
            }
        );
    }
}


/* =========================================================
   DEBUG INFORMATION
   ========================================================= */

function dashboardDebugInfo() {

    return {
        automation:
            state.automation,

        apiAutomation:
            modeApiName(),

        activeView:
            state.activeView,

        summary:
            state.data?.summary ||
            {},

        recentRuns:
            Array.isArray(
                state.runs
            )
                ? state.runs.length
                : 0
    };
}


/* =========================================================
   GLOBAL DASHBOARD API
   ========================================================= */

window.dashboard =
    {

        getState() {
            return state;
        },

        getAutomation() {
            return state.automation;
        },

        setAutomation(
            mode
        ) {
            return changeAutomation(
                mode
            );
        },

        refresh() {
            return refreshSelectedAutomation();
        },

        load() {
            return loadAutomationData(
                state.automation
            );
        },

        debug() {
            return dashboardDebugInfo();
        }
    };


/* =========================================================
   FINAL STARTUP
   ========================================================= */

async function finalDashboardStartup() {

    /*
     * Do not override an already selected context.
     */
    restoreAutomation();

    state.activeView =
        "overview";

    /*
     * Prepare UI first.
     */
    createAutomationToggleIfMissing();

    initializeAutomationToggle();

    /* ONE navigation/toggle binding. nav() owns these listeners. */
    nav();

    initializeDataControls();

    initializeLiveLogs();

    updateDashboardContext();

    /*
    * Check database health independently
    * from dashboard data loading.
    */
    await health();

    /*
     * Load ONLY selected automation.
     */
    await loadAutomationData(
        state.automation
    );

    renderSelectedOverview();

    validateCurrentContext();

    console.log(
        "[DASHBOARD] Ready:",
        dashboardDebugInfo()
    );
}


/* =========================================================
   FINAL DOM READY
   ========================================================= */

function startFinalDashboard() {

    /*
     * Small delay allows index.html dynamic elements to
     * finish rendering before event binding.
     */
    setTimeout(
        () => {

            finalDashboardStartup()
                .catch(
                    error => {

                        console.error(
                            "[DASHBOARD] Startup failed:",
                            error
                        );

                        showDashboardError(
                            "Dashboard failed to initialize."
                        );
                    }
                );

        },
        0
    );
}


/*
 * IMPORTANT:
 *
 * The original initialization already runs from Part 1.
 * This final startup only runs once.
 */

if (
    !window.__SEO_DASHBOARD_FINAL_STARTED__
) {

    window.__SEO_DASHBOARD_FINAL_STARTED__ =
        true;

    if (
        document.readyState ===
        "loading"
    ) {

        document.addEventListener(
            "DOMContentLoaded",
            startFinalDashboard,
            {
                once: true
            }
        );

    }
    else {

        startFinalDashboard();

    }
}

/* =========================================================
   END OF DASHBOARD.JS
   ========================================================= */