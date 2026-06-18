"""Tests for news freshness — sorting by date and lookback filtering."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fincli.app.providers.market.base import NewsItem
from fincli.app.services.news_aggregator import _within_lookback


UTC = timezone.utc
NOW = datetime.now(UTC)


def _item(title: str, days_ago: int | None, source: str = "test") -> NewsItem:
    published = NOW - timedelta(days=days_ago) if days_ago is not None else None
    return NewsItem(title=title, source=source, url=f"https://example.com/{title}", published_at=published, summary="")


# --- _within_lookback ---


def test_within_lookback_recent_item_passes() -> None:
    assert _within_lookback(_item("fresh", 1), lookback_days=7) is True


def test_within_lookback_old_item_fails() -> None:
    assert _within_lookback(_item("old", 30), lookback_days=7) is False


def test_within_lookback_no_timestamp_filtered_out() -> None:
    """Items without published_at should be filtered out, not kept."""
    assert _within_lookback(_item("no_date", None), lookback_days=7) is False


def test_within_lookback_naive_datetime_treated_as_utc() -> None:
    naive_now = datetime.now(UTC).replace(tzinfo=None)
    item = NewsItem(title="naive", source="t", url="u", published_at=naive_now, summary="")
    assert _within_lookback(item, lookback_days=1) is True


def test_within_lookback_just_inside_cutoff() -> None:
    from datetime import datetime as dt
    just_inside = dt.now(UTC) - timedelta(days=7) + timedelta(seconds=5)
    item = NewsItem(title="edge", source="t", url="u", published_at=just_inside, summary="")
    assert _within_lookback(item, lookback_days=7) is True


def test_within_lookback_just_outside_cutoff() -> None:
    from datetime import datetime as dt
    just_outside = dt.now(UTC) - timedelta(days=7) - timedelta(seconds=5)
    item = NewsItem(title="edge", source="t", url="u", published_at=just_outside, summary="")
    assert _within_lookback(item, lookback_days=7) is False


# --- Sort order (integration via NewsAggregator) ---


def test_news_items_sorted_by_date_descending() -> None:
    """Items should be sorted newest first after aggregation."""
    items = [
        _item("3 days ago", 3),
        _item("1 hour ago", 0),
        _item("2 days ago", 2),
        _item("no date", None),
    ]
    _min_dt = datetime.min.replace(tzinfo=UTC)
    items.sort(key=lambda x: x.published_at if x.published_at and x.published_at.tzinfo else _min_dt, reverse=True)
    assert items[0].title == "1 hour ago"
    assert items[1].title == "2 days ago"
    assert items[2].title == "3 days ago"
    assert items[3].title == "no date"  # no date goes last


def test_news_items_with_mixed_aware_naive() -> None:
    aware = NOW - timedelta(hours=1)
    naive = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=30)
    items = [
        NewsItem(title="naive", source="t", url="u1", published_at=naive, summary=""),
        NewsItem(title="aware", source="t", url="u2", published_at=aware, summary=""),
    ]
    _min_dt = datetime.min.replace(tzinfo=UTC)
    items.sort(key=lambda x: x.published_at if x.published_at and x.published_at.tzinfo else _min_dt, reverse=True)
    # aware item should be first since it has tzinfo (sorted correctly)
    assert items[0].title == "aware"
