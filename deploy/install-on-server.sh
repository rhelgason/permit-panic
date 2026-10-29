#!/bin/sh
# Install or update Permit Panic on the always-on server. Run it from your Mac, in this repo:
#   deploy/install-on-server.sh
# Safe to re-run: it pulls the latest main and restarts the service.
#
# Your Pushover keys are read from this Mac's config.toml (or the PUSHOVER_USER / PUSHOVER_TOKEN
# env vars) and written to /etc/permit-panic.env on the server, without being printed. Settings
# without secrets (digest hour, watches, reminders) are copied over only if the server has no
# config.toml yet. The server uses this Mac's time zone, so the daily summary hour is your local time.
set -eu
HOST="${PANIC_HOST:-root@104.131.18.118}"
cd "$(dirname "$0")/.."
PY=.venv/bin/python
[ -x "$PY" ] || PY=python3

KEYS=$("$PY" -c '
from permit_panic.config import load_config
c = load_config("config.toml")
if c.pushover_user and c.pushover_token:
    print(f"PUSHOVER_USER={c.pushover_user}\nPUSHOVER_TOKEN={c.pushover_token}")
' 2>/dev/null || true)
TZ_NAME=$(readlink /etc/localtime 2>/dev/null | sed 's#.*zoneinfo/##')
[ -n "$TZ_NAME" ] || TZ_NAME=UTC

echo "==> Setting up $HOST"
ssh "$HOST" 'bash -s' <<'REMOTE'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
dpkg -s python3-venv git >/dev/null 2>&1 || { apt-get update -qq && apt-get install -y -qq python3-venv git >/dev/null; }
id permit >/dev/null 2>&1 || useradd --create-home --shell /usr/sbin/nologin permit
APP=/home/permit/permit-panic
if [ -d "$APP/.git" ]; then
  sudo -u permit git -C "$APP" pull -q --ff-only
else
  sudo -u permit git clone -q https://github.com/rhelgason/permit-panic.git "$APP"
fi
cd "$APP"
[ -x .venv/bin/python ] || sudo -u permit python3 -m venv .venv
sudo -u permit .venv/bin/pip install -q --upgrade pip
sudo -u permit .venv/bin/pip install -q -e .
install -m 755 deploy/permit-panic-wrapper.sh /usr/local/bin/permit-panic
install -m 644 deploy/permit-panic.service /etc/systemd/system/permit-panic.service
touch /etc/permit-panic.env && chown root:permit /etc/permit-panic.env && chmod 640 /etc/permit-panic.env
REMOTE

if [ -n "$KEYS" ]; then
  # Keys travel over ssh's stdin, never on a command line or in the output.
  printf '%s\nTZ=%s\n' "$KEYS" "$TZ_NAME" | ssh "$HOST" 'umask 027; cat > /etc/permit-panic.env.new &&
    chown root:permit /etc/permit-panic.env.new && mv /etc/permit-panic.env.new /etc/permit-panic.env'
  echo "==> Pushover keys and time zone ($TZ_NAME) saved to /etc/permit-panic.env"
elif ! ssh "$HOST" 'grep -q "^PUSHOVER_TOKEN=." /etc/permit-panic.env'; then
  echo "No Pushover keys found here or on the server. Run: .venv/bin/permit-panic set pushover_user u... and"
  echo "set pushover_token a..., then re-run this script."
  exit 1
fi

if [ -f config.toml ]; then
  "$PY" -c '
import sys, tomli_w
from permit_panic.config import read_raw
raw = read_raw("config.toml")
for k in ("pushover_user", "pushover_token"):
    raw.get("notify", {}).pop(k, None)
sys.stdout.write(tomli_w.dumps(raw))
' | ssh "$HOST" 'f=/home/permit/permit-panic/config.toml
    if [ -f "$f" ]; then cat >/dev/null; echo "==> Kept the existing config.toml on the server";
    else cat > "$f" && chown permit:permit "$f" && chmod 600 "$f" && echo "==> Copied your settings (no secrets) to the server"; fi'
fi

ssh "$HOST" 'systemctl daemon-reload && systemctl enable -q permit-panic && systemctl restart permit-panic && sleep 3 &&
  systemctl is-active -q permit-panic' || { echo "The service did not start. See: ssh $HOST journalctl -u permit-panic -n 50"; exit 1; }
echo "==> permit-panic service is running"
if ssh "$HOST" 'permit-panic test-notify >/dev/null'; then
  echo "==> Test notification sent: check your phone for 🐻 Permit Panic test"
else
  echo "The test notification failed (reason above). Fix the keys, then re-run this script."
  exit 1
fi
echo "Open the dashboard any time with:  ssh -t $HOST permit-panic tui"
