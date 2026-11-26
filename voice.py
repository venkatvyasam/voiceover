"""Controls for the Claude Code voice-over. Installed as `voice` and the short form `vo`.
`voice help` lists every command.

Only the standard library and common.py at the top, so `voice status` and `voice help` work
before setup has installed anything. The same code runs on macOS and Windows.
"""
import json
import os
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from common import DATA, is_running, read_pid, spawn

HERE = Path(__file__).resolve().parent   # the code (in a plugin, its folder changes with every update)
LOG = DATA / "speak.log"
CLAUDE = Path.home() / ".claude"
MUTE_FLAG = CLAUDE / ".speak-off"
SESSION_MUTE_DIR = CLAUDE / "speak-muted"
SPEED_FILE = CLAUDE / "speak-speed"
NUMBER = re.compile(r"^[+-]?([0-9]+\.?[0-9]*|\.[0-9]+)$")   # 1.3, +.2, -0.1, 2
SESSION = os.environ.get("CLAUDE_CODE_SESSION_ID", "")

USAGE = """\
voice: controls for the Claude Code voice-over   (vo is the short form)
Inside Claude Code, start with !   e.g.  ! voice pause

  voice stop          stop speaking now                        vo s
  voice pause         pause                                    vo p
  voice resume        continue where it paused                 vo r
  voice again         say the last reply, even if muted        vo a
  voice +.2           speak faster by 0.2 (use - for slower)   vo -.1
  voice 1.3           set the speed (0.5 to 2)                 vo 1.3
  voice reset         speed back to the default (1.1)
  voice status        what's muted or playing, and why the last reply was spoken or skipped
  voice mute          mute every session
  voice unmute        unmute every session
  voice mute here     mute only this Claude Code session
  voice unmute here   unmute this session
  voice read FILE     read a document aloud with readalong, if it is installed
  voice help          this list

Speech also stops by itself when you send your next message.
Start a silent session:  SPEAK=0 claude"""


def speak_py_setting(name: str) -> str:
    """A setting from the top of speak.py, e.g. VOICE or SPEED."""
    m = re.search(rf'^{name} = "?([^"\s]+)"?', (HERE / "speak.py").read_text(), re.M)
    return m.group(1) if m else ""


def current_speed() -> str:
    """The reading speed: the one saved by `vo 1.3` or `vo +.2`, else the default in speak.py."""
    try:
        s = SPEED_FILE.read_text().strip()
    except OSError:
        s = ""
    return s if re.fullmatch(r"[0-9]*\.?[0-9]+", s) else speak_py_setting("SPEED")


def speech_pid() -> int | None:
    """The speak.py that is speaking now, if any. It writes speak.pid; read_pid checks the
    number still belongs to speak.py, so we never stop some other program."""
    return read_pid(DATA / "speak.pid", "speak.py")


