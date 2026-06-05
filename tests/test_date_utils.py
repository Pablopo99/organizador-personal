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


def test_today_madrid_owl_before_4am_returns_previous_day():
    """Modo búho: 23:30 UTC del 19 = 01:30 Madrid del 20 (verano, UTC+2).
    Como es antes de las 4:00, el día lógico sigue siendo el 19."""
    fake_now = datetime(2026, 7, 19, 23, 30, tzinfo=pytz.UTC)
    with patch.object(date_utils, "_now_utc", return_value=fake_now):
        assert date_utils.today_madrid() == date(2026, 7, 19)


def test_today_madrid_returns_today_when_within_same_day():
    """A las 12:00 UTC, en Madrid son las 14:00 — mismo día (>= 4:00)."""
    fake_now = datetime(2026, 7, 19, 12, 0, tzinfo=pytz.UTC)
    with patch.object(date_utils, "_now_utc", return_value=fake_now):
        assert date_utils.today_madrid() == date(2026, 7, 19)


def test_today_madrid_owl_just_before_cutoff():
    """03:59 Madrid (01:59 UTC verano) → todavía día anterior."""
    fake_now = datetime(2026, 7, 20, 1, 59, tzinfo=pytz.UTC)  # 03:59 Madrid
    with patch.object(date_utils, "_now_utc", return_value=fake_now):
        assert date_utils.today_madrid() == date(2026, 7, 19)


def test_today_madrid_owl_at_cutoff_rolls_over():
    """04:00 Madrid (02:00 UTC verano) → ya es el día nuevo."""
    fake_now = datetime(2026, 7, 20, 2, 0, tzinfo=pytz.UTC)  # 04:00 Madrid
    with patch.object(date_utils, "_now_utc", return_value=fake_now):
        assert date_utils.today_madrid() == date(2026, 7, 20)


def test_now_iso_not_shifted_by_owl_mode():
    """now_iso (timestamp real) NO se desplaza con el modo búho: a las 01:30
    Madrid devuelve la fecha/hora real, no la del día anterior."""
    fake_now = datetime(2026, 7, 19, 23, 30, tzinfo=pytz.UTC)  # 01:30 Madrid día 20
    with patch.object(date_utils, "_now_utc", return_value=fake_now):
        assert date_utils.now_iso().startswith("2026-07-20T01:30")


def test_now_madrid_naive_returns_madrid_wallclock_as_naive():
    fake_now = datetime(2026, 7, 19, 12, 0, tzinfo=pytz.UTC)
    with patch.object(date_utils, "_now_utc", return_value=fake_now):
        result = date_utils.now_madrid_naive()
        assert result.tzinfo is None
        assert result.hour == 14  # UTC 12:00 + verano = 14:00 Madrid
        assert result.day == 19
