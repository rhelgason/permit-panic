"""The config file: parsed for the watcher, and read/written raw for the TUI.

The watcher re-reads this file every cycle, so edits (by hand or from the TUI)
take effect without a restart.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import tomli_w

KINDS = ("itinerary", "entry", "campground")


@dataclass
class Watch:
    name: str
    kind: str  # itinerary | entry | campground
    entity_id: str
    earliest: date
    latest: date
    nights: list[list[str]] = field(default_factory=list)  # itinerary
    trailheads: list[str] = field(default_factory=list)  # entry
    group_size: int = 1  # entry, itinerary
    stay_nights: int = 1  # campground
    sites: list[str] = field(default_factory=list)  # campground
    enabled: bool = True

    @classmethod
    def from_dict(cls, d: dict) -> "Watch":
        kind = d["kind"]
        if kind not in KINDS:
            raise ValueError(f"{d.get('name')}: unknown kind {kind!r}")
        w = cls(
            name=d.get("name", kind),
            kind=kind,
            entity_id=str(d.get("permit_id") or d["campground_id"]),
            earliest=_as_date(d["earliest"]),
            latest=_as_date(d["latest"]),
            nights=[[str(x) for x in (n if isinstance(n, list) else [n])] for n in d.get("nights", [])]
            if kind == "itinerary" else [],
            trailheads=[str(t) for t in d.get("trailheads", [])],
            group_size=int(d.get("group_size", 1)),
            stay_nights=int(d.get("nights", 1)) if kind == "campground" else 1,
            sites=[str(s) for s in d.get("sites", [])],
            enabled=bool(d.get("enabled", True)),
        )
        if w.latest < w.earliest:
            raise ValueError(f"{w.name}: latest is before earliest")
        if kind == "itinerary" and not w.nights:
            raise ValueError(f"{w.name}: itinerary needs at least one night")
        if kind == "entry" and not w.trailheads:
            raise ValueError(f"{w.name}: entry needs at least one trailhead")
        return w


@dataclass
class Reminder:
    name: str
    permit_id: str
    ignore: list[str] = field(default_factory=list)  # mute dates whose description contains any of these


@dataclass
class Config:
    watches: list[Watch]
    reminders: list[Reminder]
    pushover_user: str | None = None  # your user key
    pushover_token: str | None = None  # the Permit Panic application's API token
    opening_sound: str | None = "bugle"  # any Pushover sound name; stands out from your other apps
    emergency_openings: bool = False  # openings keep ringing until acknowledged
    digest_hour: int | None = None  # local hour for a daily "still alive" summary
    healthcheck_url: str | None = None  # pinged every cycle; e.g. a free healthchecks.io check
    poll_minutes: float = 3.0
    state_file: Path = Path(".permit-panic-state.json")
    status_file: Path = Path(".permit-panic-status.json")


def _as_date(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def read_raw(path: str | Path) -> dict:
    p = Path(path)
    return tomllib.loads(p.read_text()) if p.exists() else {}


def write_raw(path: str | Path, raw: dict) -> None:
    parse(raw, Path(path))  # refuse to save something the watcher can't load
    p = Path(path)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(tomli_w.dumps(raw))
    tmp.replace(p)  # atomic, so the watcher never reads half a file


def parse(raw: dict, path: Path) -> Config:
    n = raw.get("notify", {})
    base = path.parent

    def rel(v: str) -> Path:
        return base / v  # state files live next to the config, wherever we're started from

    return Config(
        watches=[Watch.from_dict(w) for w in raw.get("watch", [])],
        reminders=[Reminder(r.get("name", str(r["permit_id"])), str(r["permit_id"]), [str(i) for i in r.get("ignore", [])])
                   for r in raw.get("reminder", [])],
        # Env vars win, so the keys can live in the systemd env file instead of the config.
        pushover_user=os.environ.get("PUSHOVER_USER") or n.get("pushover_user"),
        pushover_token=os.environ.get("PUSHOVER_TOKEN") or n.get("pushover_token"),
        opening_sound=n.get("opening_sound", "bugle") or None,
        emergency_openings=bool(n.get("emergency_openings", False)),
        digest_hour=int(n["digest_hour"]) if "digest_hour" in n else None,
        healthcheck_url=n.get("healthcheck_url"),
        poll_minutes=float(raw.get("poll_minutes", 3)),
        state_file=rel(raw.get("state_file", ".permit-panic-state.json")),
        status_file=rel(raw.get("status_file", ".permit-panic-status.json")),
    )


def load_config(path: str | Path) -> Config:
    return parse(read_raw(path), Path(path))
