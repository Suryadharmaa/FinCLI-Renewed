"""Terminal charting with ASCII candlestick and indicator overlays."""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from fincli.app.analysis.indicators import (
    _atr,
    _bollinger,
    _ema_series,
    _macd,
    _rsi,
    _sma,
)
from fincli.app.providers.market.base import Candle


# ---------------------------------------------------------------------------
# Chart configuration
# ---------------------------------------------------------------------------

CHART_WIDTH = 80
CHART_HEIGHT = 20

# ASCII characters for candlestick rendering
CANDLE_UP = "█"       # Bullish candle body
CANDLE_DOWN = "░"     # Bearish candle body
CANDLE_WICK = "│"     # High/Low wick
CANDLE_FLAT = "─"     # Doji (open == close)


@dataclass(frozen=True, slots=True)
class ChartConfig:
    width: int = CHART_WIDTH
    height: int = CHART_HEIGHT
    show_volume: bool = True
    overlays: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Chart rendering
# ---------------------------------------------------------------------------


def render_candlestick_chart(
    candles: list[Candle],
    symbol: str,
    period: str = "",
    config: ChartConfig | None = None,
) -> Panel:
    """Render ASCII candlestick chart in a Rich Panel."""
    if not candles:
        return Panel("[dim]No candle data available.[/dim]", title=f"Chart: {symbol}")

    cfg = config or ChartConfig()
    width = cfg.width
    height = cfg.height

    # Calculate price range
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    closes = [c.close for c in candles]
    volumes = [c.volume for c in candles]

    price_min = min(lows)
    price_max = max(highs)
    price_range = price_max - price_min if price_max > price_min else 1.0

    # Limit candles to chart width
    display_candles = candles[-width:] if len(candles) > width else candles
    chart_w = len(display_candles)

    # Build the chart grid
    grid: list[list[str]] = [[" " for _ in range(chart_w)] for _ in range(height)]

    # Map prices to row indices (0 = top = highest price)
    def price_to_row(price: float) -> int:
        return max(0, min(height - 1, int((price_max - price) / price_range * (height - 1))))

    for col, candle in enumerate(display_candles):
        if col >= width:
            break

        row_open = price_to_row(candle.open)
        row_close = price_to_row(candle.close)
        row_high = price_to_row(candle.high)
        row_low = price_to_row(candle.low)

        # Draw wick (high to low)
        for row in range(row_high, row_low + 1):
            if 0 <= row < height:
                grid[row][col] = CANDLE_WICK

        # Draw body
        body_top = min(row_open, row_close)
        body_bot = max(row_open, row_close)

        is_bullish = candle.close >= candle.open
        body_char = CANDLE_UP if is_bullish else CANDLE_DOWN

        if body_top == body_bot:
            # Doji
            if 0 <= body_top < height:
                grid[body_top][col] = CANDLE_FLAT
        else:
            for row in range(body_top, body_bot + 1):
                if 0 <= row < height:
                    grid[row][col] = body_char

    # Build text output
    lines: list[str] = []

    # Price axis labels
    for row_idx in range(height):
        price_at_row = price_max - (row_idx / (height - 1)) * price_range
        label = f"{price_at_row:>10.2f} │"
        line_chars = "".join(grid[row_idx])
        lines.append(f"{label}{line_chars}")

    # Time axis
    lines.append(" " * 11 + "└" + "─" * chart_w)

    # Volume bars (optional)
    if cfg.show_volume and volumes:
        vol_max = max(volumes) if max(volumes) > 0 else 1
        vol_height = 4
        vol_grid: list[list[str]] = [[" " for _ in range(chart_w)] for _ in range(vol_height)]

        for col, (vol, candle) in enumerate(zip(volumes[-chart_w:], display_candles)):
            if col >= chart_w:
                break
            bar_h = max(1, int(vol / vol_max * vol_height))
            char = "█" if candle.close >= candle.open else "░"
            for row in range(vol_height - bar_h, vol_height):
                if 0 <= row < vol_height:
                    vol_grid[row][col] = char

        lines.append("")
        lines.append("    Vol   │" + "".join(vol_grid[0]))
        for row in range(1, vol_height):
            lines.append("          │" + "".join(vol_grid[row]))

    # Stats summary
    if display_candles:
        last = display_candles[-1]
        change = last.close - last.open
        pct = (change / last.open * 100) if last.open else 0
        color = "green" if change >= 0 else "red"
        lines.append("")
        lines.append(
            f"  O:{last.open:.2f}  H:{last.high:.2f}  L:{last.low:.2f}  "
            f"C:[{color}]{last.close:.2f}[/{color}]  "
            f"Vol:{last.volume:,.0f}  "
            f"Change:[{color}]{change:+.2f} ({pct:+.1f}%)[/{color}]"
        )

    chart_text = "\n".join(lines)
    title = f"📊 {symbol}"
    if period:
        title += f" ({period})"
    title += f" — {len(display_candles)} candles"

    return Panel(chart_text, title=title, border_style="cyan")


