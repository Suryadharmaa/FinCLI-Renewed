"""Theme constants for the Textual UI."""

APP_CSS = """
Screen {
    background: #050505;
    color: #e5e7eb;
}

Header {
    background: #0b0f14;
    color: #22d3ee;
    text-style: bold;
}

#workspace {
    height: 1fr;
    width: 100%;
}

#main {
    width: 1fr;
    height: 1fr;
    padding: 1 6;
    background: #050505;
}

#output {
    background: #050505;
    color: #e5e7eb;
    border: none;
}

#command_area {
    dock: bottom;
    height: auto;
    background: #050505;
    padding: 0 6 1 6;
}

#command_line {
    height: 3;
    margin: 0 0 1 0;
    border: none;
    background: #262a27;
    color: #f8fafc;
}

#command_prompt {
    width: 3;
    height: 3;
    background: #262a27;
    color: #22d3ee;
    text-style: bold;
    padding: 0 0 0 2;
}

#command_input {
    width: 1fr;
    height: 3;
    border: none;
    background: #262a27;
    color: #f8fafc;
    padding: 0 2 0 0;
}

#command_input:focus {
    border: none;
}

#command_palette_scroll {
    height: 9;
    margin: 0 0 0 0;
    background: #050505;
    color: #f8fafc;
    scrollbar-size: 1 1;
    scrollbar-background: #050505;
    scrollbar-color: #22d3ee;
}

#command_palette {
    height: auto;
    margin: 0 0 0 0;
    background: #050505;
    color: #f8fafc;
}

#status_bar {
    dock: bottom;
    height: 1;
    background: #0b0f14;
    color: #64748b;
    padding: 0 6;
}

.section-title {
    color: #7dd3fc;
    text-style: bold;
}

.muted {
    color: #94a3b8;
}

#ai_selector_card {
    width: 78;
    height: 30;
    background: #252525;
    color: #f8fafc;
    padding: 1;
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
    border: solid #8a8a8a;
    background: #252525;
    color: #f8fafc;
    padding: 0 1;
}

#ai_selector_search:focus {
    border: solid #a3a3a3;
}

#ai_selector_scroll {
    height: 1fr;
    margin: 0 1;
    background: #252525;
    scrollbar-size: 1 1;
    scrollbar-background: #252525;
    scrollbar-color: #22d3ee;
}

#ai_selector_list {
    height: auto;
    background: #252525;
    color: #f8fafc;
}

#ai_selector_help {
    height: 3;
    color: #9ca3af;
    padding: 1 0 0 0;
}
"""
