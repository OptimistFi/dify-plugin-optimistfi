import json
import re

import pytest

from optimistfi import client, fmt, render

from conftest import FIXTURES, fixture

RENDERERS = {
    "perp_": (render.perp_market, {}),
    "hist_": (render.perp_history, {}),
    "prop_breakout": (render.prop_firms, {"firm": "Breakout"}),
    "prop_50k": (render.prop_firms, {"account_usd": 50000}),
    "prop_": (render.prop_firms, {}),
    "insider_": (render.insider_trades, {}),
    "congress_": (render.congress_trades, {}),
    "filings_events": (render.company_filings, {"kind": "events"}),
    "filings_pr": (render.company_filings, {"kind": "press_releases"}),
    "filings_text": (render.company_filings, {"kind": "event_text"}),
    "filings_flags": (render.company_filings, {"kind": "red_flags"}),
    "calendar_": (render.company_calendar, {}),
    "market_": (render.perps_screener, {}),
}

ALL = sorted(p.stem for p in FIXTURES.glob("*.sse"))


def summarize(name: str) -> render.Summary:
    renderer, kwargs = next(v for k, v in RENDERERS.items() if name.startswith(k))
    reply = client.parse(fixture(name))
    assert reply.error is None, reply.error
    return render.safely(renderer, reply.records, name, **kwargs)


def strict(name: str) -> render.Summary:
    """The renderer itself, with no fallback, so a shape it cannot read fails the test."""
    renderer, kwargs = next(v for k, v in RENDERERS.items() if name.startswith(k))
    records = client.parse(fixture(name)).records
    if render.notice(records):
        return render.safely(renderer, records, name, **kwargs)
    return renderer(records, **kwargs)


@pytest.mark.parametrize("name", ALL)
def test_every_recorded_reply_renders_without_the_fallback(name):
    summary = strict(name)

    assert summary.text.strip()
    assert "Traceback" not in summary.text
    assert "None" not in re.sub(r"\(.*?\)", "", summary.text.split("\n")[0])


@pytest.mark.parametrize("name", ALL)
def test_summaries_hold_no_instruction_aimed_at_the_reader_model(name):
    text = summarize(name).text
    for cue in ("You must", "MUST", "REQUIRED", "Never present", "Please ", "Say so", "Do not"):
        assert cue not in text, f"{name}: {cue!r}"


@pytest.mark.parametrize(
    "name", [n for n in ALL if n.startswith(("perp_btc", "hist_btc", "market_trending", "market_etf"))]
)
def test_charts_are_valid_echarts_json(name):
    chart = summarize(name).chart

    assert chart.startswith("```echarts\n") and chart.endswith("\n```")
    option = json.loads(chart.removeprefix("```echarts\n").removesuffix("\n```"))
    assert option["series"] and option["xAxis"]["data"]


def test_perp_market_reads_units_and_flags_stale_venues():
    summary = summarize("perp_btc")

    assert summary.text.startswith("### BTC perpetual futures")
    assert "- **Open interest:** $35.76B · 24h −1.24%" in summary.text
    assert "+0.0008%/h" in summary.text
    assert "| binance BTCUSDT | not read | $7.70B |" in summary.text
    assert "Not read this hour: binance, whose open interest above is from 2026-10-27 23:00 UTC." in summary.text
    assert summary.variables["open_interest_usd"] == 35756020262
    assert summary.variables["source_url"] == "https://optimistfi.com/perps/markets/btc"


def test_perp_market_skips_a_cohort_of_one_small_account():
    assert "$891 short" not in summarize("perp_nvda").text


def test_building_history_says_so_instead_of_inventing_numbers():
    summary = summarize("hist_sol_30d")

    assert "being built" in summary.text
    assert summary.chart is None


def test_unknown_market_returns_the_servers_note():
    assert summarize("perp_unknown").text.startswith("no perpetual futures market OptimistFi reads lists ZZZZQ")


def test_unknown_company_returns_the_servers_error():
    assert summarize("insider_unknown").text == "No entity matched 'ZZZZQ'"


def test_prop_rule_text_is_not_cut_to_its_first_clause():
    text = summarize("prop_breakout").text

    assert "- **Profit target:** 9% (Turbo) / 10% (Classic) / 12% (Pro), single phase" in text
    assert "- **Profit target:** 9%\n" not in text


