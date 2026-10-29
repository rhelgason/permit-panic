# permit-panic

A free, self-hosted tool that watches Recreation.gov for backcountry permits and campsites and sends an alert to your phone the moment something you want opens up.

It handles the three kinds of availability Recreation.gov has:

| kind         | examples                                         | what it alerts on                                   |
|--------------|--------------------------------------------------|-----------------------------------------------------|
| `itinerary`  | Grand Teton, Glacier, Yellowstone backcountry    | a **whole multi-night route** being open, night by night |
| `entry`      | Inyo, Yosemite, Sierra trailhead quotas          | ≥ `group_size` spots left at a trailhead on a date   |
| `campground` | regular reservable campgrounds                   | any site open for N consecutive nights              |

## Quick start

Setting up on the server? Follow **[SETUP.md](SETUP.md)**, which walks through it step by step.

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
cp examples/road-trip.toml config.toml   # set your Pushover keys
.venv/bin/permit-panic test-notify       # confirm your phone buzzes
.venv/bin/permit-panic tui               # add watches and reminders
.venv/bin/permit-panic watch             # poll forever (or `check` for one pass)
```

## Dashboard (`permit-panic tui`)

| key     | does                                                                          |
|---------|-------------------------------------------------------------------------------|
| `a`     | add a watch: search a park → pick zones per night / trailheads → set dates    |
| `e`     | edit the highlighted watch (dates, group size, route, trailheads)             |
| `m`     | add release + lottery reminders for a permit                                  |
| `space` | pause/resume a watch                                                          |
| `d`     | delete the highlighted watch or reminder                                      |
| `x`     | mute the highlighted reminder date                                            |
| `r`     | refresh                                                                       |

The dashboard edits `config.toml`. The watcher notices the change within seconds, runs the new watch, and sends a quiet "Now watching" ping to your phone. That ping proves the whole chain works: the config saved, the watcher is alive, Recreation.gov answered, and Pushover delivered. Run both on the same machine and use SSH for the dashboard.

## Notifications

| priority | title                              | when                                                                         |
|----------|------------------------------------|------------------------------------------------------------------------------|
| high + 🎺 | **🐻 Open: _watch_**              | new openings, collapsed per route (`Start Dec 01-19: A -> B`), **Book now** link. Bypasses quiet hours |
| high     | **⏰ In 30 min: _permit_**          | a reservation opening / lottery date is about to start                       |
| normal   | **⏰ Tomorrow: _permit_**           | the same, 24 hours ahead                                                     |
| normal   | **⚠️ Problem with / Watch broken**  | a just-saved watch fails its first check, or a watch keeps failing for 30 min |
| silent   | **✅ Now watching / Updated / Resumed** | the watcher loaded your new or edited watch, with its first result       |
| silent   | **✅ Reminders on: _permit_**       | reminders added, with the next date                                          |
| silent   | **✅ Fixed · Paused · Stopped · ⌛ Ended** | recovered, paused, deleted, or the date window passed                 |
| silent   | **🌅 Daily summary**                | optional: `permit-panic set digest_hour 8` (the server's local time)         |

Openings play the `bugle` sound so they stand out from your other Pushover apps (`set opening_sound <name>` to change it). `set emergency_openings true` makes openings repeat every minute for up to 30 minutes until you tap Acknowledge.

To know if the server itself dies, create a free check at [healthchecks.io](https://healthchecks.io), connect its Pushover integration, and `set healthcheck_url`. The watcher pings it every cycle, and healthchecks.io alerts you if the pings stop.

## Reminders

For every reminder permit, the watcher reads the "important dates" the permit lists on Recreation.gov and pings your phone **24 hours and 30 minutes before** each one. That covers reservation openings (e.g. Teton: Jan 11 2027, 8:00 AM MT), lottery windows opening, and the day a lottery window closes. If the listing gives no time, it assumes 9 AM (5 PM on a closing day) in the park's time zone and labels it `time ?`. Use `permit-panic dates <permit_id>` to preview them.

## Phone alerts (Pushover)

You need your Pushover **user key** and an **application API token**. Create a separate "Permit Panic" application (free) rather than reusing another project's token: it gets its own name and the bear icon (`assets/icon-72.png`) on iOS and Android, and you can mute it on its own. Set the keys with `permit-panic set pushover_user …` / `set pushover_token …`, or as `PUSHOVER_USER` / `PUSHOVER_TOKEN` env vars (on the server they live in `/etc/permit-panic.env`, which the service loads). All your Pushover apps share one 10,000-messages-a-month free allowance; this one uses a handful a day.

## Running it 24/7

It runs on the same always-on DigitalOcean droplet as Kalshi Desk, as its own `permit` user with a systemd service. To install or reinstall it from your Mac, run `deploy/install-on-server.sh`. For day-to-day use, `panic tui` / `panic update` (an alias for `ssh -t root@104.131.18.118 permit-panic`). The details are in [deploy/SERVER.md](deploy/SERVER.md).

## How it behaves

- It only reads the same public availability data that the Recreation.gov calendar pages show. It never logs in or books anything; you complete the booking yourself.
- By default it polls every ~3 minutes with jitter and spaces out requests by 1s.
- It alerts only on *new* openings. If something closes and later reopens, you get alerted again.

## How itinerary availability is decided

Each zone's month calendar returns `bools` and `quota_type_maps`. These were tested live on Joshua Tree, Zion, Canyonlands, Everglades and Death Valley in Oct 2026 (~3,800 zone-nights):

- `bools` is also `true` for **walk-up-only** zones (`total: 0`), which can't be booked online. That accounted for all 527 mismatches.
- With walk-up zones excluded, `bools` matched `remaining > 0` on every zone-night.
- So a zone-night counts as open only when every quota has `total > 0` and enough `remaining`. `ConstantQuotaUsageDaily` counts sites (needs ≥ 1); `QuotaUsageByMemberDaily` counts people (needs ≥ your group size).

## Known gaps / TODO

- Non-Recreation.gov systems (state parks, Parks Canada).
- Trip-wide view across several parks on a road trip.

## Future ideas

- **Simple website UI.** A read-only page served from the same server, showing watches, current openings and upcoming reminders, with editing added later. It would read the same `config.toml` and status file the TUI uses, so it can sit alongside the TUI without a rewrite.
