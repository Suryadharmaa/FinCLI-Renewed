"""Theme constants for the Textual UI.

Uses CSS variables so the theme can be swapped at runtime via build_theme_css().
Default is the midnight preset from themes.py.
"""

from __future__ import annotations

from fincli.app.tui.themes import DEFAULT_THEME, ThemePreset, get_theme


def build_theme_css(theme: ThemePreset | None = None) -> str:
    """Build the full APP_CSS with theme tokens substituted."""
    t = theme or get_theme(DEFAULT_THEME)
    gradient = ""
    if t.gradient_start and t.gradient_end:
        gradient = (
            f"    background: linear-gradient({t.gradient_angle}deg, "
            f"{t.gradient_start}, {t.gradient_end});\n"
        )
    else:
        gradient = f"    background: {t.bg};\n"

    return f"""
Screen {{
    {gradient}    color: {t.text};
}}

#workspace {{
    height: 1fr;
    width: 100%;
}}

#main {{
    width: 1fr;
    height: 1fr;
    padding: 1 4 0 4;
    background: {t.bg};
}}

#output_frame {{
    height: 1fr;
    background: {t.bg};
    border: none;
    padding: 1 2;
}}

#output {{
    background: {t.bg};
    color: {t.text};
    border: none;
    scrollbar-size: 1 1;
    scrollbar-background: {t.bg};
    scrollbar-color: {t.accent};
}}

#stream_output {{
    height: auto;
    max-height: 60%;
    background: {t.bg};
    color: {t.text};
    border: none;
    scrollbar-size: 1 1;
    scrollbar-background: {t.bg};
    scrollbar-color: {t.accent};
    margin: 0 0 1 0;
}}

#working {{
    height: 1;
    display: none;
    background: {t.bg};
    color: {t.accent};
    text-style: bold;
    padding: 0 4;
}}

#token_counter {{
    height: 1;
    display: none;
    background: {t.bg};
    color: {t.muted};
    padding: 0 4;
}}

#command_area {{
    dock: bottom;
    height: auto;
    background: {t.bg};
    padding: 0 4 1 4;
}}

#command_hint {{
    height: 1;
    background: {t.bg};
    color: {t.muted};
    padding: 0 1;
}}

#command_line {{
    height: 3;
    margin: 0 0 1 0;
    border: round {t.border};
    background: {t.bg};
    color: {t.text};
}}

#command_line:focus-within {{
    border: round {t.accent};
}}

#command_prompt {{
    width: 3;
    height: 1;
    background: {t.bg};
    color: {t.accent};
    text-style: bold;
    padding: 0 0 0 1;
}}

#command_input {{
    width: 1fr;
    height: 1;
    border: none;
    background: {t.bg};
    color: {t.text};
    padding: 0 1 0 0;
}}

#command_input:focus {{
    border: none;
}}

#command_palette_scroll {{
    height: 9;
    margin: 0 0 0 0;
    background: {t.bg};
    color: {t.text};
    scrollbar-size: 1 1;
    scrollbar-background: {t.bg};
    scrollbar-color: {t.accent};
}}

#command_palette {{
    height: auto;
    margin: 0 0 0 0;
    background: {t.bg};
    color: {t.text};
}}

#status_bar {{
    dock: bottom;
    height: 1;
    background: {t.bg};
    color: {t.muted};
    padding: 0 4;
}}

.section-title {{
    color: {t.text};
    text-style: bold;
}}

.muted {{
    color: {t.muted};
}}

.semantic-positive {{
    color: {t.positive};
    text-style: bold;
}}

.semantic-negative {{
    color: {t.negative};
    text-style: bold;
}}

.semantic-caution {{
    color: {t.caution};
    text-style: bold;
}}

#ai_selector_card {{
    width: 78;
    height: 30;
    background: {t.bg};
    color: {t.text};
    padding: 1;
    border: round {t.accent};
}}

#ai_selector_title {{
    height: 2;
    color: {t.text};
    text-style: bold;
}}

#ai_selector_provider {{
    height: 2;
    color: {t.text};
    padding: 0 2;
}}

#ai_selector_search {{
    height: 3;
    margin: 0 1 1 1;
    border: round {t.border};
    background: {t.bg};
    color: {t.text};
    padding: 0 1;
}}

#ai_selector_search:focus {{
    border: round {t.accent};
}}

#ai_selector_scroll {{
    height: 1fr;
    margin: 0 1;
    background: {t.bg};
    scrollbar-size: 1 1;
    scrollbar-background: {t.bg};
    scrollbar-color: {t.accent};
}}

#ai_selector_list {{
    height: auto;
    background: {t.bg};
    color: {t.text};
}}

#ai_selector_help {{
    height: 3;
    color: {t.muted};
    padding: 1 0 0 0;
}}
"""


# Default CSS for import compatibility
APP_CSS = build_theme_css()
