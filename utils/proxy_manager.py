"""
proxy_manager.py

IP bouncing / proxy rotation for SEO automation.

Goal: avoid Google / Bing / Yahoo / DuckDuckGo CAPTCHAs ("unusual traffic")
caused by N parallel browsers sharing ONE public IP.

Supports the recommended setup:
  - Rotating residential proxy: ONE gateway URL whose provider rotates the
    exit IP automatically (Bright Data, Oxylabs, Webshare, Decodo, etc.)
  - Static proxy list: N proxy URLs, round-robin one per browser session.

Usage:
    from utils.proxy_manager import get_proxy_for_session, mask_proxy, stagger_start

    proxy_url = get_proxy_for_session(config)   # None when disabled
    driver = setup_browser(config, browser_name, proxy_url=proxy_url)

Config (config.json):
    "proxy": {
      "enabled": false,
      "mode": "single",              # "single" | "list"
      "url": "${PROXY_URL}",         # single rotating endpoint (may be env placeholder)
      "proxies_file": "data/proxies.json",
      "rotation": "per_session",     # only "per_session" is supported (one IP per browser)
      "force_new_ip_per_session": false,
      "session_suffix_param": "",
      "max_failures": 3,
      "stagger_min": 1.0,            # random startup stagger to avoid thundering herd
      "stagger_max": 3.0
    }

Env (.env):
    PROXY_URL=http://user:pass@gateway.provider.com:port
    # optional second source for list mode:
    # PROXY_LIST=http://u1:p1@host1:port,http://u2:p2@host2:port

proxies_file formats accepted:
    - JSON list: ["http://u:p@h:port", ...] or [{"url": "..."}, ...]
    - JSON object: {"proxies": [...]}
    - TXT: one proxy URL per line (lines starting with # ignored)

Security: passwords are NEVER logged — always use mask_proxy() for output.
Failures never raise: disabled / misconfigured proxy returns None so the
automation continues on direct connection with a warning.
"""

import json
import logging
import os
import random
import re
import threading
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).resolve().parent.parent

_LOCK = threading.Lock()
_INDEX = 0
_CACHED_LIST: list = []
_CACHED_KEY: str = ""
_FAILURES: dict = {}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _expand_placeholders(value: str) -> str:
    """Expand ${VAR} / $VAR and leading ~ using environment variables."""

    if not value or not isinstance(value, str):
        return value
    try:
        # os.path.expandvars handles $VAR and ${VAR} on Windows too
        return os.path.expandvars(os.path.expanduser(value))
    except Exception:
        return value


def mask_proxy(proxy_url) -> str:
    """Mask password for safe logging: user:***@host:port."""

    if not proxy_url:
        return "direct (no proxy)"
    try:
        text = str(proxy_url).strip()
        # scheme://user:pass@host... -> scheme://user:***@host...
        masked = re.sub(
            r"(://[^/:\s]+:)([^/@\s]+)(@)",
            r"\1***\3",
            text,
        )
        return masked
    except Exception:
        return "proxy:***"


def _proxy_config(config) -> dict:
    try:
        proxy_cfg = (config or {}).get("proxy", {}) or {}
        return proxy_cfg if isinstance(proxy_cfg, dict) else {}
    except Exception:
        return {}


def is_enabled(config) -> bool:
    """Return True when proxy rotation is enabled and has a usable source."""

    try:
        cfg = _proxy_config(config)
        if not cfg.get("enabled", False):
            return False
        mode = str(cfg.get("mode", "single")).strip().lower()
        if mode == "list":
            return bool(load_proxies(config))
        # single mode: need a URL from config or env
        return bool(_single_url(config))
    except Exception:
        return False


def _single_url(config) -> str:
    """Resolve the single rotating endpoint from config / env."""

    cfg = _proxy_config(config)
    raw = str(cfg.get("url", "") or "").strip()
    raw = _expand_placeholders(raw)
    if raw and not raw.startswith("${"):
        return raw
    # Fallback to env (lets user keep credentials out of git)
    for env_name in ("PROXY_URL", "HTTP_PROXY_URL", "HTTPS_PROXY_URL"):
        env_val = (os.getenv(env_name) or "").strip().strip("\"'")
        if env_val:
            return env_val
    return ""


def _proxies_file_path(config) -> Path:
    cfg = _proxy_config(config)
    rel = str(cfg.get("proxies_file", "data/proxies.json") or "data/proxies.json")
    rel = _expand_placeholders(rel)
    path = Path(rel)
    if not path.is_absolute():
        path = _BASE_DIR / path
    return path


