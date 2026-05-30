"""Tests del helper _calculate_outcome (lógica pura, sin BD)."""
from datetime import date

import pytest

import tools


def test_same_day_is_on_time():
    assert tools._calculate_outcome(
        assigned=date(2026, 5, 30), today=date(2026, 5, 30)
    ) == "on_time"


def test_day_after_is_grace():
    assert tools._calculate_outcome(
        assigned=date(2026, 5, 30), today=date(2026, 5, 31)
    ) == "grace"


def test_two_days_after_is_none():
    assert tools._calculate_outcome(
        assigned=date(2026, 5, 30), today=date(2026, 6, 1)
    ) is None


def test_before_assigned_is_on_time():
    assert tools._calculate_outcome(
        assigned=date(2026, 5, 30), today=date(2026, 5, 29)
    ) == "on_time"


def test_assigned_none_returns_none():
    assert tools._calculate_outcome(
        assigned=None, today=date(2026, 5, 30)
    ) is None
