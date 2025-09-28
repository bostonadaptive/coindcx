// ---------------- Load TradingView Chart ----------------
// Keep a reference to the currently loaded TradingView symbol so we don't re-create the widget repeatedly
let currentTvSymbol = null;
function loadChart(symbol = "BTCUSDT.P") {
  const el = document.getElementById("tradingview_chart");
  if (!el) return;
  const s = String(symbol || '').trim();
  if (currentTvSymbol && currentTvSymbol === s) {
    // Same symbol already loaded - do nothing
    return;
  }
  currentTvSymbol = s;
  el.innerHTML = "";
  new TradingView.widget({
    container_id: "tradingview_chart",
    autosize: true,
    symbol: symbol,
    interval: "15",
    // Use India timezone for display
    timezone: "Asia/Kolkata",
    theme: "light",
    style: "1",
    locale: "en",
    toolbar_bg: "#f1f3f6",
    enable_publishing: false,
    withdateranges: true,
    hide_side_toolbar: false,
    allow_symbol_change: true
  });
}

// Normalize various stored symbol formats to a TradingView-friendly symbol
function normalizeForTV(sym) {
  if (!sym) return '';
  // already TV format
  if (sym.includes(':')) return sym;
  // examples to handle: B-BTC_USDT, B-ETH_USDT, BTCUSDT, BTC_USDT
  let s = String(sym).toUpperCase();
  // remove broker prefix like B- or BIN- etc
  if (s.indexOf('-') !== -1) {
    s = s.split('-').pop();
  }
  // remove underscores
  s = s.replace(/_/g, '');
  // if it already contains a dot suffix like .P or .BIN, keep; otherwise append .P for Binance
  if (!s.includes('.')) {
    s = s + '.P';
  }
  return s;
}

// Convert a stored TV symbol or pair to CoinDCX pair format:
// Examples:
//  'BINANCE:ETHUSDT' -> 'B-ETH_USDT'
//  'ETHUSDT' -> 'B-ETH_USDT'
//  'B-ETH_USDT' -> 'B-ETH_USDT'
function tvToCoindcxPair(sym) {
  if (!sym) return '';
  let s = String(sym).trim();
  // If already in B-BASE_QUOTE form
  if (s.startsWith('B-')) return s;
  // If it has exchange prefix like BINANCE:ETHUSDT
  if (s.includes(':')) {
    s = s.split(':', 2)[1];
  }
  // strip .P suffix or other dots
  s = s.replace(/\.P$/i, '').replace(/\./g, '');
  // separate base and quote (assume last 4 chars are quote like USDT)
  if (s.length >= 6) {
    const quote = s.slice(-4);
    const base = s.slice(0, s.length - 4);
    return `B-${base}_${quote}`;
  }
  return s;
}

// Format price with variable decimals
function formatPrice(v) {
  if (v === null || v === undefined || v === '' || isNaN(Number(v))) return '-';
  const n = Number(v);
  const abs = Math.abs(n);
  let decimals = 2;
  if (abs < 10) decimals = 6;
  else if (abs < 99) decimals = 4;
  // Use toLocaleString for thousands separators while fixing decimals
  try {
    return n.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  } catch (e) {
    return n.toFixed(decimals);
  }
}

function formatQty(q) {
  if (q === null || q === undefined || q === '' || isNaN(Number(q))) return '-';
  return Number(q).toFixed(2);
}

// Ensure a small CSS for LTP flash is present on pages that use positions
(function ensureLtpFlashStyle(){
  try{
    if (document.getElementById('ltp-flash-style')) return;
    const s = document.createElement('style');
    s.id = 'ltp-flash-style';
    s.innerHTML = `
      .ltp-cell, .ltp-card { transition: color 0.35s ease, transform 0.25s ease; }
      .ltp-flash { transform: scale(1.02); }
    `;
    document.head.appendChild(s);
  }catch(e){}
})();

// keep a map of last seen LTPs so we can do tick-wise color flashes without relying on DOM persistence
window._lastLtpMap = window._lastLtpMap || {};

// Format datetime strings to YYYY-MM-DD T HH:MM:SS (e.g. 2025-09-25 T11:26:00)
function pad(n){return n<10? '0'+n: n}
// Format dates in India timezone (Asia/Kolkata). Accepts Date, epoch ms, or ISO string.
function formatDateTime(dt){
  if(!dt) return '';
  // If dt is already a number or numeric string, treat as epoch ms
  let d;
  try {
    if (typeof dt === 'number' || (/^\d+$/).test(String(dt))) {
      d = new Date(Number(dt));
    } else {
      d = new Date(dt);
    }
  } catch(e) { return String(dt); }
  if (isNaN(d.getTime())) return String(dt);
  try {
    const opts = { year: 'numeric', month: '2-digit', day: '2-digit',
                   hour: '2-digit', minute: '2-digit', second: '2-digit',
                   hour12: false, timeZone: 'Asia/Kolkata' };
    // Use Intl.DateTimeFormat to respect timezone
    const parts = new Intl.DateTimeFormat('en-GB', opts).formatToParts(d);
    // Build YYYY-MM-DD T HH:MM:SS from parts
    const map = {};
    parts.forEach(p => { if (p.type !== 'literal') map[p.type] = p.value; });
    const year = map.year || d.getFullYear();
    const month = map.month || pad(d.getMonth()+1);
    const day = map.day || pad(d.getDate());
    const hour = map.hour || pad(d.getHours());
    const minute = map.minute || pad(d.getMinutes());
    const second = map.second || pad(d.getSeconds());
    return `${year}-${month}-${day} T${hour}:${minute}:${second}`;
  } catch(e) {
    // Fallback to naive local formatting
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }
}

