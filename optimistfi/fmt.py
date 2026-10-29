"""Number, date and table formatting for the markdown summaries.

OptimistFi sends money in US dollars.
Every formatter returns an em dash for a missing value, so a gap in the data
reads as a gap and never as a zero.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

DASH = "—"


def is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def usd(value: Any) -> str:
    """$35.76B, $171.8M, $12.3K, $950."""
    if not is_num(value):
        return DASH
    sign = "−" if value < 0 else ""
    v = abs(value)
    for size, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if v >= size:
            if v % size == 0:
                return f"{sign}${v / size:.0f}{suffix}"
            return f"{sign}${v / size:.2f}{suffix}" if size >= 1e9 else f"{sign}${v / size:.1f}{suffix}"
    return f"{sign}${v:,.0f}"


def usd_exact(value: Any) -> str:
    """$1,234.50 for prices people pay, such as a challenge fee."""
    if not is_num(value):
        return DASH
    return f"${value:,.2f}".replace(".00", "")


def price(value: Any) -> str:
    """A market price: more decimals the smaller it is."""
    if not is_num(value):
        return DASH
    v = abs(value)
    if v >= 1000:
        text = f"{value:,.0f}" if float(value).is_integer() else f"{value:,.1f}"
    elif v >= 1:
        text = f"{value:,.2f}"
    elif v == 0:
        text = "0"
    else:
        # Four significant digits in plain decimals: 5.042e-06 -> 0.000005042.
        decimals = 3 - math.floor(math.log10(v))
        text = f"{value:.{decimals}f}"
    return f"${text}"


def number(value: Any, digits: int = 0) -> str:
    if not is_num(value):
        return DASH
    if float(value).is_integer():
        digits = 0
    return f"{value:,.{digits}f}".replace("-", "−")


def parse_time(value: Any) -> datetime | None:
    if is_num(value):
        seconds = value / 1000 if value > 1e11 else value
        return datetime.fromtimestamp(seconds, UTC)
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def when(value: Any) -> str:
    """2026-10-28 23:00 UTC, or the date alone when no time was given."""
    if isinstance(value, str) and len(value) == 10:
        return value
    parsed = parse_time(value)
    if parsed is None:
        return DASH
    return parsed.strftime("%Y-%m-%d %H:%M UTC")


def clip(text: Any, limit: int = 60) -> str:
    """A long prose field cut at a word boundary, with an ellipsis showing there is more.

    Never cut at the first clause: "9% (Turbo) / 10% (Classic)" cut to "9%" reads as a rule for every account.
    """
    if text is None or text == "":
        return DASH
    value = " ".join(str(text).split())
    if len(value) <= limit:
        return value
    cut = value[: limit - 1].rsplit(" ", 1)[0]
    return f"{cut}…"


def cell(value: Any) -> str:
    text = DASH if value is None or value == "" else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def table(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    count = 0
    for row in rows:
        lines.append("| " + " | ".join(cell(v) for v in row) + " |")
        count += 1
    return "\n".join(lines) if count else ""


def link(label: str, url: Any) -> str:
    if not isinstance(url, str) or not url.startswith(("https://", "http://")):
        return label
    return f"[{label}]({url})"
