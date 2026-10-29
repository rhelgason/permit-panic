"""Release-date and lottery reminders, built from a permit's "important dates".

Recreation.gov publishes these per permit, e.g.
  {"description": "Lottery opens at 7:00 a.m. PT", "start_date": "February 15, 2026", "end_date": ""}
The date is structured; the time only appears in the text, so we pull it out
with a regex and fall back to 9am in the permit's time zone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

LEADS = (timedelta(hours=24), timedelta(minutes=30))
_TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m\b\.?", re.I)
_WINDOW = re.compile(r"lottery|appl", re.I)


@dataclass(frozen=True)
class Event:
    permit_id: str
    permit_name: str
    when: datetime
    description: str
    time_known: bool

    @property
    def key(self) -> str:
        return f"{self.permit_id}|{self.when.isoformat()}|{self.description[:40]}"


def _parse_time(text: str) -> tuple[int, int] | None:
    m = _TIME.search(text)
    if not m:
        return None
    hour = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "p" else 0)
    return hour, int(m.group(2) or 0)


def parse_events(permit_id: str, payload: dict) -> list[Event]:
    tz = ZoneInfo(payload.get("time_zone") or "America/Denver")
    name = payload.get("name", permit_id)
    events = []
    for item in payload.get("important_dates") or []:
        desc = " ".join((item.get("description") or "").split())
        hm = _parse_time(desc)
        h, m = hm or (9, 0)
        starts = [(item.get("start_date"), desc)]
        # Application windows ("lottery open Jan 1 - Jan 31") also deserve a closing reminder.
        if item.get("end_date") and _WINDOW.search(desc):
            starts.append((item["end_date"], f"CLOSES: {desc}"))
        for raw, text in starts:
            try:
                day = datetime.strptime(raw.strip(), "%B %d, %Y")
            except (AttributeError, ValueError):
                continue
            # A closing day without its own time is safest to treat as end-of-day minus a margin.
            if text.startswith("CLOSES") and not hm:
                when = day.replace(hour=17, tzinfo=tz)
            else:
                when = day.replace(hour=h, minute=m, tzinfo=tz)
            events.append(Event(permit_id, name, when, text, hm is not None))
    return sorted(events, key=lambda e: e.when)


def due_alerts(events: list[Event], now: datetime, sent: set[str]) -> list[tuple[str, Event, timedelta]]:
    """(key, event, lead) for each reminder whose send time has passed but whose event hasn't."""
    out = []
    for e in events:
        for lead in LEADS:
            key = f"{e.key}|{int(lead.total_seconds())}"
            if key not in sent and e.when - lead <= now < e.when:
                out.append((key, e, lead))
    return out


def describe_lead(lead: timedelta) -> str:
    return "tomorrow" if lead >= timedelta(hours=12) else f"in {int(lead.total_seconds() // 60)} min"
