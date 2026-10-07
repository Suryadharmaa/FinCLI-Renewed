"""Domain handlers and renderers for the v3 structured workspace contract."""

from __future__ import annotations

import json
from typing import Any

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from fincli.app.workspace.models import result

ROOTS = {"/workspace", "/company", "/document", "/workflow", "/screen", "/valuation", "/tv", "/jobs"}


def render_result(output: dict[str, Any]) -> Any:
    """Render useful tables while keeping the exact JSON in CommandResult.metadata."""
    kind, data = output["kind"], output["data"]
    if kind == "company":
        panels = [
            Panel(
                Text(str(data.get("profile", {}).get("longBusinessSummary") or "Company profile unavailable.")),
                title=output.get("symbol", "Company"),
            )
        ]
        rows = data.get("ratios", [])
        if rows:
            table = Table(title="Financial ratios — calculated from actuals")
            columns = [
                "period",
                "revenue_growth",
                "net_margin",
                "operating_margin",
                "debt_to_equity",
                "roe",
                "roic",
                "free_cash_flow",
            ]
            for column in columns:
                table.add_column(column)
            for row in rows:
                table.add_row(*(str(row.get(k)) if row.get(k) is not None else "N/A" for k in columns))
            panels.append(table)
        for name, statements in data.get("statements", {}).items():
            if not statements:
                continue
            table = Table(title=f"{name} — {data.get('financial_currency', '')}")
            table.add_column("Metric")
            for statement in statements:
                table.add_column(statement["period"])
            labels = list(dict.fromkeys(key for statement in statements for key in statement["values"]))
            for label in labels:
                table.add_row(label, *(str(s["values"].get(label, "N/A")) for s in statements))
            panels.append(table)
        panels.append(Panel(Text("Missing: " + ", ".join(data.get("missing", []))), title="Data coverage"))
        return Group(*panels)
    if kind == "document_evidence":
        return (
            Group(
                *(
                    Panel(Text(hit["quote"]), title=f"[{hit['citation_id']}] {hit['title']} · page {hit['page']}")
                    for hit in data["evidence"]
                )
            )
            if data["evidence"]
            else Panel("No matching evidence")
        )
    if kind == "workflow":
        return Group(
            Panel(
                Text(data["summary"] or "Inspect the saved tool results with /workspace run <id>."),
                title="Workflow summary",
            ),
            Panel(
                Text(
                    "\n".join(f"{i}. {step['tool']}: {step['status']}" for i, step in enumerate(data["steps"], 1))
                    + f"\nRun: {data['id']}"
                ),
                title="Execution trace",
            ),
        )
    if kind == "screen":
        table = Table(title=f"Screen · {data['id']}")
        for c in ("Symbol", "Passed", "Period", "Missing", "Reasons"):
            table.add_column(c)
        for row in data["rows"]:
            table.add_row(
                row["symbol"],
                str(row["passed"]),
                str(row["period"] or "N/A"),
                ", ".join(row["missing_fields"]),
                "; ".join(
                    f"{r['field']}={r['value']} {r['operator']} {r['threshold']}: {r['passed']}"
                    for r in row["comparisons"]
                ),
            )
        return table
    return Panel(Text(json.dumps(data, indent=2, ensure_ascii=False)), title=kind.replace("_", " ").title())


