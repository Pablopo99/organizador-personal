from datetime import date, datetime
from unittest.mock import patch

import pytz

import date_utils


def test_monday_of_week_from_monday():
    assert date_utils.monday_of_week(date(2026, 5, 11)) == date(2026, 5, 11)


def test_monday_of_week_from_wednesday():
    assert date_utils.monday_of_week(date(2026, 5, 13)) == date(2026, 5, 11)


def test_monday_of_week_from_sunday():
    assert date_utils.monday_of_week(date(2026, 5, 17)) == date(2026, 5, 11)


def test_now_iso_returns_string():
    s = date_utils.now_iso()
    parsed = datetime.fromisoformat(s)
    assert isinstance(parsed, datetime)


def test_format_human_es():
    dt = datetime(2026, 5, 22, 17, 0)
    s = date_utils.format_human_es(dt)
    assert "22" in s
    assert "may" in s.lower()
    assert "17:00" in s


def test_today_madrid_returns_madrid_date_when_utc_is_previous_day():
    """A las 23:30 UTC del 19, en Madrid son las 01:30 del 20 (verano, UTC+2)."""
    fake_now = datetime(2026, 7, 19, 23, 30, tzinfo=pytz.UTC)
    with patch.object(date_utils, "_now_utc", return_value=fake_now):
        assert date_utils.today_madrid() == date(2026, 7, 20)


def test_today_madrid_returns_today_when_within_same_day():
    """A las 12:00 UTC, en Madrid son las 14:00 — mismo día."""
    fake_now = datetime(2026, 7, 19, 12, 0, tzinfo=pytz.UTC)
    with patch.object(date_utils, "_now_utc", return_value=fake_now):
        assert date_utils.today_madrid() == date(2026, 7, 19)


def test_now_madrid_naive_returns_madrid_wallclock_as_naive():
    fake_now = datetime(2026, 7, 19, 12, 0, tzinfo=pytz.UTC)
    with patch.object(date_utils, "_now_utc", return_value=fake_now):
        result = date_utils.now_madrid_naive()
        assert result.tzinfo is None
        assert result.hour == 14  # UTC 12:00 + verano = 14:00 Madrid
        assert result.day == 19
