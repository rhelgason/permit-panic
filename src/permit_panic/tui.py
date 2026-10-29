"""Terminal dashboard: see what's open, and add/remove watches and reminders.

It edits the same config file the watcher re-reads every cycle, so run it over
SSH on the server while `permit-panic watch` keeps running.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button, DataTable, Footer, Header, Input, Label, OptionList, SelectionList, Static, TabbedContent, TabPane,
)
from textual.widgets.option_list import Option

from .config import Watch, load_config, read_raw, write_raw
from .recgov import RecGov, RecGovError, SearchResult
from .reminders import parse_events

BOOKABLE = ("permit", "campground")


class SearchScreen(ModalScreen[SearchResult | None]):
    """Type a park or permit name, pick a result."""

    BINDINGS = [("escape", "dismiss(None)", "Cancel")]

    def __init__(self, api: RecGov, title: str, permits_only: bool = False):
        super().__init__()
        self.api, self.title_text, self.permits_only = api, title, permits_only
        self.results: list[SearchResult] = []

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.title_text, classes="title")
            yield Input(placeholder="e.g. grand teton backcountry, enchantments, jenny lake", id="q")
            yield OptionList(id="results")
            yield Label("Enter to search, then pick a result. Esc to cancel.", classes="hint")

    @on(Input.Submitted, "#q")
    def do_search(self, event: Input.Submitted) -> None:
        self.query_one("#results", OptionList).clear_options()
        self.search(event.value)

    @work(thread=True, exclusive=True)
    def search(self, q: str) -> None:
        try:
            found = self.api.search(q, size=20)
        except (RecGovError, OSError) as e:
            self.app.call_from_thread(self.app.notify, str(e), severity="error")
            return
        kinds = ("permit",) if self.permits_only else BOOKABLE
        self.results = [r for r in found if r.entity_type in kinds]
        self.app.call_from_thread(self._show)

    def _show(self) -> None:
        ol = self.query_one("#results", OptionList)
        ol.clear_options()
        ol.add_options([Option(f"[{r.entity_type}] {r.name}  ({r.parent})  #{r.entity_id}") for r in self.results])
        if not self.results:
            self.app.notify("No bookable permits or campgrounds found.")
            return
        ol.highlighted = 0
        ol.focus()

    @on(OptionList.OptionSelected, "#results")
    def picked(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self.results[event.option_index])


class WatchForm(ModalScreen[dict | None]):
    """Fill in dates and pick zones/trailheads for a new watch."""

    BINDINGS = [("escape", "dismiss(None)", "Cancel")]

    def __init__(self, result: SearchResult, kind: str, divisions: dict[str, str]):
        super().__init__()
        self.result, self.kind, self.divisions = result, kind, divisions
        self.selected: set[str] = set()
        self.nights: list[list[str]] = []

    def compose(self) -> ComposeResult:
        nxt = date.today().replace(year=date.today().year + 1)
        with VerticalScroll(classes="dialog wide"):
            yield Label(f"New {self.kind} watch: {self.result.name}", classes="title")
            with Horizontal(classes="row"):
                yield Input(self.result.name, placeholder="name", id="name")
                yield Input(f"{nxt:%Y}-07-01", placeholder="earliest YYYY-MM-DD", id="earliest")
                yield Input(f"{nxt:%Y}-08-31", placeholder="latest YYYY-MM-DD", id="latest")
            if self.kind == "entry":
                yield Input("2", placeholder="group size", id="group_size")
            if self.kind == "campground":
                with Horizontal(classes="row"):
                    yield Input("2", placeholder="consecutive nights", id="stay")
                    yield Input("", placeholder="site filter, comma separated (optional)", id="sites")
            if self.divisions:
                what = "camp zones" if self.kind == "itinerary" else "trailheads"
                yield Input(placeholder=f"filter {len(self.divisions)} {what}…", id="filter")
                yield SelectionList[str](*self._options(""), id="divs")
            if self.kind == "itinerary":
                yield Label("Tick the acceptable zones for the next night, then 'Add night'. "
                            "Repeat for each night of the route.", classes="hint")
                with Horizontal(classes="row"):
                    yield Button("Add night", id="add_night")
                    yield Button("Undo night", id="undo_night")
                yield Static("Route: (no nights yet)", id="route")
            yield Label("", id="error", classes="error")
            with Horizontal(classes="row"):
                yield Button("Save", variant="primary", id="save")
                yield Button("Cancel", id="cancel")

    def _options(self, needle: str):
        needle = needle.lower()
        return [(name, div_id, div_id in self.selected)
                for div_id, name in sorted(self.divisions.items(), key=lambda kv: kv[1])
                if needle in name.lower()]

    @on(Input.Changed, "#filter")
    def refilter(self, event: Input.Changed) -> None:
        sl = self.query_one("#divs", SelectionList)
        sl.clear_options()
        sl.add_options(self._options(event.value))

    @on(SelectionList.SelectionToggled, "#divs")
    def toggled(self, event: SelectionList.SelectionToggled) -> None:
        self.selected ^= {event.selection.value}

    def _clear_selection(self) -> None:
        self.selected.clear()
        self.query_one("#divs", SelectionList).deselect_all()

    def _show_route(self) -> None:
        lines = [f"Night {i + 1}: " + " / ".join(self.divisions[d] for d in n) for i, n in enumerate(self.nights)]
        self.query_one("#route", Static).update("Route:\n" + ("\n".join(lines) or "(no nights yet)"))

    @on(Button.Pressed, "#add_night")
    def add_night(self) -> None:
        if not self.selected:
            self.query_one("#error", Label).update("Tick at least one zone for this night.")
            return
        self.nights.append(sorted(self.selected))
        self._clear_selection()
        self._show_route()

    @on(Button.Pressed, "#undo_night")
    def undo_night(self) -> None:
        if self.nights:
            self.nights.pop()
            self._show_route()

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#save")
    def save(self) -> None:
        val = lambda i: self.query_one(f"#{i}", Input).value.strip()  # noqa: E731
        d: dict = {"name": val("name"), "kind": self.kind, "earliest": val("earliest"), "latest": val("latest")}
        d["campground_id" if self.kind == "campground" else "permit_id"] = self.result.entity_id
        try:
            d["earliest"], d["latest"] = date.fromisoformat(d["earliest"]), date.fromisoformat(d["latest"])
            if self.kind == "itinerary":
                d["nights"] = self.nights
            elif self.kind == "entry":
                d["trailheads"] = sorted(self.selected)
                d["group_size"] = int(val("group_size"))
            else:
                d["nights"] = int(val("stay"))
                d["sites"] = [s.strip() for s in val("sites").split(",") if s.strip()]
            Watch.from_dict(d)
        except (ValueError, KeyError) as e:
            self.query_one("#error", Label).update(str(e))
            return
        self.dismiss(d)


class PermitPanicApp(App):
    TITLE = "Permit Panic"
    CSS = """
    .dialog { width: 90; height: auto; max-height: 90%; border: thick $accent; background: $surface; padding: 1 2; }
    .wide { width: 110; }
    ModalScreen { align: center middle; }
    .title { text-style: bold; margin-bottom: 1; }
    .hint { color: $text-muted; }
    .error { color: $error; }
    .row { height: auto; }
    .row Input { width: 1fr; }
    #results { height: 15; }
    #divs { height: 10; }
    #detail { height: auto; max-height: 12; border-top: solid $accent; padding: 0 1; }
    """
    BINDINGS = [
        ("a", "add_watch", "Add watch"),
        ("m", "add_reminder", "Add reminder"),
        ("space", "toggle", "On/off"),
        ("d", "delete", "Delete"),
        ("r", "refresh", "Refresh"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, config_path: str | Path, api: RecGov | None = None):
        super().__init__()
        self.config_path = Path(config_path)
        self.api = api or RecGov(min_interval=0.3)
        self.status: dict = {}
        self.reminder_rows: list[str] = []  # permit id per reminders-table row

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent():
            with TabPane("Watches", id="tab-watches"):
                yield DataTable(id="watches", cursor_type="row")
                yield Static("", id="detail")
            with TabPane("Reminders", id="tab-reminders"):
                yield DataTable(id="reminders", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#watches", DataTable).add_columns("On", "Name", "Kind", "Dates", "Status", "Checked")
        self.query_one("#reminders", DataTable).add_columns("When", "Permit", "What")
        self.action_refresh()
        self.set_interval(15, self.refresh_watches)

    # --- views -------------------------------------------------------------

    def refresh_watches(self) -> None:
        cfg = load_config(self.config_path)
        try:
            self.status = json.loads(cfg.status_file.read_text())
        except (OSError, ValueError):
            self.status = {}
        table = self.query_one("#watches", DataTable)
        row = table.cursor_row
        table.clear()
        for w in cfg.watches:
            s = self.status.get("watches", {}).get(w.name, {})
            if not w.enabled:
                state = "paused"
            elif "error" in s:
                state = "error"
            elif "open" in s:
                state = f"{len(s['open'])} open" if s["open"] else "nothing yet"
            else:
                state = "waiting for watcher"
            checked = s.get("checked", "")[11:19]
            table.add_row("●" if w.enabled else "○", w.name, w.kind,
                          f"{w.earliest:%b %d} – {w.latest:%b %d %Y}", state, checked, key=w.name)
        if table.row_count:
            table.move_cursor(row=min(row, table.row_count - 1))
        self.show_detail()

    @on(DataTable.RowHighlighted, "#watches")
    def show_detail(self) -> None:
        table = self.query_one("#watches", DataTable)
        detail = self.query_one("#detail", Static)
        if not table.row_count:
            detail.update("No watches yet. Press [b]a[/b] to add one.")
            return
        name = table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value
        s = self.status.get("watches", {}).get(name, {})
        if "error" in s:
            detail.update(f"[red]{s['error']}[/red]")
        else:
            detail.update("\n".join(s.get("open", [])[:10]) or "No openings right now.")

    @work(thread=True, exclusive=True, group="reminders")
    def refresh_reminders(self) -> None:
        rows: list[tuple[datetime, str, str, str]] = []
        now = datetime.now(timezone.utc)
        for r in load_config(self.config_path).reminders:
            try:
                events = parse_events(r.permit_id, self.api.permit_content(r.permit_id))
            except (RecGovError, OSError, KeyError) as e:
                rows.append((now, r.permit_id, r.name, f"error: {e}"))
                continue
            upcoming = [e for e in events if e.when > now]
            for e in upcoming:
                rows.append((e.when, r.permit_id, r.name, e.description + ("" if e.time_known else " (time ?)")))
            if not upcoming:
                rows.append((now, r.permit_id, r.name, "No upcoming dates posted yet (checks again every few hours)"))
        rows.sort(key=lambda x: x[0])
        self.call_from_thread(self._fill_reminders, rows)

    def _fill_reminders(self, rows) -> None:
        table = self.query_one("#reminders", DataTable)
        table.clear()
        self.reminder_rows = [r[1] for r in rows]
        for when, _, name, what in rows:
            table.add_row(when.strftime("%a %b %d %Y %-I:%M %p %Z"), name[:40], what if len(what) < 90 else what[:87] + "…")

    # --- actions -----------------------------------------------------------

    def action_refresh(self) -> None:
        self.refresh_watches()
        self.refresh_reminders()

    def _on_watches_tab(self) -> bool:
        return self.query_one(TabbedContent).active == "tab-watches"

    def _edit(self, fn) -> None:
        raw = read_raw(self.config_path)
        fn(raw)
        try:
            write_raw(self.config_path, raw)
        except (ValueError, KeyError) as e:
            self.notify(f"Not saved: {e}", severity="error")
        self.action_refresh()

    def action_add_watch(self) -> None:
        self.push_screen(SearchScreen(self.api, "Add a watch: search for a permit or campground"), self._picked)

    def _picked(self, result: SearchResult | None) -> None:
        if result:
            self.notify(f"Loading {result.name}…")
            self._load_and_form(result)

    @work(thread=True)
    def _load_and_form(self, result: SearchResult) -> None:
        try:
            if result.entity_type == "campground":
                kind, divisions = "campground", {}
            else:
                kind, divisions = self.api.permit_kind(result.entity_id), self.api.permit_divisions(result.entity_id)
        except (RecGovError, OSError) as e:
            self.call_from_thread(self.notify, str(e), severity="error")
            return
        self.call_from_thread(self.push_screen, WatchForm(result, kind, divisions), self._save_watch)

    def _save_watch(self, d: dict | None) -> None:
        if not d:
            return
        names = {w.get("name") for w in read_raw(self.config_path).get("watch", [])}
        if d["name"] in names:
            d["name"] += f" ({d['earliest']:%b %d})"
        self._edit(lambda raw: raw.setdefault("watch", []).append(d))
        self.notify(f"Watching {d['name']}. The watcher picks it up on its next cycle.")

    def action_add_reminder(self) -> None:
        self.push_screen(SearchScreen(self.api, "Add release/lottery reminders for a permit", permits_only=True),
                         self._save_reminder)

    def _save_reminder(self, result: SearchResult | None) -> None:
        if result:
            self._edit(lambda raw: raw.setdefault("reminder", []).append(
                {"name": result.name, "permit_id": result.entity_id}))
            self.query_one(TabbedContent).active = "tab-reminders"

    def action_toggle(self) -> None:
        if not self._on_watches_tab():
            return
        name = self._current_watch()
        if name:
            def flip(raw):
                for w in raw.get("watch", []):
                    if w.get("name") == name:
                        w["enabled"] = not w.get("enabled", True)
            self._edit(flip)

    def action_delete(self) -> None:
        if self._on_watches_tab():
            name = self._current_watch()
            if name:
                self._edit(lambda raw: raw.__setitem__("watch", [w for w in raw.get("watch", []) if w.get("name") != name]))
                self.notify(f"Deleted {name}")
        else:
            table = self.query_one("#reminders", DataTable)
            if table.row_count:
                pid = self.reminder_rows[table.cursor_row]
                self._edit(lambda raw: raw.__setitem__(
                    "reminder", [r for r in raw.get("reminder", []) if str(r.get("permit_id")) != pid]))

    def _current_watch(self) -> str | None:
        table = self.query_one("#watches", DataTable)
        if not table.row_count:
            return None
        return table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value
