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

.venv/bin/permit-panic search grand teton backcountry       # find the permit id
.venv/bin/permit-panic divisions 4675342 --filter cascade   # find camp zone names/ids

cp examples/road-trip.toml config.toml                      # edit dates, zones, ntfy topic
.venv/bin/permit-panic test-notify config.toml              # confirm your phone buzzes
.venv/bin/permit-panic check config.toml                    # one pass
.venv/bin/permit-panic watch config.toml                    # poll forever
```

**Phone alerts** use [ntfy](https://ntfy.sh): install the app, subscribe to the topic in your config, done. It's free and needs no account. Use a topic name nobody could guess, because anyone who knows the name can read the alerts. Each alert has a "Book now" button that opens the permit page.

## How it behaves

- It only reads the same public availability data that the Recreation.gov calendar pages show. It never logs in or books anything; you complete the booking yourself.
- By default it polls every ~3 minutes with jitter and spaces out requests by 1s. Please keep it polite.
- It alerts only on *new* openings. If something closes and later reopens, you get alerted again.

## Known gaps / TODO

- `itinerary` availability is read from the per-zone `bools` calendar. The meaning `true = open` has not yet been confirmed during an in-season release.
- Lottery permits (Enchantments, Half Dome, Mt. Whitney, Wave) need a "lottery opens/closes" reminder, not a watcher.
- Release-date reminders (e.g. "Teton early access opens at 8am MT on …").
- Non-Recreation.gov systems (state parks, Parks Canada).
- Trip-wide view across several parks on a road trip.
