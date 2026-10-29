# Setup checklist

You've already done steps 1–6: the icon, the Pushover app, and installing on your Mac with your keys set.
Everything below moves Permit Panic onto the server (the DigitalOcean droplet Kalshi Desk uses). Once it's there,
your Mac can be off. Server details are in [deploy/SERVER.md](deploy/SERVER.md).

## Move it to the server (on your Mac)

7. **Get the latest code:**
   ```bash
   cd ~/Documents/permit-panic && git pull
   ```
8. **(Optional) Rotate the Pushover token**, since it was pasted into a chat. On pushover.net, open your **Permit Panic** app → **Reset Token** → copy the new token. Then run:
   ```bash
   .venv/bin/permit-panic set pushover_token aNEW_TOKEN
   ```
9. **Install on the server.** One command does everything, and your keys are copied without being printed:
   ```bash
   deploy/install-on-server.sh
   ```
   It ends with **==> Test notification sent**, and your phone gets **🐻 Permit Panic test**.
10. **Add a shortcut.** After this, `panic <command>` runs on the server:
    ```bash
    echo "alias panic='ssh -t root@104.131.18.118 permit-panic'" >> ~/.zshrc && source ~/.zshrc
    ```
11. **Clean up the Mac copy.** Its `config.toml` holds your keys, and the server has everything now:
    ```bash
    cd ~ && rm -rf ~/Documents/permit-panic
    ```

## Use it

12. Run `panic tui` → press **a** → search a park → pick it → fill in the form → **Save**. Within seconds your phone shows **✅ Now watching: …**. Press **m** to add lottery and release reminders, and **q** to quit. The server keeps watching.
13. To get new code later, run `panic update`.

## Optional

14. **Ring until acknowledged:** `panic set emergency_openings true` makes openings repeat every minute until you tap Acknowledge.
15. **Get alerted if the server dies:**
    - Go to healthchecks.io → **Sign up** (free) → **Add Check** → set *Period* 10 min and *Grace* 10 min → **Save** → copy the ping URL.
    - Go to **Integrations** → **Pushover** → **Add Integration**.
    - Run `panic set healthcheck_url https://hc-ping.com/YOUR-UUID`.
