import re

import pytest

from optimistfi import client, fmt, render

from conftest import FIXTURES, fixture

RENDERERS = {
    "insider_": (render.insider_trades, {}),
    "congress_": (render.congress_trades, {}),
    "filings_events": (render.company_filings, {"kind": "events"}),
    "filings_pr": (render.company_filings, {"kind": "press_releases"}),
    "filings_text": (render.company_filings, {"kind": "event_text"}),
    "filings_flags": (render.company_filings, {"kind": "red_flags"}),
    "calendar_": (render.company_calendar, {}),
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


def test_unknown_company_returns_the_servers_error():
    assert summarize("insider_unknown").text == "No entity matched 'ZZZZQ'"


def test_insider_rows_carry_trade_and_filing_dates():
    text = summarize("insider_nvda").text

    # The server lists open-market buys and sells ahead of grants and gifts, so "newest first" alone would mislead.
    assert "open-market buys and sells first, then other filings, newest first within each" in text

    assert (
        "- **2026-09-21** Timothy S. Teter (EVP, General Counsel and Sec): sold $2.8M, 12,483 shares at $222.19"
        " · filed [2026-09-23](https://www.sec.gov/Archives/edgar/data/1045810/000169684126000014/)"
    ) in text


def test_congress_lines_name_the_account_so_look_alike_trades_read_as_separate():
    text = summarize("congress_nvda").text

    # Three buys alike in all else, one in each of Cleo Fields' accounts (House doc 20035669).
    for account in (
        "Morgan Stanley - E*TRADE #2",
        "Morgan Stanley - E*TRADE - Fields Law Firm 2, LLC",
        "Morgan Stanley - E*TRADE IRA",
    ):
        assert (
            f"- **2026-10-01** Cleo Fields (LA06): buy NVIDIA Corporation - Common Stock (NVDA), $1,001 – $15,000, in {account}"
            " · filed [2026-10-22](https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/20035669.pdf)"
        ) in text
    assert "not read yet" not in text


def test_congress_counts_the_trades_whose_account_is_not_read_yet():
    text = summarize("congress_ko").text

    assert "6 of these trades come from filings whose account names are not read yet." in text


@pytest.mark.parametrize(
    ("low", "high", "text"),
    [
        (1001, 15000, "$1,001 – $15,000"),
        (15, 15, "$15"),
        (2722.5, 2722.5, "$2,722.50"),
        (1000000, None, "over $1,000,000"),
        (None, None, "—"),
    ],
)
def test_house_amounts_read_as_the_filing_wrote_them(low, high, text):
    assert render._amount({"amount_low": low, "amount_high": high}) == text


def test_projected_earnings_reads_as_an_estimate():
    summary = summarize("calendar_aapl")

    assert (
        "- **2026-10-29** earnings, estimated: expected imminently — projected 2026-10-29 from filing cadence"
        " (median gap 91d over 8 filings), not yet filed; typically confirmed within days. Last reported 2026-07-30."
    ) in summary.text
    assert summary.variables["next_earnings_confidence"] == "estimated"
    assert ", confirmed" not in summary.text  # the basis may say a date is "typically confirmed within days"


@pytest.mark.parametrize("name", ["calendar_aapl", "calendar_mrna", "calendar_lly"])
def test_calendar_is_a_list_so_a_long_basis_wraps_in_the_chat_bubble(name):
    # A table scrolled sideways in Dify's bubble and cut the basis off mid-word.
    assert "|---" not in summarize(name).text


def test_trial_readouts_name_the_study_and_link_its_registry_entry():
    text = summarize("calendar_lly").text

    assert (
        "- **2026-11-01** trial readout, estimated: A Study of Retatrutide (LY3437943) Compared to Tirzepatide"
        " (LY3298176) in Adults Who Have Obesity (Phase 3; Obesity; active not recruiting)"
        " · [ClinicalTrials.gov](https://clinicaltrials.gov/study/NCT06662383)"
    ) in text
    assert text.index("earnings, estimated") < text.index("trial readout"), text
    assert "primary completion date as its sponsor filed it on ClinicalTrials.gov" in text
    assert "fda event" not in text
    assert text.endswith("_Source: SEC EDGAR filing cadence, computed by OptimistFi; ClinicalTrials.gov_")


LILLY = {"ticker": "LLY", "name": "ELI LILLY & Co", "cik": "0000059478"}


def _readout(day: str, precision: str = "month") -> dict:
    return {"entity": LILLY, "type": "fda_event", "direction": "forward", "event_time": day, "confidence": "estimated",
            "source": {"name": "ClinicalTrials.gov", "url": "https://clinicaltrials.gov/study/NCT07000001"},
            "data": {"event_type": "trial_readout", "drug": "A Study of Retatrutide", "phase": "PHASE3",
                     "status": "ACTIVE_NOT_RECRUITING", "date_precision": precision}}


def test_the_earnings_estimate_leads_and_is_never_cut_by_the_row_limit():
    # LLY's estimate sat twelfth in the server's nearest-first list, behind eleven readouts, past MAX_ROWS.
    earnings = {"entity": LILLY, "type": "corporate_event", "direction": "forward", "event_time": "2027-02-03",
                "as_of": "2026-10-29T19:58:33+00:00", "confidence": "estimated",
                "source": {"name": "computed from SEC 8-K Item 2.02 cadence", "url": "https://optimistfi.com"},
                "data": {"subtype": "earnings", "projected_date": "2027-02-03", "last_reported": "2026-10-29",
                         "estimate_basis": "52 weeks after the same quarter's report a year earlier (2026-02-04)"}}
    summary = render.company_calendar([_readout(f"2026-11-{i:02d}", "day") for i in range(1, 12)] + [earnings])
    items = [line for line in summary.text.splitlines() if line.startswith("- **")]

    assert items[0].startswith("- **2027-02-03** earnings, estimated: 52 weeks after"), items[0]
    assert len(items) == render.MAX_ROWS and items[1].startswith("- **2026-11-01** trial readout"), items
    assert summary.variables["as_of"] == "2026-10-29T19:58:33+00:00"
    assert summary.variables["next_earnings"] == "2027-02-03"


@pytest.mark.parametrize(
    ("day", "precision", "shown"),
    [("2026-11-01", "month", "Nov 2026"), ("2026-12-01", "day", "2026-12-01"), ("2027-02-01", None, "2027-02-01")],
)
def test_a_month_only_completion_date_reads_as_its_month(day, precision, shown):
    # ClinicalTrials.gov filed 40 of LLY's nearest 50 completion dates as a month; the server pins them to the 1st.
    assert render._calendar_line(_readout(day, precision)).startswith(f"- **{shown}** trial readout")


def test_8k_text_starts_at_the_first_item_not_the_xbrl_header():
    text = summarize("filings_text_aapl").text

    assert "Item 2.02 Results of Operations" in text
    assert "0000320193 0000320193" not in text
    assert "&#8220;" not in text


def test_an_unknown_shape_falls_back_to_a_plain_summary():
    records = [
        {
            "type": "brand_new",
            "as_of": "2026-10-28T23:00:00Z",
            "data": {"rows": [{"ticker": "AAPL", "x": 1}]},
        }
    ]

    summary = render.safely(render.insider_trades, records, "Insider trades")

    assert "| ticker | x |" in summary.text


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
        (1250.5, "$1,250.5"),
        (1000.0, "$1,000"),
        (214.2, "$214.20"),
        (0.01541, "$0.01541"),
    ],
)
def test_price(value, text):
    assert fmt.price(value) == text