// ---------------- Broker: live status & balance ----------------
// function renderBrokerBox(data) {
//   const el = document.getElementById("broker-box");
//   if (!el) return;
//   if (!data.connected) {
//     el.innerHTML = `
//       <h5 class="card-title">Broker Connection</h5>
//       <p class="text-danger">❌ Not connected</p>
//       <button class="btn btn-primary mt-2" data-bs-toggle="modal" data-bs-target="#brokerModal">
//         Add API Credentials
//       </button>`;
//   } else {
//     const ccy = data.currency || "INR";
//     el.innerHTML = `
//       <h5 class="card-title">Broker Connection</h5>
//       <p class="text-success mb-1">✅ Connected</p>
//       <h4 class="fw-bold">${ccy === "INR" ? "₹" : ""} ${data.balance}</h4>
//       <p class="text-muted">Locked: ${data.locked}</p>
//       <button class="btn btn-primary mt-2" data-bs-toggle="modal" data-bs-target="#brokerModal">
//         Edit API Credentials
//       </button>`;
//   }
// }

function renderBrokerBox(data) {
    const el = document.getElementById("broker-box") || document.getElementById("brokerStatus");
    if (!el) return;

    // Check if the broker is connected
    if (!data.connected) {
        // Render for "Not connected" state
        if (el.id === "broker-box") {
            el.innerHTML = `
                <h5 class="card-title">CoinDCX Connection</h5>
                <p class="text-danger">❌ Not connected</p>
                <button class="btn btn-primary mt-2" data-bs-toggle="modal" data-bs-target="#brokerModal">
                    Add API Credentials
                </button>`;
        } else if (el.id === "brokerStatus") {
            el.innerHTML = `
                <p class="text-danger">❌ Not connected to CoinDCX</p>
                <button class="btn btn-primary mt-2" data-bs-toggle="modal" data-bs-target="#brokerModal">
                    Add API Credentials
                </button>`;
        }
    } else {
        // Render for "Connected" state
        const ccy = data.currency || "INR";
        if (el.id === "broker-box") {
            el.innerHTML = `
                  <h5 class="card-title d-flex justify-content-between align-items-center">
                      CoinDCX Connection
                      <i class="bi bi-pencil-square" data-bs-toggle="modal" data-bs-target="#brokerModal" style="cursor: pointer;"></i>
                  </h5>
                  <p class="text-success mb-1">✅ Connected</p>
                  <h4 class="fw-bold">Balance: ${ccy === "INR" ? "₹" : ""} ${data.balance}</h4>
                  <p class="text-muted">Locked: ${data.locked}</p>
              `;
        } else if (el.id === "brokerStatus") {
            el.innerHTML = `
              <p class="text-success mb-1">✅ Connected to CoinDCX</p>
              `;
            // Find and update the existing balance element
            const balanceElement = document.getElementById("realAccountBalance");
            const brokerStatusParagraph = el.querySelector("p.text-success");
            
            if (balanceElement) {
                balanceElement.textContent = `${ccy === "INR" ? "₹" : ""} ${data.balance}`;
            }

            // Only update the status paragraph if it exists
            if (brokerStatusParagraph) {
                brokerStatusParagraph.textContent = "✅ Connected to CoinDCX";
            }
        }
    }
}


function refreshBalance() {
  // Prefer APP_CACHE if available to avoid duplicate network calls
  try {
    if (window.APP_CACHE) {
      const wallets = window.APP_CACHE.getWallets();
      if (wallets && wallets.real) {
        renderBrokerBox(wallets.real);
        return;
      }
    }
  } catch (e) { /* ignore and fallback */ }
  fetch("/get_balance")
    .then(r => r.json())
    .then(data => renderBrokerBox(data))
    .catch(err => console.error("Balance fetch error:", err));
}

// ---------------- Watchlist ----------------
function addToWatchlist(symbol) {
  fetch("/add_watchlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbol: symbol })
  })
    .then(res => res.json())
    .then(() => loadWatchlist());
}

function removeFromWatchlist(symbol) {
  const item = document.querySelector(`[data-symbol='${symbol}']`);
  if (item) {
    item.classList.remove("show");
    setTimeout(() => {
      fetch("/remove_watchlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: symbol })
      })
        .then(res => res.json())
        .then(() => loadWatchlist());
    }, 200);
  }
}

