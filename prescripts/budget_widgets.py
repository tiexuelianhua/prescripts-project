# The Budget page's per-category bars, used by both the Budget page and its
# Overview tile (same idea as spotify_widgets.py): one coloured line per
# budget filling toward it, like a fitness tracker's goals, and the totals
# under them.
import html

import streamlit as st

# Colours for categories besides the food one (which takes the accent
# colour): soft enough to sit beside it in both light and dark mode. Shared
# with the This month chart, so a category is the same colour everywhere.
CATEGORY_COLORS = ["#e0a37a", "#7fbf9b", "#c99ad1", "#c4b86a", "#7fb3c9"]

_PERIOD_WORDS = {
    True: {"daily": "today", "weekly": "this week", "monthly": "this month"},
    False: {"daily": "that day", "weekly": "that week", "monthly": "that month"},
}


def category_colors(names: list[str], food: str, accent: str) -> dict[str, str]:
    # Food the accent; the rest in turn, by their place in the list, so a
    # category keeps its colour from day to day.
    others = [name for name in names if name != food]
    colors = {name: CATEGORY_COLORS[index % len(CATEGORY_COLORS)] for index, name in enumerate(others)}
    colors[food] = accent
    return colors


def render_budget_bars(
    status: list[dict], colors: dict[str, str], is_today: bool = True, compact: bool = False,
) -> None:
    # One line per budget: name and period, spent of budget, a bar, and
    # what's left (or how far over -- the budgets are soft, so that's said
    # plainly rather than in alarm red). Compact (the Overview tile, half as
    # wide) moves the amounts under the bar, so nothing wraps.
    lines = []
    for budget in status:
        spent, allowed = budget["spent"], budget["budget"]
        share = min(spent / allowed, 1.0) if allowed > 0 else 1.0
        left = allowed - spent
        note = f"¥{left:,} left" if left >= 0 else f"¥{-left:,} over"
        if compact:
            note = f"¥{spent:,} of ¥{allowed:,} · {note}"
        if budget["carried"]:
            note += f" · {'+' if budget['carried'] > 0 else '-'}¥{abs(budget['carried']):,} carried over"
        color = colors.get(budget["category"], CATEGORY_COLORS[0])
        amounts = "" if compact else f"<span>¥{spent:,} / ¥{allowed:,}</span>"
        lines.append(
            "<div class='budget-line'>"
            f"<div class='budget-line-head'><span>{html.escape(budget['category'])} · "
            f"{_PERIOD_WORDS[is_today][budget['period']]}</span>{amounts}</div>"
            f"<div class='budget-line-track'><div style='width: {share * 100:.1f}%; background: {color}'></div></div>"
            f"<div class='budget-line-note'>{note}</div></div>"
        )
    st.markdown(
        "<style>"
        ".budget-line { margin-bottom: 0.7rem; }"
        ".budget-line-head { display: flex; justify-content: space-between; gap: 1rem; white-space: nowrap; }"
        ".budget-line-track { height: 0.5rem; border-radius: 0.25rem; margin: 0.3rem 0 0.2rem;"
        " background: rgba(128, 128, 128, 0.25); overflow: hidden; }"
        ".budget-line-track > div { height: 100%; border-radius: 0.25rem; }"
        ".budget-line-note { font-size: 0.85rem; opacity: 0.7; }"
        "</style>" + "".join(lines),
        unsafe_allow_html=True,
    )