def load_proxies(config) -> list:
    """Load static proxy list (cached). Never raises — returns []."""

    global _CACHED_LIST, _CACHED_KEY
    try:
        cfg = _proxy_config(config)
        # 1) inline list in config has highest priority
        inline = cfg.get("proxies") or cfg.get("list") or []
        candidates: list = []
        if isinstance(inline, list) and inline:
            for item in inline:
                if isinstance(item, dict):
                    url = str(item.get("url", "") or "").strip()
                else:
                    url = str(item or "").strip()
                url = _expand_placeholders(url)
                if url and not url.startswith("${"):
                    candidates.append(url)
            if candidates:
                with _LOCK:
                    _CACHED_LIST = list(candidates)
                    _CACHED_KEY = "inline"
                return list(candidates)

        # 2) env PROXY_LIST (comma/newline separated)
        env_list = (os.getenv("PROXY_LIST") or "").strip()
        if env_list:
            parts = re.split(r"[\n,;]+", env_list)
            env_proxies = [_expand_placeholders(p.strip().strip("\"'")) for p in parts]
            env_proxies = [p for p in env_proxies if p and not p.startswith("${")]
            if env_proxies:
                with _LOCK:
                    _CACHED_LIST = list(env_proxies)
                    _CACHED_KEY = "env"
                return list(env_proxies)

        # 3) file (json or txt)
        path = _proxies_file_path(config)
        try:
            mtime = str(path.stat().st_mtime) if path.exists() else "missing"
        except Exception:
            mtime = "missing"
        cache_key = f"{path}:{mtime}"
        with _LOCK:
            if cache_key == _CACHED_KEY and _CACHED_LIST:
                return list(_CACHED_LIST)
        file_proxies: list = []
        if path.exists():
            text = path.read_text(encoding="utf-8", errors="ignore").strip()
            if text:
                if path.suffix.lower() == ".json":
                    try:
                        data = json.loads(text)
                    except Exception as exc:
                        logger.warning("[PROXY] proxies file is not valid JSON: %s (%s)", path, exc)
                        data = None
                    if isinstance(data, dict):
                        data = data.get("proxies") or data.get("list") or []
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict):
                                url = str(item.get("url", "") or "").strip()
                            else:
                                url = str(item or "").strip()
                            url = _expand_placeholders(url)
                            if url and not url.startswith("${"):
                                file_proxies.append(url)
                else:
                    # txt: one URL per line
                    for line in text.splitlines():
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        line = _expand_placeholders(line)
                        if line and not line.startswith("${"):
                            file_proxies.append(line)
        with _LOCK:
            _CACHED_LIST = list(file_proxies)
            _CACHED_KEY = cache_key
        return list(file_proxies)
    except Exception as exc:
        logger.warning("[PROXY] load_proxies failed (continuing direct): %s", exc)
        return []


def validate_proxy_format(proxy_url: str) -> bool:
    """Basic sanity check: must contain host:port."""

    if not proxy_url or not isinstance(proxy_url, str):
        return False
    text = proxy_url.strip()
    if "://" in text:
        text = text.split("://", 1)[1]
    # strip user:pass@
    if "@" in text:
        text = text.rsplit("@", 1)[1]
    return ":" in text and len(text.split(":")[0]) >= 3


