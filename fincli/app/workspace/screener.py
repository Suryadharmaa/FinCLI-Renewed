"""Bounded comparison grammar; never evaluate user expressions as code."""

from __future__ import annotations

import re
from typing import Any

from fincli.app.workspace.models import finite

FIELDS = {
    "revenue_growth",
    "net_margin",
    "operating_margin",
    "debt_to_equity",
    "roe",
    "roic",
    "free_cash_flow",
    "pe",
    "market_cap",
    "rsi",
    "price",
    "sma_fast",
    "sma_slow",
    "atr",
}
PERCENT_FIELDS = {"revenue_growth", "net_margin", "operating_margin", "roe", "roic", "rsi"}
COMPARISON = re.compile(r"^([a-z_]+)\s*(>=|<=|!=|==|>|<)\s*(-?\d+(?:\.\d+)?)(%?)$", re.I)


class ScreenExpression:
    def __init__(self, expression: str):
        if not expression or len(expression) > 1000:
            raise ValueError("Screen expression must contain 1-1000 characters.")
        self.expression = expression
        self.groups = []
        clauses = re.split(r"\s+or\s+", expression, flags=re.I)
        for clause in clauses:
            group = []
            for item in re.split(r"\s+and\s+", clause, flags=re.I):
                match = COMPARISON.fullmatch(item.strip())
                if not match:
                    raise ValueError("Use comparisons joined by and/or, e.g. revenue_growth > 10% and rsi < 40.")
                field, op, number, percent = match.groups()
                field = field.lower()
                if field not in FIELDS or percent and field not in PERCENT_FIELDS:
                    raise ValueError(f"Unsupported field or percent unit: {field}.")
                threshold = finite(number)
                if threshold is None:
                    raise ValueError("Threshold must be finite.")
                group.append((field, op, threshold))
            self.groups.append(group)
        if sum(map(len, self.groups)) > 20:
            raise ValueError("At most 20 comparisons are supported.")

    def evaluate(self, row: dict[str, Any]) -> dict[str, Any]:
        reasons, missing, passing = [], set(), False
        for group in self.groups:
            matches = []
            for field, op, threshold in group:
                value = finite(row.get(field))
                if value is None:
                    missing.add(field)
                    matches.append(False)
                    continue
                success = {
                    ">": value > threshold,
                    "<": value < threshold,
                    ">=": value >= threshold,
                    "<=": value <= threshold,
                    "==": value == threshold,
                    "!=": value != threshold,
                }[op]
                matches.append(success)
                reasons.append(
                    {"field": field, "operator": op, "threshold": threshold, "value": value, "passed": success}
                )
            passing = passing or all(matches)
        return {"passed": passing, "comparisons": reasons, "missing_fields": sorted(missing)}
