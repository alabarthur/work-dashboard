"""Filesystem run-lock preventing overlapping collector runs.

The lock is a small JSON file created atomically with O_EXCL. It records the
owning PID and start time so a crashed run leaves a reclaimable (stale) lock
rather than blocking forever.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

from app import config

STALE_AFTER_SECONDS = 300  # a collector run should never exceed this


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_lock(path: Optional[Path] = None) -> Optional[dict]:
    path = path or config.LOCK_PATH
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (ValueError, OSError):
        return None


def is_locked(path: Optional[Path] = None) -> bool:
    """True if a live, non-stale lock is held."""
    path = path or config.LOCK_PATH
    info = read_lock(path)
    if info is None:
        return False
    pid = int(info.get("pid", -1))
    started = float(info.get("started", 0))
    if not _pid_alive(pid) or (time.time() - started) > STALE_AFTER_SECONDS:
        return False
    return True


def _write_lock(fd: int, trigger: str) -> bool:
    with os.fdopen(fd, "w") as fh:
        json.dump({"pid": os.getpid(), "started": time.time(), "trigger": trigger}, fh)
    return True


def acquire(trigger: str, path: Optional[Path] = None) -> bool:
    """Atomically acquire the lock, reclaiming a stale one. Returns success.

    The happy path (no existing lock) is a single atomic O_EXCL create with no
    check-then-act window. Only the stale-reclaim path has a small race, which
    is harmless for a single-user dashboard.
    """
    path = path or config.LOCK_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return _write_lock(os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644), trigger)
    except FileExistsError:
        pass
    # A lock file exists — only reclaim it if it is stale (dead pid / too old).
    if is_locked(path):
        return False
    try:
        path.unlink()
        return _write_lock(os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644), trigger)
    except (OSError, FileExistsError):
        return False


def release(path: Optional[Path] = None) -> None:
    path = path or config.LOCK_PATH
    try:
        path.unlink()
    except FileNotFoundError:
        pass
