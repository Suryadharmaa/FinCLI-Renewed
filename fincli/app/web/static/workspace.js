/* FinCLI v3 connected panels. All HTML data is escaped; results are epoch-bound. */
let cockpitEpoch = 0;
let cockpitLayout = {
  name: "research",
  panels: ["chart", "company", "news", "documents"],
  symbols: [],
  symbol: "",
  interval: "1d",
};
const cockpitJobs = new Set();
const numberText = (value) =>
  typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString(undefined, { maximumFractionDigits: 3 })
    : value == null
      ? "N/A"
      : String(value);
const wsText = (value) => escapeHtml(numberText(value));
function wsTable(headers, rows) {
  return `<div class="ws-table-scroll"><table><thead><tr>${headers.map((h) => `<th>${escapeHtml(h)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((c) => `<td>${wsText(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
function wsMetadata(output) {
  return `<div class="ws-provenance">${escapeHtml(output.provenance?.source)} · ${escapeHtml(output.provenance?.retrieved_at)} · ${escapeHtml(output.status)}<br>${escapeHtml(output.provenance?.verification)}</div>${(output.warnings || []).map((w) => `<p class="ws-warning">${escapeHtml(w)}</p>`).join("")}`;
}
function wsError(node, error) {
  if (node?.isConnected)
    node.innerHTML = `<p class="ws-warning">${escapeHtml(getErrorMessage(error))}</p>`;
}
async function cancelCockpitJobs() {
  for (const id of cockpitJobs)
    api(`/api/workspace/jobs/${id}`, { method: "DELETE" }).catch(() => {});
  cockpitJobs.clear();
}
async function workspaceJob(action, params, node, epoch = cockpitEpoch) {
  const job = await api("/api/workspace/jobs", {
    method: "POST",
    body: JSON.stringify({ action, params }),
  });
  if (epoch !== cockpitEpoch || !node.isConnected) {
    await api(`/api/workspace/jobs/${job.id}`, { method: "DELETE" });
    return null;
  }
  cockpitJobs.add(job.id);
  wsStatusPromise = null;
  node.innerHTML = `<p class="ws-progress">Working: ${escapeHtml(action)}</p><button type="button" data-cancel-job>Cancel</button>`;
  const cancel = () =>
    api(`/api/workspace/jobs/${job.id}`, { method: "DELETE" }).catch((error) =>
      wsError(node, error),
    );
  node.querySelector("[data-cancel-job]").onclick = cancel;
  try {
    for (let attempt = 0; attempt < 300; attempt++) {
      await pause(4000);
      if (epoch !== cockpitEpoch || !node.isConnected) {
        await cancel();
        return null;
      }
      const states = await workspaceStates();
      const state = states.jobs[job.id];
      if (!state) continue;
      if (state.status === "completed") return state.result;
      if (state.status === "failed") throw new Error(state.error);
      if (state.status === "cancelled") {
        node.textContent = "Cancelled";
        return null;
      }
      node.querySelector(".ws-progress").textContent =
        `${state.message} · ${state.progress}%`;
    }
    await cancel();
    throw new Error("Job exceeded the UI wait limit.");
  } catch (error) {
    await cancel();
    throw error;
  } finally {
    cockpitJobs.delete(job.id);
  }
}
async function renderCockpit() {
  cockpitEpoch++;
  cancelCockpitJobs();
  const epoch = cockpitEpoch;
  $("#chat-title").textContent = "Connected workspace";
  $("#view-content").innerHTML =
    `<section class="ws-shell"><div class="ws-heading"><div><span class="context-kicker">FINCLI 3.0</span><h1>Connected investment workspace</h1><p>Select an instrument. Every linked panel follows.</p></div><select id="ws-layout" aria-label="Workspace layout"></select></div><form id="ws-symbol-form" class="ws-toolbar"><input id="ws-symbol" placeholder="Ticker, e.g. AAPL or BBRI.JK" aria-label="Instrument"><select id="ws-interval" aria-label="Chart timeframe">${["1m", "5m", "15m", "30m", "1h", "1d", "1wk", "1mo"].map((i) => `<option>${i}</option>`).join("")}</select><button type="submit">Open instrument</button><button type="button" id="ws-save">Save layout</button><button type="button" id="ws-edit">Edit panels</button></form><div id="ws-tabs" class="ws-tabs"></div><div class="ws-tools"><button id="ws-compare">Compare companies</button><button id="ws-screen">Fundamental + technical screen</button><button id="ws-valuation">DCF sensitivity</button><button id="ws-workflow">AI research workflow</button><button id="ws-experiment">Strategy experiment</button><button id="ws-tv">TradingView bridge</button></div><div id="ws-task"></div><div id="ws-panels" class="ws-panels"></div></section>`;
  try {
    const response = await api("/api/workspace/layouts");
    if (epoch !== cockpitEpoch) return;
    const layouts = response.layouts;
    cockpitLayout =
      layouts.find((l) => l.name === cockpitLayout.name) || layouts[0];
    $("#ws-layout").innerHTML = layouts
      .map(
        (l) =>
          `<option value="${escapeHtml(l.name)}">${escapeHtml(l.name)}</option>`,
      )
      .join("");
    $("#ws-layout").value = cockpitLayout.name;
    $("#ws-layout").onchange = (event) => {
      cockpitLayout = layouts.find((l) => l.name === event.target.value);
      drawCockpit();
    };
    $("#ws-symbol-form").onsubmit = (event) => {
      event.preventDefault();
      selectCockpitSymbol($("#ws-symbol").value);
    };
    $("#ws-interval").onchange = (event) => {
      cockpitLayout.interval = event.target.value;
      drawCockpit();
    };
    $("#ws-save").onclick = async () => {
      try {
        await api("/api/workspace/layouts", {
          method: "POST",
          body: JSON.stringify(cockpitLayout),
        });
        $("#ws-save").textContent = "Saved";
      } catch (error) {
        wsError($("#ws-task"), error);
      }
    };
    $("#ws-edit").onclick = editPanels;
    $("#ws-compare").onclick = compareForm;
    $("#ws-screen").onclick = screenForm;
    $("#ws-valuation").onclick = valuationForm;
    $("#ws-workflow").onclick = workflowForm;
    $("#ws-tv").onclick = tvForm;
    $("#ws-experiment").onclick = experimentForm;
    drawCockpit();
  } catch (error) {
    wsError($("#ws-task"), error);
  }
}
function selectCockpitSymbol(value) {
  const symbol = value.trim().toUpperCase();
  if (!/^[A-Z0-9^][A-Z0-9.:^_!\/-]{0,39}$/.test(symbol)) {
    wsError($("#ws-task"), "Enter a valid instrument.");
    return;
  }
  cockpitLayout.symbol = symbol;
  if (!cockpitLayout.symbols.includes(symbol))
    cockpitLayout.symbols = [...cockpitLayout.symbols, symbol].slice(-12);
  drawCockpit();
}
function drawCockpit() {
  cockpitEpoch++;
  cancelCockpitJobs();
  $("#ws-task").innerHTML = "";
  $("#ws-symbol").value = cockpitLayout.symbol;
  $("#ws-interval").value = cockpitLayout.interval;
  $("#ws-tabs").innerHTML = cockpitLayout.symbols
    .map(
      (s) =>
        `<button data-symbol="${escapeHtml(s)}" class="${s === cockpitLayout.symbol ? "selected" : ""}">${escapeHtml(s)}</button>`,
    )
    .join("");
  $("#ws-tabs")
    .querySelectorAll("[data-symbol]")
    .forEach((b) => (b.onclick = () => selectCockpitSymbol(b.dataset.symbol)));
  $("#ws-panels").innerHTML = cockpitLayout.panels
    .map(
      (panel, index) =>
        `<section class="ws-panel"><header><h2>${escapeHtml(panel)}</h2><small>${escapeHtml(cockpitLayout.symbol || "Local workspace")}</small></header><div id="ws-panel-${index}"></div></section>`,
    )
    .join("");
  cockpitLayout.panels.forEach((panel, index) =>
    loadCockpitPanel(panel, $(`#ws-panel-${index}`), cockpitEpoch),
  );
}
function editPanels() {
  const node = $("#ws-task");
  node.innerHTML = `<form id="ws-panel-editor"><h2>Choose panels</h2>${["chart", "company", "news", "documents", "technical", "portfolio", "watchlist", "macro"].map((p) => `<label><input type="checkbox" name="panel" value="${p}" ${cockpitLayout.panels.includes(p) ? "checked" : ""}> ${p}</label>`).join("")}<label>Layout name <input name="layout" value="${escapeHtml(cockpitLayout.name)}" required pattern="[a-zA-Z0-9_-]{1,40}"></label><button>Apply</button></form>`;
  $("#ws-panel-editor").onsubmit = (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const panels = [...form.querySelectorAll("[name=panel]:checked")].map(
      (i) => i.value,
    );
    if (!panels.length) return;
    cockpitLayout = {
      ...cockpitLayout,
      name: form.elements.layout.value,
      panels,
    };
    node.innerHTML = "";
    drawCockpit();
  };
}
async function loadCockpitPanel(panel, node, epoch) {
  try {
    const symbol = cockpitLayout.symbol;
    if (panel === "watchlist") {
      const data = await api("/api/workspace/watchlist");
      if (epoch !== cockpitEpoch) return;
      const rows = Array.isArray(data)
        ? data
        : data.positions || data.watchlist || data.items || [];
      node.innerHTML = rows.length
        ? rows
            .map(
              (r) =>
                `<button data-symbol="${escapeHtml(r.symbol)}">${escapeHtml(r.symbol)}</button>`,
            )
            .join("")
        : "Your watchlist is empty. Add symbols with /watchlist add.";
      node
        .querySelectorAll("[data-symbol]")
        .forEach(
          (b) => (b.onclick = () => selectCockpitSymbol(b.dataset.symbol)),
        );
      return;
    }
    if (panel === "documents") {
      documentPanel(node, symbol, epoch);
      return;
    }
    if (panel === "portfolio") {
      portfolioForm(node, epoch);
      return;
    }
    if (panel === "macro") {
      node.innerHTML = `<button data-load-macro>Load economic indicators</button><div></div>`;
      node.querySelector("button").onclick = async () => {
        try {
          const out = await api("/api/command", {
            method: "POST",
            body: JSON.stringify({ command: "/macro" }),
          });
          if (epoch === cockpitEpoch)
            node.querySelector("div").innerHTML =
              (out.tables || [])
                .map((t) => wsTable(t.columns, t.rows))
                .join("") ||
              `<pre>${escapeHtml(out.text || out.message)}</pre>`;
        } catch (e) {
          wsError(node, e);
        }
      };
      return;
    }
    if (!symbol) {
      node.textContent = "Open an instrument to load this panel.";
      return;
    }
    const action =
      panel === "chart" || panel === "technical" ? "market" : panel;
    const output = await workspaceJob(
      action,
      { symbol, interval: cockpitLayout.interval },
      node,
      epoch,
    );
    if (!output || epoch !== cockpitEpoch) return;
    node.innerHTML = wsMetadata(output) + `<div class="ws-data"></div>`;
    const target = node.querySelector(".ws-data");
    if (panel === "chart") chartPanel(target, output.data);
    else if (panel === "technical")
      target.innerHTML = wsTable(
        ["Indicator", "Value"],
        Object.entries(output.data.technical || {}).map(([k, v]) => [k, v]),
      );
    else if (panel === "company") companyPanel(target, output.data);
    else if (panel === "news") {
      target.innerHTML =
        (output.data.items || [])
          .map((item) => {
            let url = "";
            try {
              const u = new URL(item.url);
              if (["http:", "https:"].includes(u.protocol)) url = u.href;
            } catch {}
            return `<article class="ws-news"><strong>${escapeHtml(item.title)}</strong><p>${escapeHtml(item.summary || "")}</p><small>${escapeHtml(item.source)} · ${escapeHtml(item.published_at || "Date unavailable")}</small>${url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">Open source</a>` : ""}</article>`;
          })
          .join("") || "No news returned.";
    }
  } catch (error) {
    if (epoch === cockpitEpoch) wsError(node, error);
  }
}
function chartPanel(node, data) {
  const candles = (data.candles || []).filter((c) =>
    [c.open, c.high, c.low, c.close].every(
      (v) => typeof v === "number" && Number.isFinite(v),
    ),
  );
  if (!candles.length) {
    node.textContent = "No chart data available.";
    return;
  }
  node.innerHTML = `<div class="ws-quote">${wsText(data.quote?.price)} ${escapeHtml(data.quote?.currency)} <small>${escapeHtml(data.quote?.status)} · ${escapeHtml(data.quote?.timestamp)}</small></div><div class="ws-chart"></div><label>Visible bars <input type="range" min="${Math.min(10, candles.length)}" max="${candles.length}" value="${Math.min(100, candles.length)}"></label><div class="ws-chart-readout"></div>`;
  const draw = () => {
    const rows = candles.slice(-Number(node.querySelector("input").value));
    const low = Math.min(...rows.map((c) => c.low)),
      high = Math.max(...rows.map((c) => c.high)),
      span = high - low || 1;
    const y = (v) => 210 - ((v - low) / span) * 180;
    const step = 600 / rows.length;
    node.querySelector(".ws-chart").innerHTML =
      `<svg viewBox="0 0 640 240" role="img" aria-label="OHLC candlestick chart">${rows
        .map((c, i) => {
          const x = 20 + (i + 0.5) * step;
          const color = c.close >= c.open ? "#3faf9b" : "#e77870";
          return `<g data-index="${i}"><title>${escapeHtml(c.timestamp)} O ${c.open} H ${c.high} L ${c.low} C ${c.close}</title><line x1="${x}" x2="${x}" y1="${y(c.high)}" y2="${y(c.low)}" stroke="${color}"/><rect x="${x - step * 0.3}" y="${Math.min(y(c.open), y(c.close))}" width="${Math.max(0.6, step * 0.6)}" height="${Math.max(1, Math.abs(y(c.open) - y(c.close)))}" fill="${color}"/></g>`;
        })
        .join(
          "",
        )}<text x="4" y="18" fill="currentColor" font-size="11">${wsText(high)}</text><text x="4" y="235" fill="currentColor" font-size="11">${wsText(low)}</text></svg>`;
    node.querySelectorAll("[data-index]").forEach(
      (g) =>
        (g.onmouseenter = () => {
          const c = rows[Number(g.dataset.index)];
          node.querySelector(".ws-chart-readout").textContent =
            `${c.timestamp} · O ${numberText(c.open)} H ${numberText(c.high)} L ${numberText(c.low)} C ${numberText(c.close)} V ${numberText(c.volume)}`;
        }),
    );
  };
  node.querySelector("input").oninput = draw;
  draw();
}
function companyPanel(node, data) {
  node.innerHTML = `<h3>${escapeHtml(data.profile?.longName || "Company")}</h3><p>${escapeHtml(data.profile?.longBusinessSummary || "Profile unavailable")}</p><p>${escapeHtml(data.profile?.sector || "")} · ${escapeHtml(data.profile?.industry || "")}</p>${wsTable(
    ["Period", "Growth %", "Margin %", "D/E", "ROE %"],
    (data.ratios || []).map((r) => [
      r.period,
      r.revenue_growth,
      r.net_margin,
      r.debt_to_equity,
      r.roe,
    ]),
  )}${Object.entries(data.statements || {})
    .map(
      ([name, periods]) =>
        `<details><summary>${escapeHtml(name)} · ${escapeHtml(data.financial_currency || "Currency unavailable")}</summary>${wsTable(
          ["Metric", ...periods.map((p) => p.period)],
          [...new Set(periods.flatMap((p) => Object.keys(p.values)))].map(
            (metric) => [metric, ...periods.map((p) => p.values[metric])],
          ),
        )}</details>`,
    )
    .join("")}<details><summary>Events</summary>${wsTable(
    ["Event", "Value", "Kind"],
    (data.events || []).map((e) => [e.event, e.value, e.kind]),
  )}</details><p class="ws-warning">Missing: ${escapeHtml((data.missing || []).join(", "))}</p>`;
}
async function documentPanel(node, symbol, epoch) {
  node.innerHTML = `<label>Import PDF / TXT / MD <input type="file" accept=".pdf,.txt,.md"></label><div class="ws-doc-list"></div><form><input name="query" placeholder="Search document evidence" required><button>Search</button></form><div class="ws-doc-results"></div>`;
  const refresh = async () => {
    const response = await api(
      `/api/workspace/documents?symbol=${encodeURIComponent(symbol)}`,
    );
    if (epoch === cockpitEpoch && node.isConnected)
      node.querySelector(".ws-doc-list").innerHTML =
        response.documents
          .map((d) => `<p>${escapeHtml(d.title)} · ${escapeHtml(d.symbol)}</p>`)
          .join("") || "No documents imported.";
  };
  refresh().catch((e) => wsError(node, e));
  node.querySelector("[type=file]").onchange = async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    const target = node.querySelector(".ws-doc-results");
    try {
      if (file.size > 8 * 1024 * 1024)
        throw new Error("Maximum document size is 8 MiB.");
      const bytes = new Uint8Array(await file.arrayBuffer());
      let binary = "";
      for (let i = 0; i < bytes.length; i += 8192)
        binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
      await api("/api/workspace/documents", {
        method: "POST",
        body: JSON.stringify({
          title: file.name,
          content: btoa(binary),
          symbol,
        }),
      });
      if (epoch === cockpitEpoch) {
        await refresh();
        target.textContent = "Imported.";
      }
    } catch (e) {
      wsError(target, e);
    }
  };
  node.querySelector("form").onsubmit = async (event) => {
    event.preventDefault();
    const target = node.querySelector(".ws-doc-results");
    try {
      const out = await workspaceJob(
        "documents",
        { query: event.currentTarget.elements.query.value, symbol },
        target,
        epoch,
      );
      if (!out) return;
      target.innerHTML =
        wsMetadata(out) +
        (out.data.evidence || [])
          .map(
            (hit) =>
              `<article class="ws-evidence"><button data-doc="${escapeHtml(hit.document_id)}" data-page="${hit.page}">[${escapeHtml(hit.citation_id)}] ${escapeHtml(hit.title)} · page ${hit.page}</button><pre>${escapeHtml(hit.quote)}</pre></article>`,
          )
          .join("");
      target.querySelectorAll("[data-doc]").forEach(
        (button) =>
          (button.onclick = async () => {
            try {
              const page = await api(
                `/api/workspace/documents/${button.dataset.doc}/${button.dataset.page}`,
              );
              $("#modal-root").innerHTML =
                `<div class="modal-backdrop"><section class="workspace-dialog"><button data-close-page>Close</button><h2>${escapeHtml(page.title)} · ${page.page}</h2><pre>${escapeHtml(page.text)}</pre></section></div>`;
              $("[data-close-page]").onclick = () =>
                ($("#modal-root").innerHTML = "");
            } catch (e) {
              wsError(target, e);
            }
          }),
      );
    } catch (e) {
      wsError(target, e);
    }
  };
}
function wsTaskForm(title, fields, action, params, display) {
  const node = $("#ws-task");
  node.innerHTML = `<section class="ws-panel"><h2>${escapeHtml(title)}</h2><form class="ws-task-form">${fields}<button>Run analysis</button></form><div class="ws-task-result"></div></section>`;
  node.querySelector("form").onsubmit = async (event) => {
    event.preventDefault();
    const target = node.querySelector(".ws-task-result");
    try {
      const input = params(new FormData(event.currentTarget));
      const out = await workspaceJob(action, input, target);
      if (!out) return;
      target.innerHTML = wsMetadata(out);
      const body = document.createElement("div");
      target.append(body);
      display(body, out);
    } catch (e) {
      wsError(target, e);
    }
  };
}
function compareForm() {
  wsTaskForm(
    "Compare aligned financial periods",
    `<label>Companies <input name="symbols" placeholder="AAPL,MSFT" required></label>`,
    "peers",
    (f) => ({
      symbols: String(f.get("symbols"))
        .split(",")
        .map((s) => s.trim()),
    }),
    (node, out) => {
      node.innerHTML = wsTable(
        ["Company", "Currency", "Period", "Growth %", "Margin %", "D/E"],
        out.data.rows.map((r) => [
          r.symbol,
          r.financial_currency,
          r.metrics?.period,
          r.metrics?.revenue_growth,
          r.metrics?.net_margin,
          r.metrics?.debt_to_equity,
        ]),
      );
    },
  );
}
function screenForm() {
  wsTaskForm(
    "Fundamental + technical screen",
    `<label>Symbols <input name="symbols" placeholder="AAPL,MSFT or leave empty for watchlist"></label><label>Expression <input name="expression" value="revenue_growth > 10% and rsi < 40" required></label>`,
    "screen",
    (f) => ({
      symbols: String(f.get("symbols")).trim()
        ? String(f.get("symbols"))
            .split(",")
            .map((s) => s.trim())
        : [],
      expression: String(f.get("expression")),
    }),
    (node, out) => {
      node.innerHTML =
        wsTable(
          ["Symbol", "Passed", "Period", "Missing"],
          out.data.rows.map((r) => [
            r.symbol,
            r.passed,
            r.period,
            r.missing_fields.join(", "),
          ]),
        ) +
        `<button data-export>Download JSON</button><button data-xlsx>Download Excel</button><details><summary>Reasons and metrics</summary><pre>${escapeHtml(JSON.stringify(out.data.rows, null, 2))}</pre></details>`;
      node.querySelector("[data-export]").onclick = () =>
        downloadJson(out, out.data.id);
      node.querySelector("[data-xlsx]").onclick = () =>
        downloadExcel(out.data.id);
    },
  );
}
function valuationForm() {
  wsTaskForm(
    "DCF — explicit assumptions",
    `<p>Use unlevered free cash flow. Rates are decimals; cash/debt/FCF share one currency.</p>${[
      ["fcf", "Unlevered FCF", "100"],
      ["growth", "Growth", "0.05"],
      ["discount", "Discount rate", "0.1"],
      ["terminal", "Terminal growth", "0.02"],
      ["cash", "Cash", "0"],
      ["debt", "Debt", "0"],
      ["shares", "Shares outstanding", "1"],
    ]
      .map(
        ([name, label, value]) =>
          `<label>${label}<input name="${name}" type="number" step="any" value="${value}" required></label>`,
      )
      .join("")}`,
    "valuation",
    (f) => Object.fromEntries([...f.entries()].map(([k, v]) => [k, Number(v)])),
    (node, out) => {
      node.innerHTML =
        wsTable(
          ["Enterprise", "Equity", "Per share"],
          [
            [
              out.data.enterprise_value,
              out.data.equity_value,
              out.data.per_share,
            ],
          ],
        ) +
        wsTable(
          ["Growth", "Discount", "Per share"],
          out.data.sensitivity.map((r) => [r.growth, r.discount, r.per_share]),
        );
    },
  );
}
function workflowForm() {
  wsTaskForm(
    "AI research workflow",
    `<label>Research request <textarea name="query" placeholder="Compare AAPL and MSFT and explain my portfolio exposure" required></textarea></label>`,
    "workflow",
    (f) => ({ query: String(f.get("query")) }),
    (node, out) => {
      node.innerHTML = `<pre>${escapeHtml(out.data.summary || "AI summary unavailable; inspect evidence below.")}</pre><button data-export>Download evidence</button>${out.data.steps.map((step, i) => `<details><summary>${i + 1}. ${escapeHtml(step.tool)} · ${escapeHtml(step.status)}</summary><pre>${escapeHtml(JSON.stringify(step.result || step.error, null, 2))}</pre></details>`).join("")}`;
      node.querySelector("[data-export]").onclick = () =>
        downloadJson(out, out.data.id);
    },
  );
}
function portfolioForm(node, epoch) {
  node.innerHTML = `<form class="ws-task-form"><label>Base currency <input name="base_currency" value="USD" required></label><label>Price shock % <input name="shock" type="number" value="-20" min="-100" max="500"></label><label>FX shock % <input name="fx_shock" type="number" value="0" min="-100" max="500"></label><label>Fees (bps) <input name="fee_bps" type="number" value="10" min="0" max="10000"></label><label>Benchmark (optional) <input name="benchmark" placeholder="SPY"></label><label>Window start FX to base (JSON) <input name="start_fx" value='{}'></label><label>Current FX to base (JSON) <input name="fx" value='{}' placeholder='{"IDR":0.00006}'></label><label>Entry FX to base (JSON) <input name="entry_fx" value='{}'></label><button>Value and stress portfolio</button></form><div class="ws-portfolio-result"></div>`;
  node.querySelector("form").onsubmit = async (event) => {
    event.preventDefault();
    const target = node.querySelector(".ws-portfolio-result");
    try {
      const f = new FormData(event.currentTarget);
      const out = await workspaceJob(
        "portfolio",
        {
          base_currency: f.get("base_currency"),
          shock: Number(f.get("shock")) / 100,
          fx_shock: Number(f.get("fx_shock")) / 100,
          fee_bps: Number(f.get("fee_bps")),
          fx: JSON.parse(f.get("fx")),
          entry_fx: JSON.parse(f.get("entry_fx")),
          start_fx: JSON.parse(f.get("start_fx")),
          benchmark: f.get("benchmark"),
        },
        target,
        epoch,
      );
      if (!out) return;
      const d = out.data;
      target.innerHTML =
        wsMetadata(out) +
        `<p>Valued total: ${wsText(d.valued_total)} ${escapeHtml(d.base_currency)} · stress delta: ${wsText(d.scenario.delta)}</p>` +
        wsTable(
          ["Symbol", "Value", "Weight %", "Price PnL", "FX PnL"],
          d.positions.map((r) => [
            r.symbol,
            r.market_value,
            r.weight_pct,
            r.price_contribution,
            r.fx_contribution,
          ]),
        ) +
        `<details><summary>Equal-weight rebalance preview · fees ${wsText(d.estimated_fees)}</summary>${wsTable(
          ["Symbol", "Quantity change", "Base change"],
          d.rebalance_preview.map((r) => [
            r.symbol,
            r.quantity_delta,
            r.delta_base,
          ]),
        )}</details><p>${escapeHtml(d.attribution_method)}</p>${d.benchmark ? `<details><summary>Benchmark comparison</summary><pre>${escapeHtml(JSON.stringify(d.benchmark, null, 2))}</pre></details>` : ""}`;
    } catch (e) {
      wsError(target, e);
    }
  };
}
function tvForm() {
  const node = $("#ws-task");
  node.innerHTML = `<section class="ws-panel"><h2>Optional TradingView bridge</h2><p>Connect a separately installed local bridge. UI APIs are unofficial and account permissions apply.</p><form><select name="action">${["capabilities", "status", "chart", "symbol", "timeframe", "indicator", "draw", "pine", "replay", "screenshot"].map((a) => `<option>${a}</option>`).join("")}</select><input name="value" placeholder="Symbol / timeframe / indicator / price"><label><input type="checkbox" name="confirmed"> Confirm chart changes</label><button>Run</button></form><div class="ws-tv-result"></div></section>`;
  node.querySelector("form").onsubmit = async (event) => {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    const action = f.get("action"),
      key = {
        symbol: "symbol",
        timeframe: "timeframe",
        indicator: "name",
        draw: "price",
      }[action];
    try {
      const out = await api("/api/workspace/tradingview", {
        method: "POST",
        body: JSON.stringify({
          action,
          params: key ? { [key]: f.get("value") } : {},
          confirmed: f.has("confirmed"),
        }),
      });
      node.querySelector(".ws-tv-result").innerHTML =
        `<pre>${escapeHtml(JSON.stringify(out, null, 2))}</pre>`;
    } catch (e) {
      wsError(node.querySelector(".ws-tv-result"), e);
    }
  };
}
function downloadJson(data, name) {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `fincli-${name}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function downloadExcel(id) {
  try {
    const response = await fetch(
      `${await desktopUrl()}/api/workspace/runs/${id}/export`,
      { headers: { Authorization: `Bearer ${token.trim()}` } },
    );
    if (!response.ok) throw new Error("Excel export failed");
    const url = URL.createObjectURL(await response.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = `fincli-screen-${id}.xlsx`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (e) {
    wsError($("#ws-task"), e);
  }
}

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && $(".workspace-dialog"))
    $("#modal-root").innerHTML = "";
});

function experimentForm() {
  wsTaskForm(
    "Saved strategy experiment",
    `<label>Symbol <input name="symbol" placeholder="AAPL" required></label><label>Fee profile <select name="asset_class"><option>equity</option><option>etf</option><option>crypto</option><option>forex</option><option>commodity</option><option>index</option></select></label><label>Strategy <select name="strategy"><option>sma_cross</option><option>rsi_reversion</option><option>momentum</option></select></label><label>Period <select name="period"><option>6mo</option><option>1y</option><option>2y</option></select></label>`,
    "backtest",
    (f) => Object.fromEntries(f.entries()),
    (node, out) => {
      node.innerHTML = `<button data-export>Download experiment</button><pre>${escapeHtml(JSON.stringify(out.data.backtest, null, 2))}</pre>`;
      node.querySelector("[data-export]").onclick = () =>
        downloadJson(out, out.data.id);
    },
  );
}

let wsStatusPromise = null;
let wsStatusAt = 0;
function workspaceStates() {
  if (!wsStatusPromise || Date.now() - wsStatusAt > 1000) {
    wsStatusAt = Date.now();
    wsStatusPromise = api(
      `/api/workspace/job-status?ids=${encodeURIComponent([...cockpitJobs].join(","))}`,
    );
  }
  return wsStatusPromise;
}
