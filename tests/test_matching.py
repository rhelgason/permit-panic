from datetime import date

import pytest

from permit_panic.matching import match_campground, match_entry, match_itinerary, months_between, resolve_divisions
from permit_panic.recgov import parse_campground, parse_entry, parse_itinerary

D = date


def test_parse_itinerary():
    assert parse_itinerary({"bools": {"2027-07-01": True, "2027-07-02": False}}) == {
        D(2027, 7, 1): True,
        D(2027, 7, 2): False,
    }


def test_parse_entry_skips_walkup():
    payload = {
        "2027-07-01": {
            "424": {"quota_usage_by_member_daily": {"total": 8, "remaining": 3}, "is_walkup": False},
            "999": {"quota_usage_by_member_daily": {"total": 8, "remaining": 8}, "is_walkup": True},
        }
    }
    assert parse_entry(payload) == {D(2027, 7, 1): {"424": 3}}


def test_parse_campground():
    data = {"campsites": {"1": {"site": "A1", "loop": "Loop A", "availabilities": {
        "2027-07-01T00:00:00Z": "Available", "2027-07-02T00:00:00Z": "Reserved"}}}}
    assert parse_campground(data) == {"Loop A A1": {D(2027, 7, 1): True, D(2027, 7, 2): False}}


def test_resolve_divisions_by_name_and_id():
    divs = {"1": "#1 Wilcox Point", "2": "Alaska Basin", "3": "South Fork Cascade"}
    assert resolve_divisions(["cascade", "1"], divs) == ["3", "1"]
    with pytest.raises(ValueError):
        resolve_divisions(["nowhere"], divs)


def test_itinerary_requires_every_night_open():
    avail = {
        "A": {D(2027, 7, 1): True, D(2027, 7, 2): True},
        "B": {D(2027, 7, 2): True, D(2027, 7, 3): False},
        "C": {D(2027, 7, 3): True},
    }
    nights = [["A"], ["B"], ["C", "B"]]
    m = match_itinerary(nights, avail, D(2027, 7, 1), D(2027, 7, 3), {"A": "Alpha"})
    assert [x.key for x in m] == ["2027-07-01|A;B;C"]
    assert "Alpha -> B -> C" in m[0].summary


def test_itinerary_respects_latest():
    avail = {"A": {D(2027, 7, 1): True, D(2027, 7, 2): True}}
    assert match_itinerary([["A"], ["A"]], avail, D(2027, 7, 1), D(2027, 7, 1), {}) == []


def test_entry_group_size():
    avail = {D(2027, 7, 1): {"424": 1}, D(2027, 7, 2): {"424": 4}}
    m = match_entry(avail, ["424"], 2, D(2027, 7, 1), D(2027, 7, 2), {"424": "Glacier Canyon"})
    assert [x.key for x in m] == ["2027-07-02|424"]


def test_campground_consecutive_nights():
    sites = {"A1": {D(2027, 7, 1): True, D(2027, 7, 2): False, D(2027, 7, 3): True, D(2027, 7, 4): True}}
    m = match_campground(sites, 2, D(2027, 7, 1), D(2027, 7, 4))
    assert [x.key for x in m] == ["2027-07-03|A1"]


def test_months_between_crosses_year():
    assert months_between(D(2026, 12, 5), D(2027, 2, 1)) == [(2026, 12), (2027, 1), (2027, 2)]


def test_exact_name_beats_fragment():
    divs = {"1": "La Verkin Creek 1", "11": "La Verkin Creek 11", "2": "La Verkin Creek 2"}
    assert resolve_divisions(["la verkin creek 1"], divs) == ["1"]
    assert resolve_divisions(["La Verkin"], divs) == ["1", "11", "2"]


def test_summarize_collapses_consecutive_days():
    from permit_panic.matching import Match, summarize

    ms = [Match(f"k{d}", D(2026, 12, d), "A -> B") for d in (1, 2, 3, 5, 30, 31)]
    ms += [Match("x", D(2027, 1, 1), "A -> B"), Match("y", D(2026, 12, 2), "C")]
    assert summarize(ms) == "Dec 01-03, Dec 05, Dec 30-Jan 01: A -> B\nDec 02: C"
    assert summarize(ms, limit=1).endswith("...and 1 more options")
