"""Drive the dashboard headlessly against a fake Recreation.gov."""

import asyncio

from permit_panic.config import read_raw
from permit_panic.recgov import SearchResult
from permit_panic.tui import PermitPanicApp, WatchForm


class FakeApi:
    def search(self, q, size=10):
        return [SearchResult("permit", "4675342", "Grand Teton Backcountry", "Grand Teton NP"),
                SearchResult("recarea", "1", "Not bookable", "")]

    def permit_kind(self, pid):
        return "itinerary"

    def permit_divisions(self, pid):
        return {"30": "Death Canyon Shelf", "28": "Cascade South Fork", "27": "Cascade North Fork"}

    def permit_content(self, pid):
        return {"name": "Grand Teton", "time_zone": "America/Denver", "important_dates": [
            {"description": "Opens 8:00 a.m. MT", "start_date": "January 11, 2099", "end_date": ""}]}


def test_add_itinerary_watch_and_reminder(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("")

    async def run():
        app = PermitPanicApp(cfg, api=FakeApi())
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.press("a")
            await pilot.press(*"teton", "enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("enter")  # pick first (only bookable) result
            await app.workers.wait_for_complete()
            await pilot.pause()
            form = app.screen
            assert isinstance(form, WatchForm)
            form.selected = {"30"}
            form.add_night()
            form.selected = {"28", "27"}
            form.add_night()
            form.save()
            await pilot.pause()

            await pilot.press("m")
            await pilot.press(*"teton", "enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.query_one("#reminders").row_count == 1

    asyncio.run(run())
    raw = read_raw(cfg)
    assert raw["watch"][0]["nights"] == [["30"], ["27", "28"]]
    assert raw["watch"][0]["permit_id"] == "4675342"
    assert raw["reminder"] == [{"name": "Grand Teton Backcountry", "permit_id": "4675342"}]
