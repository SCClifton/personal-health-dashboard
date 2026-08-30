#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

label="com.samuelclifton.personal-health-dashboard"
repo_dir="$(pwd)"
plist_dir="${HOME}/Library/LaunchAgents"
plist_path="${plist_dir}/${label}.plist"
log_dir="${repo_dir}/logs"
home_ip="${HEALTH_DASHBOARD_HOME_IP:-192.168.6.227}"
home_router="${HEALTH_DASHBOARD_HOME_ROUTER:-192.168.4.1}"
home_router_mac="${HEALTH_DASHBOARD_HOME_ROUTER_MAC:-}"
poll_seconds="${HEALTH_DASHBOARD_NETWORK_POLL_SECONDS:-3}"

case "$repo_dir" in
  "${HOME}/Documents"/*)
    cat >&2 <<MSG
This repo is under ~/Documents, which macOS privacy controls can block from launchd.

Move the repo to a non-protected path such as ~/Developer/personal-health-dashboard,
or run the server manually from Terminal. Refusing to install a LaunchAgent that
will immediately fail with "Operation not permitted".
MSG
    exit 1
    ;;
esac

mkdir -p "$plist_dir" "$log_dir"

cat >"$plist_path" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${repo_dir}/scripts/start_health_dashboard_server.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${repo_dir}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${log_dir}/health-dashboard-server.out.log</string>
  <key>StandardErrorPath</key>
  <string>${log_dir}/health-dashboard-server.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>PYTHONPATH</key>
    <string>src</string>
    <key>HEALTH_DASHBOARD_HOME_IP</key>
    <string>${home_ip}</string>
    <key>HEALTH_DASHBOARD_HOME_ROUTER</key>
    <string>${home_router}</string>
    <key>HEALTH_DASHBOARD_HOME_ROUTER_MAC</key>
    <string>${home_router_mac}</string>
    <key>HEALTH_DASHBOARD_NETWORK_POLL_SECONDS</key>
    <string>${poll_seconds}</string>
  </dict>
</dict>
</plist>
PLIST

chmod +x scripts/start_health_dashboard_server.sh scripts/health_network_mode.sh

if launchctl print "gui/$(id -u)/${label}" >/dev/null 2>&1; then
  launchctl bootout "gui/$(id -u)" "$plist_path" >/dev/null 2>&1 || true
fi

launchctl bootstrap "gui/$(id -u)" "$plist_path"
launchctl kickstart -k "gui/$(id -u)/${label}"

echo "Installed and started ${label}"
echo "Trusted home signature: ${home_ip} or router ${home_router}/${home_router_mac:-unset}"
echo "Plist: ${plist_path}"
echo "Logs: ${log_dir}/health-dashboard-server.out.log and ${log_dir}/health-dashboard-server.err.log"
