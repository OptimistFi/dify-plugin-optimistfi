"""Turn OptimistFi records into what a Dify tool returns.

Each renderer returns a Summary: markdown a person can read in a chat or an
Answer node, typed variables for workflow nodes, and for perps a chart block
that Dify's markdown renders. A renderer that meets a shape it does not know
falls back to a generic summary instead of failing the tool call.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from statistics import median
from typing import Any

from optimistfi import fmt
from optimistfi.fmt import DASH

SITE = "https://optimistfi.com"
MAX_ROWS = 10


@dataclass
class Summary:
    text: str
    variables: dict[str, Any] = field(default_factory=dict)
    chart: str | None = None


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


def market_label(item: dict[str, Any]) -> str:
    base = item.get("base") or item.get("symbol") or DASH
    page = item.get("page")
    return fmt.link(str(base), page) if isinstance(page, str) else str(base)


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


def echarts(option: dict[str, Any]) -> str:
    return "```echarts\n" + json.dumps(option, ensure_ascii=False, separators=(",", ":")) + "\n```"


def short_time(value: Any) -> str:
    parsed = fmt.parse_time(value)
    return parsed.strftime("%m-%d %H:%M") if parsed else str(value)


# ---------------------------------------------------------------- perp market


def perp_market(records: Sequence[Any]) -> Summary:
    record = first(records)
    data = data_of(record)
    base = data.get("base") or (record.get("entity") or {}).get("symbol")
    if not data.get("markets"):
        note = record.get("note") or f"No perpetual futures market OptimistFi reads lists {base}."
        return Summary(text=str(note), variables=base_variables(record))

    totals = data.get("totals") or {}
    change = data.get("priceChange") or {}
    lines = [
        f"### {base} perpetual futures",
        f"{data.get('venues', DASH)} venues · {data.get('assetClass', '')}".rstrip(" ·"),
    ]

    facts = [
        ("Price across venues", f"{fmt.price(totals.get('priceLow'))} – {fmt.price(totals.get('priceHigh'))}"),
        (
            "Price change",
            f"24h {fmt.pct(change.get('24h'))} · 7d {fmt.pct(change.get('7d'))}"
            + (f" (on {change['venue']})" if change.get("venue") else ""),
        ),
        (
            "Open interest",
            f"{fmt.usd(totals.get('openInterestUsd'))} · 24h {fmt.pct(totals.get('openInterestChange24h'))}",
        ),
        (
            "Funding, OI-weighted",
            f"{fmt.funding_hourly(totals.get('fundingRateHourlyOiWeighted'))} · "
            f"{fmt.funding_annual(totals.get('fundingRateAnnualizedOiWeighted'))}",
        ),
    ]
    # The largest cohorts first; a cohort of one small account is not positioning.
    cohorts = sorted(
        (
            c
            for c in data.get("largeAccountPositioning") or []
            if (c.get("longUsd") or 0) + (c.get("shortUsd") or 0) >= 100_000
        ),
        key=lambda c: (c.get("longUsd") or 0) + (c.get("shortUsd") or 0),
        reverse=True,
    )
    for cohort in cohorts[:2]:
        facts.append(
            (
                f"Large accounts on {cohort.get('venue')}",
                f"{fmt.pct(cohort.get('longShare'), signed=False, digits=0)} long: "
                f"{fmt.usd(cohort.get('longUsd'))} long vs {fmt.usd(cohort.get('shortUsd'))} short "
                f"({cohort.get('cohort', '')})",
            )
        )
    liquidations = data.get("liquidations") or {}
    falls = (liquidations.get("longsLiquidatedIfPriceFalls") or {}).get("10%")
    rises = (liquidations.get("shortsLiquidatedIfPriceRises") or {}).get("10%")
    if falls is not None or rises is not None:
        facts.append(
            (
                "Liquidations within 10%",
                f"longs {fmt.usd(falls)} if price falls · shorts {fmt.usd(rises)} if it rises "
                f"(mapped on {liquidations.get('mapPriceVenue', DASH)})",
            )
        )
    for key, label in (
        ("largestLongClustersBelow", "Largest long cluster"),
        ("largestShortClustersAbove", "Largest short cluster"),
    ):
        clusters = liquidations.get(key) or []
        if clusters:
            top = max(clusters, key=lambda c: c.get("usd") or 0)
            facts.append(
                (
                    label,
                    f"{fmt.price(top.get('priceLow'))} – {fmt.price(top.get('priceHigh'))} "
                    f"({fmt.pct_points(top.get('distancePct'))}): {fmt.usd(top.get('usd'))}",
                )
            )
    trades = data.get("whaleTrades24h") or []
    if trades:
        top = max(trades, key=lambda t: t.get("usd") or 0)
        facts.append(
            (
                "Largest trade, 24h",
                f"{fmt.usd(top.get('usd'))} {top.get('side', '')} on {top.get('venue')} at {fmt.price(top.get('price'))} "
                f"({fmt.when(top.get('at'))})",
            )
        )
    lines.append(fmt.facts(facts))

    markets = sorted(data.get("markets") or [], key=lambda m: m.get("openInterestUsd") or 0, reverse=True)
    listed = [m.get("venue") for m in markets]
    rows = []
    for market in markets[:MAX_ROWS]:
        unread = market.get("fundingState") == "not_read"
        venue = market.get("venue")
        if listed.count(venue) > 1 and market.get("symbol"):
            venue = f"{venue} {market['symbol']}"
        rows.append(
            [
                venue,
                "not read" if unread else fmt.price(market.get("price")),
                fmt.usd(market.get("openInterestUsd")),
                DASH if unread else fmt.funding_annual(market.get("fundingRateAnnualized")),
                fmt.leverage(market.get("maxLeverage")),
            ]
        )
    lines.append(f"**Top venues by open interest** ({len(markets)} markets)")
    lines.append(fmt.table(["Venue", "Price", "OI", "Funding", "Max lev."], rows))
    stale = sorted(
        {(m.get("venue"), m.get("readAt")) for m in markets[:MAX_ROWS] if m.get("fundingState") == "not_read"}
    )
    if stale:
        lines.append(
            "Not read this hour: "
            + "; ".join(f"{venue}, whose open interest above is from {fmt.when(at)}" for venue, at in stale)
            + "."
        )
    lines.append(footer(record, data.get("asOf")))

    charted = [
        m for m in markets if fmt.is_num(m.get("fundingRateAnnualized")) and fmt.is_num(m.get("openInterestUsd"))
    ][:12]
    chart = None
    if charted:
        chart = echarts(
            {
                "title": {
                    "text": f"{base}: open interest and funding by venue",
                    "left": "center",
                    "textStyle": {"fontSize": 13},
                },
                "tooltip": {"trigger": "axis"},
                "legend": {"bottom": 0},
                "grid": {"left": 64, "right": 64, "top": 48, "bottom": 64},
                "xAxis": {"type": "category", "data": [f"{m['venue']}" for m in charted], "axisLabel": {"rotate": 35}},
                "yAxis": [
                    {"type": "value", "name": "Open interest ($M)"},
                    {"type": "value", "name": "Funding (%/yr)", "splitLine": {"show": False}},
                ],
                "series": [
                    {
                        "name": "Open interest ($M)",
                        "type": "bar",
                        "data": [round(m["openInterestUsd"] / 1e6, 1) for m in charted],
                        "itemStyle": {"color": "#3b1fb0"},
                    },
                    {
                        "name": "Funding (%/yr)",
                        "type": "line",
                        "yAxisIndex": 1,
                        "data": [round(m["fundingRateAnnualized"] * 100, 2) for m in charted],
                        "itemStyle": {"color": "#f0428f"},
                    },
                ],
            }
        )

    variables = base_variables(record) | {
        "market": base,
        "asset_class": data.get("assetClass"),
        "venues": data.get("venues"),
        "open_interest_usd": totals.get("openInterestUsd"),
        "open_interest_change_24h": totals.get("openInterestChange24h"),
        "funding_hourly": totals.get("fundingRateHourlyOiWeighted"),
        "funding_annualized": totals.get("fundingRateAnnualizedOiWeighted"),
        "price_low": totals.get("priceLow"),
        "price_high": totals.get("priceHigh"),
        "price_change_24h": change.get("24h"),
        "chart": chart,
    }
    return Summary(text="\n\n".join(lines), variables=variables, chart=chart)


# --------------------------------------------------------------- perp history


def _series(points: Any) -> list[tuple[str, float]]:
    out = []
    for point in points or []:
        if isinstance(point, (list, tuple)) and len(point) == 2 and fmt.is_num(point[1]):
            out.append((point[0], point[1]))
    return out


def perp_history(records: Sequence[Any]) -> Summary:
    record = first(records)
    data = data_of(record)
    base = data.get("base")
    if not data.get("found", True):
        return Summary(
            text=str(record.get("note") or f"OptimistFi has no history for {base}."), variables=base_variables(record)
        )

    price_block = data.get("price") or {}
    prices = _series(price_block.get("points"))
    funding = _series(data.get("fundingAnnualizedOiWeighted"))
    whales = _series(((data.get("largeAccounts") or {}).get("net") or {}).get("whales"))
    flow = [p for p in data.get("takerFlowUsd") or [] if isinstance(p, dict)]
    if prices:
        # A step after the last price is still filling (one venue in, read mid-hour): its funding is no reading of now.
        closed = prices[-1][0]
        funding = [(t, v) for t, v in funding if str(t) <= str(closed)]
        whales = [(t, v) for t, v in whales if str(t) <= str(closed)]
        flow = [p for p in flow if str(p.get("at")) <= str(closed)]
    oi = data.get("openInterestChange") or {}

    lines = [
        f"### {base} perpetual futures, last {data.get('window')}",
        f"{data.get('stepHours', DASH)}-hour steps",
    ]
    facts = []
    if prices:
        values = [v for _, v in prices]
        move = values[-1] / values[0] - 1 if values[0] else None
        facts.append(
            (
                f"Price ({price_block.get('venue', 'reference venue')})",
                f"{fmt.price(values[0])} → {fmt.price(values[-1])} ({fmt.pct(move)}); "
                f"range {fmt.price(min(values))} – {fmt.price(max(values))}",
            )
        )
    if oi:
        facts.append(
            (
                "Open interest",
                f"{fmt.usd(oi.get('usdFrom'))} → {fmt.usd(oi.get('usdTo'))} ({fmt.pct(oi.get('usdChange'))}); "
                f"{fmt.pct(oi.get('quantityChange'))} once the price effect is taken out",
            )
        )
    if funding:
        values = [v for _, v in funding]
        facts.append(
            (
                "Funding, OI-weighted",
                f"now {fmt.funding_annual(values[-1])}; range {fmt.funding_annual(min(values))} – {fmt.funding_annual(max(values))}",
            )
        )
    paid = data.get("fundingPaid") or {}
    window = data.get("window")
    paid_values = [v.get(window) for v in paid.values() if isinstance(v, dict) and fmt.is_num(v.get(window))]
    if paid_values:
        facts.append(
            (
                f"Funding a long paid over {window}",
                f"median {fmt.pct(median(paid_values), signed=False, digits=3)} across {len(paid_values)} venues "
                f"({fmt.pct(min(paid_values), signed=False, digits=3)} – {fmt.pct(max(paid_values), signed=False, digits=3)})",
            )
        )
    if flow:
        buy = sum(p.get("buy") or 0 for p in flow)
        sell = sum(p.get("sell") or 0 for p in flow)
        facts.append(("Taker flow", f"bought {fmt.usd(buy)} · sold {fmt.usd(sell)} · net {fmt.usd(buy - sell)}"))
    if whales:
        facts.append(
            (
                "Net position, Hyperliquid accounts worth $10M+",
                f"{fmt.usd(whales[0][1])} → {fmt.usd(whales[-1][1])}",
            )
        )
    books = data.get("orderBook") or {}
    bid = sum(((b.get("within1pct") or {}).get("bidUsd") or 0) for b in books.values() if isinstance(b, dict))
    ask = sum(((b.get("within1pct") or {}).get("askUsd") or 0) for b in books.values() if isinstance(b, dict))
    if bid or ask:
        facts.append((f"Order book within 1% ({len(books)} venues)", f"bids {fmt.usd(bid)} · asks {fmt.usd(ask)}"))
    lines.append(fmt.facts(facts))

    if prices:
        funding_at = dict(funding)
        whales_at = dict(whales)
        flow_at = {p.get("at"): p.get("net") for p in flow}
        step = max(1, len(prices) // 8)
        picks = prices[::step][-8:]
        if picks[-1] != prices[-1]:
            picks = picks[1:] + [prices[-1]]
        lines.append("**Through the window**")
        lines.append(
            fmt.table(
                ["UTC", "Price", "Funding", "Taker net", "$10M+ net"],
                (
                    [
                        fmt.short_when(t),
                        fmt.price(v),
                        fmt.funding_annual(funding_at.get(t)),
                        fmt.usd(flow_at.get(t)),
                        fmt.usd(whales_at.get(t)),
                    ]
                    for t, v in picks
                ),
            )
        )
    lines.append(footer(record, data.get("asOf")))

    chart = None
    if prices:
        funding_at = dict(funding)
        chart = echarts(
            {
                "title": {
                    "text": f"{base}: price and funding, last {window}",
                    "left": "center",
                    "textStyle": {"fontSize": 13},
                },
                "tooltip": {"trigger": "axis"},
                "legend": {"bottom": 0},
                "grid": {"left": 72, "right": 64, "top": 48, "bottom": 56},
                "xAxis": {"type": "category", "data": [short_time(t) for t, _ in prices]},
                "yAxis": [
                    {"type": "value", "name": "Price ($)", "scale": True},
                    {"type": "value", "name": "Funding (%/yr)", "splitLine": {"show": False}},
                ],
                "series": [
                    {
                        "name": "Price ($)",
                        "type": "line",
                        "showSymbol": False,
                        "data": [v for _, v in prices],
                        "itemStyle": {"color": "#3b1fb0"},
                    },
                    {
                        "name": "Funding (%/yr)",
                        "type": "line",
                        "yAxisIndex": 1,
                        "showSymbol": False,
                        "data": [round(funding_at[t] * 100, 3) if t in funding_at else None for t, _ in prices],
                        "itemStyle": {"color": "#f0428f"},
                    },
                ],
            }
        )

    variables = base_variables(record) | {
        "market": base,
        "window": window,
        "price_start": prices[0][1] if prices else None,
        "price_end": prices[-1][1] if prices else None,
        "open_interest_change": oi.get("usdChange"),
        "funding_annualized_now": funding[-1][1] if funding else None,
        "chart": chart,
    }
    return Summary(text="\n\n".join(lines), variables=variables, chart=chart)


# -------------------------------------------------------------- perps screener

Col = tuple[str, Callable[[dict[str, Any]], Any]]


def _first_num(item: dict[str, Any], *keys: str) -> Any:
    """The first of several fields that holds a number: a market missing one change reads its same-markets twin."""
    return next((item[k] for k in keys if fmt.is_num(item.get(k))), None)


def _records(item: dict[str, Any]) -> str:
    counts = [item.get("longCount"), item.get("shortCount")]
    if not any(fmt.is_num(c) for c in counts):
        return DASH
    return fmt.number(sum(c for c in counts if fmt.is_num(c)))


COMMON: dict[str, Col] = {
    "market": ("Market", market_label),
    "class": ("Class", lambda i: i.get("assetClass") or DASH),
    "price": ("Price", lambda i: fmt.price(i.get("price"))),
    "chg24": ("24h", lambda i: fmt.pct(i.get("priceChange24h"))),
    "oi": ("OI", lambda i: fmt.usd(i.get("openInterestUsd"))),
    "oi4": ("OI 4h", lambda i: fmt.pct(_first_num(i, "openInterestChange4h", "openInterestChangeSameMarkets4h"))),
    "oi24": ("OI 24h", lambda i: fmt.pct(_first_num(i, "openInterestChange24h", "openInterestChangeSameMarkets24h"))),
    "vol": ("Volume 24h", lambda i: fmt.usd(i.get("volume24hUsd"))),
    "venues": ("Venues", lambda i: i.get("venues") if not isinstance(i.get("venues"), list) else len(i["venues"])),
    "funding": ("Funding", lambda i: fmt.funding_annual(i.get("fundingRateAnnualized"))),
}


def cols(*names: str) -> list[Col]:
    return [COMMON[n] for n in names]


def section(title: str, items: Any, columns: Sequence[Col]) -> str:
    if not isinstance(items, list) or not items:
        return ""
    body = fmt.table(
        [c[0] for c in columns], ([c[1](i) for c in columns] for i in items[:MAX_ROWS] if isinstance(i, dict))
    )
    return f"**{title}**\n\n{body}" if body else ""


def _gap_leg(leg: Any) -> str:
    if not isinstance(leg, dict):
        return DASH
    return f"{leg.get('venue')} {fmt.funding_annual(leg.get('fundingAnnualized'))}"


def _band(b: Any) -> str:
    if not isinstance(b, dict) or not b.get("usd"):
        return DASH
    return f"{fmt.price(b.get('priceLow'))} – {fmt.price(b.get('priceHigh'))} ({fmt.pct_points(b.get('distancePct'))}): {fmt.usd(b.get('usd'))}"


VIEW_TITLES = {
    "trending": "Where open interest is building",
    "movers": "Biggest price moves",
    "funding": "Highest and lowest funding",
    "funding_gaps": "Funding gaps between venues",
    "open_interest": "Largest open interest",
    "liquidations": "Liquidations",
    "liquidation_max_pain": "Liquidation max pain",
    "whales": "Large trades",
    "lean": "How Hyperliquid's $1M+ accounts lean",
    "weekend": "Stock perps over the weekend",
    "new_listings": "New listings",
    "market_overview": "Market overview",
    "fear_greed": "Crypto fear and greed",
    "etf": "Spot ETF flows",
    "sectors": "Sectors",
    "exchanges": "Venues ranked",
    "options": "Options",
    "basis": "Futures basis",
    "premium": "Premium to the index",
    "btc_cycle": "Bitcoin cycle indicators",
}


def _view_sections(view: str, data: dict[str, Any]) -> list[str]:
    if view == "trending":
        return [
            section(
                "Open interest building",
                data.get("positionsBuilding"),
                cols("market", "price", "chg24", "oi", "oi24", "venues"),
            ),
            section("Most active", data.get("mostActive"), cols("market", "price", "chg24", "oi", "vol", "venues")),
        ]
    if view == "movers":
        measured: Col = ("Venue", lambda i: i.get("measuredOn") or DASH)
        return [
            section("Up", data.get("up"), cols("market", "class", "price", "chg24", "oi") + [measured]),
            section("Down", data.get("down"), cols("market", "class", "price", "chg24", "oi") + [measured]),
        ]
    if view == "funding":
        return [
            section(
                "Highest funding (longs pay)", data.get("highest"), cols("market", "class", "funding", "oi", "venues")
            ),
            section(
                "Lowest funding (shorts pay)", data.get("lowest"), cols("market", "class", "funding", "oi", "venues")
            ),
        ]
    if view == "funding_gaps":
        return [
            section(
                "Same market, different funding",
                data.get("gaps"),
                [
                    COMMON["market"],
                    ("Lower funding", lambda i: _gap_leg(i.get("long"))),
                    ("Higher funding", lambda i: _gap_leg(i.get("short"))),
                    ("Gap", lambda i: fmt.funding_annual(i.get("gapAnnualized"))),
                    ("Thinner OI", lambda i: fmt.usd(i.get("thinnerLegOpenInterestUsd"))),
                ],
            )
        ]
    if view == "open_interest":
        return [
            section(
                "Largest open interest",
                data.get("largest"),
                cols("market", "oi", "oi4", "oi24", "price", "venues"),
            )
        ]
    if view == "liquidations":
        liq = [
            COMMON["market"],
            ("Longs", lambda i: fmt.usd(i.get("longsLiquidatedUsd"))),
            ("Shorts", lambda i: fmt.usd(i.get("shortsLiquidatedUsd"))),
            ("Records", _records),
            ("Venues", lambda i: len(i.get("liquidationVenues") or [])),
        ]
        return [
            section(f"Largest liquidations, {data.get('window', '24h')}", data.get("largestLiquidations"), liq),
            section(
                "Largest taker volume",
                data.get("largestTakerVolume"),
                [
                    COMMON["market"],
                    ("Taker buys", lambda i: fmt.usd(i.get("takerBuyUsd"))),
                    ("Taker sells", lambda i: fmt.usd(i.get("takerSellUsd"))),
                ],
            ),
        ]
    if view == "liquidation_max_pain":
        if isinstance(data.get("withinPct"), dict):
            rows = []
            for band, block in data["withinPct"].items():
                if isinstance(block, dict):
                    rows.append(
                        [
                            f"within {band}",
                            fmt.usd(block.get("longsWithinUsd")),
                            fmt.usd(block.get("shortsWithinUsd")),
                            _band(block.get("liquidationMaxPain")),
                        ]
                    )
            return [
                f"{data.get('base')} at {fmt.price(data.get('price'))} on {data.get('priceVenue')}",
                fmt.table(["Move", "Longs", "Shorts", "Max pain band"], rows),
            ]
        return [
            section(
                f"Max pain within {data.get('withinPct', 10)}% of the price",
                data.get("markets"),
                [
                    COMMON["market"],
                    COMMON["price"],
                    ("Side", lambda i: (i.get("liquidationMaxPain") or {}).get("side") or DASH),
                    ("Band", lambda i: _band(i.get("liquidationMaxPain"))),
                ],
            )
        ]
    if view == "whales":
        trade_cols = [
            COMMON["market"],
            ("Venue", lambda i: i.get("venue") or DASH),
            ("Side", lambda i: i.get("side") or DASH),
            ("Size", lambda i: fmt.usd(i.get("usd"))),
            ("Price", lambda i: fmt.price(i.get("price"))),
            ("UTC", lambda i: fmt.short_when(i.get("at") or i.get("atMs"))),
        ]
        totals = data.get("totals") or {}
        head = (
            f"{fmt.number(totals.get('trades'))} trades of $100K or more: bought {fmt.usd(totals.get('buyUsd'))}, "
            f"sold {fmt.usd(totals.get('sellUsd'))}; liquidated longs {fmt.usd(totals.get('longsLiquidatedUsd'))}, "
            f"shorts {fmt.usd(totals.get('shortsLiquidatedUsd'))}"
            if totals
            else ""
        )
        positioning = (data.get("positioning") or {}).get("markets")
        return [
            head,
            section(f"Largest trades, {data.get('window', '24h')}", data.get("largestTrades"), trade_cols),
            section(
                "Hyperliquid positioning",
                positioning,
                [
                    COMMON["market"],
                    (
                        "$10M+ L / S",
                        lambda i: (
                            f"{fmt.usd((i.get('whales') or {}).get('longUsd'))} / {fmt.usd((i.get('whales') or {}).get('shortUsd'))}"
                        ),
                    ),
                    (
                        "$1M–10M L / S",
                        lambda i: (
                            f"{fmt.usd((i.get('midsize') or {}).get('longUsd'))} / {fmt.usd((i.get('midsize') or {}).get('shortUsd'))}"
                        ),
                    ),
                ],
            ),
            section(
                "Net buying",
                data.get("netBuying"),
                [
                    COMMON["market"],
                    ("Net", lambda i: fmt.usd(i.get("netUsd"))),
                    ("Trades", lambda i: fmt.number(i.get("trades"))),
                ],
            ),
            section(
                "Net selling",
                data.get("netSelling"),
                [
                    COMMON["market"],
                    ("Net", lambda i: fmt.usd(i.get("netUsd"))),
                    ("Trades", lambda i: fmt.number(i.get("trades"))),
                ],
            ),
        ]
    if view == "lean":
        return [
            f"Cohort: {data.get('cohort', DASH)}; compared with {fmt.when(data.get('dayBefore'))}",
            section(
                "Long share",
                data.get("markets"),
                [
                    COMMON["market"],
                    (
                        "Long share",
                        lambda i: (
                            f"{fmt.pct(i.get('longShare'), signed=False, digits=1)} (was {fmt.pct(i.get('longShareThen'), signed=False, digits=1)})"
                        ),
                    ),
                    ("Long / short", lambda i: f"{fmt.usd(i.get('longUsd'))} / {fmt.usd(i.get('shortUsd'))}"),
                    (
                        "Lev. L / S",
                        lambda i: f"{fmt.leverage(i.get('longLeverage'))} / {fmt.leverage(i.get('shortLeverage'))}",
                    ),
                ],
            ),
        ]
    if view == "weekend":
        record = data.get("record") or {}
        real = record.get("likely real") or {}
        noise = record.get("noise") or {}
        state = (
            "live now"
            if data.get("active")
            else "not live now: it runs while US stock markets are closed for the weekend"
        )
        lines = [f"The weekend view is {state}."]
        if real:
            lines.append(
                f"Record so far: moves read as likely real were right {real.get('right')} times and wrong {real.get('wrong')} "
                f"of {real.get('calls')}; moves read as noise were right {noise.get('right')} and wrong {noise.get('wrong')} of {noise.get('calls')}."
            )
        if data.get("page"):
            lines.append(fmt.link("Weekend page", data["page"]))
        lines.append(section("Moves", data.get("markets") or data.get("moves"), cols("market", "price", "chg24", "oi")))
        return lines
    if view == "new_listings":
        return [
            section(
                f"Listed in the last {data.get('window', '24h')}",
                data.get("listings"),
                [
                    COMMON["market"],
                    ("Venue", lambda i: i.get("venue") or DASH),
                    ("Listed (UTC)", lambda i: fmt.short_when(i.get("listedAt"))),
                    ("Max lev.", lambda i: fmt.leverage(i.get("maxLeverage"))),
                ],
            )
        ]
    if view == "market_overview":
        overview = [
            COMMON["market"],
            COMMON["oi"],
            COMMON["vol"],
            ("OI / vol.", lambda i: fmt.number(i.get("openInterestToVolume"), 2)),
            ("Top venue", lambda i: _top_venue(i)),
        ]
        count = data.get("count")
        return [
            f"{fmt.number(count)} market{'' if count == 1 else 's'}",
            section("By open interest", data.get("byOpenInterest"), overview),
            section("By 30-day volume", data.get("byVolume30d"), overview),
        ]
    extra = _more_view_sections(view, data)
    if extra is not None:
        return extra
    raise KeyError(view)


def _more_view_sections(view: str, data: dict[str, Any]) -> list[str] | None:
    if view == "fear_greed":
        latest = data.get("latest") or {}
        return [
            f"**{fmt.number(latest.get('index'), 1)} of 100: {latest.get('label', DASH)}** "
            f"(0 is extreme fear, 100 extreme greed; each input ranked against its own past year)",
            section(
                "Inputs",
                data.get("inputs"),
                [
                    ("Input", lambda i: i.get("input")),
                    ("Score", lambda i: fmt.number(i.get("score"), 1)),
                    ("What it reads", lambda i: fmt.clip(i.get("definition"), 48)),
                ],
            ),
            section(
                "Recent days",
                list(reversed(data.get("points") or [])),
                [
                    ("Date", lambda i: fmt.when(i.get("at"))[:10]),
                    ("Index", lambda i: fmt.number(i.get("index"), 1)),
                    ("Reading", lambda i: i.get("label")),
                ],
            ),
        ]
    if view == "etf":
        totals = data.get("totals") or {}
        flows = data.get("dailyFlows") or []
        not_read = [f.get("ticker") for f in data.get("notRead") or [] if isinstance(f, dict)]
        return [
            f"{data.get('asset', '')} funds in the {data.get('flowsRegion', 'US')}: {fmt.usd(totals.get('netAssetsUsd'))} in net assets, "
            f"{fmt.number(totals.get('holdings'))} {data.get('asset', 'coins')} held, {totals.get('fundsRead', DASH)} of {totals.get('funds', DASH)} funds read",
            section(
                "Daily net flows",
                flows,
                [
                    ("Date", lambda i: i.get("date")),
                    ("Net flow", lambda i: fmt.usd(i.get("netFlowUsd"))),
                    ("Funds in", lambda i: i.get("funds")),
                    ("Not yet out", lambda i: ", ".join(i.get("missing") or []) or DASH),
                ],
            ),
            section(
                "Funds",
                sorted(
                    (f for f in data.get("funds") or [] if isinstance(f, dict)),
                    key=lambda f: (f.get("netAssetsUsd") or {}).get("value") or 0,
                    reverse=True,
                ),
                [
                    ("Fund", lambda i: fmt.link(i.get("ticker") or DASH, i.get("page"))),
                    ("Issuer", lambda i: i.get("issuer")),
                    ("Net assets", lambda i: fmt.usd((i.get("netAssetsUsd") or {}).get("value"))),
                    ("Holdings", lambda i: fmt.number((i.get("holdings") or {}).get("value"))),
                    ("Premium", lambda i: fmt.pct((i.get("premium") or {}).get("value"))),
                ],
            ),
            f"Funds whose daily figures are not read here: {', '.join(t for t in not_read if t)}." if not_read else "",
        ]
    if view == "sectors":
        returns = lambda key: lambda i: fmt.pct((i.get("returnOiWeighted") or {}).get(key))  # noqa: E731
        return [
            section(
                "Sectors by open interest",
                data.get("sectors"),
                [
                    ("Sector", lambda i: f"{i.get('sector')} ({i.get('markets')})"),
                    COMMON["oi"],
                    ("7d", returns("7d")),
                    ("30d", returns("30d")),
                    ("Largest", lambda i: ", ".join(m.get("base", "") for m in (i.get("largest") or [])[:3]) or DASH),
                ],
            )
        ]
    if view == "exchanges":
        totals = data.get("totals") or {}
        return [
            f"{totals.get('venues', DASH)} venues: {fmt.usd(totals.get('openInterestUsd'))} open interest, {fmt.usd(totals.get('volume24hUsd'))} traded in 24 hours",
            section(
                "Venues by open interest",
                data.get("exchanges"),
                [
                    ("Venue", lambda i: i.get("venue")),
                    COMMON["oi"],
                    ("Share", lambda i: fmt.pct(i.get("openInterestShare"), signed=False, digits=1)),
                    COMMON["vol"],
                    ("Liquidated", lambda i: fmt.usd((i.get("liquidations24h") or {}).get("totalUsd"))),
                    ("Taker fee", lambda i: fmt.pct(i.get("takerFee"), signed=False, digits=3)),
                ],
            ),
        ]
    if view == "options":
        out = []
        for venue in data.get("venues") or []:
            out.append(
                f"**{data.get('base')} options on {venue.get('venue')}**: index {fmt.price(venue.get('index'))}, "
                f"30-day at-the-money implied volatility {fmt.pct(venue.get('atmIv30d'), signed=False, digits=1)}, "
                f"25-delta skew {fmt.pct(venue.get('skew25d30d'))}"
            )
            out.append(
                fmt.table(
                    ["Expiry", "ATM IV", "Call / put 25d", "Put/call OI", "OI", "Max pain"],
                    (
                        [
                            fmt.when(e.get("expiry"))[:10],
                            fmt.pct(e.get("atmIv"), signed=False, digits=1),
                            f"{fmt.pct(e.get('call25dIv'), signed=False, digits=1)} / {fmt.pct(e.get('put25dIv'), signed=False, digits=1)}",
                            fmt.number(e.get("putCallOiRatio"), 2),
                            fmt.usd(e.get("openInterestUsd")),
                            fmt.price(e.get("maxPain")),
                        ]
                        for e in (venue.get("expiries") or [])[:MAX_ROWS]
                    ),
                )
            )
        return out
    if view == "basis":
        rows = []
        for venue in data.get("venues") or []:
            for e in venue.get("expiries") or []:
                if fmt.is_num(e.get("daysToExpiry")) and e["daysToExpiry"] >= 7:
                    rows.append((venue.get("venue"), e))
        rows.sort(key=lambda r: r[1].get("daysToExpiry") or 0)
        return [
            f"Dated futures on {data.get('base')}: the premium of each contract to its index, annualized to its expiry (contracts a week or more out)",
            fmt.table(
                ["Venue", "Contract", "Expiry", "Annualized", "OI"],
                (
                    [
                        v,
                        e.get("symbol"),
                        fmt.when(e.get("expiry"))[:10],
                        fmt.pct(e.get("basisAnnualized")),
                        fmt.usd(e.get("openInterestUsd")),
                    ]
                    for v, e in rows[:12]
                ),
            ),
        ]
    if view == "premium":
        cols_premium = [
            COMMON["market"],
            ("Venue", lambda i: i.get("venue")),
            ("Premium", lambda i: f"{fmt.number(i.get('premiumBps'), 1)} bp"),
            ("Perp", lambda i: fmt.price(i.get("price"))),
            ("Index", lambda i: fmt.price(i.get("indexPrice"))),
            COMMON["oi"],
        ]
        return [
            section("Furthest above the index", data.get("above"), cols_premium),
            section("Furthest below the index", data.get("below"), cols_premium),
        ]
    if view == "btc_cycle":
        latest = data.get("latest") or {}
        facts = [
            ("Price", fmt.price(latest.get("price"))),
            ("200-day average", fmt.price(latest.get("ma200"))),
            ("Mayer Multiple", fmt.number(latest.get("mayerMultiple"), 2)),
            ("AHR999", fmt.number(latest.get("ahr999"), 3)),
            ("Pi Cycle Top target", fmt.price(latest.get("piCycleTarget"))),
            ("Rainbow band", f"{latest.get('rainbowBand', DASH)} of 9"),
        ]
        return [
            fmt.facts(facts),
            section(
                f"Peak signals ({data.get('hit', DASH)} hit)",
                data.get("peakSignals"),
                [
                    ("Signal", lambda i: i.get("indicator")),
                    ("Now", lambda i: fmt.number(i.get("current"), 2)),
                    ("Top level", lambda i: fmt.number(i.get("target"), 2)),
                    ("Hit", lambda i: "yes" if i.get("hit") else "no"),
                ],
            ),
        ]
    return None


def _top_venue(item: dict[str, Any]) -> str:
    split = item.get("openInterestByVenue") or []
    if not split:
        return DASH
    top = split[0]
    return f"{top.get('venue')} {fmt.pct(top.get('share'), signed=False, digits=0)}"


def perps_screener(records: Sequence[Any], view: str = "trending", left_out: Sequence[str] = ()) -> Summary:
    record = first(records)
    data = data_of(record)
    view = data.get("view") or view
    title = VIEW_TITLES.get(view, view.replace("_", " ").capitalize())
    window = data.get("window")
    lines = [f"### Perps: {title}" + (f", {window}" if window else "")]
    if left_out:
        named = " and ".join(f"{name} filter" for name in left_out)
        lines.append(f"This view does not take a {named}, so the ranking covers every market and venue it reads.")
    body = [s for s in _view_sections(view, data) if s]
    lines.extend(body or ["No markets matched this view right now."])
    lines.append(footer(record, data.get("asOf")))
    first_list = next((v for v in data.values() if isinstance(v, list) and v and isinstance(v[0], dict)), [])
    chart = _screener_chart(view, data)
    variables = base_variables(record) | {
        "view": view,
        "window": window,
        "markets": [i.get("base") for i in first_list if isinstance(i, dict) and i.get("base")][:25],
        "chart": chart,
    }
    return Summary(text="\n\n".join(lines), variables=variables, chart=chart)


def _screener_chart(view: str, data: dict[str, Any]) -> str | None:
    """A bar chart of the view's main ranking, where it ranks by one number."""
    series = {
        "fear_greed": ("points", "at", "index", "Fear and greed index (0-100)", 1),
        "etf": ("dailyFlows", "date", "netFlowUsd", "Daily net flow ($M)", 1e-6),
    }.get(view)
    if series:
        key, x_key, y_key, label, scale = series
        points = [p for p in data.get(key) or [] if isinstance(p, dict) and fmt.is_num(p.get(y_key))]
        points.sort(key=lambda p: str(p.get(x_key)))
        if not points:
            return None
        return echarts(
            {
                "title": {"text": label, "left": "center", "textStyle": {"fontSize": 13}},
                "tooltip": {"trigger": "axis"},
                "grid": {"left": 64, "right": 24, "top": 40, "bottom": 40},
                "xAxis": {"type": "category", "data": [str(p.get(x_key))[:10] for p in points]},
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "type": "bar" if view == "etf" else "line",
                        "data": [round(p[y_key] * scale, 2) for p in points],
                        "itemStyle": {"color": "#3b1fb0"},
                    }
                ],
            }
        )
    spec = {
        "trending": ("positionsBuilding", "openInterestChange24h", "OI change, 24h (%)", 100),
        "movers": ("up", "priceChange24h", "Price change, 24h (%)", 100),
        "funding": ("highest", "fundingRateAnnualized", "Funding (%/yr)", 100),
        "open_interest": ("largest", "openInterestUsd", "Open interest ($M)", 1e-6),
        "lean": ("markets", "longShare", "Long share (%)", 100),
    }.get(view)
    if not spec:
        return None
    key, field_name, label, scale = spec
    items = [i for i in data.get(key) or [] if isinstance(i, dict) and fmt.is_num(i.get(field_name))][:MAX_ROWS]
    if view == "movers":
        items += [i for i in data.get("down") or [] if isinstance(i, dict) and fmt.is_num(i.get(field_name))][:MAX_ROWS]
    if not items:
        return None
    return echarts(
        {
            "title": {"text": label, "left": "center", "textStyle": {"fontSize": 13}},
            "tooltip": {"trigger": "axis"},
            "grid": {"left": 64, "right": 24, "top": 40, "bottom": 48},
            "xAxis": {"type": "category", "data": [i.get("base") for i in items], "axisLabel": {"rotate": 35}},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": "bar",
                    "data": [
                        {
                            "value": round(i[field_name] * scale, 2),
                            "itemStyle": {"color": "#f0428f" if i[field_name] < 0 else "#3b1fb0"},
                        }
                        for i in items
                    ],
                }
            ],
        }
    )


