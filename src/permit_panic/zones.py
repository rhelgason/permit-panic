"""Search camp zones and trailheads inside permits, not just permit names.

Recreation.gov's search only knows listing names, so "camp muir" finds nothing:
Camp Muir is a zone inside "Mount Rainier National Park Wilderness and Climbing
Permits". We keep a small index of every permit's zone names (134 permits,
rebuilt weekly by the watcher) and search that alongside the site's search.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .recgov import RecGov, RecGovError, SearchResult

TTL = timedelta(days=7)
# A snapshot shipped with the app, so zone search works before the watcher has built its own copy
# (or on a machine with no watcher at all). Refresh it with: permit-panic index && cp .permit-panic-zones.json
# src/permit_panic/data/zones.json
BUNDLED = Path(__file__).parent / "data" / "zones.json"


def build(api: RecGov, progress=None) -> dict:
    permits = {}
    listed = api.list_permits()
    for i, (pid, name) in enumerate(listed, 1):
        try:
            content = api.permit_content(pid)
        except (RecGovError, OSError):
            continue  # a broken listing shouldn't sink the whole index
        zones = {k: v.get("name", k) for k, v in (content.get("divisions") or {}).items()}
        permits[pid] = {"name": content.get("name") or name, "zones": zones}
        if progress:
            progress(i, len(listed))
    return {"built": datetime.now(timezone.utc).isoformat(), "permits": permits}


def load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def load_best(path: Path | None) -> dict | None:
    """The watcher's fresh index if there is one, else the bundled snapshot."""
    index = load(path) if path else None
    return index if index and index.get("permits") else load(BUNDLED)


def describe(index: dict | None) -> str:
    if not index:
        return "Camp/trailhead search unavailable"
    n = sum(len(p["zones"]) for p in index.get("permits", {}).values())
    return f"Searching {n:,} camps/trailheads too (list from {index['built'][:10]})"


def save(path: Path, index: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(index))
    tmp.replace(path)


def stale(index: dict | None, now: datetime | None = None) -> bool:
    if not index or not index.get("permits"):
        return True
    now = now or datetime.now(timezone.utc)
    return now - datetime.fromisoformat(index["built"]) > TTL


def search(index: dict | None, query: str, limit: int = 15) -> list[SearchResult]:
    """Zones whose name holds every word of the query (words may also come from the permit's name,
    so "rainier muir" works), best matches first."""
    words = query.lower().split()
    if not index or not words:
        return []
    scored = []
    for pid, p in index.get("permits", {}).items():
        pname = p["name"].lower()
        for div, zname in p["zones"].items():
            z = zname.lower()
            in_zone = [w for w in words if w in z]
            if not in_zone or any(w not in z and w not in pname for w in words):
                continue
            score = (len(in_zone) == len(words), z.startswith(query.lower()), len(in_zone), -len(z))
            scored.append((score, SearchResult("zone", pid, zname, p["name"], division_id=div)))
    scored.sort(key=lambda s: s[0], reverse=True)
    return [r for _, r in scored[:limit]]


def keep_fresh(path: Path, check_every: float = 3600) -> threading.Thread:
    """Background refresher for the watcher: rebuilds the index when it's missing or a week old.

    Uses its own client so the slow rebuild never delays an availability check.
    """

    def loop():
        api = RecGov(min_interval=1.5)
        while True:
            if stale(load(path)):
                try:
                    save(path, build(api))
                    print(f"zone index rebuilt: {path}", flush=True)
                except (RecGovError, OSError) as e:
                    print(f"zone index rebuild failed: {e}", flush=True)
            time.sleep(check_every)

    t = threading.Thread(target=loop, name="zone-index", daemon=True)
    t.start()
    return t
