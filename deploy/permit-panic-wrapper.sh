#!/bin/sh
# Installed on the server as /usr/local/bin/permit-panic: runs the CLI as the service's user with
# its Pushover keys loaded, against the same config.toml the watcher reads. From your Mac:
#   ssh -t root@104.131.18.118 permit-panic tui
#   ssh root@104.131.18.118 permit-panic update      # install the latest main, safely
cd /home/permit/permit-panic || exit 1
as_permit() { sudo -u permit "$@"; }

# "success", "failure", "pending" or "none" for a commit's GitHub Actions runs (public repo, no token needed).
ci_verdict() {
  python3 - "$1" <<'PY'
import json, sys, urllib.request
url = f"https://api.github.com/repos/rhelgason/permit-panic/commits/{sys.argv[1]}/check-runs"
try:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "permit-panic-update"})
    runs = json.load(urllib.request.urlopen(req, timeout=15))["check_runs"]
except Exception:
    print("none"); sys.exit()
if not runs: print("none")
elif any(r["status"] != "completed" for r in runs): print("pending")
elif all(r["conclusion"] in ("success", "skipped", "neutral") for r in runs): print("success")
else: print("failure")
PY
}

install_and_restart() {
  # pip's chatter goes to a log; it's shown only if the install fails.
  { as_permit .venv/bin/pip install -q -e . >/tmp/permit-panic-pip.log 2>&1 || { cat /tmp/permit-panic-pip.log; false; }; } &&
  # Write the new wrapper beside the old one and rename it in, so this running script isn't overwritten mid-read.
  install -m 755 deploy/permit-panic-wrapper.sh /usr/local/bin/permit-panic.new &&
  mv -f /usr/local/bin/permit-panic.new /usr/local/bin/permit-panic &&
  install -m 644 deploy/permit-panic.service /etc/systemd/system/permit-panic.service &&
  systemctl daemon-reload && systemctl restart permit-panic
}

healthy() {
  sleep 8
  systemctl is-active -q permit-panic &&
  as_permit .venv/bin/python -c "import permit_panic.watch, permit_panic.tui" 2>/dev/null
}

if [ "${1:-}" = update ]; then
  old=$(as_permit git rev-parse HEAD)
  as_permit git fetch -q origin main || { echo "Couldn't reach GitHub; nothing changed."; exit 1; }
  new=$(as_permit git rev-parse origin/main)
  if [ "$old" = "$new" ]; then
    echo "Already up to date: $(as_permit git log -1 --format='%h %s')"; exit 0
  fi
  short=$(as_permit git log -1 --format=%h "$new")

  # Don't install a commit whose tests failed on GitHub. Wait a few minutes if they're still running.
  verdict=$(ci_verdict "$new"); waited=0
  while { [ "$verdict" = pending ] || { [ "$verdict" = none ] && [ $waited -lt 60 ]; }; } && [ $waited -lt 300 ]; do
    [ $waited -eq 0 ] && echo "Waiting for GitHub's tests on $short..."
    sleep 15; waited=$((waited + 15)); verdict=$(ci_verdict "$new")
  done
  case $verdict in
    failure) echo "Tests failed on GitHub for $short. Not updating; still running $(as_permit git log -1 --format=%h)."; exit 1 ;;
    pending) echo "GitHub's tests for $short are still running. Nothing changed; try again in a few minutes."; exit 1 ;;
    none) echo "No GitHub test results for $short; updating anyway, with the rollback check." ;;
    success) echo "GitHub's tests passed for $short." ;;
  esac

  as_permit git merge -q --ff-only "$new" || { echo "Couldn't fast-forward to $short; nothing changed."; exit 1; }
  if install_and_restart && healthy; then
    echo "Updated to $(as_permit git log -1 --format='%h %s') and restarted."; exit 0
  fi
  # The new version didn't come back up: put the old one back so watching continues.
  as_permit git reset -q --hard "$old"
  install_and_restart && healthy && state="Back on $(as_permit git log -1 --format=%h) and running." ||
    state="The rollback didn't start cleanly either."
  echo "Update to $short failed to start, so it was rolled back. $state"
  echo "Details: journalctl -u permit-panic -n 50"
  exit 1
fi
exec sudo -u permit sh -c 'set -a; . /etc/permit-panic.env; set +a; exec .venv/bin/permit-panic "$@"' permit-panic "$@"
