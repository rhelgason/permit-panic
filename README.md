# permit-panic

A free, self-hosted tool that watches Recreation.gov for backcountry permits and campsites and sends an alert to your phone the moment something you want opens up.

It handles the three kinds of availability Recreation.gov has:

| kind         | examples                                         | what it alerts on                                   |
|--------------|--------------------------------------------------|-----------------------------------------------------|
| `itinerary`  | Grand Teton, Glacier, Yellowstone backcountry    | a **whole multi-night route** being open, night by night |
| `entry`      | Inyo, Yosemite, Sierra trailhead quotas          | ≥ `group_size` spots left at a trailhead on a date   |
| `campground` | regular reservable campgrounds                   | any site open for N consecutive nights              |

## Quick start

Setting up on a server for real? Follow **[SETUP.md](SETUP.md)**, which walks through it step by step.

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
cp examples/road-trip.toml config.toml   # set your ntfy topic
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

The dashboard edits `config.toml`. The watcher notices the change within seconds, runs the new watch, and sends a quiet "Now watching" ping to your phone. That ping proves the whole chain works: the config saved, the watcher is alive, Recreation.gov answered, and ntfy delivered. Run both on the same machine and use SSH for the dashboard.

## Notifications

| priority | title                              | when                                                                         |
|----------|------------------------------------|------------------------------------------------------------------------------|
| urgent   | **Open: _watch_**                  | new openings, collapsed per route (`Start Dec 01-19: A -> B`), **Book now** button |
| high     | **In 30 min: _permit_**            | a reservation opening / lottery date is about to start                       |
| default  | **Tomorrow: _permit_**             | the same, 24 hours ahead                                                     |
| default  | **Problem with / Watch broken**    | a just-saved watch fails its first check, or a watch keeps failing for 30 min |
| low      | **Now watching / Updated / Resumed** | the watcher loaded your new or edited watch, with its first result          |
| low      | **Reminders on: _permit_**         | reminders added, with the next date                                          |
| low      | **Fixed / Paused / Stopped / Ended** | recovered, paused, deleted, or the date window passed                     |
| min      | **Daily summary**                  | optional: set `[notify] digest_hour = 8` (the server's local time)           |

Every notification shows the bear logo (`assets/icon.png`) as its icon on Android; this needs the repo to be public, or set `[notify] icon_url` to any public PNG. The ntfy iPhone app doesn't show custom icons, so each type also starts with an emoji: 🐻 opening, ⏰ reminder, ✅ confirmation, ⚠️ problem.

To know if the server itself dies, create a free check at [healthchecks.io](https://healthchecks.io) and set `[notify] healthcheck_url`. The watcher pings it every cycle, and healthchecks.io alerts you (it supports ntfy) if the pings stop.

## Reminders

For every reminder permit, the watcher reads the "important dates" the permit lists on Recreation.gov and pings your phone **24 hours and 30 minutes before** each one. That covers reservation openings (e.g. Teton: Jan 11 2027, 8:00 AM MT), lottery windows opening, and the day a lottery window closes. If the listing gives no time, it assumes 9 AM (5 PM on a closing day) in the park's time zone and labels it `time ?`. Use `permit-panic dates <permit_id>` to preview them.

## Phone alerts (ntfy)

Set `ntfy_topic` in `config.toml`. You can reuse the topic you already use for another project, but a separate topic keeps the alerts apart. If the topic is reserved on an ntfy account, run `export NTFY_TOKEN=tk_...` (or put it in the systemd env file below), so the token never lives in the config. For a self-hosted ntfy server, set `ntfy_server`.

## Running it 24/7 for free

- **Your own server (recommended):** clone the repo there, then follow `deploy/permit-panic.service` (a systemd user service). Check logs with `journalctl --user -u permit-panic -f`.
- GitHub Actions cron also works, with limits: it runs every ≥5 minutes, often late. State would have to live in the Actions cache, and changing watches would mean committing `config.toml`. Use it only as a fallback.

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
