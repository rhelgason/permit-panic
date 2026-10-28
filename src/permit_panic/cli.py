"""Command line entry point."""

from __future__ import annotations

import argparse
import sys

from . import notify
from .recgov import RecGov
from .watch import load_config, run


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="permit-panic", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="find permit / campground ids")
    s.add_argument("query", nargs="+")

    d = sub.add_parser("divisions", help="list the zones, sites or trailheads in a permit")
    d.add_argument("permit_id")
    d.add_argument("--filter", default="")

    for name, help_ in (("check", "run every watch once"), ("watch", "poll forever and alert on new openings")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("config")

    t = sub.add_parser("test-notify", help="send a test alert to your phone")
    t.add_argument("config")

    args = ap.parse_args(argv)
    api = RecGov()

    if args.cmd == "search":
        for r in api.search(" ".join(args.query)):
            print(f"{r.entity_type:<11} {r.entity_id:<10} {r.name}  ({r.parent})")
    elif args.cmd == "divisions":
        for div_id, name in api.permit_divisions(args.permit_id).items():
            if args.filter.lower() in name.lower():
                print(f"{div_id:<12} {name}")
    elif args.cmd in ("check", "watch"):
        run(load_config(args.config), once=args.cmd == "check")
    elif args.cmd == "test-notify":
        cfg = load_config(args.config)
        if not cfg.ntfy_topic:
            print("set [notify] ntfy_topic in your config first", file=sys.stderr)
            return 1
        notify.send("Permit Panic test", "If you can read this on your phone, alerts work.",
                    ntfy_topic=cfg.ntfy_topic, ntfy_server=cfg.ntfy_server,
                    click_url="https://www.recreation.gov")
    return 0


if __name__ == "__main__":
    sys.exit(main())
