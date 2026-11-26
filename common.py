"""The few things that differ between macOS and Windows, in one place.

Everything else in voiceover is the same code on both. Only standard-library imports at the
top: `voice.py` runs this before setup has installed anything.
"""
import os
import subprocess
from pathlib import Path

WINDOWS = os.name == "nt"
DATA = Path(os.environ.get("VOICEOVER_DATA", Path.home() / ".claude" / "voiceover"))  # the voice, log and saved replies


def is_running(pid: int, script: str) -> bool:
    """True if process `pid` is running `script` (e.g. "speak.py").

    A process number we saved earlier may belong to another program by now, so we check
    its command line before signalling it.
    """
    try:
        import psutil   # installed by setup; before that, nothing of ours is running anyway
        return any(script in part for part in psutil.Process(pid).cmdline())
    except Exception:   # no such process, not ours to look at, or no psutil yet
        return False


def read_pid(path: Path, script: str) -> int | None:
    """The number saved in `path`, if that process is still running `script`."""
    try:
        pid = int(path.read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None
    return pid if is_running(pid, script) else None


def lock(f, wait: bool = True) -> None:
    """Lock an open file so only one process at a time gets past this point.

    With wait=False, raises OSError at once if another process holds the lock.
    The lock is released when the file is closed (or the process ends).
    """
    if WINDOWS:
        import msvcrt
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK if wait else msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(f, fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB)


def spawn(cmd: list[str], log: Path | None = None) -> None:
    """Start `cmd` in the background, fully detached, so it outlives the hook or command that started it."""
    out = open(log, "ab") if log else subprocess.DEVNULL
    try:
        if WINDOWS:
            # No console window, its own process group, and out of the hook's job if Windows allows it.
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            try:
                subprocess.Popen(cmd, stdout=out, stderr=out, stdin=subprocess.DEVNULL,
                                 creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB)
            except OSError:
                subprocess.Popen(cmd, stdout=out, stderr=out, stdin=subprocess.DEVNULL, creationflags=flags)
        else:
            subprocess.Popen(cmd, stdout=out, stderr=out, stdin=subprocess.DEVNULL, start_new_session=True)
    finally:
        if log:
            out.close()
