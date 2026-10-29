#!/bin/sh
# Installed on the server as /usr/local/bin/permit-panic: runs the CLI as the service's user with
# its Pushover keys loaded, against the same config.toml the watcher reads. From your Mac:
#   ssh -t root@104.131.18.118 permit-panic tui
#   ssh root@104.131.18.118 permit-panic update      # pull the latest main and restart
cd /home/permit/permit-panic || exit 1
if [ "${1:-}" = update ]; then
  set -e
  sudo -u permit git pull -q --ff-only
  sudo -u permit .venv/bin/pip install -q -e .
  install -m 755 deploy/permit-panic-wrapper.sh /usr/local/bin/permit-panic
  install -m 644 deploy/permit-panic.service /etc/systemd/system/permit-panic.service
  systemctl daemon-reload && systemctl restart permit-panic
  echo "Updated to $(sudo -u permit git log -1 --format='%h %s') and restarted."
  exit 0
fi
exec sudo -u permit sh -c 'set -a; . /etc/permit-panic.env; set +a; exec .venv/bin/permit-panic "$@"' permit-panic "$@"
