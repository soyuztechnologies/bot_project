import ipaddress
import json
import subprocess
import sys
import time
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.json"

IP_CHECK_URL = "https://api.ipify.org"


def _load_vpn_config():
    """Load VPN configuration from config.json."""

    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Configuration file not found: {CONFIG_PATH}"
        )

    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        config = json.load(file)

    vpn_config = config.get("vpn", {})

    if not isinstance(vpn_config, dict):
        raise RuntimeError(
            "Invalid VPN configuration in config.json."
        )

    return vpn_config


def _get_nordvpn_dir():
    """Return the configured NordVPN installation directory."""

    vpn_config = _load_vpn_config()

    provider = str(
        vpn_config.get("provider", "nordvpn")
    ).strip().lower()

    if provider != "nordvpn":
        raise RuntimeError(
            f"Unsupported VPN provider: {provider}"
        )

    installation_dir = vpn_config.get("installation_dir")

    if not installation_dir:
        raise RuntimeError(
            "VPN installation_dir is missing in config.json."
        )

    nordvpn_dir = Path(installation_dir)

    if not nordvpn_dir.exists():
        raise FileNotFoundError(
            f"NordVPN installation directory not found: "
            f"{nordvpn_dir}"
        )

    return nordvpn_dir


def _run_nordvpn_command(action):
    """Run a NordVPN CLI command."""

    nordvpn_dir = _get_nordvpn_dir()

    command = [
        "cmd",
        "/c",
        "cd",
        "/d",
        str(nordvpn_dir),
        "&&",
        "nordvpn",
        action,
    ]

    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"NordVPN command timed out after 60 seconds: {action}"
        ) from exc
    except OSError as exc:
        raise RuntimeError(
            f"Failed to execute NordVPN command '{action}': {exc}"
        ) from exc


def _is_nordlynx_active():
    """Return True when NordLynx has an active default route."""

    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        (
            "Get-NetRoute "
            "-InterfaceAlias 'NordLynx' "
            "-DestinationPrefix '0.0.0.0/0' "
            "-ErrorAction SilentlyContinue | "
            "Where-Object {$_.State -eq 'Alive'} | "
            "Select-Object -First 1"
        ),
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False

    return result.returncode == 0 and bool(result.stdout.strip())


def get_public_ip():
    """Return the current public IP address."""

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import urllib.request; "
                "print(urllib.request.urlopen("
                f"'{IP_CHECK_URL}', timeout=10"
                ").read().decode())"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Unable to determine public IP: "
            f"{result.stderr.strip()}"
        )

    ip_address = result.stdout.strip()

    if not ip_address:
        raise RuntimeError(
            "Public IP check returned an empty result."
        )

    try:
        ipaddress.ip_address(ip_address)
    except ValueError as exc:
        raise RuntimeError(
            f"Public IP check returned an invalid IP address: {ip_address}"
        ) from exc

    return ip_address


def connect_vpn():
    """Connect to NordVPN and verify the VPN connection."""

    vpn_config = _load_vpn_config()

    if not vpn_config.get("enabled", False):
        print("[VPN] VPN is disabled in config.")
        return True

    print("[VPN] Checking current public IP...")

    original_ip = get_public_ip()

    print(f"[VPN] Current public IP: {original_ip}")

    if _is_nordlynx_active():
        print("[VPN] NordLynx is already active.")
        return False

    print("[VPN] Connecting to NordVPN...")

    result = _run_nordvpn_command("-c")

    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip()

        raise RuntimeError(
            f"NordVPN connection failed: {error}"
        )

    verify_connection = vpn_config.get(
        "verify_connection",
        True,
    )

    if not verify_connection:
        print("[VPN] Connection verification disabled.")
        return True

    for attempt in range(1, 7):
        time.sleep(5)

        try:
            current_ip = get_public_ip()
        except Exception as exc:
            print(
                f"[VPN] IP check failed "
                f"(attempt {attempt}/6): {exc}"
            )
            continue

        print(
            f"[VPN] Connection check "
            f"{attempt}/6: {current_ip}"
        )

        if current_ip != original_ip:
            print("[VPN] VPN connection verified.")
            return True

    try:
        print("[VPN] Connection could not be verified.")
        print("[VPN] Attempting automatic VPN disconnect...")

        disconnect_result = _run_nordvpn_command("-d")

        if disconnect_result.returncode != 0:
            error = (
                disconnect_result.stderr.strip()
                or disconnect_result.stdout.strip()
            )

            raise RuntimeError(
                f"Automatic VPN disconnect failed: {error}"
            )

    except Exception as cleanup_error:
        raise RuntimeError(
            "NordVPN connection could not be verified, and "
            f"automatic disconnect failed: {cleanup_error}"
        ) from cleanup_error

    raise RuntimeError(
        "NordVPN command completed, but the public IP did not change. "
        "VPN connection could not be verified. "
        "VPN was automatically disconnected."
    )


def disconnect_vpn():
    """Disconnect from NordVPN and verify the VPN is disconnected."""

    vpn_config = _load_vpn_config()

    if not vpn_config.get("enabled", False):
        print("[VPN] VPN is disabled in config.")
        return True

    print("[VPN] Checking current public IP...")

    vpn_ip = get_public_ip()

    print(f"[VPN] Current public IP: {vpn_ip}")

    if not _is_nordlynx_active():
        print("[VPN] NordLynx is already disconnected.")
        return False

    print("[VPN] Disconnecting from NordVPN...")

    result = _run_nordvpn_command("-d")

    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip()

        raise RuntimeError(
            f"NordVPN disconnection failed: {error}"
        )

    verify_connection = vpn_config.get(
        "verify_connection",
        True,
    )

    if not verify_connection:
        print("[VPN] Disconnection verification disabled.")
        return True

    for attempt in range(1, 7):
        time.sleep(5)

        try:
            current_ip = get_public_ip()
        except Exception as exc:
            print(
                f"[VPN] IP check failed "
                f"(attempt {attempt}/6): {exc}"
            )
            continue

        print(
            f"[VPN] Disconnection check "
            f"{attempt}/6: {current_ip}"
        )

        if current_ip != vpn_ip:
            print("[VPN] VPN disconnection verified.")
            return True

    raise RuntimeError(
        "NordVPN command completed, but the public IP "
        "did not change. VPN disconnection could not be verified."
    )