"""CSV and JSON export helpers."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from fincli.app.utils.errors import CommandError


def export_rows(rows: list[dict[str, Any]], fmt: str, target: str | Path) -> Path:
    """Export rows to CSV or JSON and return the written path."""
    export_format = fmt.lower()
    path = _safe_export_path(target)
    path.parent.mkdir(parents=True, exist_ok=True)

    if export_format == "json":
        path.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
        return path

    if export_format == "csv":
        fieldnames = _fieldnames(rows)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return path

    raise CommandError("Format export harus csv atau json.")


def _fieldnames(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return []
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    return fields


def _safe_export_path(target: str | Path) -> Path:
    path = Path(target).expanduser()
    if any(part == ".." for part in path.parts):
        raise CommandError("Path export tidak boleh mengandung '..'.")
    if path.suffix.lower() not in {".csv", ".json"}:
        raise CommandError("Path export harus berakhiran .csv atau .json.")
    return path
