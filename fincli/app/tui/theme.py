"""Theme constants for the Textual UI.

Minimal Claude-CLI-inspired surface: neutral off-white text on near-black with a
single warm coral accent. Financial meaning still rides on the semantic colour
classes (green/red/yellow) so data keeps its bullish/bearish/caution coding.
"""

# Palette tokens
#   bg      #0d0d0d   near-black background
#   text    #e6e6e6   soft off-white
#   muted   #7a7a7a   hints, status, secondary text
#   accent  #d97757   warm coral (prompt, spinner, focus)
#   line    #3a3a3a   thin neutral borders
APP_CSS = """
Screen {
    background: #0d0d0d;
    color: #e6e6e6;
}

#workspace {
    height: 1fr;
    width: 100%;
}

#main {
    width: 1fr;
    height: 1fr;
    padding: 1 4 0 4;
    background: #0d0d0d;
}

#output_frame {
    height: 1fr;
    background: #0d0d0d;
    border: none;
    padding: 1 2;
}

#output {
    background: #0d0d0d;
    color: #e6e6e6;
    border: none;
    scrollbar-size: 1 1;
    scrollbar-background: #0d0d0d;
    scrollbar-color: #d97757;
}

#working {
    height: 1;
    display: none;
    background: #0d0d0d;
    color: #d97757;
    text-style: bold;
    padding: 0 4;
}

#command_area {
    dock: bottom;
    height: auto;
    background: #0d0d0d;
    padding: 0 4 1 4;
}

#command_hint {
    height: 1;
    background: #0d0d0d;
    color: #7a7a7a;
    padding: 0 1;
}

#command_line {
    height: 3;
    margin: 0 0 1 0;
    border: round #3a3a3a;
    background: #0d0d0d;
    color: #e6e6e6;
}

#command_line:focus-within {
    border: round #d97757;
}

#command_prompt {
    width: 3;
    height: 1;
    background: #0d0d0d;
    color: #d97757;
    text-style: bold;
    padding: 0 0 0 1;
}

#command_input {
    width: 1fr;
    height: 1;
    border: none;
    background: #0d0d0d;
    color: #e6e6e6;
    padding: 0 1 0 0;
}

#command_input:focus {
    border: none;
}

#command_palette_scroll {
    height: 9;
    margin: 0 0 0 0;
    background: #0d0d0d;
    color: #e6e6e6;
    scrollbar-size: 1 1;
    scrollbar-background: #0d0d0d;
    scrollbar-color: #d97757;
}

#command_palette {
    height: auto;
    margin: 0 0 0 0;
    background: #0d0d0d;
    color: #e6e6e6;
}

#status_bar {
    dock: bottom;
    height: 1;
    background: #0d0d0d;
    color: #7a7a7a;
    padding: 0 4;
}

.section-title {
    color: #e6e6e6;
    text-style: bold;
}

.muted {
    color: #7a7a7a;
}

.semantic-positive {
    color: #22c55e;
    text-style: bold;
}

.semantic-negative {
    color: #ef4444;
    text-style: bold;
}

.semantic-caution {
    color: #facc15;
    text-style: bold;
}

#ai_selector_card {
    width: 78;
    height: 30;
    background: #0d0d0d;
    color: #e6e6e6;
    padding: 1;
    border: round #d97757;
}

#ai_selector_title {
    height: 2;
    color: #e6e6e6;
    text-style: bold;
}

#ai_selector_provider {
    height: 2;
    color: #e6e6e6;
    padding: 0 2;
}

#ai_selector_search {
    height: 3;
    margin: 0 1 1 1;
    border: round #3a3a3a;
    background: #0d0d0d;
    color: #e6e6e6;
    padding: 0 1;
}

#ai_selector_search:focus {
    border: round #d97757;
}

#ai_selector_scroll {
    height: 1fr;
    margin: 0 1;
    background: #0d0d0d;
    scrollbar-size: 1 1;
    scrollbar-background: #0d0d0d;
    scrollbar-color: #d97757;
}

#ai_selector_list {
    height: auto;
    background: #0d0d0d;
    color: #e6e6e6;
}

#ai_selector_help {
    height: 3;
    color: #7a7a7a;
    padding: 1 0 0 0;
}
"""
