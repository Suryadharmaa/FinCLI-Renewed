"""Journal statistics and AI review prompt helpers."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class JournalStats:
    total_entries: int
    wins: int
    losses: int
    win_rate: float
    top_instrument: str
    top_emotion: str
    top_tags: list[str]


def calculate_journal_stats(entries: list[dict[str, object]]) -> JournalStats:
    total = len(entries)
    wins = sum(1 for entry in entries if str(entry.get("result", "")).lower() == "win")
    losses = sum(1 for entry in entries if str(entry.get("result", "")).lower() == "loss")
    win_rate = (wins / total * 100) if total else 0.0

    instruments = Counter(str(entry.get("instrument", "")) for entry in entries if entry.get("instrument"))
    emotions = Counter(str(entry.get("emotion", "")) for entry in entries if entry.get("emotion"))
    tags = Counter()
    for entry in entries:
        for tag in str(entry.get("tags", "")).split(","):
            cleaned = tag.strip()
            if cleaned:
                tags[cleaned] += 1

    return JournalStats(
        total_entries=total,
        wins=wins,
        losses=losses,
        win_rate=win_rate,
        top_instrument=instruments.most_common(1)[0][0] if instruments else "N/A",
        top_emotion=emotions.most_common(1)[0][0] if emotions else "N/A",
        top_tags=[tag for tag, _ in tags.most_common(5)],
    )


def build_journal_review_prompt(entries: list[dict[str, object]], stats: JournalStats) -> str:
    recent_lines = []
    for entry in entries[:20]:
        recent_lines.append(
            (
                f"- {entry.get('instrument')} | bias={entry.get('bias')} | result={entry.get('result')} | "
                f"emotion={entry.get('emotion')} | reason={entry.get('entry_reason')} | lesson={entry.get('lesson')}"
            )
        )
    return (
        "You are FinCLI's trading journal review assistant.\n"
        "Review the user's journal based only on the provided entries. Do not invent trades.\n"
        "Focus on process quality, recurring mistakes, emotional patterns, risk control, and concrete improvements.\n"
        "Do not provide financial advice or guaranteed trading signals.\n\n"
        f"Total Entries: {stats.total_entries}\n"
        f"Wins: {stats.wins}\n"
        f"Losses: {stats.losses}\n"
        f"Win Rate: {stats.win_rate:.4f}\n"
        f"Top Instrument: {stats.top_instrument}\n"
        f"Top Emotion: {stats.top_emotion}\n"
        f"Top Tags: {', '.join(stats.top_tags) if stats.top_tags else 'N/A'}\n\n"
        "Recent Entries:\n"
        f"{chr(10).join(recent_lines) if recent_lines else 'No entries.'}\n\n"
        "Return sections: Summary, Strengths, Repeated Mistakes, Risk Notes, Process Improvements, Disclaimer."
    )
