# Local Mac deployment via launchd

Two LaunchAgents wire the pipeline so you never touch the terminal:

| Agent | Runs | Purpose |
|---|---|---|
| `com.stablemischief.smcrm-reviewui` | Continuously, from login | Serves the review UI at `http://127.0.0.1:8765/`. Restarts itself if it crashes. Bookmark the URL. |
| `com.stablemischief.smcrm-daily` | Once a day at 05:00 | Runs ingest → review-queue (+ weekly-plan on Mondays). Fires a macOS notification when items are waiting for review, so you know without having to check. |

The review UI is where James approves records — Approve triggers push-on-approve
to Twenty in the same request (gh #6). Sync itself is intentionally NOT on any
scheduler; nothing lands in the CRM without a human click.

## macOS TCC — the gotcha this recipe works around

macOS blocks LaunchAgent-launched processes from reading `~/Documents/` under
"Transparency, Consent, and Control." Terminal has its own Full Disk Access
grant so manual runs work fine, but launchd's Python child processes do not
inherit that. The working recipe below sidesteps the issue by:

1. Putting the venv **outside** `~/Documents/` (at `~/.venvs/sm-crm-system/`).
2. Building that venv from **python.org's Python** (`/usr/local/bin/python3`),
   NOT Anaconda's — Anaconda's binary is signed with entitlements that don't
   accept inherited FDA.
3. Putting the SQLite DB and mock-CRM state **outside** `~/Documents/` (at
   `~/.local/share/sm-crm-system/`) via `RI_DB_PATH` and `RI_MOCK_CRM_PATH` in
   `.env`.
4. Granting `/bin/zsh` Full Disk Access via System Settings so shell-level
   operations (reading the inbox folder, etc.) work from launchd.

## Install (one-time, in order)

```bash
# 1. Grant /bin/zsh Full Disk Access
#    System Settings → Privacy & Security → Full Disk Access → +
#    Cmd+Shift+G → /bin/zsh → Open → toggle on.

# 2. Build the venv from python.org's Python (not Anaconda).
python3 --version                                    # should be from /usr/local/bin
/usr/local/bin/python3 -m venv ~/.venvs/sm-crm-system
~/.venvs/sm-crm-system/bin/pip install --upgrade pip
cd ~/Documents/GitHub/SM-CRM-System                  # or wherever the repo lives
~/.venvs/sm-crm-system/bin/pip install .             # non-editable — files copied into the venv

# 3. Move state out of ~/Documents/.
mkdir -p ~/.local/share/sm-crm-system
cp output/relationship_intel.db ~/.local/share/sm-crm-system/  # if you have existing state
cp -R output/mock_crm ~/.local/share/sm-crm-system/mock_crm    # ditto

# 4. Point .env at the new state paths (absolute, not relative).
cat >> .env <<'EOF'
RI_DB_PATH=/Users/<you>/.local/share/sm-crm-system/relationship_intel.db
RI_MOCK_CRM_PATH=/Users/<you>/.local/share/sm-crm-system/mock_crm
EOF

# 5. Install and load the LaunchAgents.
cp scripts/launchd/com.stablemischief.smcrm-reviewui.plist ~/Library/LaunchAgents/
cp scripts/launchd/com.stablemischief.smcrm-daily.plist    ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.stablemischief.smcrm-reviewui.plist
launchctl load ~/Library/LaunchAgents/com.stablemischief.smcrm-daily.plist
```

Open http://127.0.0.1:8765/ and bookmark it. Done — nothing else to type.

## Verify

```bash
launchctl list | grep smcrm
# Expect a numeric PID (not `-`) next to smcrm-reviewui, and last exit code 0.
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8765/
# Expect 200.
```

Logs live at `output/logs/smcrm-{reviewui,daily}.stderr.log`.

## Manually fire the daily now (skip waiting for 05:00)

```bash
launchctl kickstart -k gui/$(id -u)/com.stablemischief.smcrm-daily
```

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.stablemischief.smcrm-reviewui.plist
launchctl unload ~/Library/LaunchAgents/com.stablemischief.smcrm-daily.plist
rm ~/Library/LaunchAgents/com.stablemischief.smcrm-reviewui.plist
rm ~/Library/LaunchAgents/com.stablemischief.smcrm-daily.plist
```

## Known caveat — the daily ingest writes to the vault

The daily script also writes notes into `~/Documents/<your vault>/relationship-intelligence/`.
That path IS inside `~/Documents/`, and the FDA-on-`/bin/zsh` trick may not
extend to Python's write calls into it either. If the daily agent stops
writing notes even though it fires successfully, either:

- Grant Full Disk Access to `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12`
  (the underlying binary the venv points to), or
- Move the vault path out of `~/Documents/` — but that would require
  reconfiguring your Obsidian install too.

The review UI itself only READS the DB (which lives at `~/.local/…`), so
the UI stays hot regardless of what happens to the daily agent.

## Cloud deployment note

When this moves to a cloud server:
- `serve-review-ui.sh` runs under systemd (or the platform's process
  supervisor) so the URL stays hot.
- `relationship-intel-daily.sh` runs under cron — same shell script, no
  changes.
- The macOS `osascript` notification calls become no-ops (guarded with
  `|| true`) or are replaced with the platform's own notification
  channel (Slack webhook, email, etc.).
- No TCC concerns on Linux.