function loadWatchlist() {
  fetch("/get_watchlist")
    .then(res => res.json())
    .then(data => {
      const container = document.getElementById("watchlist-container");
      if (!container) return;
      container.innerHTML = "";
      if (!data.length) {
        container.innerHTML = `<p class="text-muted fst-italic">No market data found</p>`;
        return;
      }
      data.forEach(item => {
        const div = document.createElement("div");
        div.className = "d-flex justify-content-between align-items-center border p-2 mb-2 watchlist-item";
        div.dataset.symbol = item.symbol;
        const label = item.label || tvToCoindcxPair(item.symbol) || item.symbol;
        div.innerHTML = `
          <div style="flex:1;">
            <span class="symbol-click" style="cursor:pointer">${label}</span>
          </div>
          <div class="text-end" style="min-width:110px;">
            <small class="text-muted d-block">LTP</small>
            <div class="fw-bold ltp-card" data-label="${(item.label||item.symbol).replace(/[^A-Z0-9]/gi,'')}">-</div>
          </div>
          <button class="btn btn-sm btn-danger ms-2">Remove</button>`;
        container.appendChild(div);
        setTimeout(() => div.classList.add("show"), 30);
        div.querySelector(".symbol-click").addEventListener("click", () => loadChart(item.symbol));
        div.querySelector("button").addEventListener("click", () => removeFromWatchlist(item.symbol));
      });
    });
}

// ---------------- Instruments Search ----------------
let instruments = []; // [{name:"B-ETH_USDT", symbol:"BINANCE:ETHUSDT"}]

function loadInstruments() {
  fetch("/get_instruments")
    .then(res => res.json())
    .then(data => (instruments = data || []))
    .catch(err => console.error("Instrument load error:", err));
}

function setupSearch() {
  const searchBox = document.getElementById("symbolSearch");
  const suggestions = document.getElementById("suggestions");
  if (!searchBox || !suggestions) return;

  searchBox.addEventListener("input", function () {
    const q = this.value.trim().toUpperCase();
    suggestions.innerHTML = "";
    if (!q) return;
    const results = (instruments || []).filter(i => (i.name || "").toUpperCase().includes(q)).slice(0, 20);
    results.forEach(s => {
      const li = document.createElement("li");
      li.className = "list-group-item d-flex justify-content-between align-items-center";
      li.innerHTML = `
        <span class="sym" style="cursor:pointer">${s.name}</span>
        <button class="btn btn-sm btn-success">Add</button>`;
      li.querySelector(".sym").addEventListener("click", () => loadChart(s.symbol));
      li.querySelector("button").addEventListener("click", () => {
        addToWatchlist(s.symbol);
        suggestions.innerHTML = "";
        searchBox.value = "";
      });
      suggestions.appendChild(li);
    });
  });
}

// ---------------- Active Positions (UI) ----------------
// UI: Paper fallback banner helpers
function showPaperFallbackBanner() {
  try {
    if (localStorage && localStorage.getItem('paperFallbackDismissed') === '1') return;
    const b = document.getElementById('paperFallbackBanner');
    if (!b) return;
    b.classList.remove('d-none');
    b.classList.add('show');
    const btn = document.getElementById('paperFallbackDismiss');
    if (btn) {
      btn.onclick = function() {
        hidePaperFallbackBanner(true);
      };
    }
  } catch (e) { console.error('banner show error', e); }
}

function hidePaperFallbackBanner(persist=false) {
  try {
    const b = document.getElementById('paperFallbackBanner');
    if (!b) return;
    b.classList.remove('show');
    b.classList.add('d-none');
    if (persist && localStorage) localStorage.setItem('paperFallbackDismissed', '1');
  } catch (e) { console.error('banner hide error', e); }
}

