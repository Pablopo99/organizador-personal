from datetime import date, datetime

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
