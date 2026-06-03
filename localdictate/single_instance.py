"""Single-instance guard.

Running two LocalDictate instances means two tray icons fighting over the same
global hotkey and microphone. We prevent that with an advisory file lock held
for the process lifetime: a second instance fails to acquire it and bails out.

The lock is tied to the open file descriptor, so the OS releases it
automatically when the process exits (even on a crash) — no stale lock to clean
up. On platforms without ``fcntl`` (e.g. Windows) we degrade to best-effort and
never block startup.
"""

import os
from pathlib import Path

from platformdirs import user_runtime_dir


def _lock_path() -> Path:
    try:
        base = Path(user_runtime_dir("localdictate", ensure_exists=True))
    except Exception:
        # Fall back to the config dir if no runtime dir is available.
        from . import settings

        base = settings._config_dir
    base.mkdir(parents=True, exist_ok=True)
    return base / "localdictate.lock"


def acquire():
    """Try to claim the single-instance lock.

    Returns an open file handle on success — the caller MUST keep it alive for
    the whole process lifetime (releasing/closing it frees the lock). Returns
    ``None`` if another instance already holds the lock. On platforms without
    advisory locking, returns the handle without enforcing (best-effort).
    """
    try:
        fd = open(_lock_path(), "w")
    except OSError:
        # Can't even create the lock file — don't prevent the app from starting.
        return _Unenforced()

    try:
        import fcntl
    except ImportError:
        return fd  # non-POSIX: treat as acquired, no enforcement

    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fd.close()
        return None  # held by another live instance

    # Record our PID for diagnostics (purely informational).
    try:
        fd.seek(0)
        fd.truncate()
        fd.write(str(os.getpid()))
        fd.flush()
    except OSError:
        pass
    return fd


class _Unenforced:
    """No-op stand-in when we can't create a lock file; keeps the API uniform."""

    def close(self):
        pass
