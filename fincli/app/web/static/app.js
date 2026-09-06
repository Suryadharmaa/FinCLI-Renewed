const $ = (selector, root = document) => root.querySelector(selector);
const desktop = Boolean(window.__TAURI__?.core?.invoke);
let token = desktop ? "" : localStorage.fincliToken || "";
let desktopBase = "", conversationId = "", sending = false, commands = [], commandSelection = 0;
let capabilities = [], actions = [], activeView = "home";
let pendingConfirmationResolve = null;
let requestSequence = 0;
let visibleMessages = [];
let startupFailed = false;

async function desktopSession() {
  if (!desktop) return "";
  try { return await window.__TAURI__.core.invoke("desktop_session"); } catch { return ""; }
}
async function desktopUrl() {
  if (!desktop) return "";
  if (desktopBase) return desktopBase;
  try { desktopBase = await window.__TAURI__.core.invoke("desktop_url"); return desktopBase; } catch { return ""; }
}
function getErrorMessage(error) {
  if (typeof error === "string") return error;
  if (error instanceof Error) return error.message;
  if (error && typeof error === "object") return error.message || error.detail || error.error || "Request failed.";
  return "Request failed.";
}
function escapeHtml(value) { const div = document.createElement("div"); div.textContent = String(value ?? ""); return div.innerHTML; }
function sanitizeDisplayText(value) { return String(value ?? "").replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, "").replace(/[â•­â•®â•¯â•°â”€â”‚â”Œâ”â””â”˜â”œâ”¤â”¬â”´â”¼â•â•‘â•”â•—â•šâ•]/g, "").split("\n").map(line => line.trim()).filter(Boolean).join("\n"); }
async function api(path, options = {}) {
  const timeoutMs = Number(options.timeoutMs || 120000);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  const fetchOptions = { ...options, signal: controller.signal };
  delete fetchOptions.timeoutMs;
  fetchOptions.headers = { Authorization: `Bearer ${token.trim()}`, "X-FinCLI-CSRF": "local-web", "Content-Type": "application/json", ...(options.headers || {}) };
  let response;
  try { response = await fetch(`${await desktopUrl()}${path}`, fetchOptions); }
  catch (error) { if (error?.name === "AbortError") throw new Error("FinCLI command timed out. Please retry or check the backend log."); throw new Error("Cannot connect to FinCLI local server."); }
  finally { clearTimeout(timeout); }
  let data = null; try { data = await response.json(); } catch { /* non-json error */ }
  if (!response.ok) throw new Error(data?.detail || data?.error || data?.message || `Request failed (status ${response.status})`);
  return data;
}

function pause(milliseconds) { return new Promise(resolve => setTimeout(resolve, milliseconds)); }
async function waitForDesktopStatus() {
  let lastError = new Error("Cannot connect to FinCLI local server.");
  for (let attempt = 1; attempt <= 80; attempt += 1) {
    try { return await api("/api/status"); }
    catch (error) { lastError = error; setStartup(`Starting local engine... ${attempt}/80`); await pause(250); }
  }
  throw lastError;
}

