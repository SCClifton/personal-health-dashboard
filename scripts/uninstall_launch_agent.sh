#!/usr/bin/env bash
set -euo pipefail

label="com.samuelclifton.personal-health-dashboard"
plist_path="${HOME}/Library/LaunchAgents/${label}.plist"

if launchctl print "gui/$(id -u)/${label}" >/dev/null 2>&1; then
  launchctl bootout "gui/$(id -u)" "$plist_path" >/dev/null 2>&1 || true
fi

rm -f "$plist_path"
echo "Uninstalled ${label}"
