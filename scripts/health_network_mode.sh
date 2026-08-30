#!/usr/bin/env bash

# Shared network classification for the dashboard launcher and freshness monitor.
# Test overrides are intentionally process-scoped and are not installed by launchd.

health_wifi_ip() {
  if [[ -n "${HEALTH_NETWORK_TEST_WIFI_IP+x}" ]]; then
    printf '%s\n' "${HEALTH_NETWORK_TEST_WIFI_IP}"
    return
  fi

  ipconfig getifaddr "${HEALTH_DASHBOARD_WIFI_INTERFACE:-en0}" 2>/dev/null || true
}

health_default_router() {
  if [[ -n "${HEALTH_NETWORK_TEST_ROUTER+x}" ]]; then
    printf '%s\n' "${HEALTH_NETWORK_TEST_ROUTER}"
    return
  fi

  route -n get default 2>/dev/null | awk '$1 == "gateway:" { print $2; exit }'
}

health_default_router_mac() {
  if [[ -n "${HEALTH_NETWORK_TEST_ROUTER_MAC+x}" ]]; then
    printf '%s\n' "$HEALTH_NETWORK_TEST_ROUTER_MAC" | tr '[:upper:]' '[:lower:]'
    return
  fi

  local router="${1:-$(health_default_router)}"
  [[ -z "$router" ]] && return
  arp -n "$router" 2>/dev/null | awk '/ at / { print tolower($4); exit }'
}

health_network_mode() {
  local wifi_ip router router_mac home_ip home_router home_router_mac
  wifi_ip="$(health_wifi_ip)"
  router="$(health_default_router)"
  router_mac="$(health_default_router_mac "$router")"
  home_ip="${HEALTH_DASHBOARD_HOME_IP:-192.168.6.227}"
  home_router="${HEALTH_DASHBOARD_HOME_ROUTER:-192.168.4.1}"
  home_router_mac="$(printf '%s' "${HEALTH_DASHBOARD_HOME_ROUTER_MAC:-}" | tr '[:upper:]' '[:lower:]')"

  if [[ -z "$wifi_ip" ]]; then
    printf 'no_wifi\n'
  elif [[ -n "$home_router_mac" && "$router" == "$home_router" && "$router_mac" == "$home_router_mac" ]]; then
    printf 'home\n'
  elif [[ "$wifi_ip" == "$home_ip" && "$router" == "$home_router" ]]; then
    printf 'home\n'
  elif [[ "$router" == "$home_router" ]]; then
    printf 'home_unreserved\n'
  else
    printf 'away\n'
  fi
}

health_bind_host() {
  local mode="${1:-$(health_network_mode)}"
  if [[ "$mode" == "home" ]]; then
    printf '0.0.0.0\n'
  else
    printf '127.0.0.1\n'
  fi
}

health_network_summary() {
  local wifi_ip router router_mac mode bind_host
  wifi_ip="$(health_wifi_ip)"
  router="$(health_default_router)"
  router_mac="$(health_default_router_mac "$router")"
  mode="$(health_network_mode)"
  bind_host="$(health_bind_host "$mode")"
  printf 'mode=%s wifi_ip=%s router=%s router_mac=%s bind_host=%s\n' \
    "$mode" "${wifi_ip:-none}" "${router:-none}" "${router_mac:-none}" "$bind_host"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  health_network_summary
fi