def handle(router, root: str, args: list[str]):
    from fincli.app.cli.router import CommandResult

    service = router.workspace_service
    if root == "/company":
        output = (
            service.request("peers", {"symbols": args[1:]})
            if args and args[0] == "peers"
            else service.request("company", {"symbol": args[0] if args else ""})
        )
    elif root == "/document":
        action = args[0] if args else "list"
        if action == "import" and len(args) >= 2:
            output = service.documents.import_file(args[1], args[2] if len(args) > 2 else "")
        elif action == "search" and len(args) > 1:
            output = service.documents.search(" ".join(args[1:]))
        elif action == "page" and len(args) == 3:
            output = result("document_page", service.documents.page(args[1], int(args[2])))
        elif action == "list":
            output = result("documents", service.documents.list(args[1] if len(args) > 1 else ""))
        else:
            raise ValueError("Use /document list|import <path> [symbol]|search <query>|page <id> <page>.")
    elif root == "/workflow":
        if not args:
            raise ValueError("Use /workflow <research request with explicit tickers>.")
        output = service.workflow(" ".join(args))
    elif root == "/screen":
        if args and args[0] == "save" and len(args) >= 3:
            from fincli.app.workspace.screener import ScreenExpression

            name = service.store.name(args[1])
            expression = " ".join(args[2:])
            ScreenExpression(expression)
            service.store.db.execute(
                "INSERT OR REPLACE INTO workspace_screens(name,payload) VALUES (?,?)",
                (name, json.dumps({"expression": expression})),
            )
            output = result("screen_saved", {"name": name, "expression": expression})
        elif args and args[0] == "list":
            output = result(
                "screens", [dict(r) for r in service.store.db.query("SELECT name,payload FROM workspace_screens")]
            )
        else:
            if args and args[0] == "run" and len(args) >= 3:
                rows = service.store.db.query(
                    "SELECT payload FROM workspace_screens WHERE name=?", (service.store.name(args[1]),)
                )
                if not rows:
                    raise ValueError("Saved screen not found.")
                symbols, expression = args[2].split(","), json.loads(rows[0]["payload"])["expression"]
            elif len(args) >= 3 and args[1] == "--where":
                symbols, expression = args[0].split(","), " ".join(args[2:])
            else:
                raise ValueError('Use /screen AAPL,MSFT --where "revenue_growth > 10% and rsi < 40".')
            if symbols == ["watchlist"]:
                symbols = [str(r["symbol"]) for r in router.watchlist.list()]
            output = service.screen(symbols, expression)
    elif root == "/valuation":
        if len(args) < 4:
            raise ValueError(
                "Use /valuation <unlevered FCF> <growth decimal> <discount decimal> <terminal decimal> [cash] [debt] [shares]."
            )
        params = dict(
            zip(("fcf", "growth", "discount", "terminal", "cash", "debt", "shares"), map(float, args), strict=False)
        )
        output = service.request("valuation", params)
    elif root == "/portfolio":
        output = service.portfolio(json.loads(" ".join(args[1:])) if len(args) > 1 else {})
    elif root == "/tv":
        action = args[0] if args else "capabilities"
        remaining = [arg for arg in args[1:] if arg != "--confirm"]
        key = {"symbol": "symbol", "timeframe": "timeframe", "indicator": "name", "draw": "price"}.get(action)
        output = service.tradingview.execute(
            action, {key: " ".join(remaining)} if key else {}, confirmed="--confirm" in args
        )
    elif root == "/jobs":
        if len(args) != 2 or args[0] not in {"show", "cancel"}:
            raise ValueError("Use /jobs show|cancel <id>.")
        output = result("job", service.jobs.cancel(args[1]) if args[0] == "cancel" else service.jobs.get(args[1]))
    else:
        action = args[0] if args else "layouts"
        if action == "layouts":
            output = result("layouts", service.store.layouts())
        elif action == "save" and len(args) >= 2:
            output = result(
                "layout", service.store.save_layout(args[1], json.loads(" ".join(args[2:])) if len(args) > 2 else {})
            )
        elif action == "runs":
            output = result("runs", service.store.runs())
        elif action == "run" and len(args) == 2:
            output = service.store.get_run(args[1])
        elif action == "export" and len(args) == 3:
            output = result("export", {"path": service.export(args[1], args[2])})
        elif action == "job" and len(args) >= 2:
            params = json.loads(" ".join(args[2:])) if len(args) > 2 else {}
            output = result(
                "job", service.jobs.submit(lambda context: service.request(args[1], params, context), args[1])
            )
        else:
            raise ValueError("Use /workspace layouts|save|runs|run|export|job.")
    return CommandResult(render_result(output), metadata={"workspace": output})
