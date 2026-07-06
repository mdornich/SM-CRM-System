# Daily ingest via launchd (local Mac testing)

The daily ingest pipeline is scheduled with a launchd agent, not cron. See
`scripts/launchd/com.stablemischief.smcrm-daily.plist`. It fires at 05:00 local
time and runs `scripts/relationship-intel-daily.sh` (which itself runs `init →
ingest → review-queue`, plus `weekly-plan` on Mondays).

Sync to Twenty is **not** triggered by the scheduler — it fires only when a
human approves records in the review UI (gh issue #6, push-on-approve).

## Install

```bash
cp scripts/launchd/com.stablemischief.smcrm-daily.plist \
   ~/Library/LaunchAgents/com.stablemischief.smcrm-daily.plist
launchctl load ~/Library/LaunchAgents/com.stablemischief.smcrm-daily.plist
```

## Verify

```bash
launchctl list | grep smcrm-daily
tail -f output/logs/smcrm-daily.stderr.log
```

## Trigger a run right now (without waiting for 05:00)

```bash
launchctl kickstart -k gui/$(id -u)/com.stablemischief.smcrm-daily
```

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.stablemischief.smcrm-daily.plist
rm ~/Library/LaunchAgents/com.stablemischief.smcrm-daily.plist
```

## Cloud deployment note

When this moves to a cloud server, the same `scripts/relationship-intel-daily.sh`
script runs under cron (e.g. `0 5 * * * cd /opt/sm-crm && ./scripts/relationship-intel-daily.sh`).
The script itself is portable — only the scheduler wrapper is Mac-specific.
