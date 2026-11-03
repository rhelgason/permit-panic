"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from . import notify, zones
from .config import load_config, read_raw, write_raw
from .recgov import RecGov
from .reminders import parse_events
from .watch import Watcher

DEFAULT_CONFIG = "config.toml"
NOTIFY_KEYS = ("pushover_user", "pushover_token", "opening_sound", "emergency_openings", "digest_hour",
               "healthcheck_url")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="permit-panic", description="Watch Recreation.gov for permits.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="find permit / campground / camp zone ids")
    s.add_argument("query", nargs="+")
    s.add_argument("--config", default=DEFAULT_CONFIG)

    ix = sub.add_parser("index", help="rebuild the camp zone / trailhead search index now (the watcher does it weekly)")
    ix.add_argument("--config", default=DEFAULT_CONFIG)

    d = sub.add_parser("divisions", help="list the zones, sites or trailheads in a permit")
    d.add_argument("permit_id")
    d.add_argument("--filter", default="")

    dt = sub.add_parser("dates", help="show a permit's release / lottery dates")
    dt.add_argument("permit_id")

    for name, help_ in (
        ("tui", "open the dashboard"),
        ("check", "run every watch once"),
        ("watch", "poll forever and alert on new openings and upcoming release dates"),
        ("test-notify", "send a test alert to your phone"),
    ):
        p = sub.add_parser(name, help=help_)
        p.add_argument("config", nargs="?", default=DEFAULT_CONFIG)

    st = sub.add_parser("set", help="set a [notify] option, e.g. `set healthcheck_url https://...`")
    st.add_argument("key", choices=NOTIFY_KEYS)
    st.add_argument("value", help='use "" to clear')
    st.add_argument("--config", default=DEFAULT_CONFIG)

    args = ap.parse_args(argv)
    api = RecGov()

    if args.cmd == "search":
        q = " ".join(args.query)
        for z in zones.search(zones.load(load_config(args.config).zones_file), q):
            print(f"{'zone':<11} {z.entity_id:<10} {z.name}  (in {z.parent}; zone {z.division_id})")
        for r in api.search(q):
            print(f"{r.entity_type:<11} {r.entity_id:<10} {r.name}  ({r.parent})")
    elif args.cmd == "index":
        path = load_config(args.config).zones_file
        index = zones.build(RecGov(min_interval=0.5),
                            progress=lambda i, n: print(f"\r{i}/{n} permits", end="", flush=True))
        zones.save(path, index)
        print(f"\nIndexed {sum(len(p['zones']) for p in index['permits'].values())} zones in "
              f"{len(index['permits'])} permits -> {path}")
    elif args.cmd == "divisions":
        for div_id, name in api.permit_divisions(args.permit_id).items():
            if args.filter.lower() in name.lower():
                print(f"{div_id:<12} {name}")
    elif args.cmd == "dates":
        now = datetime.now(timezone.utc)
        for e in parse_events(args.permit_id, api.permit_content(args.permit_id)):
            mark = " " if e.when > now else "x"
            print(f"{mark} {e.when:%a %b %d %Y %-I:%M %p %Z}{'' if e.time_known else ' (time ?)'}  {e.description}")
    elif args.cmd == "tui":
        from .tui import PermitPanicApp  # textual is only needed for the dashboard

        PermitPanicApp(args.config).run()
    elif args.cmd in ("check", "watch"):
        Watcher(args.config, api).run(once=args.cmd == "check")
    elif args.cmd == "set":
        raw = read_raw(args.config)
        notify_cfg = raw.setdefault("notify", {})
        if args.value == "":
            notify_cfg.pop(args.key, None)
        else:
            notify_cfg[args.key] = (int(args.value) if args.key == "digest_hour"
                                    else args.value.lower() in ("1", "true", "yes", "on")
                                    if args.key == "emergency_openings" else args.value)
        write_raw(args.config, raw)
        shown = notify_cfg.get(args.key, "(cleared)")
        if args.key in ("pushover_user", "pushover_token") and args.value:
            shown = f"{args.value[:4]}…"  # don't echo secrets into the scrollback
        print(f"{args.key} = {shown}")
    elif args.cmd == "test-notify":
        cfg = load_config(args.config)
        if not (cfg.pushover_user and cfg.pushover_token):
            print("run `permit-panic set pushover_user ...` and `set pushover_token ...` first", file=sys.stderr)
            return 1
        try:
            notify.send("Permit Panic test", "If you can read this on your phone, alerts work.",
                        token=cfg.pushover_token, user=cfg.pushover_user, sound=cfg.opening_sound,
                        click_url="https://www.recreation.gov", action="Book now")
        except notify.NotifyError as e:
            print(e, file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
