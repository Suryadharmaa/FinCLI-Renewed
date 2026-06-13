"""Curated financial agent registry for FinCLI."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Agent:
    slug: str
    name: str
    category: str
    framework: str
    role: str


class AgentRegistry:
    """37-agent catalog across trader, investor, economic, and geopolitics frameworks."""

    def __init__(self, agents: tuple[Agent, ...] | None = None) -> None:
        self._agents = agents or AGENTS

    def all(self) -> tuple[Agent, ...]:
        return self._agents

    def categories(self) -> tuple[str, ...]:
        return tuple(sorted({agent.category for agent in self._agents}))

    def get(self, slug: str) -> Agent | None:
        normalized = slug.strip().lower()
        return next((agent for agent in self._agents if agent.slug == normalized), None)

    def by_category(self, category: str) -> list[Agent]:
        normalized = category.strip().lower()
        return [agent for agent in self._agents if agent.category == normalized]


AGENTS: tuple[Agent, ...] = (
    Agent("buffett", "Warren Buffett", "investor", "quality value", "Business quality, moat, cashflow durability."),
    Agent("graham", "Benjamin Graham", "investor", "deep value", "Margin of safety and balance-sheet conservatism."),
    Agent("lynch", "Peter Lynch", "investor", "growth at reasonable price", "Story, earnings growth, and valuation discipline."),
    Agent("munger", "Charlie Munger", "investor", "mental models", "Incentives, durability, and avoiding stupidity."),
    Agent("klarman", "Seth Klarman", "investor", "risk-first value", "Downside protection and asymmetric payoff."),
    Agent("marks", "Howard Marks", "investor", "cycle risk", "Market cycle, credit risk, and second-level thinking."),
    Agent("fisher", "Philip Fisher", "investor", "scuttlebutt growth", "Qualitative growth and management quality."),
    Agent("dalio", "Ray Dalio", "economic", "macro regime", "Debt cycle, liquidity, rates, and diversification."),
    Agent("soros", "George Soros", "trader", "reflexivity", "Crowded positioning and feedback loops."),
    Agent("livermore", "Jesse Livermore", "trader", "price action", "Trend following, pivots, and discipline."),
    Agent("wyckoff", "Richard Wyckoff", "trader", "accumulation distribution", "Volume, composite operator, and phase analysis."),
    Agent("minervini", "Mark Minervini", "trader", "momentum risk", "Relative strength, volatility contraction, and tight risk."),
    Agent("oneil", "William O'Neil", "trader", "CAN SLIM", "Earnings momentum, leadership, and breakout quality."),
    Agent("tudor", "Paul Tudor Jones", "trader", "macro trading", "Asymmetric trades, trend, and risk control."),
    Agent("druckenmiller", "Stanley Druckenmiller", "trader", "concentrated macro", "Liquidity, policy, and high-conviction asymmetry."),
    Agent("seykota", "Ed Seykota", "trader", "systematic trend", "Trend rules, stops, and emotional control."),
    Agent("volatility", "Volatility Analyst", "trader", "volatility regime", "ATR, options pressure, VIX, and realized volatility."),
    Agent("liquidity", "Liquidity Analyst", "trader", "market microstructure", "Liquidity zones, stops, gaps, and execution risk."),
    Agent("snr", "Support Resistance Analyst", "trader", "SNR and pivots", "Pivot highs/lows, breakouts, rejection, and volume."),
    Agent("volume", "Volume Analyst", "trader", "volume confirmation", "Participation, abnormal volume, and failed moves."),
    Agent("risk", "Risk Manager", "trader", "position risk", "Invalidation, SL/TP, RR, and exposure control."),
    Agent("fed", "Federal Reserve Analyst", "economic", "US monetary policy", "Rates, inflation, labor, and dollar liquidity."),
    Agent("ecb", "ECB Analyst", "economic", "Europe macro", "Euro area rates, inflation, PMI, and credit conditions."),
    Agent("boj", "BOJ Analyst", "economic", "Japan macro", "Yield control, JPY, inflation, and carry trades."),
    Agent("bi", "Bank Indonesia Analyst", "economic", "Indonesia macro", "BI rate, IDR, inflation, and capital flows."),
    Agent("fred", "FRED Macro Analyst", "economic", "macro indicators", "US time series and regime confirmation."),
    Agent("imf", "IMF Analyst", "economic", "global macro", "Growth, debt, current account, and country risk."),
    Agent("worldbank", "World Bank Analyst", "economic", "development macro", "Long-term country indicators and structural trend."),
    Agent("commodity", "Commodity Macro Analyst", "economic", "commodity cycle", "Energy, metals, weather, and supply chain."),
    Agent("credit", "Credit Analyst", "economic", "credit spreads", "Default risk, spreads, and funding stress."),
    Agent("geopolitics", "Geopolitical Strategist", "geopolitics", "event risk", "Conflict, sanctions, elections, and risk premium."),
    Agent("energygeo", "Energy Geopolitics Analyst", "geopolitics", "energy security", "Oil, gas, shipping routes, and supply shocks."),
    Agent("china", "China Policy Analyst", "geopolitics", "China policy", "Credit impulse, regulation, property, and geopolitics."),
    Agent("supplychain", "Supply Chain Analyst", "geopolitics", "trade routes", "Shipping, logistics, and operational disruptions."),
    Agent("fxgeo", "FX Geopolitics Analyst", "geopolitics", "currency risk", "Sovereign risk, reserves, policy, and flows."),
    Agent("sentiment", "Sentiment Analyst", "trader", "news sentiment", "Market tone, crowding, and narrative shifts."),
    Agent("judge", "FinCLI Judge", "trader", "evidence arbitration", "Weighs bull, bear, and caution cases into final scenario."),
)
