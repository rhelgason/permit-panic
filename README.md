# permit-panic

A free, self-hosted tool that watches Recreation.gov for backcountry permits and campsites and sends an alert to your phone the moment something you want opens up.

It handles the three kinds of availability Recreation.gov has:

| kind         | examples                                         | what it alerts on                                   |
|--------------|--------------------------------------------------|-----------------------------------------------------|
| `itinerary`  | Grand Teton, Glacier, Yellowstone backcountry    | a **whole multi-night route** being open, night by night |
| `entry`      | Inyo, Yosemite, Sierra trailhead quotas          | ≥ `group_size` spots left at a trailhead on a date   |
| `campground` | regular reservable campgrounds                   | any site open for N consecutive nights              |

## Quick start

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
| `m`     | add release + lottery reminders for a permit                                  |
| `space` | pause/resume a watch                                                          |
| `d`     | delete the highlighted watch or reminder                                      |
| `r`     | refresh                                                                       |

The dashboard edits `config.toml`, which the watcher re-reads every cycle, so changes apply without a restart. Run both on the same machine and use SSH for the dashboard.

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

## Known gaps / TODO

- `itinerary` availability is read from the per-zone `bools` calendar. The meaning `true = open` has not yet been confirmed during an in-season release.
- Editing an existing watch in the dashboard (today: delete and re-add).
- Per-reminder muting; busy permits like The Wave list a date every month.
- Non-Recreation.gov systems (state parks, Parks Canada).
- Trip-wide view across several parks on a road trip.
