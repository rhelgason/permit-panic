"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from . import notify
from .config import load_config, read_raw, write_raw
from .recgov import RecGov
from .reminders import parse_events
from .watch import Watcher

DEFAULT_CONFIG = "config.toml"
NOTIFY_KEYS = ("ntfy_topic", "ntfy_server", "icon_url", "digest_hour", "healthcheck_url")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="permit-panic", description="Watch Recreation.gov for permits.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="find permit / campground ids")
    s.add_argument("query", nargs="+")

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
        for r in api.search(" ".join(args.query)):
            print(f"{r.entity_type:<11} {r.entity_id:<10} {r.name}  ({r.parent})")
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
            notify_cfg[args.key] = int(args.value) if args.key == "digest_hour" else args.value
        write_raw(args.config, raw)
        print(f"{args.key} = {notify_cfg.get(args.key, '(cleared)')}")
    elif args.cmd == "test-notify":
        cfg = load_config(args.config)
        if not cfg.ntfy_topic:
            print("set [notify] ntfy_topic in your config first", file=sys.stderr)
            return 1
        notify.send("Permit Panic test", "If you can read this on your phone, alerts work.",
                    ntfy_topic=cfg.ntfy_topic, ntfy_server=cfg.ntfy_server, ntfy_token=cfg.ntfy_token,
                    icon_url=cfg.icon_url, click_url="https://www.recreation.gov")
    return 0


if __name__ == "__main__":
    sys.exit(main())