# ---------------------------------------------------------------------------
# Overlay rendering (RSI, MACD, Bollinger)
# ---------------------------------------------------------------------------


def render_rsi_overlay(candles: list[Candle], width: int = 80) -> Panel:
    """Render RSI sub-chart."""
    if len(candles) < 15:
        return Panel("[dim]Need at least 15 candles for RSI.[/dim]", title="RSI")

    closes = [c.close for c in candles]
    display = closes[-width:] if len(closes) > width else closes

    # Calculate RSI series
    rsi_values: list[float | None] = []
    for i in range(len(display)):
        window = closes[: len(closes) - width + i + 1] if len(closes) > width else display[: i + 1]
        rsi_val = _rsi(window, 14)
        rsi_values.append(rsi_val)

    height = 8
    lines: list[str] = []

    for row in range(height):
        level = 100 - (row / (height - 1)) * 100
        label = f"{level:>6.0f} │"
        line_chars = []
        for val in rsi_values:
            if val is None:
                line_chars.append(" ")
            else:
                rsi_row = int((100 - val) / 100 * (height - 1))
                if rsi_row == row:
                    if val > 70:
                        line_chars.append("[red]●[/red]")
                    elif val < 30:
                        line_chars.append("[green]●[/green]")
                    else:
                        line_chars.append("●")
                else:
                    line_chars.append(" ")
        lines.append(label + "".join(line_chars))

    # Overbought/oversold lines
    lines.append("       └" + "─" * min(width, len(rsi_values)))

    # Current RSI
    last_rsi = rsi_values[-1] if rsi_values else None
    if last_rsi is not None:
        color = "red" if last_rsi > 70 else "green" if last_rsi < 30 else "yellow"
        lines.append(f"  RSI(14): [{color}]{last_rsi:.1f}[/{color}]  "
                     f"(70=overbought, 30=oversold)")

    return Panel("\n".join(lines), title="RSI (14)", border_style="yellow")


def render_macd_overlay(candles: list[Candle], width: int = 80) -> Panel:
    """Render MACD sub-chart."""
    if len(candles) < 27:
        return Panel("[dim]Need at least 27 candles for MACD.[/dim]", title="MACD")

    closes = [c.close for c in candles]
    display = closes[-width:] if len(closes) > width else closes

    ema12 = _ema_series(closes, 12)
    ema26 = _ema_series(closes, 26)
    macd_line, signal_line = _macd(ema12, ema26)

    if not macd_line or not signal_line:
        return Panel("[dim]Insufficient data for MACD.[/dim]", title="MACD")

    # Take last N values
    macd_display = macd_line[-min(width, len(macd_line)):]
    signal_display = signal_line[-min(width, len(signal_line)):]

    height = 8
    all_vals = [v for v in macd_display + signal_display if v is not None]
    if not all_vals:
        return Panel("[dim]No MACD values.[/dim]", title="MACD")

    val_min = min(all_vals)
    val_max = max(all_vals)
    val_range = val_max - val_min if val_max != val_min else 1.0

    lines: list[str] = []
    for row in range(height):
        val_at_row = val_max - (row / (height - 1)) * val_range
        label = f"{val_at_row:>8.2f} │"
        line_chars = []
        for i in range(min(width, len(macd_display))):
            m = macd_display[i] if i < len(macd_display) else None
            s = signal_display[i] if i < len(signal_display) else None

            char = " "
            if m is not None:
                m_row = int((val_max - m) / val_range * (height - 1))
                if m_row == row:
                    char = "[cyan]█[/cyan]"
            if s is not None:
                s_row = int((val_max - s) / val_range * (height - 1))
                if s_row == row:
                    char = "[magenta]●[/magenta]"
            line_chars.append(char)
        lines.append(label + "".join(line_chars))

    lines.append("         └" + "─" * min(width, len(macd_display)))

    last_macd = macd_display[-1] if macd_display else None
    last_signal = signal_display[-1] if signal_display else None
    if last_macd is not None and last_signal is not None:
        hist = last_macd - last_signal
        color = "green" if hist >= 0 else "red"
        lines.append(
            f"  MACD: [cyan]{last_macd:.4f}[/cyan]  "
            f"Signal: [magenta]{last_signal:.4f}[/magenta]  "
            f"Histogram: [{color}]{hist:+.4f}[/{color}]"
        )

    return Panel("\n".join(lines), title="MACD (12,26,9)", border_style="magenta")