def test_clip_cuts_at_a_word_with_an_ellipsis():
    assert fmt.clip("3%, recalculated daily at 00:30 UTC from balance", 28) == "3%, recalculated daily at…"


def test_a_flow_label_reads_as_words():
    records = client.parse(fixture("filings_events_aapl")).records
    sentiment = next(r for r in records if r.get("type") == "sentiment")
    sentiment["data"]["label"] = "mildly_bearish"

    text = render.company_filings(records, kind="events").text

    assert "**mildly bearish**" in text and "mildly_bearish" not in text


@pytest.mark.parametrize(
    ("data", "text"),
    [
        (
            {"txn_code": "S", "direction": "sold", "value": 2.8e6, "shares": 12483, "price": 222.19},
            "sold $2.8M, 12,483 shares at $222.19",
        ),
        (
            {"txn_code": "G", "direction": "gave away", "value": 0, "shares": 500000, "price": 0},
            "gave away 500,000 shares",
        ),
        (
            {"txn_code": "S", "direction": "sold", "sell_to_cover": True, "value": 1e4, "shares": 50, "price": 200},
            "sold $10K, 50 shares at $200.00, to cover tax on vesting stock",
        ),
        ({"txn_code": "A", "value": None, "shares": 1000, "price": None}, "received 1,000 shares"),
        ({"txn_code": "K", "shares": 10}, "filed Form 4 code K for 10 shares"),
        (
            {"txn_code": "F", "direction": "surrendered", "shares": 2000, "price": 220},
            "surrendered 2,000 shares at $220.00",
        ),
    ],
)
def test_insider_lines_say_what_was_done_without_a_bare_code(data, text):
    assert render._insider_act(data) == text
