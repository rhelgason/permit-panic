"""Every notification the watcher can send, driven through real cycles with a fake Recreation.gov."""

from datetime import date, datetime, timedelta, timezone

import pytest

from permit_panic import notify
from permit_panic.config import read_raw, write_raw
from permit_panic.recgov import RecGovError, parse_itinerary
from permit_panic.watch import Watcher

NOW = datetime(2027, 1, 10, 15, 0, tzinfo=timezone.utc)


def cell(total, remaining):
    return {"total": total, "remaining": remaining, "show_walkup": total == 0}


def test_itinerary_uses_quota_not_bools():
    payload = {
        "bools": {"2027-07-01": True, "2027-07-02": True, "2027-07-03": True, "2027-07-04": False},
        "quota_type_maps": {
            "ConstantQuotaUsageDaily": {"2027-07-01": cell(1, 1), "2027-07-02": cell(0, 0),
                                        "2027-07-03": cell(2, 1), "2027-07-04": cell(1, 0)},
            "QuotaUsageByMemberDaily": {"2027-07-01": cell(12, 12), "2027-07-02": cell(0, 0),
                                        "2027-07-03": cell(12, 3), "2027-07-04": cell(12, 12)},
        },
    }
    days = lambda g: [d.day for d, ok in parse_itinerary(payload, g).items() if ok]  # noqa: E731
    assert days(1) == [1, 3]  # the 2nd is walk-up only: bools says true, but nothing is reservable online
    assert days(4) == [1]  # only 3 people of quota left on the 3rd
    assert [d.day for d, ok in parse_itinerary({"bools": {"2027-07-01": True}}).items() if ok] == [1]


class FakeApi:
    def __init__(self):
        self.open_days = {date(2027, 7, 2)}
        self.fail = False

    def permit_content(self, pid):
        return {"name": "Teton", "time_zone": "America/Denver",
                "divisions": {"30": {"name": "Death Canyon Shelf"}},
                "important_dates": [{"description": "Reservations open 8:00 a.m. MT",
                                     "start_date": "January 11, 2027", "end_date": ""}]}

    def itinerary_month(self, pid, div, y, m, group_size=1):
        if self.fail:
            raise RecGovError("503 from recreation.gov")
        return {date(y, m, d): date(y, m, d) in self.open_days for d in range(1, 29)}


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(notify, "send", lambda title, body, **kw: out.append((title, kw.get("priority", "urgent"))))
    return out


def watch(**over):
    w = {"name": "Teton", "kind": "itinerary", "permit_id": "1", "earliest": date(2027, 7, 1),
         "latest": date(2027, 7, 10), "nights": [["30"]]}
    return w | over


def test_lifecycle_notifications(tmp_path, sent):
    cfg = tmp_path / "config.toml"
    write_raw(cfg, {"notify": {"ntfy_topic": "t"}})
    api = FakeApi()
    w = Watcher(cfg, api)
    titles = lambda: [t for t, _ in sent]  # noqa: E731

    w.cycle(NOW - timedelta(days=5))
    assert sent == []  # nothing configured, nothing to say

    write_raw(cfg, {"notify": {"ntfy_topic": "t"}, "watch": [watch()]})
    w.cycle(NOW - timedelta(days=5))
    assert titles() == ["Now watching: Teton", "Open: Teton"]
    assert sent[0][1] == "low" and sent[1][1] == "urgent"

    sent.clear()
    w.cycle(NOW - timedelta(days=5))
    assert sent == []  # same opening, no repeat

    raw = read_raw(cfg)
    raw["watch"][0]["latest"] = date(2027, 7, 20)
    write_raw(cfg, raw)
    w.cycle(NOW - timedelta(days=5))
    assert titles() == ["Updated: Teton", "Open: Teton"]  # new criteria re-alert what matches

    sent.clear()
    raw["watch"][0]["enabled"] = False
    write_raw(cfg, raw)
    w.cycle(NOW - timedelta(days=5))
    raw["watch"][0]["enabled"] = True
    write_raw(cfg, raw)
    w.cycle(NOW - timedelta(days=5))
    assert titles() == ["Paused: Teton", "Resumed: Teton"]

    sent.clear()
    write_raw(cfg, {"notify": {"ntfy_topic": "t"}, "watch": []})
    w.cycle(NOW - timedelta(days=5))
    assert titles() == ["Stopped watching: Teton"]


def test_first_run_sends_one_summary_not_one_per_watch(tmp_path, sent):
    cfg = tmp_path / "config.toml"
    write_raw(cfg, {"watch": [watch(), watch(name="Two")]})
    Watcher(cfg, FakeApi()).cycle(NOW - timedelta(days=5))
    assert [t for t, _ in sent if not t.startswith("Open")] == ["Permit Panic is running"]