# ------------------------------------------------------------------ prop firms


def _code(firm: dict[str, Any]) -> str:
    offers = [o for o in firm.get("offers") or [] if isinstance(o, dict) and o.get("code")]
    if not offers:
        return DASH
    best = max(offers, key=lambda o: o.get("percentOff") or 0)
    return f"{best['code']} ({best.get('percentOff', '?')}% off)"


def _program_cost(program: dict[str, Any]) -> float | None:
    """What getting funded costs: the fee, plus any activation fee owed after passing."""
    fee = program.get("priceUsd")
    if not fmt.is_num(fee):
        return None
    activation = program.get("activationFeeUsd")
    return fee + (activation if fmt.is_num(activation) else 0)


def _program_price(program: dict[str, Any]) -> str:
    fee = program.get("priceUsd")
    if not fmt.is_num(fee):
        return f"€{program['priceEur']:g}" if fmt.is_num(program.get("priceEur")) else DASH
    text = fmt.usd_exact(fee)
    if fmt.is_num(program.get("activationFeeUsd")):
        text += f" + {fmt.usd_exact(program['activationFeeUsd'])} after passing"
    return text


def _program_code(program: dict[str, Any]) -> str:
    offer = program.get("offer")
    if not isinstance(offer, dict) or not offer.get("code"):
        return DASH
    after = f": {fmt.usd_exact(offer['priceAfter'])}" if fmt.is_num(offer.get("priceAfter")) else ""
    terms = ""
    if offer.get("firstPurchaseOnly"):
        count = offer.get("firstPurchases")
        terms = f" (first {count} purchases" if fmt.is_num(count) and count > 1 else " (first purchase"
        terms += f", then {fmt.usd_exact(offer['laterPrice'])})" if fmt.is_num(offer.get("laterPrice")) else ")"
    return f"{offer['code']}{after}{terms}"


