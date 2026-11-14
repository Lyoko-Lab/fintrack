"""Insights: income, spending and net cash flow over time, and where the spending went.

Periods are calendar days, Monday-to-Sunday weeks, months and years. A period still
running is compared with the same stretch of earlier periods (October 1-28 against
September 1-28, clamped at month end); a finished period is compared in full. The
comparison is the period before, the same dates a year earlier, or the average of the
three periods before. Income and spending come from measures.py, as on the Overview, so
the numbers agree across pages.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from .measures import Flow, daily_flows

GRANULARITIES = ("day", "week", "month", "year")
COMPARISONS = ("previous", "year", "average")
TREND_PERIODS = {"day": 30, "week": 26, "month": 24}  # years: every year with data
AVERAGE_OF = 3
FEATURED_GROUPS = 5  # one per donut color: a donut stays readable with five named slices plus "the rest"


def period_start(day: date, granularity: str) -> date:
    if granularity == "day":
        return day
    if granularity == "week":
        return day - timedelta(days=day.weekday())
    if granularity == "month":
        return day.replace(day=1)
    return day.replace(month=1, day=1)


def shift(start: date, granularity: str, periods: int) -> date:
    """The start of the period `periods` away from the one starting at `start`."""
    if granularity == "day":
        return start + timedelta(days=periods)
    if granularity == "week":
        return start + timedelta(weeks=periods)
    if granularity == "month":
        months = start.year * 12 + start.month - 1 + periods
        return date(months // 12, months % 12 + 1, 1)
    return date(start.year + periods, 1, 1)


def period_end(start: date, granularity: str) -> date:
    return shift(start, granularity, 1) - timedelta(days=1)


def years_earlier(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # February 29
        return day.replace(year=day.year - years, day=28)


@dataclass(frozen=True)
class Span:
    start: date
    end: date  # inclusive

    def as_dict(self) -> dict[str, str]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}


def focus_span(start: date, granularity: str, today: date) -> Span:
    """The period beginning at `start`, cut off at today while it is still running."""
    return Span(start, min(period_end(start, granularity), today))


def _same_stretch(focus: Span, granularity: str, start: date) -> Span:
    """As much of the period beginning at `start` as `focus` has covered of its own."""
    end = period_end(start, granularity)
    if focus.end == period_end(focus.start, granularity):
        return Span(start, end)
    if granularity == "month":
        return Span(start, start.replace(day=min(focus.end.day, end.day)))
    if granularity == "year":
        return Span(start, years_earlier(focus.end, focus.start.year - start.year))
    return Span(start, start + (focus.end - focus.start))


def comparison_spans(focus: Span, granularity: str, comparison: str) -> list[Span]:
    if comparison == "year":
        return [Span(years_earlier(focus.start, 1), years_earlier(focus.end, 1))]
    count = AVERAGE_OF if comparison == "average" else 1
    return [_same_stretch(focus, granularity, shift(focus.start, granularity, -k)) for k in range(1, count + 1)]


def _totals(daily: dict[date, Flow], spans: list[Span]) -> dict[str, int]:
    """Income, spending and net over `spans`, averaged when there are several."""
    total = sum((flow for day, flow in daily.items() for span in spans if span.start <= day <= span.end), Flow())
    income, spending = round(total.income / len(spans)), round(total.spending / len(spans))
    return {"income": income, "spending": spending, "net": income - spending}


def data_start(conn: sqlite3.Connection) -> date | None:
    first = conn.execute("SELECT MIN(transaction_date) FROM v_ledger").fetchone()[0]
    return date.fromisoformat(first) if first else None


def trend(conn: sqlite3.Connection, granularity: str, today: date) -> dict[str, Any]:
    """Income, spending and net for each recent period, oldest first, the running one last."""
    current = period_start(today, granularity)
    first = data_start(conn)
    if granularity == "year":
        starts = [date(year, 1, 1) for year in range((first or today).year, today.year + 1)]
    else:
        starts = [shift(current, granularity, -k) for k in range(TREND_PERIODS[granularity] - 1, -1, -1)]
    # Periods that ended before the first transaction say nothing, so leave them out.
    starts = [start for start in starts if first is None or period_end(start, granularity) >= first]
    daily = daily_flows(conn, starts[0], today) if starts else {}
    periods = []
    for start in starts:
        span = focus_span(start, granularity, today)
        periods.append(
            {**span.as_dict(), "complete": span.end == period_end(start, granularity), **_totals(daily, [span])}
        )
    return {"granularity": granularity, "today": today.isoformat(), "periods": periods}


def _by_category(conn: sqlite3.Connection, span: Span) -> dict[str, int]:
    """Spending (expense categories) or income (income categories) per category over a span."""
    rows = conn.execute(
        """
        SELECT category_id, flow_type, SUM(amount_cents)
        FROM v_ledger
        WHERE transaction_date BETWEEN ? AND ? AND flow_type IN ('income', 'expense') AND account_excluded = 0
        GROUP BY category_id
        """,
        (span.start.isoformat(), span.end.isoformat()),
    ).fetchall()
    return {row[0]: -row[2] if row[1] == "expense" else row[2] for row in rows}


def breakdown(conn: sqlite3.Connection, granularity: str, start: date, comparison: str, today: date) -> dict[str, Any]:
    """One period against its comparison: totals, plus spending and income by category group."""
    focus = focus_span(period_start(min(start, today), granularity), granularity, today)
    spans = comparison_spans(focus, granularity, comparison)
    daily = daily_flows(conn, min(span.start for span in spans), focus.end)

    current = _by_category(conn, focus)
    earlier = [_by_category(conn, span) for span in spans]
    compared = {
        category: round(sum(amounts.get(category, 0) for amounts in earlier) / len(earlier))
        for category in set().union(*earlier)
    }

    taxonomy = {row["id"]: row for row in conn.execute("SELECT id, parent_id, name, kind, position FROM categories")}
    groups: dict[str, dict[str, Any]] = {}
    children: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for category in set(current) | set(compared):
        row = taxonomy[category]
        group_id = row["parent_id"] or category
        entry = {"id": category, "name": row["name"], "current": current.get(category, 0), "comparison": compared.get(category, 0)}
        group = groups.setdefault(
            group_id,
            {"id": group_id, "name": taxonomy[group_id]["name"], "kind": row["kind"], "current": 0, "comparison": 0},
        )
        group["current"] += entry["current"]
        group["comparison"] += entry["comparison"]
        if group_id != category:
            children[group_id].append(entry)

    def ranked(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(entries, key=lambda e: (-e["current"], -e["comparison"], taxonomy[e["id"]]["position"]))

    result: dict[str, list[dict[str, Any]]] = {"expense": [], "income": []}
    for group in ranked(list(groups.values())):
        result[group.pop("kind")].append({**group, "children": ranked(children[group["id"]])})

    # The groups that usually spend the most: the past year's biggest, biggest first. The spending
    # donut gives each a fixed color, so it looks the same whichever period is selected.
    past_year = defaultdict(int)
    for category, amount in _by_category(conn, Span(years_earlier(today, 1) + timedelta(days=1), today)).items():
        if taxonomy[category]["kind"] == "expense":
            past_year[taxonomy[category]["parent_id"] or category] += amount
    featured = [group for group, amount in sorted(past_year.items(), key=lambda item: -item[1]) if amount > 0]

    return {
        "granularity": granularity,
        "comparison": comparison,
        "period": {**focus.as_dict(), "complete": focus.end == period_end(focus.start, granularity)},
        "comparison_periods": [span.as_dict() for span in spans],
        "totals": {"current": _totals(daily, [focus]), "comparison": _totals(daily, spans)},
        "spending": result["expense"],
        "income": result["income"],
        "featured": featured[:FEATURED_GROUPS],
    }
