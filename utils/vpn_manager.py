import ipaddress
import json
import logging
import subprocess
import sys
import time
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.json"

IP_CHECK_URL = "https://api.ipify.org"

# Short timeouts so a stuck VPN never blocks automation for minutes.
CONNECT_TIMEOUT = 30
DISCONNECT_TIMEOUT = 20

logger = logging.getLogger(__name__)


def _warn(message):
    """Log/print a VPN warning without ever raising.

    VPN failures must only warn and let automation continue.
    """
    try:
        print(f"[VPN WARNING] {message} Continuing without VPN.", flush=True)
    except Exception:
        pass
    try:
        logger.warning("[VPN] %s Continuing without VPN.", message)
    except Exception:
        pass


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


def _probe_cli(cli_path, timeout=6):
    """Return True only if exe behaves like a CLI (exits on --help).

    `NordVPN.exe` is a GUI: it never exits, so the probe times out
    and we reject it. Ctrl+C kills the probe instantly and re-raises.
    """
    proc = None
    try:
        proc = subprocess.Popen(
            [str(cli_path), "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:
                pass
            try:
                proc.communicate(timeout=3)
            except Exception:
                pass
            return False
        output = f"{stdout or ''}\n{stderr or ''}".strip()
        # A real CLI exits and prints usage; GUI either hangs
        # (handled above) or exits with no CLI-style output.
        if not output:
            return proc.returncode == 0
        lowered = output.lower()
        return any(
            token in lowered
            for token in ("usage", "connect", "disconnect", "nordvpn", "options", "commands")
        )
    except KeyboardInterrupt:
        try:
            if proc is not None and proc.poll() is None:
                proc.kill()
        except Exception:
            pass
        raise
    except Exception:
        return False


def _find_nordvpn_cli(nordvpn_dir):
    """Find the real NordVPN CLI exe, never the GUI.

    On Windows `C:\\Program Files\\NordVPN` only contains
    `NordVPN.exe` (GUI) + services. Because the FS is
    case-insensitive, `nordvpn.exe` resolves to that GUI, which
    never exits and used to block Ctrl+C until the app was
    manually closed. Probe candidates and fail fast instead.
    """
    # Explicit override wins (e.g. user installs a real CLI elsewhere).
    try:
        vpn_config = _load_vpn_config()
        cli_override = (vpn_config.get("cli_path") or "").strip() if isinstance(vpn_config, dict) else ""
        if cli_override:
            override_path = Path(cli_override)
            if override_path.is_file():
                return override_path
    except Exception:
        pass

    seen = set()
    candidates = []
    for name in ("nordvpn-cli.exe", "nordvpn.exe"):
        p = nordvpn_dir / name
        key = str(p).lower()
        if key not in seen:
            seen.add(key)
            candidates.append(p)
    # Any other nordvpn*.exe in the dir (services etc. get probed
    # and rejected, not blindly executed with -c).
    try:
        for child in nordvpn_dir.iterdir():
            try:
                if child.is_file() and child.name.lower().startswith("nordvpn"):
                    key = str(child).lower()
                    if key not in seen:
                        seen.add(key)
                        candidates.append(child)
            except Exception:
                continue
    except Exception:
        pass

    last_error = ""
    for candidate in candidates:
        try:
            if not candidate.is_file():
                continue
        except Exception:
            continue
        try:
            if _probe_cli(candidate):
                return candidate
            last_error = f"{candidate.name} did not respond like a CLI"
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            last_error = str(exc)
            continue
    raise RuntimeError(
        f"No NordVPN CLI found in {nordvpn_dir} "
        f"(only NordVPN.exe GUI/services exist there{': ' + last_error if last_error else ''}). "
        f"Disable VPN with \"vpn.enabled\": false, or set "
        f"\"vpn.cli_path\" to a real CLI. Skipping VPN."
    )


def _run_nordvpn_command(action, timeout):
    """Run a NordVPN CLI command, always killable by timeout/Ctrl+C.

    Uses Popen + communicate so KeyboardInterrupt immediately kills
    the child instead of hanging until the GUI is manually closed.
    Never leaves an orphaned `NordVPN.exe` blocking the console.
    """

    nordvpn_dir = _get_nordvpn_dir()
    cli_path = _find_nordvpn_cli(nordvpn_dir)

    proc = None
    try:
        proc = subprocess.Popen(
            [str(cli_path), action],
            cwd=str(nordvpn_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            try:
                proc.kill()
            except Exception:
                pass
            # Preserve any partial output (e.g. "please log in") for diagnosis.
            partial = ""
            try:
                part_out = exc.stdout or ""
                part_err = exc.stderr or ""
                if isinstance(part_out, bytes):
                    part_out = part_out.decode("utf-8", errors="ignore")
                if isinstance(part_err, bytes):
                    part_err = part_err.decode("utf-8", errors="ignore")
                partial = (part_out.strip() or part_err.strip())[:300]
            except Exception:
                partial = ""
            try:
                stdout, stderr = proc.communicate(timeout=5)
            except Exception:
                stdout, stderr = "", ""
            detail = f" {partial}" if partial else ""
            raise RuntimeError(
                f"NordVPN command timed out after {timeout} seconds: {action}.{detail}"
            ) from exc
        return subprocess.CompletedProcess(
            args=[str(cli_path), action],
            returncode=proc.returncode,
            stdout=stdout or "",
            stderr=stderr or "",
        )
    except RuntimeError:
        raise
    except KeyboardInterrupt:
        # Ctrl+C must work instantly: kill child, then re-raise
        # so callers can abort the VPN attempt (not hang).
        try:
            if proc is not None and proc.poll() is None:
                proc.kill()
        except Exception:
            pass
        raise
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
    except KeyboardInterrupt:
        raise
    except Exception:
        return False

    return result.returncode == 0 and bool((result.stdout or "").strip())


def get_public_ip():
    """Return the current public IP address."""

    try:
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
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Public IP check timed out: {exc}"
        ) from exc
    except OSError as exc:
        raise RuntimeError(
            f"Failed to run public IP check: {exc}"
        ) from exc
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        raise RuntimeError(
            f"Unexpected error during public IP check: {exc}"
        ) from exc

    if result.returncode != 0:
        raise RuntimeError(
            f"Unable to determine public IP: "
            f"{(result.stderr or '').strip()}"
        )

    ip_address = (result.stdout or "").strip()

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


def _interruptible_sleep(seconds, chunk=0.5):
    """Sleep that wakes quickly on Ctrl+C (raises KeyboardInterrupt)."""
    end = time.time() + max(0, seconds)
    while True:
        remaining = end - time.time()
        if remaining <= 0:
            return
        time.sleep(min(chunk, remaining))


def connect_vpn():
    """Connect to NordVPN and verify the VPN connection.

    Never raises on VPN/installation/network errors: logs a warning,
    skips VPN, and returns False so automation keeps running.
    KeyboardInterrupt/SystemExit still propagate so Ctrl+C works.
    """

    try:
        vpn_config = _load_vpn_config()

        if not vpn_config.get("enabled", False):
            print("[VPN] VPN is disabled in config.", flush=True)
            return False

        print("[VPN] Checking current public IP...", flush=True)

        original_ip = get_public_ip()

        print(f"[VPN] Current public IP: {original_ip}", flush=True)

        if _is_nordlynx_active():
            print("[VPN] NordLynx is already active.", flush=True)
            return False

        print(
            "[VPN] Connecting to NordVPN... "
            "(skips automatically on failure, Ctrl+C aborts VPN only)",
            flush=True,
        )

        def _cfg_int(name, default, minimum=1, maximum=120):
            try:
                value = int(vpn_config.get(name, default))
            except Exception:
                value = default
            return max(minimum, min(maximum, value))

        connect_timeout = _cfg_int("connect_timeout", CONNECT_TIMEOUT)
        verify_attempts = _cfg_int("verify_attempts", 6, 1, 12)
        verify_delay = _cfg_int("verify_delay", 5, 1, 30)
        disconnect_timeout = _cfg_int("disconnect_timeout", DISCONNECT_TIMEOUT)

        result = _run_nordvpn_command("-c", timeout=connect_timeout)

        if result.returncode != 0:
            error = (result.stderr or "").strip() or (result.stdout or "").strip()

            raise RuntimeError(
                f"NordVPN connection failed: {error}"
            )

        verify_connection = vpn_config.get(
            "verify_connection",
            True,
        )

        if not verify_connection:
            print("[VPN] Connection verification disabled.", flush=True)
            return True

        for attempt in range(1, verify_attempts + 1):
            _interruptible_sleep(verify_delay)

            try:
                current_ip = get_public_ip()
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                print(
                    f"[VPN] IP check failed "
                    f"(attempt {attempt}/{verify_attempts}): {exc}",
                    flush=True,
                )
                continue

            print(
                f"[VPN] Connection check "
                f"{attempt}/{verify_attempts}: {current_ip}",
                flush=True,
            )

            if current_ip != original_ip:
                print("[VPN] VPN connection verified.", flush=True)
                return True

        # Verification failed: try to disconnect, but never hang.
        try:
            print("[VPN] Connection could not be verified.", flush=True)
            print("[VPN] Attempting automatic VPN disconnect...", flush=True)

            disconnect_result = _run_nordvpn_command("-d", timeout=disconnect_timeout)

            if disconnect_result.returncode != 0:
                error = (
                    (disconnect_result.stderr or "").strip()
                    or (disconnect_result.stdout or "").strip()
                )

                raise RuntimeError(
                    f"Automatic VPN disconnect failed: {error}"
                )

        except KeyboardInterrupt:
            raise
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
    except (KeyboardInterrupt, SystemExit):
        # Let the caller decide: abort VPN attempt, propagate Ctrl+C.
        # Child process is already killed in _run_nordvpn_command.
        print("[VPN] VPN connect aborted by user (Ctrl+C).", flush=True)
        raise
    except Exception as exc:
        _warn(f"Skipping VPN connection due to error: {exc}")
        return False


def disconnect_vpn():
    """Disconnect from NordVPN and verify the VPN is disconnected.

    Never raises on VPN/network errors: logs a warning and returns
    False so shutdown keeps running. KeyboardInterrupt propagates.
    """

    try:
        vpn_config = _load_vpn_config()

        if not vpn_config.get("enabled", False):
            print("[VPN] VPN is disabled in config.", flush=True)
            return False

        print("[VPN] Checking current public IP...", flush=True)

        try:
            vpn_ip = get_public_ip()
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            _warn(f"Skipping VPN disconnect (IP check failed): {exc}")
            return False

        print(f"[VPN] Current public IP: {vpn_ip}", flush=True)

        if not _is_nordlynx_active():
            print("[VPN] NordLynx is already disconnected.", flush=True)
            return False

        print("[VPN] Disconnecting from NordVPN...", flush=True)

        def _cfg_int(name, default, minimum=1, maximum=120):
            try:
                value = int(vpn_config.get(name, default))
            except Exception:
                value = default
            return max(minimum, min(maximum, value))

        disconnect_timeout = _cfg_int("disconnect_timeout", DISCONNECT_TIMEOUT)
        verify_attempts = _cfg_int("verify_attempts", 6, 1, 12)
        verify_delay = _cfg_int("verify_delay", 5, 1, 30)

        result = _run_nordvpn_command("-d", timeout=disconnect_timeout)

        if result.returncode != 0:
            error = (result.stderr or "").strip() or (result.stdout or "").strip()

            raise RuntimeError(
                f"NordVPN disconnection failed: {error}"
            )

        verify_connection = vpn_config.get(
            "verify_connection",
            True,
        )

        if not verify_connection:
            print("[VPN] Disconnection verification disabled.", flush=True)
            return True

        for attempt in range(1, verify_attempts + 1):
            _interruptible_sleep(verify_delay)

            try:
                current_ip = get_public_ip()
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                print(
                    f"[VPN] IP check failed "
                    f"(attempt {attempt}/{verify_attempts}): {exc}",
                    flush=True,
                )
                continue

            print(
                f"[VPN] Disconnection check "
                f"{attempt}/{verify_attempts}: {current_ip}",
                flush=True,
            )

            if current_ip != vpn_ip:
                print("[VPN] VPN disconnection verified.", flush=True)
                return True

        raise RuntimeError(
            "NordVPN command completed, but the public IP "
            "did not change. VPN disconnection could not be verified."
        )
    except (KeyboardInterrupt, SystemExit):
        print("[VPN] VPN disconnect aborted by user (Ctrl+C).", flush=True)
        raise
    except Exception as exc:
        _warn(f"Skipping VPN disconnect due to error: {exc}")
        return False