# ---------------------------------------------------------------------------
# Combined chart command
# ---------------------------------------------------------------------------


def build_chart_output(
    candles: list[Candle],
    symbol: str,
    period: str = "",
    overlays: list[str] | None = None,
    width: int = 80,
    height: int = 20,
) -> list[Panel]:
    """Build chart panels with optional overlays. Returns list of Rich Panels."""
    panels: list[Panel] = []

    # Main candlestick chart
    config = ChartConfig(width=width, height=height, show_volume=True)
    panels.append(render_candlestick_chart(candles, symbol, period, config))

    # Overlay charts
    if overlays:
        overlay_set = {o.lower() for o in overlays}
        if "rsi" in overlay_set:
            panels.append(render_rsi_overlay(candles, width))
        if "macd" in overlay_set:
            panels.append(render_macd_overlay(candles, width))

    return panels


# ---------------------------------------------------------------------------
# Equity curve chart (for backtest results)
# ---------------------------------------------------------------------------


def render_equity_curve(
    equity_curve: list[float],
    initial_equity: float,
    title: str = "Equity Curve",
    width: int = 80,
    height: int = 15,
) -> Panel:
    """Render ASCII equity curve chart for backtest results.

    Args:
        equity_curve: List of equity values (one per trade)
        initial_equity: Starting equity value
        title: Chart title
        width: Chart width in characters
        height: Chart height in lines

    Returns:
        Rich Panel with ASCII equity curve.
    """
    if not equity_curve:
        return Panel("[dim]No trades to display equity curve.[/dim]", title=title)

    # Add initial equity at the start
    all_values = [initial_equity] + equity_curve
    n = len(all_values)

    # Calculate range
    val_min = min(all_values)
    val_max = max(all_values)
    val_range = val_max - val_min if val_max > val_min else 1.0

    # Limit to width
    display_values = all_values[-width:] if n > width else all_values
    chart_w = len(display_values)

    # Build grid
    grid: list[list[str]] = [[" " for _ in range(chart_w)] for _ in range(height)]

    for col, value in enumerate(display_values):
        if col >= width:
            break
        # Map value to row (0 = top = highest value)
        row = max(0, min(height - 1, int((val_max - value) / val_range * (height - 1))))
        grid[row][col] = "●"

        # Connect to previous point
        if col > 0:
            prev_value = display_values[col - 1]
            prev_row = max(0, min(height - 1, int((val_max - prev_value) / val_range * (height - 1))))
            # Fill between rows
            min_row = min(row, prev_row)
            max_row = max(row, prev_row)
            for r in range(min_row, max_row + 1):
                if grid[r][col] == " ":
                    grid[r][col] = "│"

    # Build text output
    lines: list[str] = []

    # Value axis labels
    for row_idx in range(height):
        val_at_row = val_max - (row_idx / (height - 1)) * val_range
        label = f"${val_at_row:>10,.0f} │"
        line_chars = "".join(grid[row_idx])
        lines.append(f"{label}{line_chars}")

    # Time axis
    lines.append(" " * 11 + "└" + "─" * chart_w)

    # Stats summary
    final_equity = all_values[-1]
    peak = max(all_values)
    trough = min(all_values)
    total_return = ((final_equity - initial_equity) / initial_equity * 100) if initial_equity else 0
    drawdown = ((peak - trough) / peak * 100) if peak else 0

    color = "green" if total_return >= 0 else "red"
    lines.append("")
    lines.append(
        f"  Initial: ${initial_equity:,.2f}  "
        f"Final: [{color}]${final_equity:,.2f}[/{color}]  "
        f"Return: [{color}]{total_return:+.2f}%[/{color}]  "
        f"Peak: ${peak:,.2f}  "
        f"Max DD: {drawdown:.1f}%"
    )

    chart_text = "\n".join(lines)
    return Panel(chart_text, title=f"📊 {title}", border_style="cyan")
