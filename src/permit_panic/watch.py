"""The polling loop: availability watches, reminders, and every phone notification.

Notifications, loudest first:
  urgent   Open: <watch>            a new opening (with a Book now button)
  high     Reminder in 30 min       a release / lottery date is about to start
  default  Reminder tomorrow        ... 24 hours ahead
  default  Watch broken / fixed     a watch kept failing for ERROR_GRACE, or recovered
  low      Now watching / Updated   the watcher loaded a watch you added or edited, and its first result
  low      Stopped / Paused / Ended removed, paused, or its date window has passed
  min      Daily summary            optional heartbeat at [notify] digest_hour
"""

from __future__ import annotations

import hashlib
import json
import random
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import notify
from .config import Config, Watch, load_config, read_raw
from .matching import Match, summarize, match_campground, match_entry, match_itinerary, months_between, resolve_divisions
from .recgov import RecGov, RecGovError, booking_url
from .reminders import Event, describe_lead, due_alerts, parse_events, visible

CONTENT_TTL = 6 * 3600  # permit metadata (zone names, important dates) rarely changes
ERROR_GRACE = timedelta(minutes=30)  # don't page for a blip; Recreation.gov hiccups often


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
            itin.setdefault(div, {}).update(api.itinerary_month(w.entity_id, div, y, m, w.group_size))
    return match_itinerary(per_night, itin, w.earliest, w.latest, names)


