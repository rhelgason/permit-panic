# On the always-on server

Permit Panic runs on the same DigitalOcean droplet as Kalshi Desk (**104.131.18.118**, Ubuntu 24.04, 1 GB). It's
set up the same way, and kept apart from Kalshi Desk:

- **Log in:** `ssh root@104.131.18.118` with your Mac's key.
- **Own user:** the watcher runs as the `permit` user, so it can't read Kalshi Desk's keys.
- **Code:** `/home/permit/permit-panic`, cloned over HTTPS (the repo is public, so no deploy key is needed).
- **Settings:** `/home/permit/permit-panic/config.toml`, plus state files next to it.
- **Secrets:** `/etc/permit-panic.env` (`PUSHOVER_USER`, `PUSHOVER_TOKEN`, `TZ`; root:permit, mode 640).
- **Service:** `deploy/permit-panic.service` → `/etc/systemd/system/permit-panic.service`. It restarts on crash and boot, with memory capped at 200 MB.
- **CLI:** `/usr/local/bin/permit-panic` (`deploy/permit-panic-wrapper.sh`) runs any command as `permit` with the keys loaded.

Install, or reinstall, from your Mac with `deploy/install-on-server.sh`.

```bash
alias panic='ssh -t root@104.131.18.118 permit-panic'   # put this in ~/.zshrc
panic tui                     # the dashboard
panic update                  # pull the latest main and restart
panic test-notify
panic dates 4675342           # a permit's release / lottery dates
ssh root@104.131.18.118 'systemctl status permit-panic --no-pager; journalctl -u permit-panic -n 50 --no-pager'
```

To change a Pushover key, edit `/etc/permit-panic.env`, then run `systemctl restart permit-panic`.
