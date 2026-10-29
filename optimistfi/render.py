"""Turn OptimistFi records into what a Dify tool returns.

Each renderer returns a Summary: markdown a person can read in a chat or an
Answer node, and typed variables for workflow nodes. A renderer that meets a
shape it does not know falls back to a generic summary instead of failing the
tool call.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from optimistfi import fmt
from optimistfi.fmt import DASH

SITE = "https://optimistfi.com"
MAX_ROWS = 10


@dataclass
class Summary:
    text: str
    variables: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------- shared


def first(records: Sequence[Any]) -> dict[str, Any]:
    for record in records:
        if isinstance(record, dict):
            return record
    return {}


def data_of(record: dict[str, Any]) -> dict[str, Any]:
    data = record.get("data")
    return data if isinstance(data, dict) else {}


def source_url(record: dict[str, Any]) -> str | None:
    source = record.get("source")
    url = source.get("url") if isinstance(source, dict) else None
    return url if isinstance(url, str) and url.startswith("https://") else None


def footer(record: dict[str, Any], as_of: Any = None) -> str:
    stamp = as_of or record.get("as_of") or data_of(record).get("asOf")
    parts = []
    if stamp:
        parts.append(f"As of {fmt.when(stamp)}")
    url = source_url(record)
    parts.append(
        f"Source: {fmt.link('OptimistFi', url) if url and 'optimistfi.com' in url else fmt.link('OptimistFi', SITE)}"
    )
    return "_" + " · ".join(parts) + "_"


def notice(records: Sequence[Any]) -> str | None:
    """A record that carries an error or a note in place of data."""
    record = first(records)
    if not record:
        return "OptimistFi returned no records for this request."
    if record.get("error"):
        return str(record["error"])
    if record.get("status") == "building":
        return str(record.get("note") or "OptimistFi is still building this answer.")
    return None


def generic(records: Sequence[Any], title: str) -> Summary:
    """A plain summary for any shape: a title, the note, and the first list as a table."""
    record = first(records)
    data = data_of(record) or record
    lines = [f"### {title}"]
    if record.get("note"):
        lines.append(str(record["note"]))
    rows = next((v for v in data.values() if isinstance(v, list) and v and isinstance(v[0], dict)), None)
    if rows:
        keys = [k for k, v in rows[0].items() if not isinstance(v, (dict, list))][:6]
        lines.append(fmt.table(keys, ([row.get(k) for k in keys] for row in rows[:MAX_ROWS])))
    elif len(records) > 1:
        lines.append(f"{len(records)} records.")
    lines.append(footer(record))
    return Summary(text="\n\n".join(line for line in lines if line), variables=base_variables(record))


def base_variables(record: dict[str, Any]) -> dict[str, Any]:
    data = data_of(record)
    return {
        "as_of": record.get("as_of") or data.get("asOf"),
        "source_url": source_url(record),
    }


def safely(render: Callable[..., Summary], records: Sequence[Any], title: str, **kwargs: Any) -> Summary:
    message = notice(records)
    if message:
        return Summary(text=message, variables={"as_of": None, "source_url": None})
    try:
        return render(records, **kwargs)
    except (KeyError, IndexError, TypeError, ValueError, AttributeError, ZeroDivisionError):
        return generic(records, title)


# -------------------------------------------------------------- SEC: insiders


def _company(records: Sequence[Any]) -> str:
    entity = first(records).get("entity") or {}
    name, ticker = entity.get("name"), entity.get("ticker")
    return f"{name} ({ticker})" if name and ticker else str(name or ticker or "")


# The SEC's Form 4 codes as verbs (Form 4, General Instructions, item 8), for a reply without the server's own.
FORM4_VERBS = {
    "P": "bought",
    "S": "sold",
    "A": "received",
    "D": "returned to the company",
    "F": "surrendered for tax",
    "M": "exercised",
    "X": "exercised",
    "O": "exercised",
    "C": "converted",
    "G": "gave away",
    "W": "inherited",
}


def _insider_act(data: dict[str, Any]) -> str:
    """What the insider did as a verb ("sold", "gave away"), then the money and the shares."""
    code = str(data.get("txn_code") or "").upper()
    verb = data.get("direction") or FORM4_VERBS.get(code) or (f"filed Form 4 code {code} for" if code else "reported")
    money = fmt.usd(data["value"]) if fmt.is_num(data.get("value")) and data["value"] else None
    shares = f"{fmt.number(data['shares'])} shares" if fmt.is_num(data.get("shares")) else None
    if shares and fmt.is_num(data.get("price")) and data["price"]:
        shares += f" at {fmt.price(data['price'])}"
    detail = ", ".join(part for part in (money, shares) if part)
    act = f"{verb} {detail}" if detail else verb
    return act + (", to cover tax on vesting stock" if data.get("sell_to_cover") else "")


def insider_trades(records: Sequence[Any]) -> Summary:
    trades = [r for r in records if isinstance(r, dict) and r.get("type") == "insider_trade"]
    if not trades:
        return generic(records, "Insider trades")
    sold = sum((r["data"].get("value") or 0) for r in trades if r["data"].get("acquired_disposed") == "D")
    bought = sum((r["data"].get("value") or 0) for r in trades if r["data"].get("acquired_disposed") == "A")
    lines = [
        f"### Insider trades: {_company(trades)}",
        f"{len(trades)} Form 4 lines, open-market buys and sells first, then other filings, newest first within each: "
        f"acquired {fmt.usd(bought)}, disposed of {fmt.usd(sold)}. "
        "Each line gives the trade date first and the date the filing made it public last.",
        "\n".join(
            f"- **{r.get('event_time')}** {fmt.clip(r['data'].get('insider_display_name') or r['data'].get('insider_name'), 60)}: "
            f"{_insider_act(r['data'])} · filed {fmt.link(str(r.get('as_of')), source_url(r))}"
            for r in trades[:25]
        ),
        "_Source: SEC EDGAR Form 4, read by OptimistFi_",
    ]
    variables = {
        "as_of": trades[0].get("as_of"),
        "source_url": source_url(trades[0]),
        "company": _company(trades),
        "count": len(trades),
        "acquired_usd": bought,
        "disposed_usd": sold,
    }
    return Summary(text="\n\n".join(lines), variables=variables)


# ------------------------------------------------------------ House disclosures


def _amount(data: dict[str, Any]) -> str:
    """The filing's range; an exact amount is both bounds, and "Over $X" has no top."""
    low, high = data.get("amount_low"), data.get("amount_high")
    if fmt.is_num(low) and high is None:
        return f"over {fmt.usd_exact(low)}"
    if fmt.is_num(low) and fmt.is_num(high):
        return fmt.usd_exact(low) if low == high else f"{fmt.usd_exact(low)} – {fmt.usd_exact(high)}"
    return DASH