async function loadPositions() {
  try {
    const accountTypeEl = document.getElementById('accountType');
    const accountType = accountTypeEl ? accountTypeEl.value : 'real';
    let open = [];
    // Prefer using centralized APP_CACHE if available
    if (window.APP_CACHE) {
      const positions = window.APP_CACHE.getPositions();
      if (accountType === 'paper') {
        open = (positions && positions.paper && positions.paper.open) ? positions.paper.open : [];
        // also ensure history is available via the cache
        try { const closed = (positions && positions.paper && positions.paper.closed) ? positions.paper.closed : []; if (closed) loadPaperHistory(); } catch(e){}
      } else {
        open = (positions && positions.real && positions.real.open) ? positions.real.open : [];
        // if empty, still attempt fallback network fetch
        if (!open || !open.length) {
          const res = await fetch('/get_positions');
          const data = await res.json().catch(()=>({}));
          if (data && data.error && String(data.error).toLowerCase().includes('no api')) {
            try { showPaperFallbackBanner(); } catch(e){}
            const pres = await fetch('/paper_positions').catch(()=>null);
            const pdata = pres ? await pres.json().catch(()=>({})) : {};
            open = pdata.open || [];
          } else {
            open = data.open || [];
          }
        }
      }
    } else {
      // original behavior
      if (accountType === 'paper') {
        const res = await fetch('/paper_positions');
        const data = await res.json();
        open = data.open || [];
        // also load history for paper
        loadPaperHistory();
      } else {
        const res = await fetch('/get_positions');
        const data = await res.json();
        // If server reports missing API credentials, gracefully fall back to paper positions
        if (data && data.error && String(data.error).toLowerCase().includes('no api')) {
          // Show banner unless user dismissed it previously
          try { showPaperFallbackBanner(); } catch(e){}
          try {
            const pres = await fetch('/paper_positions');
            const pdata = await pres.json();
            open = pdata.open || [];
          } catch (e) {
            open = [];
          }
        } else {
          open = data.open || [];
        }
      }
    }
    // Prefer table body rendering if present (algo_trading.html uses #positionsTableBody)
    const tbody = document.getElementById('positionsTableBody');
    const container = document.getElementById('positions-container');

    // helper to pick numeric INR PnL value (declare once so both table and card rendering can use it)
    function getPnlInrValue(p) {
      // prefer explicit numeric INR value from server
      if (p && p.pnl_open_inr_value !== undefined && p.pnl_open_inr_value !== null && !isNaN(Number(p.pnl_open_inr_value))) {
        return Number(p.pnl_open_inr_value);
      }
      // fallback to numeric pnl_open_inr (legacy) if it's already numeric
      if (p && p.pnl_open_inr !== undefined && p.pnl_open_inr !== null && !isNaN(Number(p.pnl_open_inr))) {
        return Number(p.pnl_open_inr);
      }
      // fallback to converting pnl in USDT if provided (server may expose pnl_usdt or pnl_open_usdt)
      if (p && (p.pnl_open_usdt !== undefined && p.pnl_open_usdt !== null && !isNaN(Number(p.pnl_open_usdt))) && window._fx_usdt_inr) {
        return Number(p.pnl_open_usdt) * Number(window._fx_usdt_inr);
      }
      if (p && (p.pnl_usdt !== undefined && p.pnl_usdt !== null && !isNaN(Number(p.pnl_usdt))) && window._fx_usdt_inr) {
        return Number(p.pnl_usdt) * Number(window._fx_usdt_inr);
      }
      // last resort: return 0
      return 0;
    }

    if (!open.length) {
      if (tbody) {
        tbody.innerHTML = '<tr><td colspan="10" class="text-muted">No open positions</td></tr>';
      } else if (container) {
        container.innerHTML = `<p class="text-muted">No open positions</p>`;
      }
      return;
    }

    // Build rows for table if tbody exists
    if (tbody) {
      let rows = '';
        // (getPnlInrValue is defined above and reused here)

        open.forEach(p => {
          // Use backend-provided normalized fields for LTP and P&L
          const ltpVal = (p.ltp !== undefined && p.ltp !== null) ? Number(p.ltp) : null;
          const runningPnl = getPnlInrValue(p);
          const pnlClass = runningPnl < 0 ? 'text-danger' : 'text-success';
          const symbol = p.pair || p.tv_symbol || '';
          const entryAt = formatDateTime(p.entry_at || '');
          const entryPx = (p.entry_px !== undefined && p.entry_px !== null) ? formatPrice(p.entry_px) : '-';
          const qty = formatQty(p.qty || 0);
          const strategy = p.strategy || '';
          // Show CoinDCX pair like B-BASE_QUOTE
          let label = tvToCoindcxPair(p.tv_symbol || p.pair || '');

          // Order id (prefer real order_id, then paper_order_id, then id)
          const ordFull = (p.order_id || p.paper_order_id || p.id || '') + '';
          let ordDisplay = ordFull ? (ordFull.length > 12 ? `<span title="${ordFull}" data-bs-toggle="tooltip">${ordFull.slice(0,5)}.....${ordFull.slice(-5)}</span>` : `<span title="${ordFull}" data-bs-toggle="tooltip">${ordFull}</span>`) : '-';

          // Side as badge
          const sideRaw = (p.side||'-').toUpperCase();
          const sideBadgeClass = (sideRaw === 'SELL' || sideRaw === 'SHORT') ? 'badge bg-danger' : 'badge bg-success';
          const sideDisplay = `<span class="${sideBadgeClass}">${sideRaw}</span>`;

      rows += `<tr>
        <td>${ordDisplay}</td>
  <td><strong>${tvToCoindcxPair(symbol)}</strong></td>
        <td>${sideDisplay}</td>
        <td class="entry-time">${entryAt}</td>
        <td>${entryPx}</td>
        <td>${qty}</td>
        <td class="ltp-cell" data-label="${label}" data-last-price="${ltpVal !== null && ltpVal !== undefined ? formatPrice(ltpVal) : ''}">${ltpVal !== null && ltpVal !== undefined ? formatPrice(ltpVal) : '-'}</td>
        <td class="running-pnl ${pnlClass}" data-pnl="${runningPnl}">${formatPrice(Number(runningPnl) || 0)}</td>
        <td>${strategy}</td>
        <td><button class="btn btn-sm btn-outline-secondary view-btn" data-symbol="${p.tv_symbol||p.pair||''}">View</button></td>
          </tr>`;
        });
      tbody.innerHTML = rows;
      // attach view handlers
      document.querySelectorAll('.view-btn').forEach(b => b.addEventListener('click', (ev)=>{
        const sym = ev.currentTarget.getAttribute('data-symbol') || '';
        if(!sym) return;
        let tvs = normalizeForTV(sym);
        if(tvs.includes(':')) loadChart(tvs);
        else loadChart('BINANCE:' + tvs.replace('.P',''));
      }))
        } else if (container) {
      // Fallback to existing card/list rendering
      let html = '';
      open.forEach(p => {
        const badgeColor = (p.side || '').toUpperCase() === 'LONG' || (p.side || '').toUpperCase() === 'BUY' ? 'success' : 'danger';
        // Prefer numeric running pnl if provided; format with currency + decimals and color by sign
        const runningPnlRaw = getPnlInrValue(p);
        const pnlClass = (runningPnlRaw === null || runningPnlRaw === undefined) ? '' : (runningPnlRaw < 0 ? 'text-danger' : 'text-success');
        const pnlText = (runningPnlRaw === null || runningPnlRaw === undefined) ? '-' : ('₹' + formatPrice(runningPnlRaw));
        html += `
          <div class="list-group-item d-flex justify-content-between align-items-center">
            <div>
              <strong>${p.pair}</strong> <span class="badge bg-${badgeColor} ms-1">${(p.side||"-").toUpperCase()}</span><br>
              Qty: ${p.qty || "-"} | Entry: ${p.entry_px || "-"} | Mark: ${p.mark_px || "-"} | Lev: ${p.lev || "-"}
            </div>
            <div class="text-end">
              <div class="fw-bold ${pnlClass}">${pnlText}</div>
              <div class="text-muted small">${p.updated_at || ""}</div>
            </div>
          </div>`;
      });
      container.innerHTML = html;
    }
  // load first open position into chart only if no chart loaded yet
  if (open.length && !currentTvSymbol) {
      try {
        const first = open[0];
        if (first) {
          // prefer tv_symbol, else normalize stored symbol for TradingView
          let raw = first.tv_symbol || first.pair || '';
          let tvsym = normalizeForTV(raw);
          // If tvsym includes exchange prefix, use as-is; otherwise default to BINANCE:
          if (tvsym.includes(':')) {
            loadChart(tvsym);
          } else {
            loadChart('BINANCE:' + tvsym.replace('.P',''));
          }
        }
      } catch (e) {
        // ignore
      }
    }
  } catch (e) {
    console.error("Positions fetch error:", e);
  }
}

