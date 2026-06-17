"""Data trust policy for AI/research outputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fincli.app.providers.reliability import STATUS_OK, STATUS_PARTIAL_DATA, STATUS_UNAVAILABLE
from fincli.app.services.data_quality import DataQualityReport


@dataclass(frozen=True, slots=True)
class DataTrustGate:
    level: str
    action: str
    confidence_cap: int
    max_signal_strength: str
    reasons: tuple[str, ...]
    required_verification: tuple[str, ...]

    def compact(self) -> str:
        reasons = "; ".join(self.reasons) if self.reasons else "none"
        verify = "; ".join(self.required_verification) if self.required_verification else "none"
        return (
            f"level={self.level} | action={self.action} | confidence_cap={self.confidence_cap}% | "
            f"max_signal={self.max_signal_strength} | reasons={reasons} | verify={verify}"
        )

    def prompt_context(self) -> str:
        return (
            "Data Trust Gate:\n"
            f"- Trust Level: {self.level}\n"
            f"- AI Action: {self.action}\n"
            f"- Confidence Cap: {self.confidence_cap}%\n"
            f"- Max Signal Strength: {self.max_signal_strength}\n"
            f"- Reasons: {', '.join(self.reasons) if self.reasons else 'none'}\n"
            f"- Required Verification: {', '.join(self.required_verification) if self.required_verification else 'none'}"
        )


def build_data_trust_gate(
    quality: DataQualityReport,
    provider_metrics: dict[str, Any] | None = None,
) -> DataTrustGate:
    """Convert data quality and provider runtime metrics into an AI confidence policy."""
    reasons: list[str] = []
    verify: list[str] = []
    metrics = provider_metrics or {}

    if quality.reliability_status == STATUS_UNAVAILABLE or "quote" in quality.missing_fields or "ohlcv" in quality.missing_fields:
        reasons.append(f"critical market data unavailable: {quality.compact()}")
        verify.extend(("quote availability", "OHLCV history availability", "provider entitlement"))
        return DataTrustGate(
            level="blocked",
            action="no_directional_signal",
            confidence_cap=20,
            max_signal_strength="caution only",
            reasons=tuple(reasons),
            required_verification=tuple(verify),
        )

    if quality.reliability_status == STATUS_PARTIAL_DATA or quality.score < 65 or quality.missing_fields:
        reasons.append(f"partial data quality: {quality.compact()}")
        if quality.missing_fields:
            verify.append("missing data: " + ", ".join(quality.missing_fields))

    weak_metrics = _weak_metric_reasons(metrics)
    reasons.extend(weak_metrics)
    if weak_metrics:
        verify.append("provider reliability/fallback chain")

    if quality.score >= 85 and quality.reliability_status == STATUS_OK and not weak_metrics:
        return DataTrustGate(
            level="strong",
            action="normal_scenario_analysis",
            confidence_cap=80,
            max_signal_strength="candidate buy/sell allowed with confirmation",
            reasons=tuple(reasons),
            required_verification=tuple(verify),
        )

    if quality.score >= 65 and quality.reliability_status == STATUS_OK and len(weak_metrics) <= 1:
        return DataTrustGate(
            level="usable",
            action="moderated_scenario_analysis",
            confidence_cap=60,
            max_signal_strength="watchlist bias only",
            reasons=tuple(reasons),
            required_verification=tuple(verify),
        )

    return DataTrustGate(
        level="limited",
        action="caution_first_analysis",
        confidence_cap=45,
        max_signal_strength="caution or wait-for-confirmation only",
        reasons=tuple(reasons) or (f"data quality below production threshold: {quality.compact()}",),
        required_verification=tuple(verify) or ("provider data quality",),
    )


def _weak_metric_reasons(provider_metrics: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for provider, metric in provider_metrics.items():
        calls = int(getattr(metric, "calls", 0))
        if calls <= 0:
            continue
        success_rate = float(getattr(metric, "success_rate", 0.0))
        errors = int(getattr(metric, "errors", 0))
        fallbacks = int(getattr(metric, "fallbacks", 0))
        if calls >= 2 and success_rate < 50:
            reasons.append(f"{provider} success rate weak ({success_rate:.1f}% over {calls} calls)")
        if errors >= 2:
            reasons.append(f"{provider} returned {errors} error(s)")
        if fallbacks >= 2:
            reasons.append(f"{provider} needed {fallbacks} fallback(s)")
    return reasons
