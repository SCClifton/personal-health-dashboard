#!/usr/bin/env bash
set -euo pipefail

label="com.samuelclifton.personal-health-dashboard.provider-refresh"
plist_path="/Users/samuelclifton/Library/LaunchAgents/${label}.plist"

launchctl bootout "gui/$(id -u)" "$plist_path" 2>/dev/null || true
if [[ -f "$plist_path" ]]; then
  rm "$plist_path"
fi

echo "Uninstalled ${label}; existing local data and logs were not removed."