def _targets(program: dict[str, Any]) -> str:
    return " / ".join(f"{t}%" for t in program.get("profitTargetsPct") or []) or DASH


def _losses(program: dict[str, Any], with_type: bool = False) -> str:
    daily = program.get("dailyLossPct")
    daily_text = f"{daily}%" if fmt.is_num(daily) else (daily or DASH)
    most = program.get("maxLossPct")
    most_text = f"{most}%" if fmt.is_num(most) else DASH
    if with_type and fmt.is_num(most) and program.get("maxLossType"):
        most_text += f" {program['maxLossType']}"
    return f"{daily_text} / {most_text}"


def _split(program: dict[str, Any]) -> str:
    return f"{program['profitSplitPct']}%" if fmt.is_num(program.get("profitSplitPct")) else DASH


def _entry(firm: dict[str, Any]) -> str:
    entry = firm.get("entry") or {}
    if fmt.is_num(entry.get("usd")):
        return f"{fmt.usd_exact(entry['usd'])} for {fmt.usd(entry.get('accountUsd'))}"
    return fmt.clip(firm.get("startingPriceUsd"), 40)


def prop_firms(records: Sequence[Any], firm: str | None = None, account_usd: Any = None) -> Summary:
    record = first(records)
    data = data_of(record)
    firms = [f for f in data.get("firms") or [] if isinstance(f, dict)]
    if not firms:
        return Summary(
            text=str(record.get("note") or "No prop firm matched these filters."), variables=base_variables(record)
        )
    lines: list[str] = []

    if firm and len(firms) == 1 and firms[0].get("programs"):
        one = firms[0]
        profile = one.get("profile") or {}
        lines.append(f"### {fmt.link(one['name'], one.get('page'))}")
        facts = [
            ("Model", fmt.clip(one.get("model"), 80)),
            ("Trades on", ", ".join(one.get("tradesOn") or []) or DASH),
            ("Markets", fmt.clip(one.get("markets"), 80)),
            ("Account sizes", ", ".join(fmt.usd(a) for a in one.get("accountSizesUsd") or []) or DASH),
            ("Starting price", _entry(one)),
            ("Profit target", fmt.clip(one.get("profitTargetPct"), 80)),
            ("Daily loss limit", fmt.clip(one.get("maxDailyLossPct"), 80)),
            ("Max drawdown", fmt.clip(one.get("maxDrawdownPct"), 80)),
            ("Profit split", fmt.clip(one.get("profitSplit"), 80)),
            ("When profits are paid", fmt.clip(one.get("payoutCadence"), 80)),
            ("US traders", fmt.clip(one.get("usTraders"), 60)),
            ("Country", profile.get("country") or DASH),
            ("Max allocation", fmt.usd(profile.get("maxAllocationUsd"))),
            ("Discount code", _code(one)),
            ("Rules confirmed", one.get("rulesConfirmed") or one.get("confirmed") or DASH),
        ]
        lines.append(fmt.facts(facts))
        programs = sorted(one["programs"], key=lambda p: (p.get("accountUsd") or 0, _program_cost(p) or 0))
        lines.append(f"**Challenges** ({len(programs)})")
        lines.append(
            fmt.table(
                ["Challenge", "Account", "Price", "Target", "Daily / max loss", "Split"],
                (
                    [
                        fmt.link(p.get("name", DASH), p.get("page")),
                        fmt.usd(p.get("accountUsd")),
                        _program_price(p),
                        _targets(p),
                        _losses(p, with_type=True),
                        _split(p),
                    ]
                    for p in programs[:20]
                ),
            )
        )
        changes = [c for c in one.get("changes") or [] if isinstance(c, dict)][:3]
        if changes:
            lines.append("**Latest rule changes**")
            lines.append("\n".join(f"- {c.get('date')}: {fmt.clip(c.get('what'), 320)}" for c in changes))
    elif account_usd:
        rows = []
        for f in firms:
            for p in f.get("programs") or []:
                cost = _program_cost(p)
                rows.append((cost if cost is not None else float("inf"), f, p))
        rows.sort(key=lambda r: r[0])
        lines.append(f"### {fmt.usd(account_usd)} prop challenges, cheapest to get funded first")
        lines.append(
            f"{len(rows)} challenges at {len(firms)} firms. The price counts any activation fee owed after passing; "
            "a code's price is before that fee."
        )
        lines.append(
            "\n".join(
                f"{n}. **{_program_price(p)}** {fmt.link(f['name'], f.get('page'))}: "
                f"{fmt.link(p.get('name', DASH), p.get('page'))} · target {_targets(p)} · "
                f"daily / max loss {_losses(p)} · split {_split(p)}"
                + (f" · code {_program_code(p)}" if p.get("offer") else "")
                for n, (_, f, p) in enumerate(rows[:15], start=1)
            )
        )
    else:
        lines.append(f"### Prop firms ({len(firms)})")
        lines.append(
            "\n".join(
                f"- **{fmt.link(f['name'], f.get('page'))}** from {_entry(f)} · daily loss "
                f"{fmt.clip(f.get('maxDailyLossPct'), 60)} · max drawdown {fmt.clip(f.get('maxDrawdownPct'), 60)}"
                + (f" · code {_code(f)}" if _code(f) != DASH else "")
                for f in firms[:25]
            )
        )
    if record.get("note"):
        lines.append(f"Note: {record['note']}")
    lines.append(footer(record))
    variables = base_variables(record) | {
        "firms": [f.get("name") for f in firms],
        "count": len(firms),
    }
    return Summary(text="\n\n".join(lines), variables=variables)