async function connect() {
  setStartup("Connecting to the secure local server...");
  try {
    token = $("#token").value.trim() || token.trim() || await desktopSession();
    if (!token) throw new Error("A local access token is required in browser mode.");
    const status = desktop ? await waitForDesktopStatus() : await api("/api/status");
    if(!desktop)localStorage.fincliToken=token;
    $("#auth").classList.add("hidden"); $("#app").classList.remove("hidden");
    if (status.desktop) document.body.classList.add("desktop-mode");
    $("#startup-message").textContent = "Workspace ready";
    startupFailed = false;
    await Promise.all([loadCapabilities(), loadHistory(), loadModel(), loadTrust()]);
    showView("home");
  } catch (error) {
    startupFailed = true;
    let detail = getErrorMessage(error);
    if (desktop) { try { detail = await window.__TAURI__.core.invoke("desktop_error"); } catch { /* retain connection error */ } }
    setStartup("Workspace could not start"); $("#auth-error").textContent = detail;
    if (desktop) { $("#auth-form").classList.add("retry-visible"); $("#auth-form button").textContent = "Retry startup"; }
  }
}
function setStartup(message) { const node = $("#startup-message"); if (node) node.textContent = message; }
async function loadCapabilities() {
  let data;
  try { data = await api("/api/desktop/capabilities"); }
  catch { data = await api("/api/commands"); }
  capabilities = data.commands || []; actions = data.actions || [];
  commands = capabilities;
}
async function loadModel() {
  try {
    const data = await api("/api/ai/status");
    $("#model").innerHTML = (data.available_providers || []).filter(item => item.has_api_key).map(item => `<option value="${escapeHtml(item.provider)}" data-model="${escapeHtml(item.model)}"${item.active ? " selected" : ""}>${escapeHtml(item.provider)} / ${escapeHtml(item.model)}</option>`).join("") || `<option value="${escapeHtml(data.provider)}" data-model="${escapeHtml(data.model)}">${escapeHtml(data.provider)} / ${escapeHtml(data.model)}</option>`;
  } catch { $("#model").innerHTML = "<option>Local model</option>"; }
}
async function loadTrust() {
  try { const data = await api("/api/providers/status"); $("#trust").textContent = data.ok ? "Trust ready" : "Trust limited"; }
  catch { $("#trust").textContent = "Trust unavailable"; }
}
async function loadHistory() {
  try {
    const rows = await api("/api/conversations");
    $("#history").innerHTML = rows.map(item => `<button data-id="${escapeHtml(item.id)}">${escapeHtml(item.title)}</button>`).join("");
    $("#history").querySelectorAll("[data-id]").forEach(button => button.onclick = () => openChat(button.dataset.id));
  } catch { $("#history").innerHTML = `<span class="history-empty">No history yet</span>`; }
}
async function openChat(id) {
  try {
    const chat = await api(`/api/conversations/${id}`); conversationId = id; activeView = "home";
    $("#view-content").innerHTML = ""; visibleMessages = (chat.messages || []).map(item => ({ kind: "message", role: item.role, content: item.content, command: item.command })); renderMessagePanel(); $("#chat-title").textContent = chat.title;
  } catch (error) { showInlineError(getErrorMessage(error)); }
}
function actionList(group) { return actions.filter(item => item.group === group); }
const VIEW_GROUPS = { research: "Research", market: "Market", portfolio: "Portfolio", trading: "Trading", watchlist: "Watchlist", alerts: "Alerts", journal: "Journal", providers: "Providers", settings: "System" };
const VIEW_COPY = {
  research: ["Research", "Turn market data into a clear, source-aware decision context."], market: ["Market", "Quotes, news, scans, calendars, and provider comparison."], portfolio: ["Portfolio", "See positions, performance, and risk before making a move."], trading: ["Trading", "Paper trading with visible risk controls and audit history."], watchlist: ["Watchlist", "Keep important instruments close and actionable."], alerts: ["Alerts", "Monitor price conditions without leaving your workspace."], journal: ["Journal", "Capture decisions and review the habits behind them."], providers: ["Providers", "Understand data trust, availability, and fallback behavior."], settings: ["System", "Health checks, cache, exports, and secure settings."]
};
function showView(view) {
  activeView = view; $("#sidebar").classList.remove("open"); visibleMessages = []; renderMessagePanel(false);
  document.querySelectorAll(".nav-item").forEach(item => item.classList.toggle("active", item.dataset.view === view));
  $("#chat-title").textContent = view === "home" ? "Home" : VIEW_COPY[view]?.[0] || "Workspace";
  if (view === "home") { renderHome(); return; }
  if (view === "settings") { openSettings(); renderSystem(); return; }
  const [title, description] = VIEW_COPY[view];
  $("#view-content").innerHTML = `<section class="view-header"><div><span class="context-kicker">FINCLI / ${escapeHtml(title.toUpperCase())}</span><h1>${escapeHtml(title)}</h1><p>${escapeHtml(description)}</p></div></section><section class="action-panel"><h2>Workspace actions</h2><p>Each action runs through CommandRouter and uses live provider or local workspace data.</p><div class="action-grid">${actionList(VIEW_GROUPS[view]).map(renderActionCard).join("")}</div></section>`;
  bindActionButtons();
}
async function renderHome() {
  $("#view-content").innerHTML = `<section class="home-view"><div class="orb">F</div><h1>What would you like to understand today?</h1><p>Research markets, inspect your portfolio, or run any safe FinCLI command.</p><div class="suggestions"><button class="suggestion" data-text="Analyze AAPL deeply">Analyze AAPL deeply</button><button class="suggestion" data-text="Show my portfolio risk">Show portfolio risk</button><button class="suggestion" data-text="Scan SP500 for RSI < 30">Scan SP500 for RSI &lt; 30</button><button class="suggestion" data-text="Compare providers for TSLA">Compare providers for TSLA</button></div><div id="overview" class="overview-grid"><div class="stat-card"><span>Portfolio</span><strong>--</strong><small>positions</small></div><div class="stat-card"><span>Watchlist</span><strong>--</strong><small>instruments</small></div><div class="stat-card"><span>Alerts</span><strong>--</strong><small>active</small></div><div class="stat-card"><span>Providers</span><strong>--</strong><small>tracked</small></div></div></section>`;
  $(".suggestions").querySelectorAll("[data-text]").forEach(button => button.onclick = () => send(button.dataset.text));
  try { const data = await api("/api/desktop/overview"); const values = [data.portfolio?.positions ?? 0, data.watchlist?.count ?? 0, data.alerts?.active ?? 0, data.provider_trust?.count ?? 0]; $("#overview").querySelectorAll(".stat-card strong").forEach((node, index) => node.textContent = values[index]); } catch { /* overview is informative; actions remain available */ }
}
function renderSystem() {
  const system = [...actionList("System"), ...actionList("Profile")];
  $("#view-content").innerHTML = `<section class="view-header"><div><span class="context-kicker">FINCLI / SYSTEM</span><h1>System</h1><p>Diagnostics and local workspace controls.</p></div></section><section class="action-panel"><h2>Tools</h2><p>Secrets are managed separately in the secure storage drawer.</p><div class="action-grid">${system.map(renderActionCard).join("")}</div></section>`;
  bindActionButtons();
}
function renderActionCard(spec) { return `<article class="action-card"><div><strong>${escapeHtml(spec.label)}</strong><small>${escapeHtml(spec.description)}</small></div><button data-action="${escapeHtml(spec.action)}">Run action</button></article>`; }
function bindActionButtons() { document.querySelectorAll("[data-action]").forEach(button => button.onclick = () => openAction(button.dataset.action)); }
function defaultValue(field, action) {
  const defaults = { interval: "1d", mode: "--deep", group: "default", strategy: "sma_cross", order_type: "market", side: "buy", condition: "above", format: "json", state: "status", currency: "USD", leverage: "1:1", field: "bias", years: "0" };
  return defaults[field.name] || field.placeholder || (action === "market.calendar" && field.name === "period" ? "week" : "");
}
function openAction(name) {
  const spec = actions.find(item => item.action === name); if (!spec) return;
  const fields = (spec.fields || []).map(field => { const value = escapeHtml(defaultValue(field, name)); const tag = field.type === "number" ? "input" : field.type === "textarea" ? "textarea" : field.type === "select" ? "select" : "input"; const content = tag === "select" ? `<option selected>${value}</option><option>status</option><option>buy</option><option>sell</option><option>--deep</option>` : ""; return `<div class="field"><label for="field-${escapeHtml(field.name)}">${escapeHtml(field.label)}${field.required ? " *" : ""}</label><${tag} id="field-${escapeHtml(field.name)}" name="${escapeHtml(field.name)}" type="${tag === "input" ? field.type || "text" : ""}" placeholder="${escapeHtml(field.placeholder || "")}">${content}</${tag}></div>`; }).join("");
  $("#modal-root").innerHTML = `<div class="modal-backdrop"><div class="modal-card"><button type="button" class="modal-close" data-close-modal aria-label="Close dialog">&times;</button><h2>${escapeHtml(spec.label)}</h2><p>${escapeHtml(spec.description)}${spec.confirmation_required ? " This action requires explicit confirmation." : ""}</p><form id="action-form">${fields}<div class="modal-actions"><button type="button" class="action-button secondary" data-close-modal>Cancel</button><button class="action-button" type="submit">${spec.confirmation_required ? "Review and confirm" : "Run action"}</button></div></form></div></div>`;
  document.querySelectorAll("[data-close-modal]").forEach(button => button.onclick = closeModal);
  $(".modal-backdrop").onclick = event => { if (event.target === event.currentTarget) closeModal(); };
  $("#action-form").onsubmit = async event => { event.preventDefault(); const params = Object.fromEntries(new FormData(event.target).entries()); closeModal(); await runAction(spec, params, false); };
}
function closeModal() { $("#modal-root").innerHTML = ""; if (pendingConfirmationResolve) { const resolve = pendingConfirmationResolve; pendingConfirmationResolve = null; resolve(false); } }
function askConfirmation(spec, command) {
  // Browser integrations may still look for window.confirm; desktop uses this branded modal instead.
  return new Promise(resolve => { pendingConfirmationResolve = resolve; const approve = () => { pendingConfirmationResolve = null; $("#modal-root").innerHTML = ""; resolve(true); }; $("#modal-root").innerHTML = `<div class="modal-backdrop"><div class="modal-card"><button type="button" class="modal-close" data-confirm="no" aria-label="Close confirmation">&times;</button><h2>Confirm ${escapeHtml(spec.label)}</h2><p>This action changes local trading state or accesses a sensitive control. Review the command before continuing.</p><div class="output-card"><pre>${escapeHtml(command)}</pre></div><div class="modal-actions"><button class="action-button secondary" data-confirm="no">Cancel</button><button class="action-button" data-confirm="yes">Confirm action</button></div></div></div>`; document.querySelectorAll("[data-confirm='no']").forEach(button => button.onclick = closeModal); $("[data-confirm='yes']").onclick = approve; $(".modal-backdrop").onclick = event => { if (event.target === event.currentTarget) closeModal(); }; });
}
async function runAction(spec, params = {}, confirmed = false) {
  let result;
  try {
    const sensitiveFields = new Set((spec.fields || []).filter(field => field.sensitive).map(field => field.name));
    const preview = (spec.command || spec.action).replace(/\{(\w+)\}/g, (_, key) => sensitiveFields.has(key) && params[key] ? "[REDACTED]" : params[key] || "");
    if (spec.confirmation_required && !confirmed && !(await askConfirmation(spec, preview))) return;
    result = await api("/api/desktop/action", { method: "POST", body: JSON.stringify({ action: spec.action, params, confirmed: Boolean(confirmed || spec.confirmation_required), conversation_id: conversationId }) });
    appendResult(result);
    await Promise.all([loadHistory(), loadTrust()]);
  } catch (error) { showInlineError(getErrorMessage(error)); }
}
function commandMatches(query) { const value = query.toLowerCase(); return commands.filter(command => command.name.toLowerCase().includes(value) || command.description.toLowerCase().includes(value) || command.group.toLowerCase().includes(value)).slice(0, 14); }
function showCommandPalette(value) {
  const palette = $("#command-palette"); if (!value.startsWith("/")) { palette.classList.add("hidden"); return; }
  const matches = commandMatches(value); commandSelection = Math.min(commandSelection, Math.max(0, matches.length - 1));
  palette.innerHTML = matches.map((command, index) => { const unavailable = command.desktop_available === false || (command.desktop_supported === false && !command.replacement_action); const note = command.replacement_action ? " Opens the safe desktop form." : command.terminal_only_reason || ""; return `<button type="button" class="command-option${index === commandSelection ? " selected" : ""}${unavailable ? " disabled" : ""}" data-command-index="${index}"${unavailable ? " disabled" : ""}><span class="command-name">${escapeHtml(command.name)}</span><span class="command-description">${escapeHtml(command.description)}${note ? ` <span class="command-warning">${escapeHtml(note)}</span>` : ""}</span><span class="command-group">${escapeHtml(command.group)}</span></button>`; }).join("") || `<div class="command-option">No matching command</div>`;
  palette.classList.remove("hidden"); palette.querySelectorAll("[data-command-index]").forEach(button => button.onclick = () => selectCommand(matches[Number(button.dataset.commandIndex)]));
}
function selectCommand(command) { if (!command) return; if (command.replacement_action) { $("#command-palette").classList.add("hidden"); openAction(command.replacement_action); return; } if (command.desktop_available === false || command.desktop_supported === false) return; $("#message").value = command.example; $("#command-palette").classList.add("hidden"); $("#message").focus(); }
async function send(text, confirmed = false) {
  if (sending) return; text = (text || $("#message").value).trim(); if (!text) return;
  const spec = commands.filter(command => text.toLowerCase().startsWith(command.name.toLowerCase())).sort((a, b) => b.name.length - a.name.length)[0];
  if (spec?.confirmation_required && !confirmed) { const proceed = await askConfirmation({ label: spec.name, description: spec.description }, text); if (!proceed) return; confirmed = true; }
  sending = true; $("#send").disabled = true; $("#command-palette").classList.add("hidden"); $("#message").value = ""; $("#view-content").innerHTML = "";
  visibleMessages = visibleMessages.filter(item => item.kind !== "loading");
  const requestId = `working-${++requestSequence}`;
  visibleMessages.push(
    { kind: "message", role: "user", content: text, command: "" },
    { kind: "loading", id: requestId },
  );
  renderMessagePanel();
  try {
    const result = await api("/api/chat", { method: "POST", body: JSON.stringify({ message: text, conversation_id: conversationId, confirmed }), timeoutMs: text === "/help" ? 15000 : 120000 });
    conversationId = result.conversation_id || conversationId;
    replaceLoading(requestId, { kind: "result", result });
    await loadHistory();
  } catch (error) {
    replaceLoading(requestId, { kind: "result", result: { ok: false, kind: "error", errors: [{ title: "Request failed", message: getErrorMessage(error), suggestion: "Check the local server and try again." }] } });
  } finally { visibleMessages = visibleMessages.filter(item => item.kind !== "loading" || item.id !== requestId); renderMessagePanel(); sending = false; $("#send").disabled = false; }
}
function resultDismissHtml() { return `<button type="button" class="result-dismiss" data-close-results aria-label="Close result panel">&times;</button>`; }
function loadingHtml() { return `<article class="message-row assistant"><div class="message-bubble">Working on your request...</div></article>`; }
function renderMessagePanel(shouldScroll = true) {
  const panel = $("#messages");
  const content = visibleMessages.map(item => item.kind === "result" ? renderResult(item.result) : item.kind === "loading" ? loadingHtml() : messageHtml(item.role, item.content, item.command)).join("");
  panel.innerHTML = content ? resultDismissHtml() + content : "";
  if (shouldScroll) scrollDown();
}
function replaceLoading(id, replacement) {
  const index = visibleMessages.findIndex(item => item.kind === "loading" && item.id === id);
  if (index >= 0) visibleMessages.splice(index, 1, replacement); else visibleMessages.push(replacement);
  renderMessagePanel();
}
function messageHtml(role, content, command = "") { const user = role === "user"; return `<article class="message-row ${user ? "user" : "assistant"}"><div class="message-bubble ${user ? "user" : ""}>${user ? "" : `<button type="button" class="result-close" data-close-results aria-label="Close results">&times;</button>`}${user ? escapeHtml(content) : `<pre>${escapeHtml(sanitizeDisplayText(content))}</pre>`}${command && !user ? `<div class="meta">Executed ${escapeHtml(command)}</div>` : ""}</div></article>`; }
function errorCard(error) { return `<section class="error-card"><div class="error-heading"><strong>${escapeHtml(error.title || "Command failed")}</strong></div><p>${escapeHtml(error.message || "The command could not be completed.")}</p>${error.suggestion ? `<p>${escapeHtml(error.suggestion)}</p>` : ""}</section>`; }
function dataTableCard(table) { return `<section class="data-table-card">${table.title ? `<h3>${escapeHtml(table.title)}</h3>` : ""}<div class="table-wrapper"><table><thead><tr>${(table.columns || []).map(column => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead><tbody>${(table.rows || []).map(row => `<tr>${row.map(cell => `<td>${escapeHtml(cell)}</td>`).join("")}</tr>`).join("")}</tbody></table></div></section>`; }
function renderResult(result) { let body = (result.errors || []).map(errorCard).join("") + (result.tables || []).map(dataTableCard).join("") + (result.cards || []).map(card => `<section class="result-card"><h3>${escapeHtml(card.title)}</h3><strong>${escapeHtml(card.value)}</strong><p>${escapeHtml(card.detail)}</p></section>`).join(""); if (result.markdown) body += `<section class="output-card"><pre>${escapeHtml(result.markdown)}</pre></section>`; if (!body) body = `<section class="output-card"><pre>${escapeHtml(result.text || result.message || result.summary || "No displayable output.")}</pre></section>`; return `<article class="message-row assistant"><div class="message-bubble"><button type="button" class="result-close" data-close-results aria-label="Close results">&times;</button><div class="assistant-result">${result.summary ? `<p class="result-summary">${escapeHtml(result.summary)}</p>` : ""}${body}</div>${result.command ? `<div class="meta">Executed ${escapeHtml(result.command)}</div>` : ""}</div></article>`; }
function appendResult(result) { visibleMessages.push({ kind: "result", result }); renderMessagePanel(); }
function showInlineError(message) { appendResult({ ok: false, errors: [{ title: "Workspace error", message }] }); }
function closeResults() { visibleMessages = []; renderMessagePanel(false); if (!$("#view-content").innerHTML.trim()) showView(activeView || "home"); }
function scrollDown() { const node = $("#messages"); node.scrollTop = node.scrollHeight; }
function newChat() { conversationId = ""; visibleMessages = []; showView("home"); }

