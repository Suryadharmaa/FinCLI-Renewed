"""Rich renderers for research workspace."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.table import Table

from fincli.app.utils.formatting import semantic_text

if TYPE_CHECKING:
    from fincli.app.research.models import ResearchBrief


def format_research_brief(brief: ResearchBrief) -> Table:
    table = Table(title=f"Research Center: {brief.symbol} | {brief.mode} | Research Brief v3", expand=True)
    table.add_column("Section", style="cyan", no_wrap=True)
    table.add_column("Description", overflow="fold")
    table.add_row("Snapshot", semantic_text(brief.snapshot))
    table.add_row("Signal", semantic_text(brief.signal))
    table.add_row("Risk", semantic_text(brief.risk))
    table.add_row("Context", semantic_text(brief.context_blend))
    table.add_row("Trust Gate", semantic_text(brief.trust_gate))
    table.add_row("Missing Data", semantic_text(brief.missing_data))
    table.add_row("Source Quality", semantic_text(brief.source_quality))
    table.add_row("Decision Points", semantic_text(" | ".join(brief.decision_points[:2])))
    if brief.sources:
        table.add_row("Sources", semantic_text("\n".join(f"- {source.citation()}" for source in brief.sources[:6])))
    if brief.mode == "report":
        if brief.trust_summary is not None:
            table.add_row(
                "Trust Summary",
                semantic_text(
                    f"{brief.trust_summary.label} | cap {brief.trust_summary.confidence_cap:g}% | "
                    f"{brief.trust_summary.max_signal_strength}"
                ),
            )
        if brief.scenario_matrix:
            table.add_row(
                "Scenario Matrix",
                semantic_text(
                    "\n".join(
                        f"- {item.name}: {item.thesis} Trigger: {item.trigger} Invalidation: {item.invalidation} Confidence: {item.confidence:g}% [{', '.join(item.citation_ids) or 'no citations'}]"
                        for item in brief.scenario_matrix
                    )
                ),
            )
        if brief.facts:
            table.add_row(
                "Verified Facts",
                semantic_text("\n".join(f"- {item.text} [{', '.join(item.citation_ids) or 'no citations'}]" for item in brief.facts)),
            )
        if brief.inferences:
            table.add_row(
                "Inferences",
                semantic_text(
                    "\n".join(
                        f"- {item.text} ({item.confidence:g}%) [{', '.join(item.citation_ids) or 'no citations'}]"
                        for item in brief.inferences
                    )
                ),
            )
        if brief.missing_data_items:
            table.add_row(
                "Missing Data Items",
                semantic_text("\n".join(f"- {item.severity}: {item.field} — {item.impact}" for item in brief.missing_data_items)),
            )
        if brief.citations:
            table.add_row(
                "Citations",
                semantic_text(
                    "\n".join(
                        f"- {item.id}: {item.title} | {item.source} | score {item.score:g} | {item.evidence_kind}"
                        for item in brief.citations[:8]
                    )
                ),
            )
        table.add_row("Report Notes", semantic_text("\n".join(f"- {item}" for item in brief.report_notes)))
    if brief.ai_summary:
        table.add_row("AI Summary", brief.ai_summary)
    table.add_row("Final Summary", semantic_text(brief.final_summary))
    table.caption = "Research output is informational only. Not financial advice."
    return table
