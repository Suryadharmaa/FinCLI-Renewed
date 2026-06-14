"""Export helpers for Research Engine v2 reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fincli.app.research.models import ResearchBrief
from fincli.app.utils.errors import CommandError


def write_research_report(brief: ResearchBrief, fmt: str, target: str | Path) -> Path:
    report_format = fmt.lower()
    path = _safe_research_path(target, report_format)
    path.parent.mkdir(parents=True, exist_ok=True)
    if report_format == "json":
        path.write_text(json.dumps(_research_payload(brief), indent=2, default=str), encoding="utf-8")
        return path
    if report_format in {"md", "markdown"}:
        path.write_text(_research_markdown(brief), encoding="utf-8")
        return path
    raise CommandError("Research export format harus md atau json.")


def _safe_research_path(target: str | Path, fmt: str) -> Path:
    path = Path(target).expanduser()
    if any(part == ".." for part in path.parts):
        raise CommandError("Research export path tidak boleh mengandung '..'.")
    allowed = {".md", ".json"} if fmt in {"md", "markdown", "json"} else set()
    if path.suffix.lower() not in allowed:
        raise CommandError("Research export path harus berakhir .md atau .json.")
    return path


def _research_payload(brief: ResearchBrief) -> dict[str, Any]:
    return {
        "symbol": brief.symbol,
        "mode": brief.mode,
        "snapshot": brief.snapshot,
        "signal": brief.signal,
        "risk": brief.risk,
        "missing_data": brief.missing_data,
        "source_quality": brief.source_quality,
        "decision_points": brief.decision_points,
        "risks": brief.risks,
        "final_summary": brief.final_summary,
        "ai_summary": brief.ai_summary,
        "report_notes": list(brief.report_notes),
        "disclaimer": "Not financial advice.",
    }


def _research_markdown(brief: ResearchBrief) -> str:
    notes = "\n".join(f"- {item}" for item in brief.report_notes)
    points = "\n".join(f"- {item}" for item in brief.decision_points)
    risks = "\n".join(f"- {item}" for item in brief.risks)
    return "\n".join(
        [
            f"# FinCLI Research Report: {brief.symbol}",
            "",
            f"- Mode: {brief.mode}",
            f"- Snapshot: {brief.snapshot}",
            f"- Signal: {brief.signal}",
            f"- Risk: {brief.risk}",
            f"- Missing Data: {brief.missing_data}",
            f"- Source Quality: {brief.source_quality}",
            "",
            "## Decision Points",
            "",
            points or "- None.",
            "",
            "## Risk Notes",
            "",
            risks or "- None.",
            "",
            "## Report Notes",
            "",
            notes or "- None.",
            "",
            "## Final Summary",
            "",
            brief.final_summary,
            "",
            "## Disclaimer",
            "",
            "Not financial advice.",
            "",
        ]
    )

