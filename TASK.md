Act as a senior full-stack engineer fixing FinCLI v1.9.0 Local Web UI.

Important: Do not solve this by only changing CSS. The real bug is that terminal-rendered Rich/ASCII output is being sent to the browser. Create a separate structured web renderer and make the web API return JSON data for cards, tables, errors, and markdown.

Current bug:
The FinCLI Web UI still renders terminal-style output directly inside the browser. For example, errors appear inside ASCII/Rich terminal boxes like:

```text
╭──────────── Error ────────────╮
│ Provider openrouter rate limited. │
╰───────────────────────────────╯
```

This is wrong for the web UI.

The web UI must not display terminal/Rich/ASCII layout. It should render clean native web components, similar to a polished ChatGPT-style interface.

Main goal:
Separate terminal output rendering from web output rendering.

Terminal users should still see Rich/ASCII terminal panels.
Web users should see clean HTML cards, tables, badges, markdown, and error components.

Do not break the terminal UI.

---

## Task 1 — Find terminal renderer leakage

Inspect the command execution flow used by the web API:

* `/api/chat`
* `/api/command`
* command bridge
* router execution wrapper
* Rich Console capture
* error formatting
* provider compare command
* AI command handler

Find where the web backend captures terminal output from Rich/Textual/Console and sends it directly to the frontend.

The web API should not send terminal-rendered UI as the primary response.

---

## Task 2 — Add output mode/context

Introduce an execution context that supports different output modes:

```py
class OutputMode:
    TERMINAL = "terminal"
    WEB = "web"
    JSON = "json"
```

or:

```py
@dataclass
class CommandExecutionContext:
    output_mode: Literal["terminal", "web", "json"]
    source: Literal["cli", "web"]
    user_confirmed: bool = False
```

When command is executed from terminal:

```py
output_mode = "terminal"
```

When command is executed from local web UI:

```py
output_mode = "web"
```

All command handlers must know whether they are rendering for terminal or web.

---

## Task 3 — Create structured web result schema

The backend web API must return structured JSON, not terminal-formatted strings.

Use schema like this:

```py
@dataclass
class WebCommandResult:
    ok: bool
    kind: str
    title: str | None = None
    summary: str | None = None
    message: str | None = None
    command: str | None = None
    markdown: str | None = None
    text: str | None = None
    tables: list[WebTable] = field(default_factory=list)
    cards: list[WebCard] = field(default_factory=list)
    errors: list[WebError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
```

Table schema:

```py
@dataclass
class WebTable:
    title: str | None
    columns: list[str]
    rows: list[list[str]]
    caption: str | None = None
```

Error schema:

```py
@dataclass
class WebError:
    title: str = "Error"
    message: str
    code: str | None = None
    provider: str | None = None
    suggestion: str | None = None
```

Example web response for OpenRouter rate limit:

```json
{
  "ok": false,
  "kind": "error",
  "title": "OpenRouter rate limited",
  "message": "Provider openrouter is currently rate limited.",
  "errors": [
    {
      "title": "OpenRouter rate limited",
      "message": "Provider openrouter is currently rate limited.",
      "provider": "openrouter",
      "code": "RATE_LIMITED",
      "suggestion": "Wait a moment, switch model, or use another configured provider."
    }
  ],
  "metadata": {
    "provider": "openrouter",
    "model": "openai/gpt-oss-120b:free"
  }
}
```

The frontend should render this as a clean web error card, not ASCII.

---

## Task 4 — Stop sending Rich/ASCII panels to frontend

In web mode:

* Do not use `rich.Panel`.
* Do not use `rich.Table` output as final browser content.
* Do not use terminal box drawing.
* Do not send ANSI escape codes.
* Do not send captured console output unless it is fallback debug text.
* Do not render terminal borders inside the browser.

Create helpers:

```py
ANSI_ESCAPE_RE = re.compile(r"\x1b\\[[0-?]*[ -/]*[@-~]")
BOX_DRAWING_RE = re.compile(r"[╭╮╯╰─│┌┐└┘├┤┬┴┼═║╔╗╚╝]")

def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text or "")

def looks_like_terminal_box(text: str) -> bool:
    if not text:
        return False
    box_chars = BOX_DRAWING_RE.findall(text)
    return len(box_chars) >= 4

def sanitize_web_text(text: str) -> str:
    text = strip_ansi(text or "")
    if looks_like_terminal_box(text):
        # fallback only: remove box drawing characters
        text = BOX_DRAWING_RE.sub("", text)
    return text.strip()
```

But this sanitizer is only fallback. The correct fix is structured web output.

---

## Task 5 — Add web renderers for command outputs

For each major command, add a web result adapter.

Required adapters:

* `/provider compare`
* `/provider status`
* `/research`
* `/market`
* `/technical`
* `/portfolio`
* `/portfolio risk`
* `/watchlist`
* `/backtest`
* `/scan`
* generic AI chat
* generic errors

Example:

```py
def provider_compare_to_web(symbol: str, result: ProviderCompareResult) -> WebCommandResult:
    return WebCommandResult(
        ok=True,
        kind="provider_compare",
        title=f"Provider Compare: {symbol}",
        summary="Compared available market data providers. Lower latency is better.",
        tables=[
            WebTable(
                title=f"Provider Compare: {symbol}",
                columns=["Provider", "Price", "Currency", "Status", "Latency", "Error"],
                rows=[
                    [
                        row.provider,
                        format_price(row.price),
                        row.currency,
                        row.status,
                        f"{row.latency_ms}ms",
                        row.error or ""
                    ]
                    for row in result.rows
                ],
                caption="Lower latency is better."
            )
        ],
        metadata={"symbol": symbol}
    )
```

For errors:

```py
def error_to_web(error: Exception) -> WebCommandResult:
    return WebCommandResult(
        ok=False,
        kind="error",
        title="Command failed",
        message=str(error),
        errors=[
            WebError(
                title="Command failed",
                message=str(error),
                suggestion="Check provider status or try another configured model."
            )
        ]
    )
```

---

## Task 6 — Fix frontend rendering priority

Frontend must render by structured fields, not by raw text first.

Rendering priority:

1. `errors[]` → render `<ErrorCard />`
2. `tables[]` → render `<DataTableCard />`
3. `cards[]` → render specific cards
4. `markdown` → render markdown message
5. `text` → render fallback contained text card
6. fallback → readable “No displayable output.”

Do not render raw terminal output if structured data exists.

Example:

```tsx
function AssistantResult({ result }: { result: WebCommandResult }) {
  return (
    <div className="assistant-result">
      {result.summary && <p className="result-summary">{result.summary}</p>}

      {result.errors?.map((error, index) => (
        <ErrorCard key={index} error={error} />
      ))}

      {result.tables?.map((table, index) => (
        <DataTableCard key={index} table={table} />
      ))}

      {result.markdown && <MarkdownMessage content={result.markdown} />}

      {!result.errors?.length &&
        !result.tables?.length &&
        !result.markdown &&
        result.text && (
          <CommandOutputCard text={result.text} />
        )}
    </div>
  );
}
```

---

## Task 7 — Build proper web components

Create these frontend components:

### ErrorCard

Requirements:

* Rounded card.
* Clear title.
* Human-readable message.
* Optional provider badge.
* Optional suggestion.
* No ASCII border.
* No terminal box drawing.

Example visual content:

```text
OpenRouter rate limited
Provider openrouter is currently rate limited.

Suggestion:
Wait a moment, switch model, or use another configured provider.
```

### DataTableCard

Requirements:

* Card container.
* Title.
* Responsive table.
* Horizontal scroll only inside table wrapper.
* No page-level horizontal overflow.
* Caption below table.

### CommandOutputCard

Requirements:

* Only for fallback plain text.
* Use contained `<pre>`.
* Soft wrapping.
* Max width.
* Internal horizontal scroll if needed.
* No terminal border overflow.

---

## Task 8 — CSS: prevent terminal-style overflow

Apply these layout constraints:

```css
.chat-content {
  width: 100%;
  max-width: 900px;
  margin: 0 auto;
  padding: 32px 24px 160px;
  box-sizing: border-box;
}

.message-row {
  display: flex;
  width: 100%;
  margin: 18px 0;
  box-sizing: border-box;
}

.message-row.user {
  justify-content: flex-end;
}

.message-row.assistant,
.message-row.tool,
.message-row.error {
  justify-content: flex-start;
}

.message-bubble {
  max-width: min(760px, 100%);
  overflow-wrap: anywhere;
  word-break: break-word;
  box-sizing: border-box;
}

.message-bubble.user {
  max-width: min(620px, 78%);
}

.assistant-result,
.output-card,
.error-card,
.data-table-card {
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
}

.output-card pre {
  max-width: 100%;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

.table-wrapper {
  width: 100%;
  max-width: 100%;
  overflow-x: auto;
}

.table-wrapper table {
  width: 100%;
  min-width: 560px;
  border-collapse: collapse;
}

.table-wrapper th,
.table-wrapper td {
  padding: 10px 12px;
  white-space: nowrap;
}

.table-wrapper td:last-child {
  white-space: normal;
  word-break: break-word;
}
```

Hard requirement:
The page must never horizontally scroll because of command output.

---

## Task 9 — Fix error example from screenshot

Current web output:

```text
╭──── Error ────╮
│ Provider openrouter rate limited. │
╰───────────────╯
```

Expected web output:

```text
OpenRouter rate limited

Provider openrouter is currently rate limited.

Suggestion:
Wait a moment, switch to another model, or configure a fallback provider.
```

It should appear inside a clean web error card.

---

## Task 10 — Keep terminal behavior unchanged

Terminal mode should still use Rich tables and panels.

Example:

* Terminal `/provider compare TSLA` may render Rich table.
* Web `/provider compare TSLA` must render structured JSON → HTML table.

Do not delete Rich terminal output.
Only prevent it from leaking into web responses.

---

## Task 11 — Tests

Add backend tests:

* Web command response does not contain box drawing characters.
* Web error response is structured JSON.
* Web provider compare response includes `tables`.
* Terminal command output still supports Rich rendering.
* `sanitize_web_text` strips ANSI codes.
* Web API does not return terminal panels for errors.

Add frontend tests:

* ErrorCard renders clean message.
* DataTableCard renders provider compare result.
* Raw box drawing characters are not visible.
* Long output does not overflow viewport.
* No page-level horizontal scroll.
* The OpenRouter rate limit error appears as a card, not ASCII.

Test assertion examples:

```ts
expect(screen.queryByText(/╭|╰|─|│/)).not.toBeInTheDocument();
expect(screen.getByText(/OpenRouter rate limited/i)).toBeInTheDocument();
```

Backend assertion example:

```py
assert "╭" not in response.text
assert "╰" not in response.text
assert "│" not in response.text
assert response.json()["kind"] == "error"
assert response.json()["errors"][0]["message"]
```

---

## Task 12 — Final validation

Run:

```bash
npm run web:build
npm run test:web
pytest
ruff check .
python -m compileall .
npm pack --dry-run
```

Fix all failures before finishing.

Expected final result:

* Web UI no longer displays terminal templates.
* No ASCII/Rich boxes appear in the browser.
* Errors render as clean web cards.
* Tables render as responsive HTML tables.
* Long output stays inside the message card.
* Terminal UI remains unchanged.
* Web UI feels like a proper ChatGPT-style local dashboard, not a terminal embedded in a webpage.