// Periodic updater: refresh LTPs and running P&L every 1 second while the positions tab is active
let _positionsInterval = null;
function startPositionsAutoRefresh() {
  // avoid multiple intervals
  if (_positionsInterval) return;
  _positionsInterval = setInterval(() => {
    try {
      const tabActive = document.querySelector('#positions-tab')?.classList.contains('active');
      if (!tabActive) return; // only refresh when positions tab is visible to save CPU
      // delegate to loadPositions which already chooses the correct endpoint
  loadPositions();
      // If paper account is selected, also refresh wallet info
      const accountTypeEl = document.getElementById('accountType');
      const accountType = accountTypeEl ? accountTypeEl.value : 'real';
      if (accountType === 'paper') {
        try{ refreshPaperWalletUI(); }catch(e){}
      }
    } catch (e) {
      console.error('positions auto-refresh error', e);
    }
  }, 1000);
}

function stopPositionsAutoRefresh() {
  if (_positionsInterval) {
    clearInterval(_positionsInterval);
    _positionsInterval = null;
  }
}

// refresh wallet UI values from server for paper accounts
function refreshPaperWalletUI() {
  // Prefer APP_CACHE wallet data
  try {
    if (window.APP_CACHE) {
      const wallets = window.APP_CACHE.getWallets();
      if (wallets && wallets.paper) {
        const data = wallets.paper;
        const acc = document.getElementById('accountBalance');
        const realized = document.getElementById('paperRealizedPnL');
        const unreal = document.getElementById('paperUnrealizedPnL');
        const avail = document.getElementById('availableFunds');
        if (acc && data.balance !== undefined) acc.innerText = '₹' + Number(data.balance).toFixed(2);
        if (realized && data.realized_pnl !== undefined) realized.innerText = '₹' + Number(data.realized_pnl).toFixed(2);
        if (unreal && data.unrealized_pnl !== undefined) unreal.innerText = '₹' + Number(data.unrealized_pnl).toFixed(2);
        if (avail && data.available_balance !== undefined) avail.innerText = '₹' + Number(data.available_balance).toFixed(2);
        return;
      }
    }
  } catch(e){}
  fetch('/get_paper_wallet')
    .then(r => r.json())
    .then(data => {
      try {
        const acc = document.getElementById('accountBalance');
        const realized = document.getElementById('paperRealizedPnL');
        const unreal = document.getElementById('paperUnrealizedPnL');
        const avail = document.getElementById('availableFunds');
        if (acc && data.balance !== undefined) acc.innerText = '₹' + Number(data.balance).toFixed(2);
        if (realized && data.realized_pnl !== undefined) realized.innerText = '₹' + Number(data.realized_pnl).toFixed(2);
        if (unreal && data.unrealized_pnl !== undefined) unreal.innerText = '₹' + Number(data.unrealized_pnl).toFixed(2);
        if (avail && data.available_balance !== undefined) avail.innerText = '₹' + Number(data.available_balance).toFixed(2);
      } catch (e) { console.error('wallet ui update error', e); }
    }).catch(e=>{/* ignore */});
}

// Start/stop refresh based on tab visibility and accountType
document.addEventListener('visibilitychange', () => {
  if (document.hidden) stopPositionsAutoRefresh();
  else startPositionsAutoRefresh();
});

// Observe clicks on the trade tabs to start/stop auto-refresh when Positions tab is activated
document.addEventListener('DOMContentLoaded', () => {
  const posTab = document.getElementById('positions-tab');
  if (posTab) {
    posTab.addEventListener('shown.bs.tab', () => startPositionsAutoRefresh());
    posTab.addEventListener('hidden.bs.tab', () => stopPositionsAutoRefresh());
    // start initially if visible
    if (posTab.classList.contains('active')) startPositionsAutoRefresh();
  }
});

