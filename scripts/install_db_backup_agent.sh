#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

label="${HEALTH_DB_BACKUP_LABEL:-com.samuelclifton.personal-health-dashboard.db-backup}"
repo_dir="$(pwd)"
plist_dir="${HOME}/Library/LaunchAgents"
plist_path="${plist_dir}/${label}.plist"
log_dir="${repo_dir}/logs"
interval_seconds="${HEALTH_DB_BACKUP_INTERVAL_SECONDS:-86400}"
db_path="${HEALTH_DB_BACKUP_DB:-${repo_dir}/data/health_dashboard.db}"
backup_dir="${HEALTH_DB_BACKUP_DIR:-${repo_dir}/local_exports/db_backups}"

mkdir -p "$plist_dir" "$log_dir" "$backup_dir"
chmod +x scripts/backup_health_db.py

cat >"$plist_path" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${repo_dir}/.venv/bin/python</string>
    <string>${repo_dir}/scripts/backup_health_db.py</string>
    <string>--db</string>
    <string>${db_path}</string>
    <string>--out-dir</string>
    <string>${backup_dir}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${repo_dir}</string>
  <key>StartInterval</key>
  <integer>${interval_seconds}</integer>
  <key>StandardOutPath</key>
  <string>${log_dir}/db-backup.out.log</string>
  <key>StandardErrorPath</key>
  <string>${log_dir}/db-backup.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
</dict>
</plist>
PLIST

if launchctl print "gui/$(id -u)/${label}" >/dev/null 2>&1; then
  launchctl bootout "gui/$(id -u)" "$plist_path" >/dev/null 2>&1 || true
fi

launchctl bootstrap "gui/$(id -u)" "$plist_path"

echo "Installed ${label}"
echo "Plist: ${plist_path}"
echo "Interval seconds: ${interval_seconds}"
echo "Backups: ${backup_dir}"