def test_prop_ranking_counts_the_activation_fee():
    summary = summarize("prop_50k")
    text = summary.text

    ranked = [line for line in text.splitlines() if line.split(". ", 1)[0].isdigit()]
    # Leveraged's $8.88 start fee owes $340.12 more after passing, so $139 Kraken Prop Lite ranks first.
    assert ranked[0].startswith("1. **$139** [Kraken Prop]")
    assert not any("**$8.88**" in row for row in ranked)
    leveraged = next(
        f for f in client.parse(fixture("prop_50k")).records[0]["data"]["firms"] if f["name"] == "Leveraged"
    )
    turbo = next(p for p in leveraged["programs"] if p["name"] == "Turbo")
    assert render._program_price(turbo) == "$8.88 + $340.12 after passing"
    assert render._program_code(turbo) == "TRYTURBO: $4.44 (first purchase)"


def test_insider_rows_carry_trade_and_filing_dates():
    text = summarize("insider_nvda").text

    assert (
        "- **2026-09-21** Timothy S. Teter (EVP, General Counsel and Sec): S (sale) of $2.8M, 12,483 shares at $222.19"
        " · filed [2026-09-23](https://www.sec.gov/Archives/edgar/data/1045810/000169684126000014/)"
    ) in text


def test_projected_earnings_reads_as_an_estimate():
    summary = summarize("calendar_aapl")

    assert "| 2026-10-29 | earnings | estimated: median gap 91d over 8 filings |" in summary.text
    assert summary.variables["next_earnings_confidence"] == "estimated"
    assert "confirmed" not in summary.text


def test_8k_text_starts_at_the_first_item_not_the_xbrl_header():
    text = summarize("filings_text_aapl").text

    assert "Item 2.02 Results of Operations" in text
    assert "0000320193 0000320193" not in text
    assert "&#8220;" not in text


def test_a_view_that_needs_a_market_passes_on_the_servers_reason():
    assert "haven't looked" in summarize("market_basis_no_market").text


def test_an_unknown_shape_falls_back_to_a_plain_summary():
    records = [
        {
            "type": "perps_market",
            "as_of": "2026-10-28T23:00:00Z",
            "data": {"view": "brand_new", "rows": [{"base": "BTC", "x": 1}]},
        }
    ]

    summary = render.safely(render.perps_screener, records, "Perps screener", view="brand_new")

    assert "| base | x |" in summary.text


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (35756020262, "$35.76B"),
        (171845055, "$171.8M"),
        (50000, "$50K"),
        (-64938865, "−$64.9M"),
        (None, "—"),
    ],
)
def test_usd(value, text):
    assert fmt.usd(value) == text


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (81135.8, "$81,135.8"),
        (80000.0, "$80,000"),
        (214.2, "$214.20"),
        (5.042e-06, "$0.000005042"),
        (0.01541, "$0.01541"),
    ],
)
def test_price(value, text):
    assert fmt.price(value) == text


def test_small_shares_keep_a_visible_digit():
    assert fmt.pct(0.00331, signed=False, digits=0) == "0.3%"
    assert fmt.pct(-0.0124) == "−1.24%"


def test_clip_cuts_at_a_word_with_an_ellipsis():
    assert fmt.clip("3%, recalculated daily at 00:30 UTC from balance", 28) == "3%, recalculated daily at…"


def test_history_leaves_out_a_step_still_filling_after_the_last_price():
    records = client.parse(fixture("hist_btc_7d")).records
    data = records[0]["data"]
    last = data["price"]["points"][-1][0]
    data["fundingAnnualizedOiWeighted"].append(["2099-01-01T00:00:00Z", -0.04])
    data["takerFlowUsd"].append({"at": "2099-01-01T00:00:00Z", "buy": 1, "sell": 999999999999, "net": -999999999998})

    summary = render.perp_history(records)

    assert "−4.00%/yr" not in summary.text
    assert summary.variables["funding_annualized_now"] == dict(data["fundingAnnualizedOiWeighted"])[last]


def test_a_code_reads_its_own_terms():
    offer = {"code": "ELITE", "priceAfter": 142, "firstPurchaseOnly": True, "firstPurchases": 2, "laterPrice": 152}

    assert render._program_code({"offer": offer}) == "ELITE: $142 (first 2 purchases, then $152)"
    assert render._program_code({"offer": {"code": "WEN", "priceAfter": 287.25}}) == "WEN: $287.25"


def test_a_cohort_too_small_to_be_positioning_is_left_out_even_when_alone():
    records = client.parse(fixture("perp_nvda")).records
    records[0]["data"]["largeAccountPositioning"] = [
        {"venue": "entropyio", "cohort": "accounts worth $1M-$10M", "longUsd": 0, "shortUsd": 891, "longShare": 0.0}
    ]

    assert "Large accounts on entropyio" not in render.perp_market(records).text
