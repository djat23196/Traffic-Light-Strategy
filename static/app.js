/* RG Candle Breakout — Frontend JS */

let currentPairTab = "1m";
let allPairs = {};
let allTradeLog = [];
let activeFilter = "all";
let lastPrice = 0;

// Request notification permission
if ("Notification" in window && Notification.permission === "default") {
    Notification.requestPermission();
}

function notify(title, body, color) {
    showToast(body, color);
    if ("Notification" in window && Notification.permission === "granted") {
        new Notification(title, { body, icon: "/static/favicon.ico" });
    }
    // Beep sound
    try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.frequency.value = color === "red" ? 300 : 800;
        gain.gain.value = 0.1;
        osc.start();
        osc.stop(ctx.currentTime + 0.15);
    } catch(e) {}
}

// ── SSE Connection ───────────────────────────────────────────────────────

const evtSource = new EventSource("/api/events");

evtSource.addEventListener("snapshot", (e) => {
    const d = JSON.parse(e.data);
    updatePrice(d.price, d.index || "NIFTY");
    updateMode(d.mode);
    updateConnection(d.connected);
    if (d.pairs) {
        allPairs = d.pairs;
        renderPairs();
    }
    if (d.day_summary) renderDaySummary(d.day_summary);
    if (d.active_trades) renderActiveTrades(d.active_trades);
    if (d.completed_trades) renderCompletedTrades(d.completed_trades);
});

evtSource.addEventListener("price", (e) => {
    const d = JSON.parse(e.data);
    updatePrice(d.price, d.index);
});

evtSource.addEventListener("pairs", (e) => {
    const d = JSON.parse(e.data);
    allPairs[d.timeframe] = d.pairs;
    renderPairs();
});

evtSource.addEventListener("trades", (e) => {
    const d = JSON.parse(e.data);
    if (d.active) renderActiveTrades(d.active);
    if (d.completed) renderCompletedTrades(d.completed);
    if (d.day_summary) renderDaySummary(d.day_summary);
    // Notify on SL hit
    if (d.completed && d.completed.length > 0) {
        const latest = d.completed[d.completed.length - 1];
        if (latest.is_sl_hit) {
            notify("SL Hit!", `${latest.direction === 'CALL' ? 'CE' : 'PE'} SL hit | PnL: ₹${latest.pnl.toFixed(0)}`, "red");
        }
    }
});

evtSource.addEventListener("status", (e) => {
    const d = JSON.parse(e.data);
    if (d.mode !== undefined) updateMode(d.mode);
    if (d.connected !== undefined) updateConnection(d.connected);
});

evtSource.addEventListener("error_event", (e) => {
    const d = JSON.parse(e.data);
    showToast(d.message, "red");
});

evtSource.addEventListener("backtest", (e) => {
    const d = JSON.parse(e.data);
    if (d.status === "complete") renderBacktest(d.summary, d.results);
});

evtSource.onerror = () => {
    const dot = document.getElementById("conn-dot");
    const txt = document.getElementById("conn-text");
    if (dot) dot.className = "dot";
    if (txt) txt.textContent = "Reconnecting...";
};

// ── DOM Updaters ─────────────────────────────────────────────────────────

function updatePrice(price, index) {
    const el = document.getElementById("spot-price");
    const idxEl = document.getElementById("price-index");
    const card = document.getElementById("price-card");
    if (!el) return;

    if (price > 0) {
        el.textContent = price.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        el.className = "price-display " + (price >= lastPrice ? "up" : "down");
        if (card && lastPrice > 0) {
            card.classList.remove("pulse-up", "pulse-down");
            void card.offsetWidth; // reflow
            card.classList.add(price >= lastPrice ? "pulse-up" : "pulse-down");
        }
        lastPrice = price;
    }
    if (idxEl && index) idxEl.textContent = index;
}

function updateMode(mode) {
    const badge = document.getElementById("mode-badge");
    if (!badge) return;
    badge.textContent = mode.toUpperCase().replace("_", " ");
    badge.className = "mode-badge " + mode;

    const running = mode !== "idle";
    const btnScan = document.getElementById("btn-scan");
    const btnLive = document.getElementById("btn-live");
    const btnStop = document.getElementById("btn-stop");
    const btnBt = document.getElementById("btn-bt");
    if (btnScan) btnScan.disabled = running;
    if (btnLive) btnLive.disabled = running;
    if (btnStop) btnStop.disabled = !running;
    if (btnBt) btnBt.disabled = running;
}

