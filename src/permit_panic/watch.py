"""Config loading and the polling loop."""

from __future__ import annotations

import json
import random
import time
import tomllib
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from . import notify
from .matching import Match, match_campground, match_entry, match_itinerary, months_between, resolve_divisions
from .recgov import RecGov, RecGovError, booking_url


@dataclass
class Watch:
    name: str
    kind: str  # itinerary | entry | campground
    entity_id: str
    earliest: date
    latest: date
    nights: list[list[str]] = field(default_factory=list)  # itinerary
    trailheads: list[str] = field(default_factory=list)  # entry
    group_size: int = 1  # entry
    stay_nights: int = 1  # campground
    sites: list[str] = field(default_factory=list)  # campground

    @classmethod
    def from_dict(cls, d: dict) -> "Watch":
        kind = d["kind"]
        if kind not in ("itinerary", "entry", "campground"):
            raise ValueError(f"{d.get('name')}: unknown kind {kind!r}")
        return cls(
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
        )


@dataclass
class Config:
    watches: list[Watch]
    ntfy_topic: str | None = None
    ntfy_server: str = "https://ntfy.sh"
    poll_minutes: float = 3.0
    state_file: Path = Path(".permit-panic-state.json")


def _as_date(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def load_config(path: str | Path) -> Config:
    raw = tomllib.loads(Path(path).read_text())
    n = raw.get("notify", {})
    return Config(
        watches=[Watch.from_dict(w) for w in raw.get("watch", [])],
        ntfy_topic=n.get("ntfy_topic"),
        ntfy_server=n.get("ntfy_server", "https://ntfy.sh"),
        poll_minutes=float(raw.get("poll_minutes", 3)),
        state_file=Path(raw.get("state_file", ".permit-panic-state.json")),
    )


def check(api: RecGov, w: Watch, names_cache: dict[str, dict[str, str]]) -> list[Match]:
    months = months_between(w.earliest, w.latest)
    if w.kind == "campground":
        sites: dict = {}
        for y, m in months:
            for label, days in api.campground_month(w.entity_id, y, m).items():
                sites.setdefault(label, {}).update(days)
        return match_campground(sites, w.stay_nights, w.earliest, w.latest, w.sites or None)

    if w.entity_id not in names_cache:
        names_cache[w.entity_id] = api.permit_divisions(w.entity_id)
    names = names_cache[w.entity_id]

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


def run(cfg: Config, once: bool = False) -> None:
    api = RecGov()
    names_cache: dict[str, dict[str, str]] = {}
    seen: dict[str, list[str]] = json.loads(cfg.state_file.read_text()) if cfg.state_file.exists() else {}
    while True:
        for w in cfg.watches:
            try:
                matches = check(api, w, names_cache)
            except (RecGovError, OSError, ValueError) as e:
                print(f"[{datetime.now():%H:%M:%S}] {w.name}: error: {e}", flush=True)
                continue
            prev = set(seen.get(w.name, []))
            new = [m for m in matches if m.key not in prev]
            # Only remember what is open now, so a site that closes and reopens alerts again.
            seen[w.name] = [m.key for m in matches]
            print(f"[{datetime.now():%H:%M:%S}] {w.name}: {len(matches)} open, {len(new)} new", flush=True)
            if new:
                body = "\n".join(m.summary for m in new[:15])
                if len(new) > 15:
                    body += f"\n...and {len(new) - 15} more"
                notify.send(f"Permit Panic: {w.name}", body, ntfy_topic=cfg.ntfy_topic,
                            ntfy_server=cfg.ntfy_server, click_url=booking_url(w.kind, w.entity_id))
        cfg.state_file.write_text(json.dumps(seen, indent=1))
        if once:
            return
        # Jitter keeps us from hammering on a fixed beat.
        time.sleep(cfg.poll_minutes * 60 * random.uniform(0.8, 1.2))
