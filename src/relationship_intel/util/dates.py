"""Week math. Weeks start Monday (decision 2026-07-04)."""

from __future__ import annotations

from datetime import date, timedelta


def monday_of_week(d: date) -> date:
    return d - timedelta(days=d.weekday())


def week_label(week_start: date) -> str:
    iso = week_start.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def parse_iso_date(value: str) -> date:
    return date.fromisoformat(value)
