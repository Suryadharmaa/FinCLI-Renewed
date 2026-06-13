"""Rich renderers for research workspace."""

from __future__ import annotations

from rich.table import Table

from fincli.app.research.models import ResearchBrief
from fincli.app.utils.formatting import semantic_text


def format_research_brief(brief: ResearchBrief) -> Table:
    table = Table(title=f"Research Brief: {brief.symbol} | {brief.mode}", expand=True)
    table.add_column("Section", style="cyan", no_wrap=True)
    table.add_column("Description", overflow="fold")
    table.add_row("Data Quality", semantic_text(f"{brief.overview.data_quality.score}/100 | {brief.overview.data_quality.provider}"))
    table.add_row("Decision Points", semantic_text("\n".join(f"- {point}" for point in brief.decision_points)))
    table.add_row("Risks", semantic_text("\n".join(f"- {risk}" for risk in brief.risks)))
    if brief.ai_summary:
        table.add_row("AI Summary", brief.ai_summary)
    table.add_row("Final Summary", semantic_text(brief.final_summary))
    table.caption = "Research output is informational only, not financial advice."
    return table
