"""Phone alerts via ntfy: install the app and subscribe to a topic.

The bear logo (assets/icon.png) shows as the notification icon on Android; ntfy's
iOS app ignores custom icons, so every type also leads with an emoji tag.
"""

from __future__ import annotations

import urllib.request


def send(title: str, body: str, *, ntfy_topic: str | None, click_url: str | None = None,
         ntfy_server: str = "https://ntfy.sh", ntfy_token: str | None = None,
         priority: str = "urgent", tags: str = "bear", action: str = "Open",
         icon_url: str | None = None) -> None:
    print(f"\n*** {title}\n{body}\n{click_url or ''}", flush=True)
    if not ntfy_topic:
        return
    headers = {"Title": title, "Priority": priority, "Tags": tags}
    if icon_url:
        headers["Icon"] = icon_url
    if ntfy_token:
        headers["Authorization"] = f"Bearer {ntfy_token}"
    if click_url:
        headers["Click"] = click_url
        headers["Actions"] = f"view, {action}, {click_url}"
    req = urllib.request.Request(f"{ntfy_server.rstrip('/')}/{ntfy_topic}", data=body.encode("utf-8"),
                                 headers=headers, method="POST")
    urllib.request.urlopen(req, timeout=15).close()
