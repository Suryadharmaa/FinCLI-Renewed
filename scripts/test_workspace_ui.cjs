/* Offline DOM regressions for shared browser/desktop workspace interactions. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");
const root = path.join(__dirname, "../fincli/app/web/static");
const html = fs
  .readFileSync(path.join(root, "index.html"), "utf8")
  .replace(/<script[^>]*>[\s\S]*?<\/script>/g, "");
const dom = new JSDOM(html, {
  url: "http://127.0.0.1:19850",
  runScripts: "dangerously",
});
const window = dom.window;
const jobs = new Map();
let sequence = 0;
let pendingAapl = null;
const requests = [];
const result = (kind, data, symbol = "") => ({
  kind,
  data,
  symbol,
  contract: "3.0",
  status: "ok",
  provenance: {
    source: "offline",
    retrieved_at: "2025-12-31",
    verification: "fixture",
  },
  warnings: [],
});
function fixture(action, params) {
  const symbol = params.symbol;
  if (action === "market")
    return result(
      "market",
      {
        quote: { price: symbol === "MSFT" ? 222 : 111, currency: "USD" },
        candles: [
          {
            timestamp: "2025-01-01",
            open: 10,
            high: 12,
            low: 9,
            close: 11,
            volume: 100,
          },
          {
            timestamp: "2025-01-02",
            open: null,
            high: null,
            low: null,
            close: null,
          },
        ],
        technical: { rsi: 35 },
      },
      symbol,
    );
  if (action === "company")
    return result(
      "company",
      {
        profile: {
          longBusinessSummary: '<img src=x onerror="window.injected=true">',
        },
        statements: {},
        ratios: [],
        events: [],
        missing: ["consensus_estimates"],
      },
      symbol,
    );
  if (action === "news")
    return result(
      "news",
      {
        items: [
          { title: "Safe news", url: "javascript:alert(1)", source: "fixture" },
        ],
      },
      symbol,
    );
  if (action === "screen")
    return result("screen", {
      id: "screen1",
      rows: [
        {
          symbol: "AAPL",
          passed: true,
          period: "2025-12-31",
          missing_fields: [],
          metrics: {},
          comparisons: [],
        },
      ],
    });
  if (action === "workflow")
    return result("workflow", {
      id: "flow1",
      summary: "Evidence [1:D1]",
      steps: [
        { tool: "documents", status: "ok", result: { data: { evidence: [] } } },
      ],
    });
  if (action === "valuation")
    return result("valuation", {
      enterprise_value: 1000,
      equity_value: 1000,
      per_share: 100,
      sensitivity: [{ growth: 0.05, discount: 0.1, per_share: 100 }],
    });
  if (action === "peers")
    return result("peers", {
      rows: [
        {
          symbol: "AAPL",
          financial_currency: "USD",
          metrics: { period: "2025-12-31" },
        },
      ],
    });
  if (action === "backtest")
    return result("experiment", {
      id: "experiment1",
      backtest: { total_return: 10 },
    });
  if (action === "documents")
    return result("document_evidence", {
      evidence: [
        {
          document_id: "doc1",
          page: 1,
          citation_id: "D1",
          title: 'Report " margin',
          quote: "Margin risk",
        },
      ],
    });
  if (action === "portfolio")
    return result("portfolio_intelligence", {
      base_currency: "USD",
      valued_total: 0,
      positions: [],
      scenario: { delta: 0 },
      rebalance_preview: [],
      estimated_fees: 0,
      attribution_method: "fixed holding fixture",
    });
  throw new Error(`Missing fixture: ${action}`);
}
window.fetch = async (url, options = {}) => {
  const parsed = new URL(url, window.location.href),
    endpoint = parsed.pathname;
  const body = options.body ? JSON.parse(options.body) : {};
  requests.push({ endpoint, method: options.method || "GET", body });
  let payload;
  if (endpoint === "/api/workspace/layouts")
    payload =
      options.method === "POST"
        ? body
        : {
            layouts: ["research", "trading", "portfolio", "macro"].map(
              (name) => ({
                name,
                panels:
                  name === "portfolio"
                    ? ["portfolio", "watchlist"]
                    : ["chart", "company", "news", "documents"],
                symbols: ["AAPL"],
                symbol: "AAPL",
                interval: "1d",
              }),
            ),
          };
  else if (endpoint === "/api/workspace/documents")
    payload = { documents: [{ title: 'Report " margin', symbol: "AAPL" }] };
  else if (endpoint === "/api/workspace/documents/doc1/1")
    payload = {
      title: 'Report " margin',
      page: 1,
      text: "Margin risk evidence",
    };
  else if (endpoint === "/api/workspace/watchlist")
    payload = { items: [{ symbol: "AAPL" }, { symbol: "MSFT" }] };
  else if (endpoint === "/api/workspace/jobs") {
    const id = `job${++sequence}`;
    jobs.set(id, {
      status: "completed",
      result: fixture(body.action, body.params),
    });
    if (
      pendingAapl &&
      body.action === "market" &&
      body.params.symbol === "AAPL"
    )
      await pendingAapl;
    payload = { id };
  } else if (endpoint === "/api/workspace/job-status")
    payload = {
      jobs: Object.fromEntries(
        (parsed.searchParams.get("ids") || "")
          .split(",")
          .filter(Boolean)
          .map((id) => [id, jobs.get(id)]),
      ),
    };
  else if (endpoint.startsWith("/api/workspace/jobs/"))
    payload = { status: "cancelled" };
  else if (endpoint === "/api/workspace/tradingview")
    payload = result("tradingview_capabilities", {
      configured: false,
      orders: false,
    });
  else throw new Error(`Unexpected API: ${endpoint}`);
  return { ok: true, json: async () => payload };
};
const script = window.document.createElement("script");
script.textContent =
  fs.readFileSync(path.join(root, "app.js"), "utf8") +
  "\n" +
  fs.readFileSync(path.join(root, "workspace.js"), "utf8");
window.document.body.append(script);
window.eval(
  'pause = () => new Promise(resolve => setTimeout(resolve, 1)); token = "test-token";',
);
const tick = () => new Promise((resolve) => setTimeout(resolve, 30));
async function submit(action, values) {
  window[action]();
  const form = window.document.querySelector("#ws-task form");
  for (const [name, value] of Object.entries(values))
    form.elements[name].value = value;
  form.dispatchEvent(
    new window.Event("submit", { bubbles: true, cancelable: true }),
  );
  await tick();
  assert(
    !window.document.querySelector("#ws-task .ws-progress"),
    `${action} did not finish`,
  );
  assert(
    !window.document
      .querySelector("#ws-task")
      .textContent.includes("operation failed"),
  );
}
(async () => {
  await window.renderCockpit();
  await tick();
  assert(window.document.querySelector(".ws-chart svg"));
  assert(!window.document.querySelector(".ws-chart").innerHTML.includes("NaN"));
  assert.equal(window.document.querySelectorAll(".ws-data img").length, 0);
  assert.equal(
    window.document.querySelectorAll('.ws-news a[href^="javascript:"]').length,
    0,
  );
  assert(window.escapeHtml('" onerror="x').startsWith("&quot;"));
  const docs = window.document.querySelector(".ws-doc-results").parentElement;
  const search = docs.querySelector("form");
  search.elements.query.value = "margin";
  search.dispatchEvent(new window.Event("submit", { cancelable: true }));
  await tick();
  docs.querySelector("[data-doc]").click();
  await tick();
  assert(
    window.document
      .querySelector(".workspace-dialog")
      .textContent.includes("Margin risk evidence"),
  );
  window.document.dispatchEvent(
    new window.KeyboardEvent("keydown", { key: "Escape" }),
  );
  assert.equal(window.document.querySelector(".workspace-dialog"), null);
  await submit("screenForm", { symbols: "AAPL,MSFT", expression: "rsi < 40" });
  assert(window.document.querySelector("[data-xlsx]"));
  await submit("workflowForm", { query: "Explain AAPL risk" });
  assert(
    window.document
      .querySelector("#ws-task")
      .textContent.includes("Evidence [1:D1]"),
  );
  await submit("valuationForm", {});
  await submit("compareForm", { symbols: "AAPL,MSFT" });
  await submit("experimentForm", { symbol: "AAPL", asset_class: "crypto" });
  const layout = window.document.querySelector("#ws-layout");
  layout.value = "portfolio";
  layout.dispatchEvent(new window.Event("change"));
  await tick();
  assert(window.document.querySelectorAll("[data-symbol]").length >= 3);
  const portfolio = window.document.querySelector(".ws-task-form");
  portfolio.dispatchEvent(new window.Event("submit", { cancelable: true }));
  await tick();
  assert(
    window.document
      .querySelector(".ws-portfolio-result")
      .textContent.includes("Valued total"),
  );
  layout.value = "research";
  layout.dispatchEvent(new window.Event("change"));
  await tick();
  let release;
  pendingAapl = new Promise((resolve) => {
    release = resolve;
  });
  window.selectCockpitSymbol("AAPL");
  window.selectCockpitSymbol("MSFT");
  await tick();
  release();
  pendingAapl = null;
  await tick();
  assert(
    window.document.querySelector(".ws-quote").textContent.includes("222"),
  );
  assert(
    !window.document.querySelector(".ws-quote").textContent.includes("111"),
  );
  window.document.querySelector("#ws-save").click();
  await tick();
  assert(
    requests.some(
      (r) =>
        r.endpoint === "/api/workspace/layouts" && r.body.symbol === "MSFT",
    ),
  );
  assert(
    requests.some(
      (r) => r.method === "DELETE" && r.endpoint.includes("/jobs/"),
    ),
  );
  window.tvForm();
  window.document
    .querySelector("#ws-task form")
    .dispatchEvent(new window.Event("submit", { cancelable: true }));
  await tick();
  assert(
    window.document
      .querySelector(".ws-tv-result")
      .textContent.includes('"orders": false'),
  );
  dom.window.close();
  console.log(
    "Workspace UI: linked symbols, stale response cancellation, safe rendering, citations, layouts, screen, DCF, portfolio, workflow, experiments, and optional bridge passed.",
  );
})().catch((error) => {
  dom.window.close();
  console.error(error);
  process.exitCode = 1;
});