def engine_pid() -> int | None:
    try:
        pid = json.loads((DATA / "engine.json").read_text())["pid"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return pid if is_running(pid, "voice_server.py") else None


def remove(*paths: Path) -> None:
    for p in paths:
        p.unlink(missing_ok=True)


def stop_all() -> None:
    pid = speech_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    remove(DATA / "speak.state", DATA / "speak.pid", DATA / "speak.pause")


def playback() -> str:
    """What speak.py is doing: preparing, speaking or paused; empty if idle."""
    pid = speech_pid()
    if not pid:
        return ""
    if paused_by_us(pid):
        return "paused"   # before speak.py has noticed (it checks 20 times a second)
    try:
        return (DATA / "speak.state").read_text().strip()
    except OSError:
        return ""


def paused_by_us(pid: int) -> bool:
    try:
        return (DATA / "speak.pause").read_text() == str(pid)
    except OSError:
        return False


def fmt(v: float) -> str:
    """1.30 -> 1.3, 2.00 -> 2"""
    return f"{v:.2f}".rstrip("0").rstrip(".")


def set_speed(arg: str) -> None:
    """`vo 1.3` sets the speed; `vo +.2` and `vo -.1` change it by that much; `vo reset` goes
    back to the default in speak.py. Kokoro accepts 0.5 to 2."""
    old = current_speed()
    clamped = False
    if arg == "reset":
        remove(SPEED_FILE)
        new = current_speed()
    else:
        v = float(old) + float(arg) if arg[0] in "+-" else float(arg)
        clamped = v < 0.5 or v > 2
        new = fmt(min(2.0, max(0.5, v)))
        SPEED_FILE.parent.mkdir(parents=True, exist_ok=True)
        SPEED_FILE.write_text(new + "\n")
    remove(DATA / "last.wav")   # the saved audio is at the old speed, so `voice again` makes it fresh at the new one
    if clamped:
        print(f"speed {new}x (was {old}x; the range is 0.5 to 2)")
    else:
        print(f"speed {new}x (was {old}x)")
    # A replay plays a finished recording, so its speed is fixed.
    pid = speech_pid()
    if pid and is_replay(pid):
        print(f"the replay playing now keeps its speed; the next reply, or vo a, uses {new}x")


def is_replay(pid: int) -> bool:
    try:
        import psutil
        return "--play" in psutil.Process(pid).cmdline()
    except Exception:
        return False


def again_file() -> Path:
    """What `voice again` repeats: inside Claude Code, that session's last spoken reply; elsewhere, the last from any session."""
    return DATA / "last-by-session" / f"{SESSION}.txt" if SESSION else DATA / "last.txt"


def saved_audio_matches(text: Path) -> bool:
    """last.wav is the audio of last.txt, so it can be replayed only when that's the text we want."""
    try:
        return (DATA / "last.wav").stat().st_size > 0 and text.read_bytes() == (DATA / "last.txt").read_bytes()
    except OSError:
        return False


def nonempty(p: Path) -> bool:
    try:
        return p.stat().st_size > 0
    except OSError:
        return False


def venv_python() -> Path:
    for p in (DATA / ".venv/bin/python", DATA / ".venv/Scripts/python.exe"):
        if p.exists():
            return p
    return DATA / ".venv/bin/python"


def last_decision() -> str:
    """The last hook decision: this session's if we know it, else the most recent overall."""
    try:
        lines = [ln for ln in LOG.read_text(errors="replace").splitlines() if ln.startswith("--- ")]
    except OSError:
        return ""
    mine = [ln for ln in lines if SESSION and f"[{SESSION[:8]}]" in ln]
    pick = mine or lines
    return pick[-1][4:] if pick else ""


def status() -> None:
    print("Voice-over status")
    print("  All sessions:  MUTED  (voice unmute)" if MUTE_FLAG.exists() else "  All sessions:  on")
    if SESSION:
        if (SESSION_MUTE_DIR / SESSION).exists():
            print("  This session:  MUTED  (! voice unmute here)")
        elif os.environ.get("SPEAK") == "0":
            print("  This session:  silent (started with SPEAK=0)")
        else:
            print("  This session:  on")
    else:
        print("  This session:  run '! voice status' inside Claude Code to see")
    print({"paused": "  Playback:      paused  (voice resume)",
           "speaking": "  Playback:      speaking",
           "preparing": "  Playback:      preparing speech"}.get(playback(), "  Playback:      idle"))
    if not venv_python().exists() or not nonempty(DATA / "models/kokoro-v1.0.onnx"):
        if (DATA / "setup.lock").is_dir():
            print(f"  Setup:         downloading the voice now (see {DATA / 'setup.log'})")
        else:
            print("  Setup:         not done yet (it runs by itself at the next session start, or run /voiceover:setup)")
    if engine_pid():
        print("  Voice engine:  loaded (quick start; quits after 45 minutes unused)")
    else:
        print("  Voice engine:  not loaded (the next reply takes ~6s to start)")
    print(f"  Voice:         {speak_py_setting('VOICE')} at {current_speed()}x speed  (vo +.2 faster, vo -.1 slower)")
    again = again_file()
    if not nonempty(again):
        print("  Again:         nothing spoken yet")
    elif saved_audio_matches(again):
        print("  Again:         ready, instant")
    else:
        print("  Again:         regenerates (~3s)")
    last = last_decision()
    print(f"  Last reply:    {last}" if last else "  Last reply:    nothing logged yet")


def need_session(what: str) -> None:
    if not SESSION:
        print(f"run this inside Claude Code, with ! in front:  ! voice {what} here")
        sys.exit(1)


def on_prompt() -> None:
    """UserPromptSubmit hook: stop the old reply when you send a new message.

    Silent on purpose: this hook's output would be added to Claude's context. A message that
    is itself a voice command (e.g. "voice resume") must not stop the speech it targets.
    """
    try:
        prompt = json.load(sys.stdin).get("prompt") or ""
    except Exception:
        prompt = ""
    if not re.match(r"\s*!?\s*(voice|vo)\b", prompt, re.I):
        stop_all()


def main(args: list[str]) -> int:
    first = args[0] if args else "help"
    # A number is a speed, checked before the dashes below are stripped: "-.1" means slower, not ".1".
    if NUMBER.match(first):
        set_speed(first)
        return 0

    # Accept words or short forms, with or without dashes: "stop", "-stop", "s" all work.
    cmd = first.lower().lstrip("-")
    where = args[1].lower() if len(args) > 1 else ""

    if cmd in ("stop", "s"):
        stop_all()
        print("stopped")
    elif cmd in ("pause", "p"):
        # speak.py holds its exact place; this also works before the first sound.
        pid = speech_pid()
        if pid and playback():
            (DATA / "speak.pause").write_text(str(pid))
            print("paused (voice resume to continue)")
        else:
            print("nothing playing")
    elif cmd in ("resume", "r", "continue"):
        pid = speech_pid()
        if pid and playback() == "paused":
            remove(DATA / "speak.pause")
            print("resumed")
        else:
            print("nothing paused")
    elif cmd in ("again", "a", "repeat", "replay"):
        text = again_file()
        if not nonempty(text):
            print("nothing spoken yet to repeat")
            return 0
        stop_all()
        py = sys.executable
        if saved_audio_matches(text):   # saved audio: instant
            spawn([py, str(HERE / "speak.py"), "--play", str(DATA / "last.wav")])
        else:                           # another session spoke since, or the reply was cut off
            spawn([py, str(HERE / "speak.py"), text.read_text()])
        print("saying the last reply again")
    elif cmd in ("status", "st"):
        status()
    elif cmd in ("mute", "m"):
        if where == "here":
            need_session("mute")
            stop_all()
            SESSION_MUTE_DIR.mkdir(parents=True, exist_ok=True)
            (SESSION_MUTE_DIR / SESSION).touch()
            print("this session muted (! voice unmute here to undo)")
        else:
            stop_all()
            MUTE_FLAG.touch()
            print("all sessions muted (voice unmute to undo)")
    elif cmd in ("unmute", "u"):
        if where == "here":
            need_session("unmute")
            remove(SESSION_MUTE_DIR / SESSION)
            print("this session unmuted")
        else:
            remove(MUTE_FLAG)
            print("all sessions unmuted")
    elif cmd == "read":   # documents are readalong's job: github.com/venkatvyasam/readalong
        readalong = shutil.which("readalong")
        if not readalong:
            print("voice read needs readalong: github.com/venkatvyasam/readalong")
            return 1
        return subprocess.call([readalong, *args[1:]])
    elif cmd == "speed":
        # "voice speed" shows it; "voice speed 1.3", "voice speed +.2" or "voice speed reset" changes it
        if NUMBER.match(args[1] if len(args) > 1 else "") or where == "reset":
            set_speed(where)
        else:
            print(f"speed {current_speed()}x  (vo +.2 faster, vo -.1 slower, vo reset for the default)")
    elif cmd == "reset":
        set_speed("reset")
    elif cmd in ("help", "h"):
        print(USAGE)
    elif cmd == "on-prompt":
        on_prompt()
    else:
        print(f"voice: unknown command '{first}' (nothing was changed)")
        print()
        print(USAGE)
        return 1
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--on-prompt"]:
        try:
            on_prompt()
        except Exception:
            pass   # a hook must never print or fail
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