def congress_trades(records: Sequence[Any]) -> Summary:
    summary = next((r for r in records if isinstance(r, dict) and r.get("type") == "gov_trade_summary"), None)
    trades = [r for r in records if isinstance(r, dict) and r.get("type") == "gov_trade"]
    if not trades:
        return generic(records, "Congressional trades")
    lines = ["### Congressional trade disclosures"]
    if summary:
        s = summary.get("data") or {}
        members = ", ".join(f"{m.get('name')} ({m.get('trades')})" for m in (s.get("members") or [])[:5])
        window = s.get("window") or {}
        span = f" from {window['from']} to {window['to']}" if window.get("from") and window.get("to") else ""
        lines.append(
            f"{_company([summary])}: {s.get('trades')} trades{span}, {s.get('buys')} buys and {s.get('sells')} sells, "
            f"leaning {s.get('lean')}. Most active: {members}."
        )
    lines.append("Each line gives the trade date the member reported first and the date the disclosure was filed last.")
    lines.append(
        "\n".join(
            f"- **{r.get('event_time')}** {r['data'].get('politician')} "
            f"({r['data'].get('state_district') or r['data'].get('chamber')}): "
            f"{r['data'].get('txn_type') or ('detail not parsed from a paper filing' if r['data'].get('index_only') else 'trade')} "
            f"{fmt.clip(r['data'].get('asset'), 70)}, {_amount(r['data'])}"
            + (f", in {r['data']['account']}" if r["data"].get("account") else "")
            + (f" ({r['data']['owner']})" if r["data"].get("owner") else "")
            + f" · filed {fmt.link(str(r.get('as_of')), source_url(r))}"
            for r in trades[:25]
        )
    )
    unread = sum(1 for r in trades[:25] if r["data"].get("account_not_read"))
    if unread:
        lines.append(f"{unread} of these trades come from filings whose account names are not read yet.")
    lines.append("_Source: US House Clerk disclosure filings (PTRs), read by OptimistFi_")
    variables = {
        "as_of": trades[0].get("as_of"),
        "source_url": source_url(trades[0]),
        "count": len(trades),
        "lean": (summary or {}).get("data", {}).get("lean"),
    }
    return Summary(text="\n\n".join(lines), variables=variables)