function updateConnection(connected) {
    const dot = document.getElementById("conn-dot");
    const txt = document.getElementById("conn-text");
    if (dot) dot.className = "dot" + (connected ? " connected" : "");
    if (txt) txt.textContent = connected ? "Connected" : "Disconnected";
}

function renderPairs() {
    const tbody = document.getElementById("pairs-body");
    if (!tbody) return;
    const pairs = allPairs[currentPairTab] || [];
    if (pairs.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="empty">No pairs detected</td></tr>';
        return;
    }
    tbody.innerHTML = pairs.map(p => `
        <tr>
            <td>${p.candle1_time}-${p.time}</td>
            <td class="${p.pattern.startsWith('RED') ? 'text-red' : 'text-green'}">${p.pattern}</td>
            <td>${p.range_high}</td>
            <td>${p.range_low}</td>
            <td>${p.range_points}</td>
        </tr>
    `).join("");
}

function renderActiveTrades(trades) {
    const tbody = document.getElementById("trades-body");
    if (!tbody) return;
    if (!trades || trades.length === 0) {
        tbody.innerHTML = '<tr><td colspan="10" class="empty">No active trades</td></tr>';
        return;
    }
    tbody.innerHTML = trades.map(t => `
        <tr>
            <td>${t.entry_time}</td>
            <td class="${t.direction === 'CALL' ? 'text-green' : 'text-red'}">${t.direction === 'CALL' ? 'CE' : 'PE'}</td>
            <td>${t.strike_price}</td>
            <td>\u20B9${t.entry_price.toFixed(2)}</td>
            <td>${t.spot_price}</td>
            <td class="text-red">${t.stop_loss}${t.trailing_sl ? ' ↑' : ''}</td>
            <td class="${t.pnl >= 0 ? 'text-green' : 'text-red'}">₹${t.pnl.toFixed(0)}</td>
            <td class="text-dim" style="font-size:11px">${t.option_symbol}</td>
            <td>${t.qty}</td>
            <td><button class="btn btn-red btn-sm" onclick="exitTrade('${t.option_symbol}')">Exit</button></td>
        </tr>
    `).join("");
}

function renderCompletedTrades(trades) {
    const card = document.getElementById("completed-card");
    const tbody = document.getElementById("completed-body");
    if (!tbody || !card) return;
    if (!trades || trades.length === 0) {
        card.style.display = "none";
        return;
    }
    card.style.display = "block";
    tbody.innerHTML = trades.map(t => `
        <tr>
            <td>${t.entry_time}</td>
            <td>${t.exit_time || '--'}</td>
            <td class="${t.direction === 'CALL' ? 'text-green' : 'text-red'}">${t.direction === 'CALL' ? 'CE' : 'PE'}</td>
            <td>${t.strike_price}</td>
            <td>\u20B9${t.entry_price.toFixed(2)}</td>
            <td>\u20B9${(t.exit_price || 0).toFixed(2)}</td>
            <td class="${t.pnl >= 0 ? 'text-green' : 'text-red'}">\u20B9${t.pnl.toFixed(0)}</td>
            <td class="${t.is_sl_hit ? 'text-red' : 'text-green'}">${t.is_sl_hit ? 'Yes' : 'No'}</td>
        </tr>
    `).join("");
}

function renderDaySummary(ds) {
    const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    if (!ds) return;
    set("ds-sl", `${ds.total_sl} / ${ds.max_sl}`);
    set("ds-1m-sl", `${ds.onemin_sl} / ${ds.max_1m_sl}`);
    set("ds-1m-trades", `${ds.onemin_trades} / ${ds.max_1m_trades}`);
    set("ds-1m-status", ds.onemin_disabled ? "Disabled" : "Active");
    const tradingEl = document.getElementById("ds-trading");
    if (tradingEl) {
        tradingEl.textContent = ds.trading_stopped ? "Stopped" : "Active";
        tradingEl.className = "value " + (ds.trading_stopped ? "text-red" : "text-green");
    }
    set("ds-total", ds.active_count + ds.completed_count);
}