def _with_forced_session(proxy_url: str, config) -> str:
    """Optionally force a fresh exit IP per browser session.

    Many residential providers rotate IP per super-proxy session id, e.g.
    username-session-<random>. Enabled only when config sets:
        "force_new_ip_per_session": true
    Otherwise the URL is returned unchanged (provider default rotation).
    """

    try:
        cfg = _proxy_config(config)
        if not cfg.get("force_new_ip_per_session", False):
            return proxy_url
        text = proxy_url.strip()
        scheme = ""
        rest = text
        if "://" in text:
            scheme, rest = text.split("://", 1)
            scheme += "://"
        if "@" not in rest:
            return proxy_url  # no username to attach session to
        creds, host = rest.rsplit("@", 1)
        suffix = str(cfg.get("session_suffix_param", "") or "").strip() or "session"
        token = f"{suffix}-{uuid.uuid4().hex[:8]}"
        # Bright Data / Oxylabs style: append -session-<id> to username
        if ":" in creds:
            user, pwd = creds.split(":", 1)
            new_creds = f"{user}-{token}:{pwd}"
        else:
            new_creds = f"{creds}-{token}"
        return f"{scheme}{new_creds}@{host}"
    except Exception:
        return proxy_url


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def get_proxy_for_session(config, session_hint: str = "") -> str | None:
    """Return one proxy URL for the current browser session.

    - disabled / misconfigured -> None (direct connection, warning logged once)
    - mode=single -> the rotating endpoint (optionally with forced session id)
    - mode=list   -> round-robin next healthy proxy, skipping ones that
                     exceeded max_failures consecutive failures.
    Never raises.
    """

    _ = session_hint
    try:
        cfg = _proxy_config(config)
        if not cfg.get("enabled", False):
            return None
        mode = str(cfg.get("mode", "single")).strip().lower()

        if mode == "list":
            proxies = load_proxies(config)
            if not proxies:
                logger.warning(
                    "[PROXY] mode=list but no proxies found "
                    "(config proxies / PROXY_LIST / %s). Continuing direct.",
                    _proxies_file_path(config),
                )
                return None
            max_failures = 3
            try:
                max_failures = max(1, int(cfg.get("max_failures", 3)))
            except Exception:
                max_failures = 3
            global _INDEX
            with _LOCK:
                # find next proxy below failure threshold (single pass over list)
                for _ in range(len(proxies)):
                    candidate = proxies[_INDEX % len(proxies)]
                    _INDEX += 1
                    if _FAILURES.get(candidate, 0) < max_failures:
                        return candidate
                # all flagged bad -> reset counters and reuse round-robin
                # (proxies may have recovered; better than going direct)
                _FAILURES.clear()
                candidate = proxies[_INDEX % len(proxies)]
                _INDEX += 1
                return candidate

        # default: single rotating endpoint
        url = _single_url(config)
        if not url:
            logger.warning(
                "[PROXY] enabled but no proxy URL found "
                "(set proxy.url in config.json or PROXY_URL in .env). Continuing direct."
            )
            return None
        if not validate_proxy_format(url):
            logger.warning("[PROXY] proxy URL looks invalid (%s). Continuing direct.", mask_proxy(url))
            return None
        return _with_forced_session(url, config)
    except Exception as exc:
        logger.warning("[PROXY] get_proxy_for_session failed (continuing direct): %s", exc)
        return None


def report_failure(proxy_url) -> None:
    """Record a proxy failure (list mode skips it after max_failures)."""

    if not proxy_url:
        return
    try:
        with _LOCK:
            _FAILURES[str(proxy_url)] = _FAILURES.get(str(proxy_url), 0) + 1
    except Exception:
        pass


def report_success(proxy_url) -> None:
    """Clear failure counter after a successful session."""

    if not proxy_url:
        return
    try:
        with _LOCK:
            _FAILURES.pop(str(proxy_url), None)
    except Exception:
        pass


def stagger_start(config, stop_event=None) -> None:
    """Sleep a small random delay so parallel browsers don't hit Google same ms.

    Called once per session BEFORE browser startup. Interruptible via stop_event.
    Disabled when proxy.stagger_min/max are 0.
    """

    try:
        cfg = _proxy_config(config)
        try:
            lo = float(cfg.get("stagger_min", 1.0))
        except Exception:
            lo = 1.0
        try:
            hi = float(cfg.get("stagger_max", 3.0))
        except Exception:
            hi = 3.0
        lo = max(0.0, lo)
        hi = max(0.0, hi)
        if hi < lo:
            lo, hi = hi, lo
        if hi <= 0:
            return
        delay = random.uniform(lo, hi)
        if stop_event is not None:
            try:
                stop_event.wait(delay)
                return
            except Exception:
                pass
        time.sleep(delay)
    except Exception:
        pass


def describe(config) -> str:
    """One-line safe description for startup logs (no credentials)."""

    try:
        cfg = _proxy_config(config)
        if not cfg.get("enabled", False):
            return "proxy disabled (direct connection)"
        mode = str(cfg.get("mode", "single")).strip().lower()
        if mode == "list":
            count = len(load_proxies(config))
            return f"proxy list mode: {count} proxie(s), per-session rotation"
        url = _single_url(config)
        if not url:
            return "proxy enabled but NO URL configured (will run direct)"
        forced = bool(cfg.get("force_new_ip_per_session", False))
        extra = ", force-new-IP per session" if forced else ""
        return f"rotating proxy: {mask_proxy(url)}{extra}"
    except Exception:
        return "proxy status unknown"
