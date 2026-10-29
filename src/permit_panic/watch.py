"""The polling loop: availability watches plus release/lottery reminders."""

from __future__ import annotations

import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from . import notify
from .config import Config, Watch, load_config
from .matching import Match, match_campground, match_entry, match_itinerary, months_between, resolve_divisions
from .recgov import RecGov, RecGovError, booking_url
from .reminders import Event, describe_lead, due_alerts, parse_events

CONTENT_TTL = 6 * 3600  # permit metadata (zone names, important dates) rarely changes


def check(api: RecGov, w: Watch, names: dict[str, str]) -> list[Match]:
    months = months_between(w.earliest, w.latest)
    if w.kind == "campground":
        sites: dict = {}
        for y, m in months:
            for label, days in api.campground_month(w.entity_id, y, m).items():
                sites.setdefault(label, {}).update(days)
        return match_campground(sites, w.stay_nights, w.earliest, w.latest, w.sites or None)

    if w.kind == "entry":
        ids = resolve_divisions(w.trailheads, names)
        avail: dict = {}
        for y, m in months:
            avail.update(api.entry_month(w.entity_id, y, m))
        return match_entry(avail, ids, w.group_size, w.earliest, w.latest, names)

    per_night = [resolve_divisions(opts, names) for opts in w.nights]
    itin: dict = {}
    for div in {d for opts in per_night for d in opts}:
        for y, m in months:
            itin.setdefault(div, {}).update(api.itinerary_month(w.entity_id, div, y, m))
    return match_itinerary(per_night, itin, w.earliest, w.latest, names)


class Watcher:
    def __init__(self, config_path: str | Path, api: RecGov | None = None):
        self.config_path = Path(config_path)
        self.api = api or RecGov()
        self._content: dict[str, tuple[float, dict]] = {}

    def content(self, permit_id: str) -> dict:
        hit = self._content.get(permit_id)
        if not hit or time.monotonic() - hit[0] > CONTENT_TTL:
            hit = (time.monotonic(), self.api.permit_content(permit_id))
            self._content[permit_id] = hit
        return hit[1]

    def names(self, permit_id: str) -> dict[str, str]:
        return {k: v.get("name", k) for k, v in (self.content(permit_id).get("divisions") or {}).items()}

    def _send(self, cfg: Config, title: str, body: str, **kw) -> None:
        try:
            notify.send(title, body, ntfy_topic=cfg.ntfy_topic, ntfy_server=cfg.ntfy_server,
                        ntfy_token=cfg.ntfy_token, **kw)
        except OSError as e:
            print(f"notify failed: {e}", flush=True)

    def cycle(self) -> Config:
        cfg = load_config(self.config_path)  # re-read so TUI edits apply without a restart
        state = json.loads(cfg.state_file.read_text()) if cfg.state_file.exists() else {}
        seen: dict[str, list[str]] = state.get("openings", {})
        sent: set[str] = set(state.get("reminders_sent", []))
        status: dict = {"watches": {}, "reminders": []}
        stamp = lambda: datetime.now().strftime("%H:%M:%S")  # noqa: E731

        for w in cfg.watches:
            if not w.enabled:
                status["watches"][w.name] = {"disabled": True}
                continue
            try:
                names = {} if w.kind == "campground" else self.names(w.entity_id)
                matches = check(self.api, w, names)
            except (RecGovError, OSError, ValueError, KeyError) as e:
                print(f"[{stamp()}] {w.name}: error: {e}", flush=True)
                status["watches"][w.name] = {"error": str(e), "checked": datetime.now().isoformat()}
                continue
            prev = set(seen.get(w.name, []))
            new = [m for m in matches if m.key not in prev]
            # Only remember what is open now, so a site that closes and reopens alerts again.
            seen[w.name] = [m.key for m in matches]
            status["watches"][w.name] = {"open": [m.summary for m in matches], "checked": datetime.now().isoformat()}
            print(f"[{stamp()}] {w.name}: {len(matches)} open, {len(new)} new", flush=True)
            if new:
                body = "\n".join(m.summary for m in new[:15])
                if len(new) > 15:
                    body += f"\n...and {len(new) - 15} more"
                self._send(cfg, f"Open: {w.name}", body, click_url=booking_url(w.kind, w.entity_id))

        now = datetime.now(timezone.utc)
        events: list[Event] = []
        for r in cfg.reminders:
            try:
                events += parse_events(r.permit_id, self.content(r.permit_id))
            except (RecGovError, OSError, KeyError) as e:
                print(f"[{stamp()}] reminder {r.name}: error: {e}", flush=True)
        for key, e, lead in due_alerts(events, now, sent):
            local = e.when.strftime("%a %b %d %-I:%M %p %Z") + ("" if e.time_known else " (time not listed)")
            self._send(cfg, f"{describe_lead(lead).capitalize()}: {e.permit_name}", f"{e.description}\n{local}",
                       click_url=booking_url("permit", e.permit_id), priority="high", tags="alarm_clock")
            sent.add(key)
        status["reminders"] = [
            {"permit": e.permit_name, "when": e.when.isoformat(), "description": e.description,
             "time_known": e.time_known}
            for e in events if e.when > now
        ]
        status["updated"] = datetime.now().isoformat()

        cfg.state_file.write_text(json.dumps({"openings": seen, "reminders_sent": sorted(sent)}, indent=1))
        cfg.status_file.write_text(json.dumps(status, indent=1))
        return cfg

    def run(self, once: bool = False) -> None:
        while True:
            try:
                cfg = self.cycle()
                minutes = cfg.poll_minutes
            except (ValueError, KeyError, OSError) as e:  # e.g. a hand-edit broke the config
                print(f"config error: {e}", flush=True)
                minutes = 1
            if once:
                return
            # Jitter keeps us from hammering on a fixed beat.
            time.sleep(minutes * 60 * random.uniform(0.8, 1.2))
