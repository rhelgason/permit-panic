# Setup checklist

About 10 minutes. Do these in order.

## GitHub

1. **Download the icon.** Open `assets/icon-72.png` in the repo → click the **Download raw file** button (↓, top right of the file view).

## Pushover (browser)

2. **Create the app.** At pushover.net, log in → scroll to **Your Applications** → **Create an Application/API Token** → fill in:
   - *Name*: `Permit Panic`
   - *Type*: **Application**
   - *Icon*: **Choose File** → the `icon-72.png` from step 1
   - Tick the terms box → **Create Application**
3. **Copy two keys.** On the new app's page, copy the **API Token/Key** (starts with `a`). Then go back to the dashboard and copy **Your User Key** (top right, starts with `u`).

## Server (SSH)

4. **Install:**
   ```bash
   git clone https://github.com/rhelgason/permit-panic.git ~/permit-panic
   cd ~/permit-panic
   python3 -m venv .venv && .venv/bin/pip install -e .
   ```
   This needs Python 3.11+ (check with `python3 --version`).
5. **Add your keys and test.** Paste in your keys from step 3:
   ```bash
   .venv/bin/permit-panic set pushover_user uYOUR_USER_KEY
   .venv/bin/permit-panic set pushover_token aYOUR_APP_TOKEN
   .venv/bin/permit-panic set digest_hour 8      # optional daily summary at 8am, server time
   chmod 600 config.toml
   .venv/bin/permit-panic test-notify
   ```
   Your phone should get **🐻 Permit Panic test** with the bear icon. If it doesn't, the command prints Pushover's reason.
6. **Run it 24/7:**
   ```bash
   mkdir -p ~/.config/systemd/user && cp deploy/permit-panic.service ~/.config/systemd/user/
   systemctl --user daemon-reload && systemctl --user enable --now permit-panic
   sudo loginctl enable-linger $USER
   ```
   Check it with `systemctl --user status permit-panic`. It should say **active (running)**.

## Use it

7. `cd ~/permit-panic && .venv/bin/permit-panic tui` → press **a** → search a park → pick it → fill in the form → **Save**. Within seconds your phone shows **✅ Now watching: …**. Press **m** to add lottery and release reminders, and **q** to quit. The watcher keeps running.

## Optional

8. **Ring until acknowledged.** Run `.venv/bin/permit-panic set emergency_openings true` so openings repeat every minute until you tap Acknowledge.
9. **Get alerted if the server dies.**
    - Go to healthchecks.io → **Sign up** (free) → **Add Check** → set *Period* 10 min and *Grace* 10 min → **Save** → copy the ping URL.
    - Then go to **Integrations** → **Pushover** → **Add Integration** → **Subscribe with Pushover**.
    - On the server, run:
      ```bash
      .venv/bin/permit-panic set healthcheck_url https://hc-ping.com/YOUR-UUID
      ```
    No restart is needed.