async function loadPaperHistory() {
  try {
    const tbody = document.getElementById('historyTableBody');
    if (!tbody) return;
    const accountTypeEl = document.getElementById('accountType');
    const accountType = accountTypeEl ? accountTypeEl.value : 'paper';
    let closed = [];
    if (accountType === 'real') {
      // fetch positions which returns open and closed derived from orders
      const res = await fetch('/get_positions');
      const data = await res.json();
      closed = (data.closed || []).slice(0,10);
    } else {
      const res = await fetch('/paper_history');
      const data = await res.json();
      closed = data.closed || [];
    }
    if (!closed.length) {
      tbody.innerHTML = '<tr><td colspan="9" class="text-muted">No history</td></tr>';
      return;
    }
    let html = '';
    closed.forEach(r => {
      // compute pnl if possible (exit_px - entry_px) * qty
      let pnl = '';
      try {
        const entry = parseFloat(r.entry_px) || 0;
        const exit = parseFloat(r.exit_px) || 0;
        const qty = parseFloat(r.qty) || 0;
        pnl = ((exit - entry) * qty).toFixed(2);
      } catch(e){ pnl = ''; }
      // add a view-history icon only for real accounts
      const viewIcon = (accountType === 'real') ? `<a href="/trade_history" title="View full history"><i class="bi bi-clock-history"></i></a>` : '';
      html += `<tr>
        <td>${r.pair || ''}</td>
        <td>${r.side || ''}</td>
        <td>${formatDateTime(r.entry_at || '')}</td>
        <td>${r.entry_px || ''}</td>
        <td>${formatDateTime(r.exit_at || '')}</td>
        <td>${r.exit_px || ''}</td>
        <td>${r.qty || ''}</td>
        <td>${pnl}</td>
        <td>${r.strategy || ''} ${viewIcon}</td>
      </tr>`;
    });
    tbody.innerHTML = html;
  } catch (e) {
    console.error('Paper history fetch error', e);
  }
}

// ---------------- Init ----------------

function updateStrategyStatusUI(configId, isActive) {
  // Table row
  const row = document.querySelector(`tr[data-config-id='${configId}']`);
  if (row) {
    // Update status badge
    const statusCell = row.querySelector('td:nth-child(8) .badge');
    if (statusCell) {
      statusCell.className = isActive ? 'badge bg-success' : 'badge bg-secondary';
      statusCell.textContent = isActive ? 'Running' : 'Stopped';
    }
    // Update play button icon
    const playBtn = row.querySelector('.play-btn i');
    if (playBtn) {
      playBtn.className = isActive ? 'bi bi-pause-fill' : 'bi bi-play-fill';
    }
  }
  // Card view
  const card = document.querySelector(`.card-width[data-config-id='${configId}']`);
  if (card) {
    // Update status badge
    const statusBadge = card.querySelector('.status-badge');
    if (statusBadge) {
      statusBadge.className = isActive ? 'badge rounded-pill bg-success status-badge' : 'badge rounded-pill bg-secondary status-badge';
      statusBadge.textContent = isActive ? 'Running' : 'Stopped';
    }
    // Remove both play/pause buttons, add correct one
    const btnGroup = card.querySelector('.d-flex.gap-2');
    if (btnGroup) {
      // Remove existing play/pause buttons
      btnGroup.querySelectorAll('.card-play-btn').forEach(btn => btn.remove());
      // Create new button
      const btn = document.createElement('button');
      btn.className = isActive ? 'btn btn-sm btn-danger icon-btn card-play-btn' : 'btn btn-sm btn-outline-primary icon-btn card-play-btn';
      btn.setAttribute('data-id', configId);
      btn.setAttribute('title', isActive ? 'Pause' : 'Start');
      btn.innerHTML = `<i class="bi ${isActive ? 'bi-pause-fill' : 'bi-play-fill'}"></i>`;
      // Prefer inserting before the edit button if present so Edit remains at the right-most position
      const editBtn = btnGroup.querySelector('.card-edit-btn');
      if (editBtn && editBtn.parentNode === btnGroup) btnGroup.insertBefore(btn, editBtn);
      else btnGroup.appendChild(btn);
    }
  }
}

function attachStrategyToggleHandlers() {
  // Table view
  document.querySelectorAll('.play-btn').forEach(btn => {
    btn.onclick = function() {
      const configId = this.getAttribute('data-id');
      fetch(`/toggle_strategy/${configId}`, { method: 'POST' })
        .then(res => res.json())
        .then(data => {
          if (data.success) {
            updateStrategyStatusUI(configId, data.is_active);
            attachStrategyToggleHandlers(); // re-attach for new buttons
          }
        });
    };
  });
  // Card view
  document.querySelectorAll('.card-play-btn').forEach(btn => {
    // clear any previous handler
    try { btn.onclick = null; } catch(e){}
    btn.onclick = function() {
      const configId = this.getAttribute('data-id');
      fetch(`/toggle_strategy/${configId}`, { method: 'POST' })
        .then(res => res.json())
        .then(data => {
          if (data.success) {
            updateStrategyStatusUI(configId, data.is_active);
            attachStrategyToggleHandlers(); // re-attach for new buttons
          }
        });
    };
  });
}

