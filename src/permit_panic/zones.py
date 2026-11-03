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


FETCH_ERRORS = (RecGovError, OSError, ValueError, KeyError)  # incl. a cut-off ~1 MB response


def build(api: RecGov, progress=None, previous: dict | None = None, retry_waits=(5, 20)) -> dict:
    """Fetch every permit's zone names. Each permit's details are ~1 MB, so over 134 of them a few
    requests can fail: those are retried, and any still failing keep their entry from `previous`
    (default: the bundled snapshot) rather than vanishing from search. Failures are listed in
    the result's "failed"."""
    previous = previous if previous is not None else load(BUNDLED) or {}
    listed = api.list_permits()
    permits: dict = {}
    errors: dict[str, str] = {}
    pending = listed
    for wait in (0, *retry_waits):
        if not pending:
            break
        time.sleep(wait)
        retry = []
        for pid, name in pending:
            try:
                content = api.permit_content(pid)
            except FETCH_ERRORS as e:
                retry.append((pid, name))
                errors[pid] = f"{name}: {str(e)[:120]}"
                continue
            errors.pop(pid, None)
            permits[pid] = {"name": content.get("name") or name,
                            "zones": {k: v.get("name", k) for k, v in (content.get("divisions") or {}).items()}}
            if progress:
                progress(len(permits), len(listed))
        pending = retry
    for pid in errors:
        if pid in previous.get("permits", {}):
            permits[pid] = previous["permits"][pid]
    return {"built": datetime.now(timezone.utc).isoformat(), "permits": permits, "failed": errors}


def load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def load_best(path: Path | None) -> dict | None:
    """The bundled snapshot with the watcher's fresher index laid over it, permit by permit, so a
    permit missing from the local copy still turns up from the snapshot."""
    bundled, local = load(BUNDLED), (load(path) if path else None)
    if not (local and local.get("permits")):
        return bundled
    if not bundled:
        return local
    return {"built": local["built"], "permits": {**bundled["permits"], **local["permits"]}}


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
            current = load(path)
            if stale(current):
                try:
                    index = build(api, previous=load_best(path))
                    save(path, index)
                    print(f"zone index rebuilt: {path} ({len(index['failed'])} permits failed)", flush=True)
                except FETCH_ERRORS as e:
                    print(f"zone index rebuild failed: {e}", flush=True)
            time.sleep(check_every)

    t = threading.Thread(target=loop, name="zone-index", daemon=True)
    t.start()
    return t