def fingerprint(raw_watch: dict) -> str:
    """Changes whenever the watch's settings change (ignoring on/off, which is reported separately)."""
    body = {k: v for k, v in raw_watch.items() if k != "enabled"}
    return hashlib.sha1(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:12]


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


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
                        ntfy_token=cfg.ntfy_token, icon_url=cfg.icon_url, **kw)
        except OSError as e:
            print(f"notify failed: {e}", flush=True)

    def cycle(self, now: datetime | None = None) -> Config:
        now = now or datetime.now(timezone.utc)
        local_now = now.astimezone()
        raw = read_raw(self.config_path)
        cfg = load_config(self.config_path)  # re-read so TUI edits apply without a restart
        raw_by_name = {w.get("name"): w for w in raw.get("watch", [])}
        state = json.loads(cfg.state_file.read_text()) if cfg.state_file.exists() else {}
        first_run = not state
        seen: dict[str, list[str]] = state.get("openings", {})
        sent: set[str] = set(state.get("reminders_sent", []))
        known: dict[str, dict] = state.get("watches", {})  # name -> {fp, enabled, expired}
        errors: dict[str, dict] = state.get("errors", {})  # name -> {since, alerted}
        known_reminders: list[str] = state.get("reminder_ids", [])
        status: dict = {"watches": {}, "reminders": []}
        stamp = local_now.strftime("%H:%M:%S")
        low = {"priority": "low", "tags": "white_check_mark"}

        for w in cfg.watches:
            fp = fingerprint(raw_by_name.get(w.name, {}))
            prev = known.get(w.name)
            expired = w.latest < local_now.date()
            if expired:
                status["watches"][w.name] = {"expired": True}
                if prev and not prev.get("expired") and not first_run:
                    self._send(cfg, f"Ended: {w.name}", f"Its last date ({w.latest:%b %d}) has passed, so it's no "
                               "longer checked. Delete or edit it in the dashboard.", priority="low", tags="hourglass")
                known[w.name] = {"fp": fp, "enabled": w.enabled, "expired": True}
                continue
            if not w.enabled:
                status["watches"][w.name] = {"disabled": True}
                if prev and prev.get("enabled", True) and not first_run:
                    self._send(cfg, f"Paused: {w.name}", "No longer checking until you resume it.", **low)
                known[w.name] = {"fp": fp, "enabled": False}
                continue

            try:
                names = {} if w.kind == "campground" else self.names(w.entity_id)
                matches = check(self.api, w, names)
            except (RecGovError, OSError, ValueError, KeyError) as e:
                print(f"[{stamp}] {w.name}: error: {e}", flush=True)
                status["watches"][w.name] = {"error": str(e), "checked": local_now.isoformat()}
                err = errors.setdefault(w.name, {"since": now.isoformat(), "alerted": False})
                is_new_or_changed = not prev or prev.get("fp") != fp
                if is_new_or_changed and not first_run:
                    # A watch you just saved that can't run should tell you right away, not in 30 min.
                    self._send(cfg, f"Problem with {w.name}", f"Saved, but the first check failed:\n{e}\nPress e on it in the dashboard to fix.",
                               priority="default", tags="warning")
                    err["alerted"] = True
                elif not err["alerted"] and now - datetime.fromisoformat(err["since"]) >= ERROR_GRACE:
                    self._send(cfg, f"Watch broken: {w.name}", f"Failing since {err['since'][11:16]} UTC:\n{e}",
                               priority="default", tags="warning")
                    err["alerted"] = True
                known[w.name] = {"fp": fp, "enabled": True}
                continue

            if w.name in errors and errors.pop(w.name)["alerted"]:
                self._send(cfg, f"Fixed: {w.name}", "Checking normally again.", **low)

            if not first_run:
                if not prev:
                    self._send(cfg, f"Now watching: {w.name}", self._describe(w, len(matches)), **low)
                elif prev.get("fp") != fp:
                    seen.pop(w.name, None)  # new criteria: re-alert on everything that matches them
                    self._send(cfg, f"Updated: {w.name}", self._describe(w, len(matches)), **low)
                elif not prev.get("enabled", True):
                    self._send(cfg, f"Resumed: {w.name}", self._describe(w, len(matches)), **low)
            known[w.name] = {"fp": fp, "enabled": True}

            prev_open = set(seen.get(w.name, []))
            new = [m for m in matches if m.key not in prev_open]
            # Only remember what is open now, so a site that closes and reopens alerts again.
            seen[w.name] = [m.key for m in matches]
            status["watches"][w.name] = {"open": [m.summary for m in matches], "checked": local_now.isoformat()}
            print(f"[{stamp}] {w.name}: {len(matches)} open, {len(new)} new", flush=True)
            if new:
                lead = "Start " if w.kind == "itinerary" else ""
                self._send(cfg, f"Open: {w.name}", lead + summarize(new), click_url=booking_url(w.kind, w.entity_id),
                           action="Book now")

        current = {w.name for w in cfg.watches}
        for gone in [n for n in known if n not in current]:
            known.pop(gone)
            seen.pop(gone, None)
            errors.pop(gone, None)
            self._send(cfg, f"Stopped watching: {gone}", "Removed from your config.", **low)

        events = self._reminders(cfg, now, sent, known_reminders, first_run, stamp)
        status["reminders"] = [
            {"permit": e.permit_name, "when": e.when.isoformat(), "description": e.description,
             "time_known": e.time_known}
            for e in events if e.when > now
        ]
        if first_run and (cfg.watches or cfg.reminders):
            self._send(cfg, "Permit Panic is running",
                       f"{_plural(len(cfg.watches), 'watch')}, {_plural(len(cfg.reminders), 'reminder permit')}. "
                       "You'll get a quiet ping like this whenever you add or change one.", **low)

        last_digest = state.get("last_digest")
        if cfg.digest_hour is not None and local_now.hour == cfg.digest_hour \
                and last_digest != local_now.date().isoformat():
            self._send(cfg, "Permit Panic daily summary", self._digest(cfg, status, now),
                       priority="min", tags="sunrise")
            last_digest = local_now.date().isoformat()

        status["updated"] = local_now.isoformat()
        cfg.state_file.write_text(json.dumps({
            "openings": seen, "reminders_sent": sorted(sent), "watches": known, "errors": errors,
            "reminder_ids": [r.permit_id for r in cfg.reminders], "last_digest": last_digest,
        }, indent=1))
        cfg.status_file.write_text(json.dumps(status, indent=1))
        if cfg.healthcheck_url:
            try:  # dead-man's switch: the check service alerts you if these pings stop
                urllib.request.urlopen(cfg.healthcheck_url, timeout=10).close()
            except OSError as e:
                print(f"healthcheck ping failed: {e}", flush=True)
        return cfg

    def _reminders(self, cfg, now, sent, known_ids, first_run, stamp) -> list[Event]:
        events: list[Event] = []
        for r in cfg.reminders:
            try:
                mine = visible(parse_events(r.permit_id, self.content(r.permit_id)), r.ignore)
            except (RecGovError, OSError, KeyError) as e:
                print(f"[{stamp}] reminder {r.name}: error: {e}", flush=True)
                continue
            events += mine
            if r.permit_id not in known_ids and not first_run:
                upcoming = [e for e in mine if e.when > now]
                nxt = (f"Next: {upcoming[0].description[:120]}\n{upcoming[0].when:%a %b %d %-I:%M %p %Z}"
                       if upcoming else "No upcoming dates posted yet; checking again every few hours.")
                self._send(cfg, f"Reminders on: {r.name}", nxt, priority="low", tags="white_check_mark")
        for key, e, lead in due_alerts(events, now, sent):
            local = e.when.strftime("%a %b %d %-I:%M %p %Z") + ("" if e.time_known else " (time not listed)")
            soon = lead < timedelta(hours=12)
            self._send(cfg, f"{describe_lead(lead).capitalize()}: {e.permit_name}", f"{e.description}\n{local}",
                       click_url=booking_url("permit", e.permit_id),
                       priority="high" if soon else "default", tags="alarm_clock")
            sent.add(key)
        return events

    @staticmethod
    def _describe(w: Watch, n_open: int) -> str:
        what = {"itinerary": f"{_plural(len(w.nights), 'night')} route", "entry": f"{len(w.trailheads)} trailhead(s)",
                "campground": f"{w.stay_nights}-night stay"}[w.kind]
        found = f"{n_open} open right now, alert coming." if n_open else "Nothing open yet. I'll ping you when there is."
        return f"{what}, {w.earliest:%b %d} - {w.latest:%b %d %Y}, group of {w.group_size}.\nFirst check worked: {found}"

    @staticmethod
    def _digest(cfg: Config, status: dict, now: datetime) -> str:
        lines = []
        for name, s in status["watches"].items():
            if "error" in s:
                lines.append(f"! {name}: failing")
            elif "open" in s:
                lines.append(f"- {name}: {len(s['open'])} open")
            else:
                lines.append(f"- {name}: {'ended' if s.get('expired') else 'paused'}")
        week = [r for r in status["reminders"] if datetime.fromisoformat(r["when"]) < now + timedelta(days=7)]
        if week:
            lines.append("This week:")
            lines += [f"  {datetime.fromisoformat(r['when']):%a %-I:%M %p} {r['permit'][:40]}" for r in week[:6]]
        return "\n".join(lines) or "Nothing configured."

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
            # Jitter keeps us from hammering on a fixed beat; a config edit cuts the wait short
            # so the "Now watching" confirmation arrives within seconds of saving.
            deadline = time.monotonic() + minutes * 60 * random.uniform(0.8, 1.2)
            mtime = self._mtime()
            while time.monotonic() < deadline:
                time.sleep(3)
                if self._mtime() != mtime:
                    break

    def _mtime(self) -> float:
        try:
            return self.config_path.stat().st_mtime
        except OSError:
            return 0.0
