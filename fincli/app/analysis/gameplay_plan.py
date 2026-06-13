"""Translate local user profile into risk constraints for AI analysis."""

from __future__ import annotations

from dataclasses import dataclass

from fincli.app.modules.user_profile import UserProfile


@dataclass(frozen=True, slots=True)
class GameplayPlan:
    gameplay: str
    asset_class: str
    max_sl: str
    minimum_rr: str
    note: str


def build_gameplay_plan(profile: UserProfile | None, symbol: str) -> GameplayPlan | None:
    if profile is None:
        return None

    asset_class = infer_asset_class(symbol)
    gameplay = profile.gameplay
    max_sl = _max_sl(gameplay, asset_class, symbol)
    note = (
        f"Profile equity {profile.equity:g} {profile.currency}, leverage {profile.leverage}, "
        f"experience {profile.years_in_investment:g} years. Use risk-aware scenarios, not guarantees."
    )
    return GameplayPlan(gameplay=gameplay, asset_class=asset_class, max_sl=max_sl, minimum_rr="1:1.5", note=note)


def format_gameplay_context(profile: UserProfile | None, symbol: str) -> str:
    plan = build_gameplay_plan(profile, symbol)
    if profile is None or plan is None:
        return (
            "User Gameplay Profile: not configured.\n"
            "Ask user to run /profile set <name> <equity> <currency> <leverage> <years> for tailored SL/TP context."
        )
    return (
        "User Gameplay Profile:\n"
        f"- Name: {profile.name}\n"
        f"- Equity: {profile.equity:g} {profile.currency}\n"
        f"- Leverage: {profile.leverage}\n"
        f"- Experience: {profile.years_in_investment:g} years\n"
        f"- Gameplay: {plan.gameplay}\n"
        f"- Asset Class: {plan.asset_class}\n"
        f"- Max SL Guide: {plan.max_sl}\n"
        f"- Minimum RR: {plan.minimum_rr}\n"
        f"- Risk Note: {plan.note}"
    )


def infer_asset_class(symbol: str) -> str:
    normalized = symbol.upper()
    if any(token in normalized for token in ("XAU", "GOLD", "XAG", "SILVER", "WTI", "BRENT", "OIL")):
        return "commodities"
    if any(token in normalized for token in ("SPX", "SP500", "NAS", "NDX", "DAX", "FTSE", "NIKKEI", "HSI", "DJI", "US30")):
        return "indices"
    compact = normalized.replace("/", "").replace("-", "").replace("=", "")
    if len(compact) == 6 and compact[:3].isalpha() and compact[3:].isalpha():
        return "forex"
    return "stocks/crypto"


def _max_sl(gameplay: str, asset_class: str, symbol: str) -> str:
    if asset_class == "forex":
        return {"Scalper": "< 15 pips", "Intra day": "< 20 pips", "Day trade": "< 25 pips"}.get(gameplay, "profile-dependent")
    if asset_class == "commodities":
        if gameplay == "Scalper":
            return "< 31 pips"
        if gameplay == "Intra day":
            return "< 60 pips"
        if gameplay == "Day trade":
            return "< 120 pips for gold, < 60 pips for other commodities"
        return "profile-dependent"
    if asset_class == "indices":
        return {"Scalper": "< 51 pips", "Intra day": "< 71 pips", "Day trade": "< 120 pips"}.get(gameplay, "profile-dependent")
    return "use ATR/support-resistance based invalidation; keep RR >= 1:1.5"
