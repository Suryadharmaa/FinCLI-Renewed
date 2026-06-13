"""Theme constants for the Textual UI."""

APP_CSS = """
Screen {
    background: #00110b;
    color: #d9f99d;
}

Header {
    background: #000805;
    color: #22c55e;
    text-style: bold;
}

#workspace {
    height: 1fr;
    width: 100%;
}

#main {
    width: 1fr;
    height: 1fr;
    padding: 1 4 0 4;
    background: #00110b;
}

#top_strip {
    height: 3;
    content-align: center middle;
    background: #031b10;
    color: #86efac;
    border: heavy #15803d;
    text-style: bold;
    margin: 0 0 1 0;
}

#market_ribbon {
    height: 1;
    content-align: center middle;
    background: #020d08;
    color: #22c55e;
    text-style: bold;
    margin: 0 0 1 0;
}

#output_header {
    height: 1;
    background: #052e16;
    color: #bbf7d0;
    text-style: bold;
    padding: 0 1;
}

#output_frame {
    height: 1fr;
    background: #000805;
    border: heavy #166534;
    padding: 1 2;
}

#output {
    background: #000805;
    color: #e5e7eb;
    border: none;
    scrollbar-size: 1 1;
    scrollbar-background: #000805;
    scrollbar-color: #22c55e;
}

#command_area {
    dock: bottom;
    height: auto;
    background: #00110b;
    padding: 0 4 1 4;
}

#command_hint {
    height: 1;
    background: #020d08;
    color: #84cc16;
    padding: 0 1;
}

#command_line {
    height: 3;
    margin: 0 0 1 0;
    border: heavy #15803d;
    background: #031b10;
    color: #f8fafc;
}

#command_prompt {
    width: 4;
    height: 1;
    background: #031b10;
    color: #22c55e;
    text-style: bold;
    padding: 0 0 0 1;
}

#command_input {
    width: 1fr;
    height: 1;
    border: none;
    background: #031b10;
    color: #f8fafc;
    padding: 0 1 0 0;
}

#command_input:focus {
    border: none;
}

#command_palette_scroll {
    height: 9;
    margin: 0 0 0 0;
    background: #00110b;
    color: #f8fafc;
    scrollbar-size: 1 1;
    scrollbar-background: #00110b;
    scrollbar-color: #22c55e;
}

#command_palette {
    height: auto;
    margin: 0 0 0 0;
    background: #00110b;
    color: #f8fafc;
}

#status_bar {
    dock: bottom;
    height: 1;
    background: #000805;
    color: #86efac;
    padding: 0 4;
}

.section-title {
    color: #86efac;
    text-style: bold;
}

.muted {
    color: #64748b;
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
    background: #031b10;
    color: #f8fafc;
    padding: 1;
    border: heavy #15803d;
}

#ai_selector_title {
    height: 2;
    color: #f8fafc;
    text-style: bold;
}

#ai_selector_provider {
    height: 2;
    color: #f8fafc;
    padding: 0 2;
}

#ai_selector_search {
    height: 3;
    margin: 0 1 1 1;
    border: solid #22c55e;
    background: #020d08;
    color: #f8fafc;
    padding: 0 1;
}

#ai_selector_search:focus {
    border: solid #86efac;
}

#ai_selector_scroll {
    height: 1fr;
    margin: 0 1;
    background: #031b10;
    scrollbar-size: 1 1;
    scrollbar-background: #031b10;
    scrollbar-color: #22c55e;
}

#ai_selector_list {
    height: auto;
    background: #031b10;
    color: #f8fafc;
}

#ai_selector_help {
    height: 3;
    color: #9ca3af;
    padding: 1 0 0 0;
}
"""
