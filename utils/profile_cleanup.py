"""
profile_cleanup.py

Full clear of the browser_profiles folder, run when the dashboard starts.

Unlike the per-run stale sweep in browser/browser.py (which only removes the
bot's own <browser>_<thread>_<uuid8> folders older than N minutes), this
removes EVERYTHING inside the profile root -- any name, any age -- except
items a running process is still using.

Kept free of selenium/seleniumbase imports so the dashboard can use it with
its slim requirements. psutil is optional: without it, "in use" cannot be
checked, so recent bot-named profile folders are left alone to be safe.
"""

import logging
import os
import re
import shutil
import stat
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_BOT_PROFILE_RE = re.compile(r"^(chrome|edge|firefox|opera|brave)_\d+_[0-9a-f]{8}$")
DEFAULT_STALE_PROFILE_MINUTES = 10


def resolve_profile_root(config, base_dir) -> Path:
    """Same root setup_browser uses: browser.profile_dir, else <base_dir>/browser_profiles."""
    browser_cfg = (config or {}).get("browser", {}) or {}
    root = browser_cfg.get("profile_dir") or os.path.join(str(base_dir), "browser_profiles")
    root = Path(root)
    if not root.is_absolute():
        root = Path(base_dir) / root
    return root


def _is_unsafe_root(root: Path) -> bool:
    """Refuse obviously dangerous roots (drive root, home dir, project dir)."""
    try:
        r = root.resolve()
    except Exception:
        return True
    unsafe = {Path(r.anchor), Path.home().resolve()}
    try:
        unsafe.add(Path(__file__).resolve().parents[1])  # project root
    except Exception:
        pass
    return r in unsafe


def _onerror(func, path, _exc):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def _paths_in_use(root: Path):
    """Return the set of root entries referenced on a running process's command line, or None if unknown."""
    try:
        import psutil
    except ImportError:
        return None
    root_norm = os.path.normpath(str(root)).replace("\\", "/").lower().rstrip("/") + "/"
    used = set()
    for proc in psutil.process_iter(["cmdline"]):
        try:
            cmd = proc.info.get("cmdline")
            if not cmd:
                continue
            joined = " ".join(cmd).replace("\\", "/").lower()
            idx = joined.find(root_norm)
            while idx != -1:
                rest = joined[idx + len(root_norm):]
                # Entry name runs until the next path separator / arg boundary.
                name = re.split(r"[/\"']|\s--", rest, maxsplit=1)[0].strip()
                if name:
                    used.add(name)
                idx = joined.find(root_norm, idx + 1)
        except Exception:
            continue
    return used


def _remove(path: Path, retries: int = 4, delay: float = 0.5) -> bool:
    kw = {"onexc": _onerror} if sys.version_info >= (3, 12) else {"onerror": _onerror}
    for _ in range(retries):
        try:
            if path.is_symlink() or path.is_file():
                path.unlink()  # never follow a symlink out of the root
            elif path.is_dir():
                shutil.rmtree(path, **kw)
        except Exception:
            pass
        if not os.path.lexists(path):
            return True
        time.sleep(delay)
    return not os.path.lexists(path)


def clear_profile_root(config, base_dir, stale_after_minutes=None) -> dict:
    """Delete every entry inside the profile root that no running process is using."""
    stats = {"removed": 0, "skipped_in_use": 0, "failed": 0}
    root = resolve_profile_root(config, base_dir)
    if not root.is_dir():
        return stats
    if _is_unsafe_root(root):
        logger.warning("Profile cleanup skipped: refusing to clear unsafe root %s", root)
        return stats

    if stale_after_minutes is None:
        stale_after_minutes = ((config or {}).get("browser", {}) or {}).get(
            "stale_profile_minutes", DEFAULT_STALE_PROFILE_MINUTES
        )
    try:
        min_age = max(0.0, float(stale_after_minutes)) * 60
    except (TypeError, ValueError):
        min_age = DEFAULT_STALE_PROFILE_MINUTES * 60

    in_use = _paths_in_use(root)
    now = time.time()

    for entry in list(root.iterdir()):
        name_l = entry.name.lower()
        if in_use is not None:
            if name_l in in_use:
                stats["skipped_in_use"] += 1
                continue
        else:
            # No psutil: protect recent bot-owned profiles that might be live.
            try:
                if _BOT_PROFILE_RE.match(entry.name) and now - entry.stat().st_mtime < min_age:
                    stats["skipped_in_use"] += 1
                    continue
            except Exception:
                stats["skipped_in_use"] += 1
                continue
        if _remove(entry):
            stats["removed"] += 1
        else:
            stats["failed"] += 1

    msg = (f"[PROFILE CLEANUP] {root}: removed {stats['removed']}, "
           f"kept {stats['skipped_in_use']} in use, {stats['failed']} could not be removed")
    logger.info(msg)
    print(msg)
    return stats