function setInitialPlayPauseIcons() {
  // Table view
  document.querySelectorAll('tr[data-config-id]').forEach(row => {
    const statusCell = row.querySelector('td:nth-child(8) .badge');
    const playBtn = row.querySelector('.play-btn i');
    if (statusCell && playBtn) {
      playBtn.className = statusCell.textContent.trim() === 'Running' ? 'bi bi-pause-fill' : 'bi bi-play-fill';
    }
  });
  // Card view
  document.querySelectorAll('.card-width[data-config-id]').forEach(card => {
    const statusBadge = card.querySelector('.status-badge');
    const btnGroup = card.querySelector('.d-flex.gap-2');
    if (statusBadge && btnGroup) {
      // Remove both play/pause buttons, add correct one
      btnGroup.querySelectorAll('.card-play-btn').forEach(btn => btn.remove());
      const configId = card.getAttribute('data-config-id');
      const isActive = statusBadge.textContent.trim() === 'Running';
      const btn = document.createElement('button');
      btn.className = isActive ? 'btn btn-sm btn-danger icon-btn card-play-btn' : 'btn btn-sm btn-outline-primary icon-btn card-play-btn';
      btn.setAttribute('data-id', configId);
      btn.setAttribute('title', isActive ? 'Pause' : 'Start');
      btn.innerHTML = `<i class="bi ${isActive ? 'bi-pause-fill' : 'bi-play-fill'}"></i>`;
      const editBtn = btnGroup.querySelector('.card-edit-btn');
      if (editBtn && editBtn.parentNode === btnGroup) btnGroup.insertBefore(btn, editBtn);
      else btnGroup.appendChild(btn);
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  loadChart("BTCUSDT.P");
  refreshBalance();
  setInterval(refreshBalance, 10000);

  loadInstruments();
  setupSearch();
  loadWatchlist();

  // Use APP_CACHE positions if available, otherwise load once
  if (window.APP_CACHE) {
    const pos = window.APP_CACHE.getPositions();
    if (pos) {
      // trigger a render by invoking loadPositions which will read from APP_CACHE
      loadPositions();
    }
    // subscribe to positions updates
    try { window.APP_CACHE.on('positions', ()=>{ loadPositions(); }); } catch(e){}
    // subscribe to wallet updates
    try { window.APP_CACHE.on('wallets', ()=>{ refreshPaperWalletUI(); refreshBalance(); }); } catch(e){}
    // subscribe to ltp updates: apply prices to DOM to avoid extra polling
    try {
      window.APP_CACHE.on('ltp', (map)=>{
        try{
          Object.keys(map || {}).forEach(label => {
            const price = map[label];
            if (price === null || price === undefined) return;
            const priceStr = formatPrice(Number(price));
            document.querySelectorAll('.ltp-cell[data-label="'+label+'"]') .forEach(el=>{ el.textContent = priceStr; });
            document.querySelectorAll('.ltp-card[data-label="'+label+'"]') .forEach(el=>{ el.textContent = '₹'+priceStr; });
          });
        }catch(e){}
      });
    } catch(e){}
  } else {
    loadPositions();
  }
  // positions auto-refresh is handled by startPositionsAutoRefresh when the Positions tab is active

  // Ensure wallet panels reflect current account type on load
  const acct = document.getElementById('accountType');
  if (acct) {
    acct.addEventListener('change', function () {
      const isPaper = this.value === 'paper';
      // toggle wallet panels
      const pw = document.getElementById('paperWalletDetails');
      const rw = document.getElementById('realWalletDetails');
      if (pw) pw.classList.toggle('d-none', !isPaper);
      if (rw) rw.classList.toggle('d-none', isPaper);

      // Load the correct wallet info for selected account type
      if (isPaper) {
        fetch('/get_paper_wallet').then(r => r.json()).then(data => {
          if (!data) return;
          const accEl = document.getElementById('accountBalance');
          const realized = document.getElementById('paperRealizedPnL');
          const unreal = document.getElementById('paperUnrealizedPnL');
          const avail = document.getElementById('availableFunds');
          if (accEl) accEl.innerText = '₹' + (data.balance || 0);
          if (realized) realized.innerText = '₹' + (data.realized_pnl || 0);
          if (unreal) unreal.innerText = '₹' + (data.unrealized_pnl || 0);
          if (avail) avail.innerText = '₹' + (data.available_balance || 0);
        }).catch(()=>{});
      } else {
        // Robust fetch: handle 404 or non-JSON responses gracefully
        fetch('/get_real_wallet').then(async (r) => {
          if (!r.ok) {
            // If 404 or other error, don't throw - fallback to showing placeholders
            console.warn('/get_real_wallet returned', r.status);
            return null;
          }
          // Try to parse JSON but guard against HTML or invalid body
          const ct = r.headers.get('content-type') || '';
          if (!ct.includes('application/json')) {
            // Unexpected content-type (likely HTML) - skip
            console.warn('/get_real_wallet returned non-json content-type:', ct);
            return null;
          }
          try {
            return await r.json();
          } catch (e) {
            console.warn('Failed to parse /get_real_wallet JSON:', e);
            return null;
          }
        }).then(data => {
          if (!data) return;
          const accEl = document.getElementById('realAccountBalance');
            const realized = document.getElementById('realLockedAmount');
          const unreal = document.getElementById('realUnrealizedPnL');
          const avail = document.getElementById('realAvailableFunds');
          if (accEl) accEl.innerText = '₹' + (data.balance || 0);
          if (realized) realized.innerText = '₹' + (data.realized_pnl || 0);
          if (unreal) unreal.innerText = '₹' + (data.unrealized_pnl || 0);
          if (avail) avail.innerText = '₹' + (data.available_balance || 0);
        }).catch((e)=>{ console.warn('Error fetching /get_real_wallet', e); });
      }

      // Immediately refresh positions/history for the selected account type
      // and restart tab-aware auto-refresh so it respects the new selection
      stopPositionsAutoRefresh();
      loadPositions();
      try { loadPaperHistory(); } catch(e) {}
      startPositionsAutoRefresh();
    });
  }

  setInitialPlayPauseIcons();
  attachStrategyToggleHandlers();
  // Maximize / Minimize table handlers - improved layout
  const maximizeBtn = document.getElementById('maximizeTableBtn');
  const minimizeBtn = document.getElementById('minimizeTableBtn');
  const tvCard = document.getElementById('tradingview_chart');
  const tradesCard = document.getElementById('tradesCard');
  const leftCol = document.getElementById('leftCol');
  const rightCol = document.getElementById('rightCol');
  if (maximizeBtn && minimizeBtn && tvCard && tradesCard && leftCol && rightCol) {
    // store references for restore
    let originalParent = tradesCard.parentNode;
    let originalNext = tradesCard.nextSibling;
    let containerInserted = null;

    maximizeBtn.addEventListener('click', ()=>{
      // preserve current scroll position of the page and table container so we can restore later
      const pageScroll = document.documentElement.scrollTop || document.body.scrollTop;
      tradesCard.__savedScroll = pageScroll;

      // create a full-width container below the main row and move tradesCard into it
      const mainRow = leftCol.parentNode; // the .row element
      containerInserted = document.createElement('div');
      containerInserted.className = 'col-12';
      containerInserted.style.marginTop = '10px';

      // animate fade out of left and right columns
      leftCol.classList.add('fade-hide');
      rightCol.classList.add('fade-hide');

      // after fade-out duration, hide them and move the trades card
      setTimeout(()=>{
        leftCol.style.display = 'none';
        rightCol.style.display = 'none';

        // move tradesCard into containerInserted
        containerInserted.appendChild(tradesCard);
        mainRow.appendChild(containerInserted);

        // Ensure tradesCard fills width
        tradesCard.style.width = '100%';
        tradesCard.style.boxSizing = 'border-box';

        // destroy TradingView widget by clearing container and resetting currentTvSymbol
        const tvEl = document.getElementById('tradingview_chart');
        if (tvEl) {
          tvEl.innerHTML = '';
          // clear any inline widgets if TradingView added global references
          try { if (window.tvWidget && typeof window.tvWidget.remove === 'function') window.tvWidget.remove(); } catch(e){}
          currentTvSymbol = null;
        }

        // show minimize, hide maximize
        maximizeBtn.classList.add('d-none');
        minimizeBtn.classList.remove('d-none');

        // restore fade classes on trades card so it appears smoothly
        tradesCard.classList.add('fade-show');
        // restore scroll position into view
        window.scrollTo(0, tradesCard.__savedScroll || 0);
      }, 260);
    });

    minimizeBtn.addEventListener('click', ()=>{
      // remove fade-show from tradesCard for smooth transition
      tradesCard.classList.remove('fade-show');

      // move tradesCard back to original location
      if (containerInserted && originalParent) {
        // move back then remove container
        originalParent.insertBefore(tradesCard, originalNext);
        containerInserted.remove();
        containerInserted = null;
      }

      // show left/right columns but keep them hidden until fade-in
      leftCol.style.display = tradesCard.__originalLeftDisplay || '';
      rightCol.style.display = tradesCard.__originalRightDisplay || '';

      // start with fade-hide removed so they can animate in
      leftCol.classList.remove('fade-hide');
      rightCol.classList.remove('fade-hide');
      leftCol.classList.add('fade-show');
      rightCol.classList.add('fade-show');

      // re-create TradingView widget if there was a current symbol
      // If you want to keep the last symbol, the loadChart will handle avoidance of re-creation
      // delay slightly to allow fade-in
      setTimeout(()=>{
        // restore tradesCard sizing
        tradesCard.style.width = '';
        // try to re-load the first open position symbol if available and not already loaded
        try {
          const firstSymbolCell = document.querySelector('#positionsTableBody tr td strong');
          if (firstSymbolCell && !currentTvSymbol) {
            const raw = firstSymbolCell.textContent || '';
            const tvsym = normalizeForTV(raw);
            if (tvsym.includes(':')) loadChart(tvsym);
            else loadChart('BINANCE:' + tvsym.replace('.P',''));
          }
        } catch(e){}

        // restore controls
        maximizeBtn.classList.remove('d-none');
        minimizeBtn.classList.add('d-none');

        // restore scroll position saved earlier
        if (typeof tradesCard.__savedScroll !== 'undefined') window.scrollTo(0, tradesCard.__savedScroll || 0);
      }, 300);
    });
  }
});
