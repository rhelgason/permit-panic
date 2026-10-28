"""Read-only client for Recreation.gov's public availability endpoints.

These are the same JSON endpoints the website's calendar pages call. They are
undocumented, so shapes may change; every parser here is deliberately small so
it is easy to fix when they do.

Three availability shapes exist:

* itinerary  - zone/campsite permits where you pick a site per night
               (Grand Teton, Glacier, Yellowstone backcountry, ...)
* entry      - trailhead entry quotas keyed by entry date
               (Inyo, Yosemite, Sierra wilderness, ...); the site calls these "permitinyo"
* campground - ordinary reservable campgrounds
"""

from __future__ import annotations

import calendar
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date

BASE = "https://www.recreation.gov"
USER_AGENT = "permit-panic/0.1 (personal availability watcher)"


class RecGovError(RuntimeError):
    pass


@dataclass(frozen=True)
class SearchResult:
    entity_type: str
    entity_id: str
    name: str
    parent: str


class RecGov:
    def __init__(self, min_interval: float = 1.0, timeout: float = 20.0):
        # min_interval spaces out consecutive requests so we stay a polite client.
        self.min_interval = min_interval
        self.timeout = timeout
        self._last = 0.0

    def _get(self, path: str, params: dict | None = None) -> dict:
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        url = BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:200]
            raise RecGovError(f"{e.code} from {url}: {body}") from e
        finally:
            self._last = time.monotonic()

    # --- discovery -------------------------------------------------------

    def search(self, query: str, size: int = 10) -> list[SearchResult]:
        data = self._get("/api/search", {"q": query, "size": size})
        return [
            SearchResult(
                entity_type=r.get("entity_type", ""),
                entity_id=str(r.get("entity_id", "")),
                name=r.get("name", ""),
                parent=r.get("parent_name", ""),
            )
            for r in data.get("results", [])
        ]

    def permit_divisions(self, permit_id: str) -> dict[str, str]:
        """Map division id -> name (camp zones, sites, or trailheads)."""
        payload = self._get(f"/api/permitcontent/{permit_id}")["payload"]
        return {k: v.get("name", k) for k, v in (payload.get("divisions") or {}).items()}

    # --- availability ----------------------------------------------------

    def itinerary_month(self, permit_id: str, division_id: str, year: int, month: int) -> dict[date, bool]:
        payload = self._get(
            f"/api/permititinerary/{permit_id}/division/{division_id}/availability/month",
            {"month": month, "year": year},
        )["payload"]
        return parse_itinerary(payload)

    def entry_month(self, permit_id: str, year: int, month: int) -> dict[date, dict[str, int]]:
        # This endpoint only accepts exact first/last-of-month bounds.
        start = date(year, month, 1)
        end = date(year, month, calendar.monthrange(year, month)[1])
        payload = self._get(
            f"/api/permitinyo/{permit_id}/availabilityv2",
            {"start_date": start.isoformat(), "end_date": end.isoformat(), "commercial_acct": "false"},
        )["payload"]
        return parse_entry(payload)

    def campground_month(self, campground_id: str, year: int, month: int) -> dict[str, dict[date, bool]]:
        data = self._get(
            f"/api/camps/availability/campground/{campground_id}/month",
            {"start_date": f"{year:04d}-{month:02d}-01T00:00:00.000Z"},
        )
        return parse_campground(data)


# --- parsers (pure; covered by tests) -------------------------------------


def parse_itinerary(payload: dict) -> dict[date, bool]:
    return {date.fromisoformat(d): bool(v) for d, v in (payload.get("bools") or {}).items()}


def parse_entry(payload: dict) -> dict[date, dict[str, int]]:
    """date -> {division_id: remaining spots}."""
    out: dict[date, dict[str, int]] = {}
    for d, divisions in payload.items():
        day = out.setdefault(date.fromisoformat(d[:10]), {})
        for div_id, info in divisions.items():
            if info.get("is_walkup"):
                continue
            day[div_id] = int((info.get("quota_usage_by_member_daily") or {}).get("remaining", 0))
    return out


def parse_campground(data: dict) -> dict[str, dict[date, bool]]:
    """site label -> {date: available}."""
    out: dict[str, dict[date, bool]] = {}
    for site in (data.get("campsites") or {}).values():
        label = f"{site.get('loop', '')} {site.get('site', site.get('campsite_id'))}".strip()
        out[label] = {
            date.fromisoformat(ts[:10]): status == "Available"
            for ts, status in (site.get("availabilities") or {}).items()
        }
    return out


def booking_url(kind: str, entity_id: str) -> str:
    if kind == "campground":
        return f"{BASE}/camping/campgrounds/{entity_id}"
    return f"{BASE}/permits/{entity_id}"
