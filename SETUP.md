# Setup checklist

About 15 minutes. Do these in order.

## On GitHub (browser)

1. **Merge the code into `main`.** Open github.com/rhelgason/permit-panic → **Pull requests** tab → **New pull request** → set *compare* to `claude/initial-scaffold` → **Create pull request** → **Create pull request** → **Merge pull request** → **Confirm merge**.
2. **(Optional) Make the repo public**, so the bear icon can load on Android. Nothing secret is in the repo; your `config.toml` and state files are git-ignored. Go to **Settings** → **General** → scroll to **Danger Zone** → **Change visibility** → **Change to public** → confirm. Skip this and notifications still work, just without the icon.
3. **Only if the repo stays private:** create a token for the server to clone it. Click your avatar → **Settings** → **Developer settings** → **Personal access tokens** → **Fine-grained tokens** → **Generate new token** → *Repository access*: **Only select repositories** → `permit-panic` → *Permissions*: **Contents → Read-only** → **Generate token** → copy it. When `git clone` asks for a password, paste this token.

## On your phone

4. Install **ntfy** from the App Store or Play Store → open it → **+** → *Topic*: make up something unguessable, e.g. `permit-panic-k7x2q9`, and write it down → **Subscribe**. Allow notifications when asked.
   - Already have an ntfy account with reserved topics? Use one of those, then on ntfy.sh/app go to **Account** → **Access tokens** → **Create access token** → copy the `tk_...` value for step 7.

## On your server (SSH)

5. **Install.** You need Python 3.11+; check with `python3 --version`.
   ```bash
   git clone https://github.com/rhelgason/permit-panic.git ~/permit-panic
   cd ~/permit-panic
   python3 -m venv .venv && .venv/bin/pip install -e .
   ```
6. **Only if you have a `tk_...` token from step 4:**
   ```bash
   mkdir -p ~/.config && echo 'NTFY_TOKEN=tk_yourtoken' > ~/.config/permit-panic.env && chmod 600 ~/.config/permit-panic.env
   export NTFY_TOKEN=tk_yourtoken
   ```
7. **Point it at your phone.** Replace the topic with yours from step 4:
   ```bash
   .venv/bin/permit-panic set ntfy_topic permit-panic-k7x2q9
   .venv/bin/permit-panic set digest_hour 8      # daily summary at 8am (server time)
   .venv/bin/permit-panic test-notify
   ```
   Your phone should buzz with "🐻 Permit Panic test".
8. **Run it 24/7:**
   ```bash
   mkdir -p ~/.config/systemd/user && cp deploy/permit-panic.service ~/.config/systemd/user/
   systemctl --user daemon-reload && systemctl --user enable --now permit-panic
   sudo loginctl enable-linger $USER
   ```
   Check it with `systemctl --user status permit-panic`. It should say **active (running)**.

## Use it

9. `cd ~/permit-panic && .venv/bin/permit-panic tui` → press **a** → search a park → pick it → fill in the form → **Save**. Within seconds your phone shows **✅ Now watching: …**. Press **m** to add lottery and release reminders, and **q** to quit. The watcher keeps running.

## Optional: alert if the server dies

10. Go to healthchecks.io → **Sign up** (free) → **Add Check** → set *Period* 10 min and *Grace* 10 min → **Save** → copy the ping URL. Then go to **Integrations** → **ntfy** → enter your topic → **Save Integration**. On the server, run:
    ```bash
    cd ~/permit-panic && .venv/bin/permit-panic set healthcheck_url https://hc-ping.com/YOUR-UUID
    ```
    No restart needed.