function secretRowHtml(label, envKey, hasKey) { return `<div class="secret-row"><div class="secret-info"><div class="secret-name">${escapeHtml(label)}</div><div class="secret-env">${escapeHtml(envKey)}</div></div><span class="secret-status ${hasKey ? "set" : "unset"}">${hasKey ? "Configured" : "Not set"}</span><div class="secret-actions"><input type="password" placeholder="${hasKey ? "Replace key..." : "Paste API key..."}" data-input-key="${escapeHtml(envKey)}" autocomplete="off"><button data-save-key="${escapeHtml(envKey)}">Save</button></div><div class="secret-feedback" data-feedback="${escapeHtml(envKey)}"></div></div>`; }
async function loadSecrets() { try { const data = await api("/api/secrets"); const list = $("#secrets-list"); let html = `<div class="secret-group-title">AI Providers</div>`; Object.entries(data.ai_keys || {}).forEach(([name, info]) => html += secretRowHtml(name, info.env_key, info.has_key)); html += `<div class="secret-group-title">Market Data Providers</div>`; (data.market_keys || []).forEach(item => html += secretRowHtml(item.provider, item.env_key, item.has_key)); list.innerHTML = html; list.querySelectorAll("[data-save-key]").forEach(button => button.onclick = () => saveSecret(button.dataset.saveKey, button)); } catch (error) { $("#secrets-list").innerHTML = `<p class="auth-error">${escapeHtml(getErrorMessage(error))}</p>`; } }
async function saveSecret(envKey, button) { const input = document.querySelector(`[data-input-key="${envKey}"]`); const feedback = document.querySelector(`[data-feedback="${envKey}"]`); const value = input?.value.trim(); if (!value) { feedback.textContent = "Value required"; feedback.className = "secret-feedback err"; return; } button.disabled = true; try { await api("/api/secrets", { method: "POST", body: JSON.stringify({ key: envKey, value }) }); input.value = ""; feedback.textContent = "Saved"; feedback.className = "secret-feedback ok"; await Promise.all([loadSecrets(), loadModel()]); } catch (error) { feedback.textContent = getErrorMessage(error); feedback.className = "secret-feedback err"; } finally { button.disabled = false; } }
function openSettings() { $("#settings-panel").classList.remove("hidden"); loadSecrets(); }
function closeSettings() { $("#settings-panel").classList.add("hidden"); }
function setTheme(light) {
  document.body.classList.toggle("light", light);
  localStorage.fincliTheme = light ? "light" : "dark";
  const meta = document.querySelector('meta[name="theme-color"]'); if (meta) meta.content = light ? "#f7f4ee" : "#171717";
  $("#theme").setAttribute("aria-label", light ? "Use dark theme" : "Use light theme");
}

