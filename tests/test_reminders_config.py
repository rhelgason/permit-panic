from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from permit_panic.config import load_config, read_raw, write_raw
from permit_panic.reminders import due_alerts, parse_events

TETON = {
    "name": "Grand Teton National Park Backcountry Permits",
    "time_zone": "America/Denver",
    "important_dates": [{
        "description": "Advance backcountry permit reservations open 8:00 a.m. MT on January 11th, 2027 ...",
        "start_date": "January 11, 2027",
        "end_date": "October 31, 2027",
    }],
}
WAVE = {
    "name": "The Wave",
    "time_zone": "America/Denver",
    "important_dates": [
        {"description": "Lottery open to applications for permits during May",
         "start_date": "January 1, 2027", "end_date": "January 31, 2027"},
        {"description": "Lottery closes at 11:59 p.m. PT", "start_date": "March 1, 2027", "end_date": ""},
    ],
}


def test_parse_time_and_zone():
    [e] = parse_events("4675342", TETON)  # season end_date is not a lottery window, so no close reminder
    assert e.when == datetime(2027, 1, 11, 8, 0, tzinfo=ZoneInfo("America/Denver"))
    assert e.time_known


def test_lottery_window_gets_open_and_close_reminders():
    events = parse_events("274309", WAVE)
    assert [(e.when.month, e.when.day, e.when.hour) for e in events] == [(1, 1, 9), (1, 31, 17), (3, 1, 23)]
    assert not events[0].time_known
    assert events[1].description.startswith("CLOSES")


def test_due_alerts_fire_once_per_lead():
    [e] = parse_events("4675342", TETON)
    sent: set[str] = set()
    assert due_alerts([e], e.when - timedelta(hours=25), sent) == []
    day_before = due_alerts([e], e.when - timedelta(hours=23), sent)
    assert len(day_before) == 1
    sent |= {k for k, *_ in day_before}
    assert due_alerts([e], e.when - timedelta(hours=22), sent) == []
    assert len(due_alerts([e], e.when - timedelta(minutes=10), sent)) == 1
    assert due_alerts([e], e.when + timedelta(minutes=1), set()) == []  # missed: don't alert late


def test_config_roundtrip_and_validation(tmp_path):
    path = tmp_path / "config.toml"
    raw = {"watch": [{"name": "x", "kind": "entry", "permit_id": "1", "earliest": "2027-07-01",
                      "latest": "2027-07-02", "trailheads": ["424"]}],
           "reminder": [{"name": "t", "permit_id": "4675342"}]}
    write_raw(path, raw)
    assert read_raw(path)["watch"][0]["trailheads"] == ["424"]
    cfg = load_config(path)
    assert cfg.state_file.parent == tmp_path
    assert cfg.reminders[0].permit_id == "4675342"

    raw["watch"][0]["latest"] = "2027-06-01"
    with pytest.raises(ValueError):
        write_raw(path, raw)
    assert load_config(path).watches[0].latest.month == 7  # bad edit didn't clobber the file
