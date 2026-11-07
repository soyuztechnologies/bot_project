"""
Per-run identity and stop handling, shared by the dashboard and the bots.

Every run has its own identity. The dashboard passes it to the runs it starts; a run
started any other way (launcher.py, python main.py) makes up its own:

    RANKORA_JOB_ID        stored on the run's database rows
    RANKORA_PROFILE_ROOT  folder holding the browser profiles of this run only
    RANKORA_STOP_FILE     created to ask this run to stop

Each run also keeps a record in logs/runs/ while it is alive. That is how this
install's dashboard finds and stops a run it did not start itself. logs/ is per
install (and shared by both Docker containers), so another install's runs are not
visible here.

Keep this module free of heavy imports: the dashboard imports it too.
"""

import _thread
import atexit
import json
import os
import socket
import threading
import time
import uuid
from pathlib import Path

ENV_JOB_ID = "RANKORA_JOB_ID"
ENV_PROFILE_ROOT = "RANKORA_PROFILE_ROOT"
ENV_STOP_FILE = "RANKORA_STOP_FILE"

PROJECT_DIR = Path(__file__).resolve().parents[1]
RUNS_DIR = PROJECT_DIR / "logs" / "runs"
HEARTBEAT_SECONDS = 2
STALE_SECONDS = 15


_current_record = None
_stop_interrupts_held = threading.Event()


def current_job_id():
    return os.environ.get(ENV_JOB_ID) or None


def current_run_record():
    """This process's run record, if it registered one."""
    return _current_record


def hold_stop_interrupts():
    """The run is writing its report and email: a Stop must no longer interrupt it."""
    _stop_interrupts_held.set()


def _write_record(path, record):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record), "utf-8")
    tmp.replace(path)


def start_stop_watcher(mode, poll_seconds=0.5):
    """Register this run and turn a stop request into a Ctrl+C in this process, so a
    Stop takes the same path as Ctrl+C: browsers closed, rows marked INTERRUPTED,
    summary report sent."""
    global _current_record
    import psutil

    job_id = os.environ.setdefault(ENV_JOB_ID, f"{mode.lower()}-{uuid.uuid4().hex[:8]}")
    profile_root = os.environ.setdefault(
        ENV_PROFILE_ROOT, str(PROJECT_DIR / "browser_profiles" / f"run-{job_id}"))
    stop_file = os.environ.setdefault(ENV_STOP_FILE, str(RUNS_DIR / f"{job_id}.stop"))
    record = {
        "job_id": job_id, "mode": mode, "pid": os.getpid(), "host": socket.gethostname(),
        "create_time": psutil.Process().create_time(), "started_at": time.time(),
        "profile_root": profile_root, "stop_file": stop_file,
    }
    _current_record = record
    path = RUNS_DIR / f"{job_id}.json"
    closing = threading.Event()
    try:
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        _write_record(path, record)
    except OSError:
        pass  # the run itself must not fail over this; it just can't be found from the dashboard

    def close():
        closing.set()
        forget_run(record)

    atexit.register(close)

    def watch():
        interrupted = False
        last_beat = time.time()
        while not closing.is_set():
            if not interrupted and not _stop_interrupts_held.is_set() and os.path.exists(stop_file):
                interrupted = True
                _thread.interrupt_main()
            if time.time() - last_beat >= HEARTBEAT_SECONDS:
                last_beat = time.time()
                try:
                    os.utime(path)
                except FileNotFoundError:
                    if not closing.is_set():
                        try:
                            _write_record(path, record)
                        except OSError:
                            pass
                except OSError:
                    pass
            time.sleep(poll_seconds)

    threading.Thread(target=watch, daemon=True, name="StopWatcher").start()


def list_runs():
    """Records of this install's runs, including ones that have died without cleaning up."""
    records = []
    for path in RUNS_DIR.glob("*.json"):
        try:
            records.append(json.loads(path.read_text("utf-8")))
        except (OSError, ValueError):
            continue
    return records


def _same_process(record):
    """True if the recorded pid is still that run. PIDs get reused, the start time doesn't."""
    import psutil

    try:
        return abs(psutil.Process(record["pid"]).create_time() - record["create_time"]) < 1
    except (psutil.Error, KeyError, TypeError):
        return False


def run_is_alive(record):
    """On this machine ask the OS. Across Docker containers process ids mean nothing,
    so go by the heartbeat on the shared record."""
    if record.get("host") == socket.gethostname():
        return _same_process(record)
    try:
        age = time.time() - (RUNS_DIR / f"{record['job_id']}.json").stat().st_mtime
    except OSError:
        return False
    return age < STALE_SECONDS


def request_run_stop(record):
    Path(record["stop_file"]).parent.mkdir(parents=True, exist_ok=True)
    Path(record["stop_file"]).touch()


def stop_was_requested(record):
    return os.path.exists(record["stop_file"])


def kill_run(record):
    """Force-stop a run. Returns False if it lives where this process can't reach it."""
    if record.get("host") != socket.gethostname():
        return False
    if _same_process(record):
        kill_process_tree(record["pid"])
    kill_processes_using(record["profile_root"])
    return True


def forget_run(record):
    for path in (RUNS_DIR / f"{record['job_id']}.json", Path(record["stop_file"])):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _kill_tree(proc):
    import psutil

    try:
        victims = proc.children(recursive=True) + [proc]
    except psutil.Error:
        victims = [proc]
    for victim in victims:
        try:
            victim.kill()
        except psutil.Error:
            pass


def kill_process_tree(pid):
    """Kill a process and everything it started."""
    import psutil

    try:
        _kill_tree(psutil.Process(pid))
    except psutil.Error:
        pass


def kill_processes_using(path):
    """Kill processes with a path inside `path` on their command line. Chrome started
    in undetected mode has no parent process, so killing the bot's process tree is not
    enough to close it. Only this run's own profile folder is ever passed here."""
    import psutil

    fragment = os.path.normpath(str(path)).replace("\\", "/").rstrip("/").lower() + "/"
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = " ".join(proc.info["cmdline"] or []).replace("\\", "/").lower()
            if fragment in cmdline and proc.info["pid"] != os.getpid():
                _kill_tree(proc)
        except (psutil.Error, OSError):
            continue