$("#auth-form").onsubmit = async event => {
  event.preventDefault();
  if (desktop && startupFailed) {
    setStartup("Restarting local engine...");
    try { await window.__TAURI__.core.invoke("desktop_restart"); desktopBase = ""; await pause(300); }
    catch (error) { $("#auth-error").textContent = getErrorMessage(error); return; }
  }
  connect();
};
$("#composer").onsubmit = event => { event.preventDefault(); send(); };
$("#message").oninput = event => { commandSelection = 0; showCommandPalette(event.target.value); };
$("#message").onkeydown = event => { const value = event.target.value; if (value.startsWith("/") && ["ArrowDown", "ArrowUp", "Tab"].includes(event.key)) { event.preventDefault(); const matches = commandMatches(value); if (event.key === "ArrowDown") commandSelection = Math.min(commandSelection + 1, matches.length - 1); if (event.key === "ArrowUp") commandSelection = Math.max(commandSelection - 1, 0); if (event.key === "Tab") selectCommand(matches[commandSelection]); showCommandPalette(value); } else if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); send(); } };
document.querySelectorAll("[data-view]").forEach(button => button.onclick = () => showView(button.dataset.view));
$("#new-chat").onclick = newChat; $("#settings").onclick = openSettings; $("#settings-close").onclick = closeSettings; $("#mobile-menu").onclick = () => $("#sidebar").classList.toggle("open"); $("#collapse").onclick = () => document.body.classList.toggle("collapsed"); $("#theme").onclick = () => setTheme(!document.body.classList.contains("light")); $("#clear-history").onclick = newChat;
$("#messages").onclick = event => { if (event.target.closest("[data-close-results]")) closeResults(); };
$("#model").onchange = event => { const option = event.target.selectedOptions[0]; const spec = actions.find(item => item.action === "ai.model"); if (spec) runAction(spec, { provider: event.target.value, model: option?.dataset.model || "" }); };
document.addEventListener("keydown", event => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "n") { event.preventDefault(); newChat(); } if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); $("#message").focus(); $("#message").value = "/"; showCommandPalette("/"); } if (event.key === "Escape") { $("#sidebar").classList.remove("open"); $("#command-palette").classList.add("hidden"); closeSettings(); closeModal(); } });
setTheme(localStorage.fincliTheme === "light");
if (desktop) document.body.classList.add("desktop-mode");
if (desktop || token) connect();
