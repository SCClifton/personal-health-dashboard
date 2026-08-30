#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

label="${HEALTH_AUTO_EXPORT_MONITOR_LABEL:-com.samuelclifton.personal-health-dashboard.apple-health-monitor}"
repo_dir="$(pwd)"
plist_dir="${HOME}/Library/LaunchAgents"
plist_path="${plist_dir}/${label}.plist"
log_dir="${repo_dir}/logs"
interval_seconds="${HEALTH_AUTO_EXPORT_MONITOR_INTERVAL_SECONDS:-3600}"
port="${PORT:-8000}"
max_age_hours="${MAX_APPLE_HEALTH_AGE_HOURS:-30}"
home_ip="${HEALTH_DASHBOARD_HOME_IP:-192.168.6.227}"
home_router="${HEALTH_DASHBOARD_HOME_ROUTER:-192.168.4.1}"
home_router_mac="${HEALTH_DASHBOARD_HOME_ROUTER_MAC:-}"

case "$repo_dir" in
  "${HOME}/Documents"/*)
    cat >&2 <<MSG
This repo is under ~/Documents, which macOS privacy controls can block from launchd.

Install the monitor from the live non-protected checkout instead, for example:

  cd ~/Developer/personal-health-dashboard
  scripts/install_health_auto_export_monitor.sh
MSG
    exit 1
    ;;
esac

mkdir -p "$plist_dir" "$log_dir"
chmod +x scripts/health_auto_export_monitor.sh scripts/health_network_mode.sh

cat >"$plist_path" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${repo_dir}/scripts/health_auto_export_monitor.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${repo_dir}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>StartInterval</key>
  <integer>${interval_seconds}</integer>
  <key>StandardOutPath</key>
  <string>${log_dir}/health-auto-export-monitor.out.log</string>
  <key>StandardErrorPath</key>
  <string>${log_dir}/health-auto-export-monitor.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>PORT</key>
    <string>${port}</string>
    <key>MAX_APPLE_HEALTH_AGE_HOURS</key>
    <string>${max_age_hours}</string>
    <key>EXPECTED_REPO_DIR</key>
    <string>${repo_dir}</string>
    <key>HEALTH_DASHBOARD_DB</key>
    <string>data/health_dashboard.db</string>
    <key>HEALTH_DASHBOARD_HOME_IP</key>
    <string>${home_ip}</string>
    <key>HEALTH_DASHBOARD_HOME_ROUTER</key>
    <string>${home_router}</string>
    <key>HEALTH_DASHBOARD_HOME_ROUTER_MAC</key>
    <string>${home_router_mac}</string>
  </dict>
</dict>
</plist>
PLIST

if launchctl print "gui/$(id -u)/${label}" >/dev/null 2>&1; then
  launchctl bootout "gui/$(id -u)" "$plist_path" >/dev/null 2>&1 || true
fi

launchctl bootstrap "gui/$(id -u)" "$plist_path"
launchctl kickstart -k "gui/$(id -u)/${label}"

echo "Installed and started ${label}"
echo "Trusted home signature: ${home_ip} or router ${home_router}/${home_router_mac:-unset}"
echo "Plist: ${plist_path}"
echo "Logs: ${log_dir}/health-auto-export-monitor.out.log and ${log_dir}/health-auto-export-monitor.err.log"
