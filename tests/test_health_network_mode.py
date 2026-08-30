from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "health_network_mode.sh"


def classify(
    wifi_ip: str,
    router: str,
    router_mac: str = "",
    home_router_mac: str = "",
) -> tuple[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "HEALTH_NETWORK_TEST_WIFI_IP": wifi_ip,
            "HEALTH_NETWORK_TEST_ROUTER": router,
            "HEALTH_NETWORK_TEST_ROUTER_MAC": router_mac,
            "HEALTH_DASHBOARD_HOME_IP": "192.168.6.227",
            "HEALTH_DASHBOARD_HOME_ROUTER": "192.168.4.1",
            "HEALTH_DASHBOARD_HOME_ROUTER_MAC": home_router_mac,
        }
    )
    command = (
        f'source "{HELPER}"; '
        'mode="$(health_network_mode)"; '
        'printf "%s %s\\n" "$mode" "$(health_bind_host "$mode")"'
    )
    result = subprocess.run(
        ["bash", "-c", command],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return tuple(result.stdout.strip().split())  # type: ignore[return-value]


def test_home_signature_allows_lan_binding() -> None:
    assert classify("192.168.6.227", "192.168.4.1") == ("home", "0.0.0.0")


def test_home_router_identity_allows_dhcp_address() -> None:
    assert classify(
        "192.168.4.40",
        "192.168.4.1",
        "d0:cb:dd:69:64:8d",
        "D0:CB:DD:69:64:8D",
    ) == ("home", "0.0.0.0")


def test_same_gateway_address_with_different_router_is_loopback_only() -> None:
    assert classify(
        "192.168.4.40",
        "192.168.4.1",
        "00:11:22:33:44:55",
        "d0:cb:dd:69:64:8d",
    ) == ("home_unreserved", "127.0.0.1")


def test_public_wifi_is_loopback_only() -> None:
    assert classify("172.17.33.112", "172.17.35.254") == ("away", "127.0.0.1")


def test_iphone_hotspot_is_loopback_only() -> None:
    assert classify("172.20.10.4", "172.20.10.1") == ("away", "127.0.0.1")


def test_home_gateway_without_reservation_is_loopback_only() -> None:
    assert classify("192.168.4.47", "192.168.4.1") == (
        "home_unreserved",
        "127.0.0.1",
    )


def test_no_wifi_is_loopback_only() -> None:
    assert classify("", "") == ("no_wifi", "127.0.0.1")
