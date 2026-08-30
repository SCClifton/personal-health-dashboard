#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
label="com.samuelclifton.personal-health-dashboard.provider-refresh"
plist_path="/Users/samuelclifton/Library/LaunchAgents/${label}.plist"
log_dir="${project_dir}/logs"

mkdir -p "$log_dir"

tmp_plist="$(mktemp)"
trap 'rm -f "$tmp_plist"' EXIT

cat >"$tmp_plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${project_dir}/scripts/run_health_report_with_op_env.sh</string>
    <string>${project_dir}/.venv/bin/python</string>
    <string>${project_dir}/scripts/auto_health_report.py</string>
    <string>--days</string>
    <string>180</string>
    <string>--sync-days</string>
    <string>7</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${project_dir}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>PYTHONPATH</key>
    <string>src</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>StartInterval</key>
  <integer>21600</integer>
  <key>StandardOutPath</key>
  <string>${log_dir}/provider-refresh.out.log</string>
  <key>StandardErrorPath</key>
  <string>${log_dir}/provider-refresh.err.log</string>
</dict>
</plist>
PLIST

plutil -lint "$tmp_plist"
cp "$tmp_plist" "$plist_path"
launchctl bootout "gui/$(id -u)" "$plist_path" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$plist_path"

echo "Installed ${label}"
echo "Schedule: every 6 hours with a 7-day idempotent overlap"
echo "Logs: ${log_dir}/provider-refresh.out.log and ${log_dir}/provider-refresh.err.log"
