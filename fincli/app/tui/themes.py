"""Theme presets for FinCLI TUI.

Each theme defines color tokens for the terminal UI.
Supports true color (24-bit hex) and optional gradient backgrounds.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ThemePreset:
    """Color tokens for a FinCLI theme."""
    name: str
    description: str
    bg: str
    bg_alt: str
    text: str
    muted: str
    accent: str
    border: str
    positive: str
    negative: str
    caution: str
    gradient_start: str = ""
    gradient_end: str = ""
    gradient_angle: int = 180


THEMES: dict[str, ThemePreset] = {
    "midnight": ThemePreset(
        name="midnight",
        description="near-black + warm coral accent",
        bg="#0d0d0d",
        bg_alt="#141414",
        text="#e6e6e6",
        muted="#7a7a7a",
        accent="#d97757",
        border="#3a3a3a",
        positive="#22c55e",
        negative="#ef4444",
        caution="#facc15",
    ),
    "ocean": ThemePreset(
        name="ocean",
        description="deep navy + teal accent",
        bg="#0a1628",
        bg_alt="#0f1f38",
        text="#d4e5f7",
        muted="#5a7a9a",
        accent="#2dd4bf",
        border="#1e3a5f",
        positive="#34d399",
        negative="#f87171",
        caution="#fbbf24",
    ),
    "forest": ThemePreset(
        name="forest",
        description="dark green + gold accent",
        bg="#0a1a0a",
        bg_alt="#0f250f",
        text="#d4e8d4",
        muted="#5a8a5a",
        accent="#d4a824",
        border="#1a3a1a",
        positive="#4ade80",
        negative="#f87171",
        caution="#facc15",
    ),
    "solarized": ThemePreset(
        name="solarized",
        description="classic solarized dark",
        bg="#002b36",
        bg_alt="#073642",
        text="#93a1a1",
        muted="#586e75",
        accent="#b58900",
        border="#073642",
        positive="#859900",
        negative="#dc322f",
        caution="#cb4b16",
    ),
    "dracula": ThemePreset(
        name="dracula",
        description="purple/pink accents",
        bg="#282a36",
        bg_alt="#343746",
        text="#f8f8f2",
        muted="#6272a4",
        accent="#ff79c6",
        border="#44475a",
        positive="#50fa7b",
        negative="#ff5555",
        caution="#f1fa8c",
    ),
    "light": ThemePreset(
        name="light",
        description="clean white background",
        bg="#fafafa",
        bg_alt="#f0f0f0",
        text="#1a1a1a",
        muted="#6b7280",
        accent="#2563eb",
        border="#d1d5db",
        positive="#16a34a",
        negative="#dc2626",
        caution="#ca8a04",
    ),
    "gradient": ThemePreset(
        name="gradient",
        description="true-color gradient background",
        bg="#0f0c29",
        bg_alt="#1a1545",
        text="#e6e6e6",
        muted="#7a7a7a",
        accent="#f72585",
        border="#3a3a5a",
        positive="#22c55e",
        negative="#ef4444",
        caution="#facc15",
        gradient_start="#0f0c29",
        gradient_end="#302b63",
        gradient_angle=135,
    ),
}

DEFAULT_THEME = "midnight"


def get_theme(name: str) -> ThemePreset:
    """Get theme by name, falling back to midnight."""
    return THEMES.get(name, THEMES[DEFAULT_THEME])


def list_themes() -> list[ThemePreset]:
    """Return all available themes."""
    return list(THEMES.values())


def load_custom_theme(path: Path) -> ThemePreset:
    """Load a custom theme from a JSON file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    required = {"name", "bg", "text", "muted", "accent", "border", "positive", "negative", "caution"}
    missing = required - set(data.keys())
    if missing:
        raise ValueError(f"Theme JSON missing fields: {', '.join(missing)}")
    return ThemePreset(
        name=str(data["name"]),
        description=str(data.get("description", "custom theme")),
        bg=str(data["bg"]),
        bg_alt=str(data.get("bg_alt", data["bg"])),
        text=str(data["text"]),
        muted=str(data["muted"]),
        accent=str(data["accent"]),
        border=str(data["border"]),
        positive=str(data["positive"]),
        negative=str(data["negative"]),
        caution=str(data["caution"]),
        gradient_start=str(data.get("gradient_start", "")),
        gradient_end=str(data.get("gradient_end", "")),
        gradient_angle=int(data.get("gradient_angle", 180)),
    )


def save_custom_theme(path: Path, preset: ThemePreset) -> None:
    """Save a theme preset to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(preset), indent=2), encoding="utf-8")


def register_custom_theme(preset: ThemePreset) -> None:
    """Register a custom theme in the runtime theme registry."""
    THEMES[preset.name] = preset
