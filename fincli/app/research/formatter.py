"""Rich renderers for research workspace."""

from __future__ import annotations

from rich.table import Table

from fincli.app.research.models import ResearchBrief
from fincli.app.utils.formatting import semantic_text


def format_research_brief(brief: ResearchBrief) -> Table:
    table = Table(title=f"Research Center: {brief.symbol} | {brief.mode} | Research Brief v2", expand=True)
    table.add_column("Section", style="cyan", no_wrap=True)
    table.add_column("Description", overflow="fold")
    table.add_row("Snapshot", semantic_text(brief.snapshot))
    table.add_row("Signal", semantic_text(brief.signal))
    table.add_row("Risk", semantic_text(brief.risk))
    table.add_row("Trust Gate", semantic_text(brief.trust_gate))
    table.add_row("Missing Data", semantic_text(brief.missing_data))
    table.add_row("Source Quality", semantic_text(brief.source_quality))
    table.add_row("Decision Points", semantic_text(" | ".join(brief.decision_points[:2])))
    if brief.mode == "report":
        table.add_row("Report Notes", semantic_text("\n".join(f"- {item}" for item in brief.report_notes)))
    if brief.ai_summary:
        table.add_row("AI Summary", brief.ai_summary)
    table.add_row("Final Summary", semantic_text(brief.final_summary))
    table.caption = "Research output is informational only. Not financial advice."
    return table
