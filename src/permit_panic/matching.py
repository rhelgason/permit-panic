"""Turn raw availability into concrete, bookable options.

All functions here are pure so they can be tested without the network.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class Match:
    key: str  # stable id used to avoid re-alerting on the same opening
    day: date  # entry / first night
    detail: str  # what is open that day

    @property
    def summary(self) -> str:
        return f"{self.day:%a %b %d}: {self.detail}"


def summarize(matches: list[Match], limit: int = 12) -> str:
    """Phone-sized text: the same option on consecutive days collapses to one line.

    "Dec 01-15, Dec 17: La Verkin Creek 2 -> Hop Valley A" instead of 16 lines.
    """
    by_detail: dict[str, list[date]] = {}
    for m in matches:
        by_detail.setdefault(m.detail, []).append(m.day)
    lines = []
    for detail, days in by_detail.items():
        days = sorted(set(days))
        spans, start = [], days[0]
        for prev, cur in zip(days, days[1:] + [None]):
            if cur is None or cur - prev > timedelta(days=1):
                spans.append(f"{start:%b %d}" if start == prev else f"{start:%b %d}-{prev:%d}"
                             if start.month == prev.month else f"{start:%b %d}-{prev:%b %d}")
                start = cur
        lines.append(f"{', '.join(spans)}: {detail}")
    if len(lines) > limit:
        lines = lines[:limit] + [f"...and {len(lines) - limit} more options"]
    return "\n".join(lines)


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def months_between(start: date, end: date) -> list[tuple[int, int]]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def resolve_divisions(patterns: list[str], divisions: dict[str, str]) -> list[str]:
    """Resolve ids or case-insensitive name fragments to division ids, preserving order."""
    ids: list[str] = []
    for pat in patterns:
        exact = [k for k, name in divisions.items() if name.lower() == pat.lower()]
        if pat in divisions:
            found = [pat]
        elif exact:
            found = exact  # "La Verkin Creek 1" must not also pick up "La Verkin Creek 11"
        else:
            found = [k for k, name in divisions.items() if pat.lower() in name.lower()]
        if not found:
            raise ValueError(f"no division matches {pat!r}")
        ids.extend(f for f in found if f not in ids)
    return ids


def match_itinerary(
    nights: list[list[str]],
    avail: dict[str, dict[date, bool]],
    earliest: date,
    latest: date,
    names: dict[str, str],
) -> list[Match]:
    """Find start dates where night i can be spent at one of nights[i]'s divisions.

    This is the multi-night route check that single-site alert services skip:
    an opening at Alaska Basin is useless unless Death Canyon Shelf is open the
    night before.
    """
    matches = []
    last_start = latest - timedelta(days=len(nights) - 1)
    for start in daterange(earliest, last_start):
        plan = []
        for i, options in enumerate(nights):
            day = start + timedelta(days=i)
            open_here = [d for d in options if avail.get(d, {}).get(day)]
            if not open_here:
                break
            plan.append(open_here)
        else:
            route = " -> ".join(" / ".join(names.get(d, d) for d in opts) for opts in plan)
            key = f"{start.isoformat()}|" + ";".join(",".join(opts) for opts in plan)
            matches.append(Match(key, start, route))
    return matches


def match_entry(
    avail: dict[date, dict[str, int]],
    division_ids: list[str],
    group_size: int,
    earliest: date,
    latest: date,
    names: dict[str, str],
) -> list[Match]:
    matches = []
    for day in daterange(earliest, latest):
        for div in division_ids:
            remaining = avail.get(day, {}).get(div, 0)
            if remaining >= group_size:
                # Recreation.gov reports 900000 for days with no quota (off-season, often no permit needed).
                note = " (no quota)" if remaining >= 100_000 else ""
                matches.append(Match(f"{day.isoformat()}|{div}", day, f"{names.get(div, div)}{note}"))
    return matches


def match_campground(
    sites: dict[str, dict[date, bool]],
    nights: int,
    earliest: date,
    latest: date,
    site_filter: list[str] | None = None,
) -> list[Match]:
    matches = []
    last_start = latest - timedelta(days=nights - 1)
    for label, days in sites.items():
        if site_filter and not any(f.lower() in label.lower() for f in site_filter):
            continue
        for start in daterange(earliest, last_start):
            if all(days.get(start + timedelta(days=i)) for i in range(nights)):
                matches.append(Match(f"{start.isoformat()}|{label}", start, f"site {label}, {nights} nights"))
    return matches
