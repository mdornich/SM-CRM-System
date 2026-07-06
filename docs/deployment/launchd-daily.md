# Local Mac deployment via launchd

Two LaunchAgents wire the pipeline so you never touch the terminal:

| Agent | Runs | Purpose |
|---|---|---|
| `com.stablemischief.smcrm-reviewui` | Continuously, from login | Serves the review UI at `http://127.0.0.1:8765/`. Restarts itself if it crashes. Bookmark the URL. |
| `com.stablemischief.smcrm-daily` | Once a day at 05:00 | Runs ingest → review-queue (+ weekly-plan on Mondays). Fires a macOS notification when items are waiting for review, so you know without having to check. |

The review UI is where James approves records — Approve triggers push-on-approve
to Twenty in the same request (gh #6). Sync itself is intentionally NOT on any
scheduler; nothing lands in the CRM without a human click.

## Install (one-time)

```bash
# Both plists
cp scripts/launchd/com.stablemischief.smcrm-reviewui.plist ~/Library/LaunchAgents/
cp scripts/launchd/com.stablemischief.smcrm-daily.plist    ~/Library/LaunchAgents/

# Load them
launchctl load ~/Library/LaunchAgents/com.stablemischief.smcrm-reviewui.plist
launchctl load ~/Library/LaunchAgents/com.stablemischief.smcrm-daily.plist
```

Then open http://127.0.0.1:8765/ and bookmark it. Done — nothing else to type.

## Verify

```bash
launchctl list | grep smcrm
tail -f output/logs/smcrm-reviewui.stderr.log
tail -f output/logs/smcrm-daily.stderr.log
```

## Manually fire either now (without waiting for the schedule)

```bash
launchctl kickstart -k gui/$(id -u)/com.stablemischief.smcrm-daily
# Review UI is already running as a service; just refresh the browser
```

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.stablemischief.smcrm-reviewui.plist
launchctl unload ~/Library/LaunchAgents/com.stablemischief.smcrm-daily.plist
rm ~/Library/LaunchAgents/com.stablemischief.smcrm-reviewui.plist
rm ~/Library/LaunchAgents/com.stablemischief.smcrm-daily.plist
```

## Cloud deployment note

When this moves to a cloud server:
- The `serve-review-ui.sh` script runs under systemd (or the platform's
  process supervisor) so the URL stays hot.
- `relationship-intel-daily.sh` runs under cron — same shell script, no changes.
- The macOS `osascript` notification calls become no-ops (the `|| true`
  guards them) or are replaced with the platform's own notification
  channel (Slack webhook, email, etc.).