# ----------------------------------------------------------------- SEC filings

ITEM_RE = re.compile(r"Item\s+\d\.\d\d")


def _excerpt(text: Any, limit: int = 280) -> str:
    if not isinstance(text, str):
        return DASH
    match = ITEM_RE.search(text)
    body = html.unescape(text[match.start() :] if match else text)
    return fmt.clip(body, limit) if len(body) > limit else body


def _thesis_line(records: Sequence[Any]) -> str:
    impact = next((r for r in records if isinstance(r, dict) and r.get("type") == "thesis_impact"), None)
    context = ((impact or {}).get("data") or {}).get("analysis_context") or {}
    if not context.get("thesis"):
        return ""
    line = f"**OptimistFi thesis:** {context['thesis']}"
    if context.get("breaks_the_case"):
        line += f"\n\n**What would break it:** {fmt.clip(context['breaks_the_case'], 240)}"
    return line + f"\n\n{fmt.link('Full case', source_url(impact))}"


def _event_line(record: dict[str, Any]) -> str:
    data = record.get("data") or {}
    if data.get("headline"):
        items = ", ".join(data.get("items") or [])
        detail = " · ".join(x for x in (f"items {items}" if items else "", data.get("significance") or "") if x)
        return f"- **{record.get('event_time')}** {data['headline']}" + (f" ({detail})" if detail else "")
    what = str(data.get("subtype") or "event").replace("_", " ")
    amount = f" of {fmt.usd_exact(data['amount'])}" if fmt.is_num(data.get("amount")) else ""
    period = f" for {data['fiscal_period']}" if data.get("fiscal_period") else ""
    return f"- **{record.get('event_time')}** {what}{amount}{period}"


def company_filings(records: Sequence[Any], kind: str = "events") -> Summary:
    company = _company(records)
    lines = [
        f"### {company}: "
        + {
            "events": "filed events",
            "press_releases": "press releases",
            "event_text": "8-K text",
            "red_flags": "red-flag checks",
        }.get(kind, kind)
    ]
    by_type: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if isinstance(record, dict):
            by_type.setdefault(str(record.get("type")), []).append(record)

    for record in by_type.get("sentiment", [])[:1]:
        d = record.get("data") or {}
        lines.append(
            f"Insider and congressional open-market flow over {d.get('window')}: **{str(d.get('label')).replace('_', ' ')}** "
            f"({fmt.number(d.get('score'), 2)} on a {d.get('scale')} scale)."
        )
    events = by_type.get("news", []) + by_type.get("corporate_event", [])
    events.sort(key=lambda r: str(r.get("event_time")), reverse=True)
    if events and kind != "event_text":
        lines.append("\n".join(_event_line(r) for r in events[:MAX_ROWS]))
    if kind == "event_text":
        for record in by_type.get("news", [])[:3]:
            d = record.get("data") or {}
            lines.append(
                f"**{record.get('event_time')}, items {', '.join(d.get('items') or [])}** ({fmt.link('filing', source_url(record))})\n\n> {_excerpt(d.get('text'))}"
            )
    releases = by_type.get("press_release", [])
    if releases:
        lines.append(
            fmt.table(
                ["Date", "Release", "Exhibit"],
                (
                    [
                        r.get("event_time"),
                        (r.get("data") or {}).get("filing_summary") or DASH,
                        fmt.link((r.get("data") or {}).get("exhibit") or "EX-99", (r.get("data") or {}).get("url")),
                    ]
                    for r in releases[:MAX_ROWS]
                ),
            )
        )
    flags = by_type.get("red_flag", [])
    if flags:
        lines.append(
            "\n".join(
                f"- **{(r.get('data') or {}).get('status')}** {(r.get('data') or {}).get('question')} "
                f"{fmt.clip((r.get('data') or {}).get('evidence'), 200)}"
                for r in flags
            )
        )
    insiders = by_type.get("insider_trade", [])
    if insiders:
        lines.append(f"The window also holds {len(insiders)} insider Form 4 lines; the Insider Trades tool lists them.")
    thesis = _thesis_line(records)
    if thesis:
        lines.append(thesis)
    if len(lines) == 1:
        return generic(records, lines[0][4:])
    lines.append("_Source: SEC EDGAR, read by OptimistFi_")
    dated = next((r for r in records if isinstance(r, dict) and r.get("as_of")), {})
    variables = {
        "as_of": dated.get("as_of"),
        "source_url": source_url(dated) if dated else None,
        "company": company,
        "kind": kind,
        "count": sum(len(v) for k, v in by_type.items() if k != "thesis_impact"),
        "flags_happened": sum(1 for r in flags if (r.get("data") or {}).get("status") == "HAPPENED"),
    }
    return Summary(text="\n\n".join(lines), variables=variables)