# -------------------------------------------------------------- SEC: insiders


def _company(records: Sequence[Any]) -> str:
    entity = first(records).get("entity") or {}
    name, ticker = entity.get("name"), entity.get("ticker")
    return f"{name} ({ticker})" if name and ticker else str(name or ticker or "")


# The SEC's Form 4 codes (Form 4, General Instructions, item 8).
FORM4_CODES = {
    "P": "purchase",
    "S": "sale",
    "A": "award",
    "D": "to company",
    "F": "tax withheld",
    "M": "option exercise",
    "X": "option exercise",
    "O": "option exercise",
    "C": "conversion",
    "G": "gift",
    "J": "other",
    "W": "inheritance",
}


def _form4_code(code: Any) -> str:
    if not code:
        return DASH
    meaning = FORM4_CODES.get(str(code).upper())
    return f"{code} ({meaning})" if meaning else str(code)


def insider_trades(records: Sequence[Any]) -> Summary:
    trades = [r for r in records if isinstance(r, dict) and r.get("type") == "insider_trade"]
    if not trades:
        return generic(records, "Insider trades")
    sold = sum((r["data"].get("value") or 0) for r in trades if r["data"].get("acquired_disposed") == "D")
    bought = sum((r["data"].get("value") or 0) for r in trades if r["data"].get("acquired_disposed") == "A")
    lines = [
        f"### Insider trades: {_company(trades)}",
        f"{len(trades)} Form 4 lines, newest first: acquired {fmt.usd(bought)}, disposed of {fmt.usd(sold)}. "
        "Each line gives the trade date first and the date the filing made it public last.",
        "\n".join(
            f"- **{r.get('event_time')}** {fmt.clip(r['data'].get('insider_display_name') or r['data'].get('insider_name'), 60)}: "
            f"{_form4_code(r['data'].get('txn_code'))} of {fmt.usd(r['data'].get('value'))}, "
            f"{fmt.number(r['data'].get('shares'))} shares at {fmt.price(r['data'].get('price'))} · "
            f"filed {fmt.link(str(r.get('as_of')), source_url(r))}"
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
    low, high = data.get("amount_low"), data.get("amount_high")
    if fmt.is_num(low) and fmt.is_num(high):
        return f"{fmt.usd_exact(low)} – {fmt.usd_exact(high)}"
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
            + (f" ({r['data']['owner']})" if r["data"].get("owner") else "")
            + f" · filed {fmt.link(str(r.get('as_of')), source_url(r))}"
            for r in trades[:25]
        )
    )
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
            f"Insider and congressional open-market flow over {d.get('window')}: **{d.get('label')}** "
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


