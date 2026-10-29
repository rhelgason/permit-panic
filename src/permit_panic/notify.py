"""Phone alerts via Pushover (https://pushover.net/api).

The bear logo is the icon you upload when creating the Pushover application, so
it shows on iOS and Android without hosting anything. Each notification type
also leads its title with an emoji.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.pushover.net/1/messages.json"

PRIORITY = {"min": -1, "low": -1, "default": 0, "high": 1, "urgent": 1}
EMOJI = {"bear": "🐻", "alarm_clock": "⏰", "white_check_mark": "✅", "warning": "⚠️", "sunrise": "🌅",
         "hourglass": "⌛"}


class NotifyError(OSError):
    pass


def send(title: str, body: str, *, token: str | None, user: str | None, click_url: str | None = None,
         priority: str = "urgent", tags: str = "bear", action: str = "Open", sound: str | None = None,
         emergency: bool = False) -> None:
    emoji = EMOJI.get(tags.split(",")[0], "")
    title = f"{emoji} {title}".strip()
    print(f"\n*** {title}\n{body}\n{click_url or ''}", flush=True)
    if not (token and user):
        return
    form = {"token": token, "user": user, "title": title[:250], "message": body[:1024],
            "priority": PRIORITY.get(priority, 0)}
    if priority == "urgent":
        if sound:
            form["sound"] = sound
        if emergency:
            # Re-alerts every minute for up to 30 min until you tap Acknowledge.
            form.update(priority=2, retry=60, expire=1800)
    if click_url:
        form["url"], form["url_title"] = click_url, action
    req = urllib.request.Request(API, data=urllib.parse.urlencode(form).encode(), method="POST")
    try:
        urllib.request.urlopen(req, timeout=15).close()
    except urllib.error.HTTPError as e:
        try:
            errors = json.load(e).get("errors", [])
        except ValueError:
            errors = []
        raise NotifyError(f"Pushover rejected the message ({e.code}): {'; '.join(errors) or e.reason}") from e