def test_errors_wait_for_grace_period_then_report_fix(tmp_path, sent):
    cfg = tmp_path / "config.toml"
    write_raw(cfg, {"watch": [watch()]})
    api = FakeApi()
    w = Watcher(cfg, api)
    w.cycle(NOW)
    sent.clear()

    api.fail = True
    w.cycle(NOW)
    w.cycle(NOW + timedelta(minutes=20))
    assert sent == []  # a blip isn't worth a ping
    w.cycle(NOW + timedelta(minutes=31))
    assert [t for t, _ in sent] == ["Watch broken: Teton"]
    w.cycle(NOW + timedelta(minutes=40))
    assert len(sent) == 1

    api.fail = False
    w.cycle(NOW + timedelta(minutes=45))
    assert [t for t, _ in sent][1:] == ["Fixed: Teton"]


def test_new_watch_that_fails_says_so_immediately(tmp_path, sent):
    cfg = tmp_path / "config.toml"
    write_raw(cfg, {"watch": [watch()]})
    api = FakeApi()
    w = Watcher(cfg, api)
    w.cycle(NOW)
    sent.clear()
    api.fail = True
    write_raw(cfg, {"watch": [watch(), watch(name="New one")]})
    w.cycle(NOW)
    assert ("Problem with New one", "default") in sent


def test_expired_watch_reports_once(tmp_path, sent):
    cfg = tmp_path / "config.toml"
    write_raw(cfg, {"watch": [watch()]})
    w = Watcher(cfg, FakeApi())
    w.cycle(datetime(2027, 7, 5, 12, tzinfo=timezone.utc))
    sent.clear()
    w.cycle(datetime(2027, 7, 12, 12, tzinfo=timezone.utc))
    w.cycle(datetime(2027, 7, 13, 12, tzinfo=timezone.utc))
    assert [t for t, _ in sent] == ["Ended: Teton"]


def test_reminder_confirmation_and_alerts(tmp_path, sent):
    cfg = tmp_path / "config.toml"
    write_raw(cfg, {"watch": [watch()]})
    w = Watcher(cfg, FakeApi())
    w.cycle(NOW - timedelta(days=5))
    sent.clear()

    write_raw(cfg, {"watch": [watch()], "reminder": [{"name": "Teton", "permit_id": "1"}]})
    w.cycle(NOW - timedelta(days=5))
    assert [t for t, _ in sent] == ["Reminders on: Teton"]

    sent.clear()
    w.cycle(datetime(2027, 1, 10, 16, tzinfo=timezone.utc))  # 23h before 8am MT on the 11th
    w.cycle(datetime(2027, 1, 11, 14, 45, tzinfo=timezone.utc))  # 15 min before
    assert sent == [("Tomorrow: Teton", "default"), ("In 30 min: Teton", "high")]


def test_muted_reminder_is_silent(tmp_path, sent):
    cfg = tmp_path / "config.toml"
    write_raw(cfg, {"reminder": [{"name": "Teton", "permit_id": "1", "ignore": ["reservations open"]}]})
    w = Watcher(cfg, FakeApi())
    w.cycle(datetime(2027, 1, 11, 14, 45, tzinfo=timezone.utc))
    assert [t for t, _ in sent] == ["Permit Panic is running"]


def test_daily_digest_once_per_day(tmp_path, sent):
    at = datetime(2027, 6, 1, 15, 1, tzinfo=timezone.utc)
    cfg = tmp_path / "config.toml"
    write_raw(cfg, {"notify": {"digest_hour": at.astimezone().hour}, "watch": [watch()]})  # server-local hour
    w = Watcher(cfg, FakeApi())
    w.cycle(at - timedelta(minutes=11))
    sent.clear()
    w.cycle(at)
    w.cycle(at + timedelta(minutes=29))
    assert [t for t, _ in sent] == ["Permit Panic daily summary"]


def test_send_sets_icon_emoji_and_button(monkeypatch):
    import urllib.request as ur

    captured = {}

    class Resp:
        def close(self):
            pass

    def fake_urlopen(req, timeout=None):
        captured.update(req.headers, url=req.full_url)
        return Resp()

    monkeypatch.setattr(ur, "urlopen", fake_urlopen)
    from permit_panic import notify as real_notify

    real_notify.send("Open: X", "body", ntfy_topic="t", click_url="https://r.gov/p", action="Book now",
                     icon_url="https://example.com/icon.png")
    assert captured["Icon"] == "https://example.com/icon.png"
    assert captured["Tags"] == "bear"
    assert captured["Actions"] == "view, Book now, https://r.gov/p"


def test_icon_defaults_on_and_can_be_turned_off(tmp_path):
    from permit_panic.config import DEFAULT_ICON, load_config

    cfg = tmp_path / "config.toml"
    write_raw(cfg, {})
    assert load_config(cfg).icon_url == DEFAULT_ICON
    write_raw(cfg, {"notify": {"icon_url": ""}})
    assert load_config(cfg).icon_url is None