function renderBacktest(summary, results) {
    const card = document.getElementById("backtest-card");
    const sumEl = document.getElementById("bt-summary");
    const tbody = document.getElementById("bt-body");
    if (!card || !sumEl || !tbody) return;

    card.style.display = "block";

    if (!summary || !summary.total) {
        sumEl.innerHTML = '<div class="empty">No results</div>';
        tbody.innerHTML = "";
        return;
    }

    const stats = [
        { label: "Total", value: summary.total },
        { label: "Wins", value: summary.wins, cls: "text-green" },
        { label: "Losses", value: summary.losses, cls: "text-red" },
        { label: "Win Rate", value: summary.win_rate + "%" },
        { label: "Avg Profit", value: summary.avg_profit + " pts" },
        { label: "SL Rate", value: summary.sl_rate + "%" },
    ];
    if (summary.trailing_sl_count > 0) {
        stats.push({ label: "Trailing SL", value: summary.trailing_sl_count });
    }
    if (summary.exit_types) {
        if (summary.exit_types.MARKET_CLOSE) {
            stats.push({ label: "Mkt Close", value: summary.exit_types.MARKET_CLOSE });
        }
    }
    sumEl.innerHTML = stats.map(s => `
        <div class="stat-box">
            <div class="stat-value ${s.cls || ''}">${s.value}</div>
            <div class="stat-label">${s.label}</div>
        </div>
    `).join("");

    const exitCls = (et) => {
        if (et === "SL") return "text-red";
        if (et === "TRAILING_SL") return "text-yellow";
        if (et === "MARKET_CLOSE") return "text-muted";
        return "text-green";
    };
    const exitLabel = (et) => {
        if (et === "SL") return "SL";
        if (et === "TRAILING_SL") return "Trail SL";
        if (et === "MARKET_CLOSE") return "Mkt Close";
        if (et === "EOD") return "EOD";
        return et || "-";
    };

    tbody.innerHTML = results.slice(0, 200).map(r => `
        <tr>
            <td>${r.date}</td>
            <td>${r.pair_time}</td>
            <td>${r.pattern}</td>
            <td class="${r.direction === 'CE' ? 'text-green' : 'text-red'}">${r.direction}</td>
            <td>${Number(r.range_high).toFixed(1)} - ${Number(r.range_low).toFixed(1)}</td>
            <td>${Number(r.range_points).toFixed(1)}</td>
            <td>${r.breakout_time}</td>
            <td>${r.exit_time || '-'}</td>
            <td>${r.stop_loss ? Number(r.stop_loss).toFixed(1) : '-'}${r.trailing_sl ? ' ↑' : ''}</td>
            <td class="${exitCls(r.exit_type)}">${exitLabel(r.exit_type)}</td>
            <td class="${Number(r.profit_pts) >= 0 ? 'text-green' : 'text-red'}">${Number(r.profit_pts).toFixed(1)}</td>
        </tr>
    `).join("");

    card.scrollIntoView({ behavior: "smooth" });
}

// ── Tab Switching ────────────────────────────────────────────────────────

function switchPairTab(el) {
    document.querySelectorAll(".tabs .tab").forEach(t => t.classList.remove("active"));
    el.classList.add("active");
    currentPairTab = el.dataset.tf;
    renderPairs();
}

// ── Control Actions ──────────────────────────────────────────────────────

async function startScan() {
    const res = await fetch("/api/control/start-scan", { method: "POST" });
    const data = await res.json();
    if (!res.ok) showToast(data.detail || "Error", "red");
    else showToast("Scan started", "green");
}

async function startLive() {
    const paper = document.getElementById("paper-toggle")?.checked ?? true;
    const strike = document.getElementById("sel-strike")?.value || "ATM";
    const lots = parseInt(document.getElementById("inp-lots")?.value || "1");
    const tf = document.getElementById("sel-tf")?.value || "all";
    const afternoon = document.getElementById("afternoon-toggle")?.checked ?? false;

    const res = await fetch("/api/control/start-live", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paper, strike, lots, timeframe: tf, afternoon }),
    });
    const data = await res.json();
    if (!res.ok) showToast(data.detail || "Error", "red");
    else showToast(data.message, paper ? "yellow" : "green");
}

async function stopAll() {
    await fetch("/api/control/stop", { method: "POST" });
    showToast("Stop signal sent", "blue");
}

async function exitTrade(symbol) {
    if (!confirm("Exit this trade now?")) return;
    const res = await fetch("/api/control/exit-trade", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol }),
    });
    const data = await res.json();
    if (!res.ok) showToast(data.detail || "Exit failed", "red");
    else {
        notify("Trade Exited", data.message, data.trade?.pnl >= 0 ? "green" : "red");
    }
}

async function runBacktest() {
    const days = parseInt(document.getElementById("inp-bt-days")?.value || "7");
    const tf = document.getElementById("sel-tf")?.value || "5";
    const tfVal = tf === "all" ? "5" : tf;

    const res = await fetch("/api/control/backtest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ timeframe: tfVal, days }),
    });
    const data = await res.json();
    if (!res.ok) showToast(data.detail || "Error", "red");
    else showToast("Backtest running...", "blue");
}