# -------------------------------------------------------------------- calendar


PHASE_RE = re.compile(r"(EARLY_)?PHASE(\d)")


def _phase(value: Any) -> str | None:
    found = PHASE_RE.findall(str(value or ""))
    if not found:
        return None
    return ("Early " if found[0][0] else "") + "Phase " + "/".join(n for _, n in found)


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _day(record: dict[str, Any]) -> str:
    """The date as the source gave it: ClinicalTrials.gov files most completion dates as a month only."""
    d = record.get("data") or {}
    day = str(d.get("projected_date") or record.get("event_time") or "")
    if d.get("date_precision") == "month" and re.match(r"\d{4}-\d{2}", day):
        return f"{MONTHS[int(day[5:7]) - 1]} {day[:4]}"
    return day or DASH


def _calendar_line(record: dict[str, Any]) -> str:
    d = record.get("data") or {}
    when = f"- **{_day(record)}**"
    status = record.get("confidence") or d.get("status") or DASH
    if d.get("event_type") == "trial_readout":
        facts = [
            _phase(d.get("phase")),
            d.get("indication"),
            str(d.get("status") or "").replace("_", " ").lower() or None,
        ]
        about = "; ".join(fmt.clip(f, 90) for f in facts if f)
        return (
            f"{when} trial readout, {status}: {fmt.clip(d.get('drug'), 120)}"
            + (f" ({about})" if about else "")
            + f" · {fmt.link('ClinicalTrials.gov', source_url(record))}"
        )
    event = (d.get("subtype") or record.get("type") or "event").replace("_", " ")
    line = f"{when} {event}, {status}" + (f": {d['estimate_basis']}" if d.get("estimate_basis") else "")
    return line + (f". Last reported {d['last_reported']}." if d.get("last_reported") else "")


def company_calendar(records: Sequence[Any]) -> Summary:
    company = _company(records)
    events = [r for r in records if isinstance(r, dict) and r.get("type") not in ("thesis_impact",) and r.get("data")]
    if not events:
        return generic(records, f"{company}: what is ahead")
    # The earnings estimate leads: LLY's sat twelfth, behind eleven nearer trial readouts, past the row limit.
    earnings = [r for r in events if (r.get("data") or {}).get("subtype") == "earnings"]
    shown = earnings + [r for r in events if r not in earnings][: MAX_ROWS - len(earnings)]
    lines = [f"### {company}: what is ahead", "\n".join(_calendar_line(r) for r in shown)]
    if any((r.get("data") or {}).get("estimate_basis") for r in shown):
        lines.append(
            "An estimated earnings date is projected from the company's own filing cadence; it is not a date the company announced."
        )
    if any((r.get("data") or {}).get("event_type") == "trial_readout" for r in shown):
        lines.append(
            "A trial readout date is the study's primary completion date as its sponsor filed it on ClinicalTrials.gov."
        )
    thesis = _thesis_line(records)
    if thesis:
        lines.append(thesis)
    sources = ["SEC EDGAR filing cadence, computed by OptimistFi"]
    if any((r.get("data") or {}).get("event_type") == "trial_readout" for r in shown):
        sources.append("ClinicalTrials.gov")
    lines.append(f"_Source: {'; '.join(sources)}_")
    earnings = earnings[0] if earnings else {}
    variables = {
        "as_of": earnings.get("as_of") or events[0].get("as_of"),
        "source_url": source_url(earnings) if earnings else None,
        "company": company,
        "next_earnings": (earnings.get("data") or {}).get("projected_date"),
        "next_earnings_confidence": earnings.get("confidence"),
    }
    return Summary(text="\n\n".join(lines), variables=variables)