def company_calendar(records: Sequence[Any]) -> Summary:
    company = _company(records)
    events = [r for r in records if isinstance(r, dict) and r.get("type") not in ("thesis_impact",) and r.get("data")]
    if not events:
        return generic(records, f"{company}: what is ahead")
    lines = [f"### {company}: what is ahead"]
    rows = []
    for r in events[:MAX_ROWS]:
        d = r.get("data") or {}
        basis = d.get("estimate_basis")
        status = r.get("confidence") or d.get("status")
        rows.append(
            [
                d.get("projected_date") or r.get("event_time"),
                (d.get("subtype") or r.get("type") or DASH).replace("_", " "),
                f"{status}" + (f": {basis}" if basis else ""),
                d.get("last_reported") or DASH,
            ]
        )
    lines.append(fmt.table(["Date", "Event", "Status and basis", "Last reported"], rows))
    lines.append(
        "An estimated date is projected from the company's own filing cadence; it is not a date the company announced."
    )
    thesis = _thesis_line(records)
    if thesis:
        lines.append(thesis)
    lines.append("_Source: SEC EDGAR filing cadence, computed by OptimistFi_")
    earnings = next((r for r in events if (r.get("data") or {}).get("subtype") == "earnings"), {})
    variables = {
        "as_of": earnings.get("as_of") or events[0].get("as_of"),
        "source_url": source_url(earnings) if earnings else None,
        "company": company,
        "next_earnings": (earnings.get("data") or {}).get("projected_date"),
        "next_earnings_confidence": earnings.get("confidence"),
    }
    return Summary(text="\n\n".join(lines), variables=variables)