// ── Auth Actions ─────────────────────────────────────────────────────────

async function connectAuth() {
    const res = await fetch("/api/auth/connect", { method: "POST" });
    const data = await res.json();
    showToast(data.message, "blue");
    setTimeout(loadAuthStatus, 5000);
}

async function clearAuth() {
    await fetch("/api/auth/clear", { method: "POST" });
    showToast("Tokens cleared", "red");
    loadAuthStatus();
}

async function loadAuthStatus() {
    try {
        const res = await fetch("/api/auth/status");
        const data = await res.json();
        updateConnection(data.connected);
        const statusEl = document.getElementById("auth-status");
        const tokenEl = document.getElementById("auth-token");
        const expiryEl = document.getElementById("auth-expiry");
        if (statusEl) statusEl.textContent = data.connected ? "Connected" : "Disconnected";
        if (statusEl) statusEl.className = "value " + (data.connected ? "text-green" : "text-red");
        if (tokenEl) tokenEl.textContent = data.token_saved ? "Yes" : "No";
        if (expiryEl) expiryEl.textContent = data.expiry ? new Date(data.expiry).toLocaleString() : "--";
    } catch (e) {}
}

// ── Settings ─────────────────────────────────────────────────────────────

async function loadSettings() {
    try {
        const res = await fetch("/api/settings");
        const data = await res.json();
        for (const [key, val] of Object.entries(data)) {
            const el = document.querySelector(`[name="${key}"]`);
            if (el) el.value = val;
        }
    } catch (e) {}
}

async function saveSettings(e) {
    e.preventDefault();
    const form = document.getElementById("settings-form");
    if (!form) return;
    const formData = new FormData(form);
    const body = Object.fromEntries(formData.entries());
    const res = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    if (res.ok) showToast("Settings saved", "green");
    else showToast("Failed to save", "red");
}

async function resetSettings() {
    const res = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
    });
    if (res.ok) {
        showToast("Reset to defaults", "blue");
        loadSettings();
    }
}

// ── Trade Log (trades page) ──────────────────────────────────────────────

async function loadTradeLog() {
    try {
        const res = await fetch("/api/trades/log");
        const data = await res.json();
        allTradeLog = data.trades || [];
        renderTradeLog();
    } catch (e) {}
}

function renderTradeLog() {
    const tbody = document.getElementById("trade-log-body");
    if (!tbody) return;

    let filtered = allTradeLog;
    if (activeFilter !== "all") {
        filtered = filtered.filter(t =>
            t.timeframe === activeFilter || t.mode === activeFilter
        );
    }

    if (filtered.length === 0) {
        tbody.innerHTML = '<tr><td colspan="13" class="empty">No trades found</td></tr>';
        return;
    }

    tbody.innerHTML = filtered.map(t => `
        <tr>
            <td>${t.timestamp}</td>
            <td>${t.timeframe}</td>
            <td>${t.pattern}</td>
            <td class="${t.direction === 'CALL' ? 'text-green' : 'text-red'}">${t.direction === 'CALL' ? 'CE' : 'PE'}</td>
            <td>${t.range_high}</td>
            <td>${t.range_low}</td>
            <td>${t.range_points}</td>
            <td>${t.spot_price || '--'}</td>
            <td class="text-red">${t.stop_loss || '--'}</td>
            <td>\u20B9${t.entry_price}</td>
            <td class="text-dim" style="font-size:11px">${t.option_symbol}</td>
            <td>${t.qty}</td>
            <td class="${t.mode === 'PAPER' ? 'text-yellow' : 'text-blue'}">${t.mode}</td>
        </tr>
    `).join("");
}

function filterTrades(el) {
    document.querySelectorAll(".filters .chip").forEach(c => c.classList.remove("active"));
    el.classList.add("active");
    activeFilter = el.dataset.filter;
    renderTradeLog();
}

// ── Toast ────────────────────────────────────────────────────────────────

function showToast(msg, color = "blue") {
    const container = document.getElementById("toast-container");
    if (!container) return;
    const toast = document.createElement("div");
    toast.className = "toast";
    toast.style.borderColor = `var(--${color})`;
    toast.textContent = msg;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
}

// ── Init ─────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
    loadAuthStatus();
    loadSettings();
    loadTradeLog();
    // Poll trade log every 30s on trades page
    if (document.getElementById("trade-log-body")) {
        setInterval(loadTradeLog, 30000);
    }
});
