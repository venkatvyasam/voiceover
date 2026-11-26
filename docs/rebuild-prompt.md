# Prompt: rebuild "voiceover" from scratch

Paste everything below the line into Claude Code (in an empty folder, on a Mac or, in Git Bash, on a Windows PC).

---

Build a **Claude Code plugin** called **voiceover** (macOS and Windows) in the current (empty) folder. It makes Claude Code read its own replies aloud using **Kokoro**, a free text-to-speech model that runs locally via `kokoro-onnx`. The folder is both the plugin and its own one-plugin marketplace, so once it's on GitHub as `<owner>/voiceover`, anyone installs it with `/plugin install voiceover --marketplace <owner>/voiceover`. Follow this spec exactly: file names, constants, regexes, messages and behaviors all matter. Keep the code simple and readable; the users are a student and their family. Use **uv**, never pip. The plugin brings its own hooks (`hooks/hooks.json`); never add hooks to `~/.claude/settings.json`. `setup_hooks.py` exists only to *remove* hooks an older install.sh version put there.

**macOS and Windows run the same files.** Claude Code runs hook commands with bash on macOS and with Git Bash on Windows (it comes with Git for Windows), so the few shell scripts run on both; they stay short, and the real work is in Python. Everything that differs between the two systems lives in two files: `run` (which Python to use) and `common.py` (process checks, file locks, detached starts). No signals other than SIGTERM, no Unix sockets, no `ps`, no `fcntl` outside `common.py`.

**Code and data are separate.** The code is the plugin folder (called `HERE` in Python, `DIR` or `ROOT` in bash); Claude Code replaces it with every plugin update, so nothing that changes is ever written there. Everything downloaded or changing lives in `DATA` = `~/.claude/voiceover` (overridable with the env var `VOICEOVER_DATA`, for tests): `.venv/`, `models/`, `speak.log`, `last.txt`, `last.wav`, `last-by-session/`, `speak.pid`, `speak.state`, `speak.pause`, `engine.json`, `engine.lock`, `hook.lock`, `root`, `READY`, `welcomed`, `setup.log`, `setup.lock/`. In Python: `DATA = Path(os.environ.get("VOICEOVER_DATA", Path.home() / ".claude" / "voiceover"))`; in bash: `DATA="${VOICEOVER_DATA:-$HOME/.claude/voiceover}"`.

## Files to create

```
.claude-plugin/plugin.json  .claude-plugin/marketplace.json  hooks/hooks.json  commands/setup.md
.gitignore  .gitattributes  .python-version  pyproject.toml  LICENSE  setup.sh  session_start.sh  install.sh  uninstall.sh
run  common.py  setup_hooks.py  speak.py  voice_server.py  speak_reply.py  voice  voice.py  audition.py
README.md  CLAUDE.md  docs/guide.html
```

`setup.sh`, `session_start.sh`, `install.sh`, `uninstall.sh`, `run`, `voice` must be executable (`chmod +x`). `LICENSE` is the standard MIT license text.

## Load-bearing rules (never break these)

1. A hook must never block or fail a Claude Code turn. `speak_reply.py` starts speech in a detached process and **always exits 0**, even on exceptions (`try: main() except Exception: pass; sys.exit(0)`).
2. `voice.py --on-prompt` must **print nothing** (UserPromptSubmit hook output is added to Claude's context).
3. Pause is the file `DATA/speak.pause`: `voice pause` writes speak.py's number into it and `voice resume` deletes it; speak.py plays the sound itself and holds its exact place. Not a signal: Windows has no SIGUSR1, and `SIGSTOP` on macOS skips ahead on resume (the sound clock keeps running). `speak.py` starts its watcher thread before its slow imports, so a pause works while it is still starting.
4. Only `setup_hooks.py` edits `~/.claude/settings.json`, and only to remove old install.sh hooks; it backs the file up first and touches only this tool's hooks.
5. `onnxruntime` is pinned to `==1.23.2` (last version with Intel Mac wheels; has Apple Silicon wheels too). Never upgrade it.
6. **Write nothing that changes into the plugin folder**; use `DATA`.
7. **Stop processes by the number they wrote, never by name.** `speak.py` writes `DATA/speak.pid`; the engine writes its number into `DATA/engine.json`. Before stopping one, check with `common.is_running(pid, "speak.py")` (psutil: the process's command line contains that script) that the number still belongs to it (a stale number may belong to another program). Names change with plugin versions. Stopping is `os.kill(pid, SIGTERM)`, which on Windows ends the process at once.
8. Speech must **still work without the engine**. Every engine failure in `speak.py` falls back to loading Kokoro directly.
9. The hooks must **do nothing until setup is done**: `run` exits 0 at once when `DATA/.venv` has no Python yet (except for `voice.py`), and the Stop and UserPromptSubmit commands end in `2>/dev/null || true`.
10. The SessionStart hook may print **only JSON with a `systemMessage`** (shown to the user); plain text would be added to Claude's context.
11. **Keep macOS and Windows on the same code.** Anything that differs goes in `run` or `common.py`, never in an `if` scattered through the other files. Text files are UTF-8 everywhere (`run` exports `PYTHONUTF8=1`; Windows would otherwise use its old code page). Shell scripts keep Unix line endings (`.gitattributes`).

## .python-version
```
3.11
```

## pyproject.toml
```toml
[project]
name = "voiceover"
version = "0.1.0"
description = "Claude Code reads its replies aloud with a free, local voice (Kokoro)"
requires-python = ">=3.11"
dependencies = [
    "kokoro-onnx>=0.6.1",
    # 1.23.2 is the last onnxruntime with Intel Mac builds; it has Apple Silicon builds too.
    "onnxruntime==1.23.2",
    "psutil>=7.0.0",
    "sounddevice>=0.5.6",
    "soundfile>=0.14.0",
]
```
Run `uv lock` to produce `uv.lock` (it is universal: it covers macOS and Windows).

## .gitignore
Standard Python ignores (`__pycache__/`, `*.py[oc]`, `build/`, `dist/`, `wheels/`, `*.egg-info`, `.venv`) plus:
`last.txt`, `last.wav`, `last-by-session/`, `last.tmp.wav`, `speak.state`, `speak.pause`, `engine.json`, `engine.lock`, `hook.lock`, `models/` (comment: Kokoro model files ~337 MB, downloaded by setup), `speak.log`.

## .gitattributes
```
# Keep Unix line endings on every system. On Windows, Git may otherwise check files out with
# Windows line endings, and bash then fails on the scripts ("\r: command not found").
* text=auto eol=lf
*.wav binary
```

## run (bash; starts every hook and the `voice` command)
Usage: `run SCRIPT.py ARGS...`. The one place that knows where setup's Python is:
```bash
ROOT=$(cd "$(dirname "$0")" && { pwd -W 2>/dev/null || pwd; })   # pwd -W: as C:/... on Windows, which Python understands
DATA="${VOICEOVER_DATA:-$HOME/.claude/voiceover}"
PY="$DATA/.venv/bin/python"
[ -x "$PY" ] || PY="$DATA/.venv/Scripts/python.exe"
if [ ! -x "$PY" ]; then   # not set up yet
  [ "$1" = voice.py ] || exit 0              # the hooks do nothing until then
  PY=$(command -v python3 || command -v python)   # `voice help` and `voice status` still work
fi
export PYTHONUTF8=1   # read and write text as UTF-8; Windows would otherwise use its older code page
script="$1"; shift
exec "$PY" "$ROOT/$script" "$@"
```

## common.py (the few things that differ between macOS and Windows)
Only standard-library imports at the top (`voice.py` imports it before setup has installed anything).
- `WINDOWS = os.name == "nt"`; `DATA` as above (every other Python file imports `DATA` from here).
- `is_running(pid, script) -> bool`: `import psutil` inside the function; True if any part of `psutil.Process(pid).cmdline()` contains `script`. Any exception (no such process, access denied, no psutil yet) -> False.
- `read_pid(path, script) -> int | None`: the first word of the file as an int, if `is_running(pid, script)`; None on any read/parse error or when it isn't running.
- `lock(f, wait=True)`: an exclusive lock on an open file, released when it's closed. Windows: `f.seek(0)`, `msvcrt.locking(f.fileno(), LK_LOCK if wait else LK_NBLCK, 1)`. Otherwise `fcntl.flock(f, LOCK_EX` (plus `LOCK_NB` when not waiting)`)`. When not waiting it raises `OSError` if another process holds it. (Never keep data in a locked file: on Windows a locked byte can't be read by others.)
- `spawn(cmd, log=None)`: start `cmd` fully detached, stdout and stderr appended to `log` (or DEVNULL), stdin DEVNULL. Windows: `creationflags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`, first trying with `CREATE_BREAKAWAY_FROM_JOB` added (so it outlives the hook) and falling back without it on `OSError`. Otherwise `start_new_session=True`. Close the log file afterwards.

## install.sh (bash, `set -euo pipefail`; for working on the code)
- `DIR` = this folder; `DATA` as above; `mkdir -p "$DATA"`.
- If `$DIR/models` exists and `$DATA/models` doesn't, `mv` it there and print `moved the voice model to <path>` (older versions kept the model in the folder; don't download it again).
- `echo "$DIR" > "$DATA/root"` (so `voice` runs this clone's code), then run `"$DIR/setup.sh"`.
- Print: `To try this folder as the plugin, for one session:  claude --plugin-dir "<DIR>"`.
- It does **not** add hooks anywhere.

## uninstall.sh (bash, `set -euo pipefail`; removes what an older install.sh set up)
Run `"$DIR/voice" stop` (ignore errors). Pick a Python: `$DATA/.venv/bin/python`, else `$DIR/.venv/bin/python`, else `python3`, and run `setup_hooks.py uninstall` with it. Remove `~/.local/bin/voice` and `vo` only if they are symlinks pointing exactly at `$DIR/voice` (print `  removed the old link ~/.local/bin/<name>`). Then print: `The old hooks are gone. If the voiceover plugin is installed, it carries on as before.`, and how to remove everything: `claude plugin uninstall voiceover@voiceover` and `rm -rf ~/.claude/voiceover ~/.local/bin/voice ~/.local/bin/vo ~/.local/bin/voice.cmd ~/.local/bin/vo.cmd ~/.claude/speak-speed ~/.claude/.speak-off ~/.claude/speak-muted`.

## setup.sh (bash, `set -euo pipefail`; safe to run again, fetches only what's missing)
The plugin's setup: run in the background by session_start.sh, and on request by `/voiceover:setup`.
- Runs on macOS, and on Windows in Git Bash. `ROOT=$(cd "$(dirname "$0")" && { pwd -W 2>/dev/null || pwd; })` (as `C:/...` on Windows), `DATA` as above, `step()` prints `\n==> <msg>`. Prepend `$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin` to `PATH` (where uv usually lives; a hook's PATH may lack it).
- `uname` is `Darwin` -> `windows=no`; `MINGW*`, `MSYS*` or `CYGWIN*` (Git Bash) -> `windows=yes`; anything else: print `voiceover works on macOS and Windows only.` and exit 1. No `uv`: print how to install it (`curl -LsSf https://astral.sh/uv/install.sh | sh`), "then start a new Claude Code session", exit 1.
- `mkdir -p "$DATA"`, then `DATA=$(cd "$DATA" && { pwd -W 2>/dev/null || pwd; })` (uv and curl are Windows programs there, and need `C:/...` paths). One setup at a time: `mkdir "$DATA/setup.lock"` or print `voiceover setup is already running` and exit 0; `trap 'rmdir "$DATA/setup.lock" 2>/dev/null' EXIT`. Remember `first_time` = whether `$DATA/READY` was missing.
- Step "Installing the Python packages (first time: about a minute)": `UV_PROJECT_ENVIRONMENT="$DATA/.venv" uv sync --project "$ROOT" --frozen --quiet`.
- Step "Downloading the Kokoro voice (about 340 MB, first time only)": into `$DATA/models/`, from base URL `https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0`, files `kokoro-v1.0.onnx` and `voices-v1.0.bin`. Skip a non-empty file (print `already downloaded`); otherwise `curl -fL --progress-bar` to `<file>.part`, then `mv` into place (an interrupted download never looks complete).
- Step "Making the 'voice' command (and its short form 'vo') available": `mkdir -p ~/.local/bin`; for `voice` and `vo`: if the path exists and is neither our wrapper (contains `voiceover wrapper`) nor a symlink whose target folder contains `speak.py` (an older install), print `  skipped <name>: ~/.local/bin/<name> already exists and belongs to something else`. Otherwise replace it with this wrapper (the code moves with every update, so it looks up where the code is now) and `chmod +x`, printing `  made ~/.local/bin/<name>`:
  ```bash
  #!/bin/bash
  # voiceover wrapper: runs the voice script of the installed version
  exec "$(cat "<DATA>/root")/voice" "$@"
  ```
  On Windows, also write `<name>.cmd` next to it (CRLF line endings), for Command Prompt and PowerShell:
  ```
  @echo off
  rem voiceover wrapper: runs the voice script of the installed version
  set /p VOICEOVER_ROOT=<"%USERPROFILE%\.claude\voiceover\root"
  set PYTHONUTF8=1
  "%USERPROFILE%\.claude\voiceover\.venv\Scripts\python.exe" "%VOICEOVER_ROOT%\voice.py" %*
  ```
  If `$DATA/root` is empty, write `$ROOT` to it. If `~/.local/bin` isn't on `PATH`, print the one-liner that adds `export PATH="$HOME/.local/bin:$PATH"` to `~/.zshrc`.
- Write `cksum < "$ROOT/uv.lock" | cut -d' ' -f1` to `$DATA/READY` (a new uv.lock, meaning new packages, makes session_start.sh run setup again).
- Print `voiceover is set up. Replies will be read aloud.` and the controls: `Controls (in Claude Code, type them with ! in front):`, `  vo p pause   vo r resume   vo s stop   vo a say it again`, `  vo +.2 / vo -.1 faster / slower   vo reset normal speed   vo help everything`.
- If `first_time` and `~/.claude/.speak-off` doesn't exist, say with `"$ROOT/run" speak.py`: `voiceover is ready. Claude's replies will now be read aloud. Type vo help to see the controls.` (`|| true`).

## session_start.sh (bash; the SessionStart hook; must be quick)
- `ROOT` (with `pwd -W` as in setup.sh), `DATA`, the same `PATH` prepend. `mkdir -p "$DATA"` and `echo "$ROOT" > "$DATA/root"` every time (the plugin folder changes with updates). Collect messages with `say()`, which appends to `msg` with a space.
- **Guard 1:** if `grep -qE 'speak_reply\.py|voice\\?" --on-prompt' ~/.claude/settings.json` matches, say `voiceover: the old hooks from install.sh are still in ~/.claude/settings.json. Run ./uninstall.sh in the old folder. Until then each reply is still read only once.`
- `ready()`: `DATA/.venv/bin/python` or `DATA/.venv/Scripts/python.exe` is executable, both model files are non-empty, and `DATA/READY` equals the cksum of `ROOT/uv.lock`.
- Not ready: if `DATA/setup.lock` exists and is not older than 30 minutes (`find ... -maxdepth 0 -mmin +30` prints nothing), say `voiceover: still setting up the voice. Replies will be read aloud once it's ready.`; else if no `uv`, say `voiceover needs uv to install its voice. Run: curl -LsSf https://astral.sh/uv/install.sh | sh   then start a new session.`; else `rmdir` a stale lock, start `$bg "$ROOT/setup.sh" >> "$DATA/setup.log" 2>&1 < /dev/null &` with `bg=$(command -v nohup)` (Git Bash may not have nohup), and say `voiceover: setting up the voice in the background (about 340 MB, a minute or two). You'll hear it say it's ready. Then type  ! vo help  to see the controls.`
- Ready, but `DATA/welcomed` doesn't exist: create it and say (once, the first session after setup) `voiceover is on: replies are read aloud. Controls (type them with ! in front): vo p pause, vo r resume, vo s stop, vo a say it again, vo +.2 / vo -.1 faster / slower, vo reset normal speed, vo mute here silence this session, vo help everything.`
- If `msg` isn't empty, print `{"systemMessage": "<msg>"}` (the messages contain no double quotes or backslashes). Always exit 0.

## .claude-plugin/plugin.json
`name` `voiceover`; `description` "Claude Code reads its replies aloud with a free, local voice (Kokoro). macOS and Windows (beta). Control it with `! vo pause`, `! vo +.2` and more."; `author` `{ "name": "<your name>" }`; `homepage` and `repository` the GitHub URL; `license` `MIT`; `keywords` voice, text-to-speech, tts, kokoro, accessibility, macos, windows. No `version`: then every commit is an update.

## .claude-plugin/marketplace.json
`name` `voiceover`; `description` "voiceover: Claude Code reads its replies aloud"; `owner` `{ "name": "<your name>" }`; `plugins`: one entry, `name` `voiceover`, `source` `"./"` (the plugin is this same folder), and a one-line description.

## hooks/hooks.json
A top-level `description` and `hooks` with three events, each `[ { "hooks": [ { "type": "command", "command": ... } ] } ]`:
- `SessionStart`: `"${CLAUDE_PLUGIN_ROOT}/session_start.sh"` (quoted).
- `Stop`: `"${CLAUDE_PLUGIN_ROOT}/run" speak_reply.py 2>/dev/null || true`.
- `UserPromptSubmit`: `"${CLAUDE_PLUGIN_ROOT}/run" voice.py --on-prompt 2>/dev/null || true`.
(On Windows, Claude Code gives `${CLAUDE_PLUGIN_ROOT}` with forward slashes, `C:/Users/...`, which Git Bash runs.)

## commands/setup.md (`/voiceover:setup`)
Front matter `description: Install or repair voiceover's voice (Python packages and the 340 MB Kokoro model)`. Body: run `"${CLAUDE_PLUGIN_ROOT}/setup.sh"` with the Bash tool and wait (allow up to 10 minutes the first time), then tell the user in two or three plain sentences whether the voice is set up and, if not, what the output says to do. Don't show the whole output unless it failed.

## setup_hooks.py
Only `uninstall.sh` uses it now, for old macOS installs (its `install` action is kept but unused). Usage `setup_hooks.py install|uninstall` (otherwise `sys.exit(__doc__)`).
- `HERE` = resolved folder. `SETTINGS = ~/.claude/settings.json`.
- `STOP_CMD = f'"{HERE}/.venv/bin/python" "{HERE}/speak_reply.py"'`
- `PROMPT_CMD = f'"{HERE}/voice" --on-prompt 2>/dev/null || true'`
- `OURS = ("speak_reply.py", "speak-reply.py", "shush --on-prompt", 'shush" --on-prompt', 'voice" --on-prompt')`; a hook is ours if any marker is a substring of its `command`.
- Load settings (or `{}`). If the file exists, copy it to `settings.json.bak-%Y%m%d-%H%M%S-%f` (with `shutil.copy2`) and print the backup path.
- For events `Stop` and `UserPromptSubmit`: remove our hooks from every entry's `hooks` list (this also removes copies installed from other folders, so replies are never spoken twice); keep entries that still have other hooks; drop the event key if nothing is left.
- On install, append `{"hooks": [{"type": "command", "command": STOP_CMD}]}` to `Stop` and the same shape with `PROMPT_CMD` to `UserPromptSubmit`.
- If `hooks` ends up empty, remove the `hooks` key. Write JSON with `indent=2, ensure_ascii=False` plus trailing newline. Print "registered"/"removed the voice-over hooks in <path>".

## speak.py
Usage: `speak.py "text"`, text on stdin (`" ".join(sys.argv[1:]) or sys.stdin.read()`; do nothing if blank), or `speak.py --play FILE.wav` (plays a saved recording; `voice again` uses it).

It plays the sound **itself**, through `sounddevice` (which works on macOS and Windows), not through the Mac's `afplay`. `afplay` has two problems: it keeps running about a second after its sound ends (a 1-second silence between chunks), and pausing it with `SIGSTOP` skips ahead on resume, because the Mac's sound clock keeps running.

**Pause and resume are a file:** `voice pause` writes speak.py's process number into `DATA/speak.pause`, `voice resume` deletes it. A watcher thread checks 20 times a second. A pause can arrive while speak.py is still starting, so the very top of the file, **before** the slow imports (numpy, sounddevice, soundfile), is only:
```python
import os
import threading
import time
from pathlib import Path
from common import DATA, spawn
HERE = Path(__file__).parent   # the code
STATE = DATA / "speak.state"   # "preparing", "speaking" or "paused"; removed when done
PID = DATA / "speak.pid"       # this process's number, so stop and pause reach it after an update too
PAUSE = DATA / "speak.pause"   # holds our number while paused
paused = False
started = False                # has any sound been queued yet?
def set_state(): STATE.write_text("paused" if paused else "speaking" if started else "preparing")
def watch_pause():   # forever: now = (PAUSE's text == str(os.getpid())), False on OSError;
                     # when it differs from `paused`, set `paused` (global) and set_state(); sleep 0.05
if __name__ == "__main__":
    DATA.mkdir(parents=True, exist_ok=True)
    PAUSE.unlink(missing_ok=True)   # a pause left from an older reply isn't for us
    PID.write_text(str(os.getpid()))
    set_state()
    threading.Thread(target=watch_pause, daemon=True).start()
```
In this file, `ENGINE`, the model files, `speak.log`, `last.txt`, `last.wav` and `last.tmp.wav` are all under `DATA` (only `voice_server.py` is under `HERE`).
Then the other imports, then constants:
```python
VOICE = "af_heart"      # alternatives: am_fenrir, bm_fable
SPEED = 1.1             # the default; `vo 1.3`, `vo +.2` or `vo -.1` saves a different one in SPEED_FILE
SPEED_FILE = Path.home() / ".claude" / "speak-speed"
FIRST_CHUNK_CHARS = 80  # short first chunk = quick first sound
CHUNK_CHARS = 250       # largest chunk
GROWTH = 1.8            # next chunk is generated while the previous one plays; generation is ~2.2x
                        # faster than speech, so a chunk under ~2x the previous one is ready in time
MIN_CHUNK = 40          # don't end a chunk on a tiny sentence like "Done."
LEAD = 0.3              # hand the next chunk to the player when this many seconds of sound are left
BUFFER = 0.2            # seconds of sound queued at the sound card. With the default (about 0.02 s),
                        # busy web pages in Chrome made playback crackle; a bigger buffer rides that out.
                        # Pause takes effect this much later, and still resumes at the exact place.
ENGINE = DATA / "engine.json"   # the voice engine's process number and network port
local_kokoro = None     # set only when the engine can't be used
```

`class Player` (plays chunks one after another with no gap; while paused it sends silence and keeps its place):
- `__init__(sample_rate)`: `self.rate`, `self.queue = collections.deque()` (arrays of samples; the first is playing), `self.pos = 0` (how far into `queue[0]`), `self.lock = threading.Lock()`, `self.late = 0` (times the sound card had to wait for us, each heard as a crackle), then `self.stream = sd.OutputStream(samplerate=sample_rate, channels=1, dtype="float32", callback=self.fill, latency=BUFFER, blocksize=1024)` and `self.stream.start()`. (The buffer means the sound card asks for audio about 24 times a second instead of about 1,660; measured with Yahoo and Economic Times open in Chrome, the crackling stopped.)
- `fill(out, frames, _time, status)` (the sound card calls it for each block): if `status.output_underflow`, add 1 to `self.late`; `out.fill(0)`; if `paused`, return (silence, place kept). Otherwise, under the lock, copy samples from `queue[0][pos:]` into `out[:, 0]` until `frames` are filled or the queue is empty, popping each array once fully played and resetting `pos`. If the queue runs dry, the rest stays silent (it never skips).
- `add(samples)`: append under the lock.
- `seconds_left()`: `(sum of queued lengths - pos) / rate`, under the lock.
- `wait(until=0.0)`: sleep 0.05 s at a time while `seconds_left() > until` (paused time doesn't count, because nothing is consumed while paused).
- `finish()`: `wait()`, then `stream.stop()` (returns once the last block has played) and `stream.close()`. If `self.late`, print `f"\n=== {time.ctime()} [player] the sound card waited {self.late} times (a crackle each)"` with `flush=True` (stdout goes to speak.log, so the log shows whether a crackle was ours; `===`, not `---`, as in the engine).

Import `kokoro_onnx` **only inside `load_kokoro()`** (it takes about a second to import, and the engine usually makes it unnecessary). `load_kokoro()` returns `Kokoro(DATA/"models/kokoro-v1.0.onnx", DATA/"models/voices-v1.0.bin")`.

`chunks(text)`: split into sentences with `re.split(r"(?<=[.!?:])\s+", text.strip())`. Start with `limit = FIRST_CHUNK_CHARS`. A sentence longer than `limit` is split further with `re.split(r"(?<=[,;])\s+", sentence)`. For each piece: if `len(cur) >= MIN_CHUNK and len(cur) + len(piece) > limit`, emit `cur`, set `limit = min(CHUNK_CHARS, max(FIRST_CHUNK_CHARS, int(len(cur) * GROWTH)))`, reset `cur`. Then `cur = f"{cur} {piece}".strip()`. Return remaining `cur` too.

`connect_engine(timeout)`: read `port` from `ENGINE` (JSON; a parse error or missing key raises `OSError`) and return `socket.create_connection(("127.0.0.1", port), timeout=timeout)`. 127.0.0.1 means only this computer can reach it.

`engine_ready()`: `connect_engine(2).close()`; True if that worked, False on `OSError`.

`start_engine()`: `spawn([sys.executable, HERE/"voice_server.py"], DATA/"speak.log")`, then poll `engine_ready()` every 0.1 s for up to 30 s (loading usually takes about 5). Return True once ready, else False.

`speed()`: return `float(SPEED_FILE.read_text())` clamped to 0.5–2.0 (Kokoro's range); on `OSError` or `ValueError` return `SPEED`. Call it for **every chunk** (never cache it).

`make_wav(chunk, rate)` (returns a WAV file path): if `local_kokoro` is None, `with connect_engine(60) as s:` send one line `json.dumps({"text": chunk, "voice": VOICE, "speed": rate}) + "\n"`, read one line back and return its `"wav"`. On `OSError`, `ValueError` or `KeyError`, set `local_kokoro = load_kokoro()` (the engine went away: finish this reply the old way) and continue. With `local_kokoro`: `create(chunk, voice=VOICE, speed=rate, lang="en-us")`, write to a `NamedTemporaryFile(suffix=".wav", delete=False)` with soundfile, return its path.

`make_audio(chunk, rate)`: `make_wav`, read it with `sf.read(wav, dtype="float32")`, delete the file, return `(samples, sample_rate)`.

`speak(text)`:
1. Delete `last.wav` (missing_ok), write `last.txt` = text.
2. `if not (engine_ready() or start_engine()): local_kokoro = load_kokoro()`.
3. `player = None`, `recording = []`. For each chunk: `rate = speed()`; `samples, sample_rate = make_audio(chunk, rate)` (made while the previous chunk plays); if there is a player, `player.wait(LEAD)`; if `speed() != rate` (the user changed the speed meanwhile), remake it with `make_audio(chunk, speed())` so the change is heard as soon as the current chunk ends; `player = player or Player(sample_rate)`; `player.add(samples)`; append to `recording`; the first time, set `started = True` and `set_state()`.
4. Write the concatenated recording (numpy) to `last.tmp.wav` and `replace` it onto `last.wav` (`Path.replace`, not `rename`, which fails on Windows when the target exists; atomic, so `voice again` never plays a half-written or mismatched file).
5. `player.finish()`.

`play(wav)`: read it, make a `Player`, add the samples, set `started = True` and `set_state()`, `finish()`.

Main: inside `try:` run `play(argv[2])` for `--play`, else `speak(text)`; in `finally:`, only if `PID` still holds this process's number (a newer reply may have taken over), delete `STATE`, `PID` and `PAUSE`.

Measured on an Intel Mac: from the first sound to the end takes the recording's length plus about 0.3 s, and a 3 s pause adds 3.1 s (the extra tenth is the `vo` command starting; nothing is skipped).

## voice_server.py (the voice engine)
A background process that keeps Kokoro loaded between replies, so speech starts in about half the time (measured on an Intel Mac: about 3 s to the first sound instead of about 6 s). While waiting it uses no CPU and about 500 MB of memory. Its docstring notes that `voice stop` stops speech, not the engine (it stops only the number in speak.pid), and that it listens on a port only this computer can reach.
```python
from common import DATA, lock
ENGINE = DATA / "engine.json"   # {"pid": ..., "port": ...}: how speak.py finds us, and `voice status` too
LOCK = DATA / "engine.lock"     # held while we run, so only one engine starts
IDLE_MINUTES = 45
```
- `log(msg)`: print `f"\n=== {time.ctime()} [engine] {msg}"` with `flush=True` (stdout goes to speak.log). Use `===`, **not** `---`: `voice status` reads the last `---` line as the last reply's decision.
- `serve(conn, kokoro)`: `conn.settimeout(10)`, read one line; if it's empty, return (that's `engine_ready()` checking). Otherwise parse the JSON, run `kokoro.create(text, voice=..., speed=..., lang="en-us")`, write a temp WAV (`delete=False`) and send back `json.dumps({"wav": path}) + "\n"`. If sending fails with `OSError`, delete the WAV (speak.py was stopped; nobody will play it) and re-raise.
- `main()`: `DATA.mkdir`; open `LOCK` in mode `"a"` and `lock(held, wait=False)`; on `OSError` return (another engine is already running). Model files are under `DATA`. Load Kokoro (do **not** run a warm-up sentence: the first real request warms it, and a warm-up only delays the first reply). `server = socket.create_server(("127.0.0.1", 0))` (port 0: the system picks a free one), `me = {"pid": os.getpid(), "port": <its port>}`, write `json.dumps(me)` to `ENGINE`, `settimeout(60)` so it wakes once a minute to check the idle clock. Log `voice engine ready (quits after 45 minutes unused)`. Loop while less than `IDLE_MINUTES` have passed since the last request: `accept()` (continue on `socket.timeout`), call `serve` inside `with conn:`, log `request failed: <repr>` on any exception, then reset the idle clock. After the loop log `voice engine quit after 45 minutes unused`. In a `finally`, delete `ENGINE` only if it still holds `json.dumps(me)`.

## speak_reply.py (the Stop hook)
Module docstring explains: Claude Code runs it after each reply, passing JSON on stdin with `last_assistant_message` and `session_id`; never block, never break a turn, never read the whole transcript (can exceed 100 MB, only its tail as fallback). Supports `--dry-run` (prints the speech text, does not speak or log).

Constants:
```python
from common import DATA, lock, read_pid, spawn
SPEAK = [sys.executable, HERE/"speak.py"]   # the same Python that runs this hook
LOG = DATA / "speak.log"
MIN_CHARS = 120     # shorter replies are skipped (mostly notices like "Login expired")
MAX_CHARS = 5000    # ~4-5 minutes of speech; cut at a sentence end
TAIL_BYTES = 4_000_000
MUTE_FLAG = ~/.claude/.speak-off           # voice mute / unmute
SESSION_MUTE_DIR = ~/.claude/speak-muted   # one empty file per muted session id
SESSION_LAST_DIR = DATA / "last-by-session"  # each session's last reply text (spoken or muted), for voice again
```

`already_taken(session, text) -> bool` (guard 2: if old install.sh hooks and the plugin's both fire, each reply is spoken once): `key = sha1(f"{session}\n{text}")`; holding `lock()` on `DATA/hook.lock` opened in mode `"a"` (the two copies run at the same moment), return True if `SESSION_LAST_DIR/<session>.taken` holds `key` and was written less than 60 s ago; otherwise write `key` there and return False.

`stop_old_speech()`: `pid = read_pid(DATA/"speak.pid", "speak.py")`; if found, `os.kill(pid, signal.SIGTERM)`.

`log(session, msg)`: no-op in dry-run; else append `f"\n--- {time.ctime()} [{session[:8]}] {msg}\n"` to `speak.log`.

`last_assistant_text(path)`: seek to `size - TAIL_BYTES`, split lines, iterate in reverse, skip blank/unparseable lines (a seek may land mid-line), keep rows with `type == "assistant"`, return the first `message.content[]` block of `type == "text"` whose stripped text is `>= MIN_CHARS`.

`strip_markdown(s)` in this order:
```python
s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)     # links -> link text
s = re.sub(r"`([^`]*)`", r"\1", s)                 # inline code
s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)           # bold
s = re.sub(r"(?<!\w)\*([^*]+)\*(?!\w)", r"\1", s)  # italic
s = re.sub(r"\s*[—–]\s*", ", ", s)                  # em/en dashes read badly
return re.sub(r"\s+", " ", s).strip()
```

`shorten_paths(s)`: a path read in full is unlistenable; say the name at its end.
```python
PATH_RE = re.compile(
    r"""(?<![\w/:~.-])                                       # not already inside a URL or token
        (?P<path>(?:~|\.{1,2})?/[\w.~+-]+(?:/[\w.~+-]+)+/?    # /a/b/c, ~/a/b, ./a/b
                 |[\w+-]+(?:/[\w.+-]+)+/?)                    # a/b, a/b/c
        (?<![.-])                                            # leave a sentence's full stop behind
        (?::(?P<line>\d+(?:-\d+)?))?                          # file.py:120, file.py:120-125
    """, re.X)
EXT_RE = re.compile(r"\.[A-Za-z]\w{0,4}$")
```
Replacement for each match:
- `name` = last segment of path (trailing `/` stripped); `parts` = path stripped of `/` split on `/`.
- `looks_like_one` = path starts with `~`, `.` or `/`, OR has more than 2 parts, OR name has an extension.
- `kind` = "the file" if name has an extension or starts with `.`, else "the folder".
- Clean name: strip leading dots, remove extension; split camelCase (`(?<=[a-z])(?=[A-Z])` -> space); `_+` and hyphens not between digits -> space (`r"_+|(?<!\d)-|-(?!\d)"`); collapse spaces; lowercase all-caps words longer than 1 char (so `TEMPLATE` is said, not spelled).
- If not `looks_like_one` or the cleaned name has no ASCII letter: return the original text unchanged (keeps `and/or`, `24/7/365`, dates).
- `sayable` = at most 6 words and not a hex hash (`[0-9a-f]{8,}`). Say `f"{kind} {name}"` if sayable else `"this path"`, plus `f", line {line}"` when a line number was matched.
- Example: `/Users/x/proj/spec/notes/_TEMPLATE.md:12` -> `the file template, line 12`.

`drop_foreign_scripts(s)`: Kokoro's English voice spells other scripts letter by letter, which is meaningless. Keep a char if: its Unicode category starts with `L`/`M` and its name starts with `LATIN`, `GREEK` or `COMBINING`; category `N` and name starts with `DIGIT`, `SUPERSCRIPT`, `SUBSCRIPT`, `VULGAR` or `ROMAN`; any other category (punctuation, spaces, symbols). Then clean up:
```python
s = re.sub(r"[(\[«“\"']\s*[)\]»”\"']", "", s)  # brackets/quotes left empty
s = re.sub(r"\s+([.,;:!?])", r"\1", s)         # "is ." -> "is."
s = re.sub(r"[:;,]+([.!?])", r"\1", s)         # "Hindi:." -> "Hindi."
return re.sub(r"\s+", " ", s).strip()
```

`say_powers(s)`: replace `²` with `" squared"` and `³` with `" cubed"`.

`join_lines(lines) -> str`: join a block's lines into one run of text, ending each list item with a full stop. Without it, "- Run the build" and "- Tell me the result" are spoken in one breath as "Run the build Tell me the result".
```python
LIST_MARKER = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")
```
Walk the lines building `[text, is_list_item]` pieces: a line matching `LIST_MARKER` starts a new item (marker removed, stripped); any other line is appended with a space to the previous piece (a wrapped line continues the item or paragraph), or starts a non-item piece if there is none yet. Join the pieces with spaces, adding `"."` to an item whose text is non-empty and, after stripping trailing `*_` `` ` `` and spaces (so `**Label:**` counts as ending in a colon), does not already end in one of `. ! ? : ; ,`.

`speakable(text) -> str | None`:
1. Replace fenced code blocks `re.sub(r"```.*?```", "\n\n\x00\n\n", text, flags=re.S)` (a placeholder, so the colon rule below can see that something followed).
2. Split into blocks on `\n\s*\n`. For each block (stripped): append `None` if empty, the `\x00` placeholder, starts with `#` (heading) or `>` (quote). Drop lines starting with `|` (tables); if no lines remain append `None`. Join the remaining lines with `join_lines(lines)` (below; lists are kept, because often the list is the whole answer) and run `say_powers(drop_foreign_scripts(shorten_paths(strip_markdown(joined))))`. Append it if `len >= 15`, else `None`.
3. Dangling colons: for each kept block ending in `:`, look at the very next entry in the list; if it is `None` (what it introduced was dropped), split the block into sentences with `r"(?<=[.!?])\s+(?=[A-Z])"`, drop sentences ending in `:`, and keep the rest (or `None`).
4. Add a `.` to any remaining part not ending in `.?!:`; join with spaces. Return `None` if nothing is left.
5. If longer than `MAX_CHARS`: cut to `MAX_CHARS`, then cut back to the last `". "`, `"? "` or `"! "` if it is beyond position 200, else to the last space.

`main()` order (each skip logs a reason and returns):
0. `DATA.mkdir(parents=True, exist_ok=True)`, `SESSION_LAST_DIR.mkdir(exist_ok=True)`.
1. Parse stdin JSON; on failure log `skipped: unreadable hook input` with session `?`.
2. `session = payload.get("session_id") or "?"`.
3. `text = payload.last_assistant_message` stripped (use the payload, NOT the transcript: reading the transcript races the write of the reply and can return the previous message). If non-empty and shorter than `MIN_CHARS` -> `skipped: reply too short (N chars, minimum 120)`.
4. Only if the key `last_assistant_message` is absent entirely (old Claude Code versions): use `transcript_path` with `last_assistant_text`; if missing -> `skipped: no reply text and no transcript`; source = "transcript".
5. No text -> `skipped: no reply text found`. `speakable()` returns None -> `skipped: nothing speakable (only code, tables or headings)`.
6. `--dry-run`: print the line and return.
7. Muted: if `MUTE_FLAG` exists (`all sessions muted (voice unmute)`), or env `SPEAK == "0"` (`session started with SPEAK=0`, so `SPEAK=0 claude` is a silent session), or `SESSION_MUTE_DIR/<session>` exists (`this session muted (! voice unmute here)`): write the line to `last-by-session/<session>.txt` anyway (so `voice again` reads this reply when asked, not an older one that happened to be spoken), log `skipped: <reason>; saved for voice again`, and return.
8. If `already_taken(session, line)`, log `skipped: already spoken by the other copy of this hook (run ./uninstall.sh in the old folder)` and return. Otherwise `stop_old_speech()` (a new reply replaces the old one). Log `spoke N chars (payload|transcript): <first 80 chars repr>`. Write the line to `last-by-session/<session>.txt`. Start `spawn(SPEAK + [line], LOG)` (so speak.py errors land in the log).

## voice (bash) and voice.py (the user's control panel, installed as `voice` and `vo`)
`voice` is only a wrapper: `DIR=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)`, then `exec "$DIR/run" voice.py "$@"`.

`voice.py` uses only the standard library and `common` at the top (`voice help` and `voice status` work before setup). `HERE` = resolved folder, `LOG = DATA/"speak.log"`, `MUTE_FLAG = ~/.claude/.speak-off`, `SESSION_MUTE_DIR = ~/.claude/speak-muted`, `SPEED_FILE = ~/.claude/speak-speed`, `NUMBER = re.compile(r"^[+-]?([0-9]+\.?[0-9]*|\.[0-9]+)$")`, `SESSION = os.environ.get("CLAUDE_CODE_SESSION_ID", "")` (set inside Claude Code `!` commands). All `last.*`, `speak.*` and `engine.json` paths are under `DATA`.
- `speak_py_setting(name)`: `VOICE` or `SPEED` read from the top of speak.py with `re.search(rf'^{name} = "?([^"\s]+)"?', text, re.M)`.
- `current_speed()`: the stripped contents of `SPEED_FILE` if it fully matches `[0-9]*\.?[0-9]+`, else `speak_py_setting("SPEED")`. Returned as text, as written.
- `set_speed(arg)`: if `reset`, delete `SPEED_FILE` and take `current_speed()` as the new speed. Otherwise a signed arg (`+.2`, `-.1`) is added to the current speed and an unsigned one (`1.3`) replaces it; `clamped` = outside 0.5–2; clamp, and format with `f"{v:.2f}".rstrip("0").rstrip(".")` (`1.30` -> `1.3`, `2.00` -> `2`); write it plus `\n` to `SPEED_FILE`. Either way, delete `last.wav` (the saved audio is at the old speed, so `voice again` makes it fresh), and print `speed 1.3x (was 1.1x)`, or `speed 2x (was 1.1x; the range is 0.5 to 2)` when clamped. If a replay is playing (the speech process's psutil `cmdline()` contains `--play`), also print `the replay playing now keeps its speed; the next reply, or vo a, uses <new>x`.
- `speech_pid()`: `read_pid(DATA/"speak.pid", "speak.py")`. `engine_pid()`: the `pid` in `engine.json`, if `is_running(pid, "voice_server.py")`.
- `stop_all()`: `os.kill(speech_pid, SIGTERM)` if any (ignore `OSError`); delete `speak.state`, `speak.pid`, `speak.pause`.
- `playback()`: empty when there is no speech process; `paused` when `speak.pause` holds its number (before speak.py has noticed); else the stripped `speak.state`.
- `again_file()`: `DATA/last-by-session/<SESSION>.txt` if `SESSION`, else `DATA/last.txt`. `saved_audio_matches(file)`: `last.wav` non-empty AND the file's bytes equal `last.txt`'s.
- `venv_python()`: `DATA/.venv/bin/python` or `DATA/.venv/Scripts/python.exe`, whichever exists (for the status Setup line).
- `main(args)`: `first = args[0]` or `help`. **First**, if `first` matches `NUMBER`, `set_speed(first)` and return 0 (before dash-stripping, or `-.1` would become `.1`). Then `cmd = first.lower().lstrip("-")` (so `stop`, `-stop`, `s` all work), `where` = second word lowercased.
- Commands:
  - `stop|s` -> stop_all; print `stopped`.
  - `pause|p` -> if there is a speech process and `playback()` is non-empty, write its number to `speak.pause` and print `paused (voice resume to continue)` (works before the first sound too); else `nothing playing`.
  - `resume|r|continue` -> if `playback()` is `paused`, delete `speak.pause` and print `resumed`; else `nothing paused`.
  - `again|a|repeat|replay` -> if the again file is empty/missing print `nothing spoken yet to repeat`; else stop_all, then if saved audio matches `spawn([sys.executable, HERE/"speak.py", "--play", DATA/"last.wav"])` (instant, and pause works the same), else `spawn([sys.executable, speak.py, <file's text>])` (regenerates); print `saying the last reply again`.
  - `speed` -> with a second word matching `NUMBER` or equal to `reset`, `set_speed` it; otherwise print `speed <current>x  (vo +.2 faster, vo -.1 slower, vo reset for the default)`.
  - `reset` -> `set_speed("reset")`.
  - `status|st` -> print `Voice-over status` then lines: `All sessions:  MUTED  (voice unmute)` or `on`; `This session:` MUTED / `silent (started with SPEAK=0)` / `on`, or `run '! voice status' inside Claude Code to see` when there's no session id; `Playback:` `paused  (voice resume)`, `speaking`, `preparing speech`, or `idle`; `Setup:` only when `venv_python()` or the model is missing: `downloading the voice now (see <DATA>/setup.log)` if `DATA/setup.lock` is a folder, else `not done yet (it runs by itself at the next session start, or run /voiceover:setup)`; `Voice engine:` `loaded (quick start; quits after 45 minutes unused)` if `engine_pid()`, else `not loaded (the next reply takes ~6s to start)`; `Voice:` `<VOICE> at <speed>x speed  (vo +.2 faster, vo -.1 slower)`; `Again:` `nothing spoken yet` / `ready, instant` / `regenerates (~3s)`; `Last reply:` the last line starting `--- ` in speak.log for this session (containing `[first 8 chars of session id]`), falling back to the most recent overall, without the `--- `, or `nothing logged yet`. Labels are padded so values line up (`  All sessions:  `, `  Playback:      `).
  - `mute|m` -> with `here`: require a session id (else print `run this inside Claude Code, with ! in front:  ! voice mute here` and exit 1), stop_all, touch `~/.claude/speak-muted/<id>`, print `this session muted (! voice unmute here to undo)`. Without: stop_all, touch `~/.claude/.speak-off`, print `all sessions muted (voice unmute to undo)`.
  - `unmute|u` -> the reverse (`this session unmuted` / `all sessions unmuted`).
  - `read` -> if `shutil.which("readalong")`, run it with the remaining arguments and return its exit code; else print `voice read needs readalong: github.com/venkatvyasam/readalong` and return 1. (Optional external tool; this repo does not read documents itself.)
  - `help|h` -> usage text (below).
  - anything else -> `voice: unknown command '<x>' (nothing was changed)`, blank line, usage, return 1.
- `--on-prompt` (the UserPromptSubmit hook), checked in `__main__` before `main`: read the hook JSON on stdin; if `prompt` matches `re.match(r"\s*!?\s*(voice|vo)\b", p, re.I)` do nothing (a voice command must not stop the speech it targets), otherwise stop_all. Wrapped in `try/except Exception: pass`; print nothing, always exit 0.
- Usage text:
```
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
Start a silent session:  SPEAK=0 claude
```

## audition.py
Model files under `DATA`. Plays every voice saying `"<name>. The agent reads the reply, runs the tool, and sends back an observation. Does this voice sound natural to you?"`. Args are voice-name prefixes (default `af_ am_ bf_ bm_`). Voices from `kokoro.get_voices()`, sorted. `lang` = `en-us` for prefix `a`, `en-gb` for `b`. Speed 1.1. Play with `sounddevice`: make the next voice while the current one plays (`sd.wait()` then `sd.play(samples, rate)`), print `NN/total  voice` as each starts, and `sd.wait()` at the end.

## README.md
Sections: intro (natural voice, free, offline, runs on your computer, a Mac or Windows, with Kokoro, link to kokoro-onnx), pointer to `docs/guide.html`, Requirements (on a Mac: Apple Silicon or Intel, macOS 13+, Claude Code, git via `xcode-select --install`, uv; on Windows, marked beta: Git for Windows (includes Git Bash), Claude Code and uv via their PowerShell installers, and adding `%USERPROFILE%\.local\bin` to PATH if `claude` or `uv` isn't found; ~500 MB disk), Install (`/plugin install voiceover --marketplace <owner>/voiceover`, then a new session; first-time setup runs by itself in the background and says "voiceover is ready"; `/voiceover:setup` repeats it; data in `~/.claude/voiceover`; a note for users of the older install.sh to run `./uninstall.sh` once; `./install.sh` and `claude --plugin-dir` for working on the code), Controls table (every command above, with short forms; note dashes optional and the `!` prefix inside Claude Code), "Speech stops by itself when you send your next message. Start a silent session with `SPEAK=0 claude`.", Change the voice (`./run audition.py af_ am_` or `bf_ bm_`, then edit `VOICE`), Uninstall (`/plugin uninstall voiceover@voiceover`, then `rm -rf ~/.claude/voiceover ~/.local/bin/voice ~/.local/bin/vo`, plus the `.cmd` wrappers on Windows), Files table (every file above, including `run` and `common.py`) (include `voice_server.py`: "the voice engine: keeps the voice loaded so replies start in about half the time; quits after 45 minutes unused").

## CLAUDE.md
Describe how the pieces fit (the plugin files, the three hooks, code vs data, what each function in speak_reply.py does, chunking, the voice engine and its fallback, state files `~/.claude/.speak-off`, `~/.claude/speak-muted/<session_id>` and `~/.claude/speak-speed`), list the load-bearing rules above, the testing commands below, the macOS/Windows split (`run` and `common.py`), a note that changes to `voice_server.py` need the running engine stopped first (`kill` the `pid` in `~/.claude/voiceover/engine.json`; the next reply starts the new one; `hooks/hooks.json` changes need `/reload-plugins`), and: replies in this repo are read aloud, so prefer short spoken-style paragraphs and put commands/paths/code in code blocks (the voice skips them). Users are learners: explain changes in plain terms.

## docs/guide.html
A single self-contained, friendly HTML guide for a beginner (light/dark aware, readable on a phone). Sections: Setup (which kind of Mac do you have; install git with `xcode-select --install`, since Claude Code needs it to download plugins; install uv; on Windows instead: Git for Windows, Claude Code and uv from PowerShell, the PATH fix, `curl.exe` in PowerShell, and a firewall note for "connection refused"; install the plugin; what the first session does), Daily use (the controls), How it works (hooks: your code runs at moments Claude Code chooses; what the Stop hook receives; what speak_reply.py decides, in order; why the first sound comes so quickly; how pause and stop work (the pause file, and why not a signal); the log; the files), Customize (pick a voice; other settings: SPEED, MIN_CHARS, MAX_CHARS, chunk sizes).

## When you're done, verify
```bash
claude plugin validate .                     # passes
./install.sh                                 # sets up DATA, the vo wrappers; hear "voiceover is ready"
P=./run
echo '{"session_id":"test","last_assistant_message":"Here is a longer reply about /Users/me/project/src/RootManifestFile.py:42 and some numbers like 5 m² so that it passes the 120 character minimum easily."}' | ./run speak_reply.py --dry-run
# expect: "... the file Root Manifest File, line 42 ... 5 m squared ..."
printf '%s' '{"session_id":"test","last_assistant_message":"Here are the next steps for the project, in the order I would do them this week:\n\n- Run the build\n- Tell me the result\n- **Then:** merge it"}' | ./run speak_reply.py --dry-run
# expect: "Here are the next steps ... this week: Run the build. Tell me the result. Then: merge it."
./run speak.py "First test starts the voice engine."     # about 6 s to the first sound
./run speak.py "Second test uses the loaded engine."     # about 3 s
vo status                                    # "Voice engine:  loaded ..."
vo +.2; vo -.1; vo +5; vo reset              # 1.3x, 1.2x, 2x (clamped, says the range), back to 1.1x
vo help; tail -5 ~/.claude/voiceover/speak.log; vo stop
```
Also test a **fresh install** without touching my real setup: run `session_start.sh` with `HOME` set to an empty temporary folder (keep `UV_CACHE_DIR` and `UV_PYTHON_INSTALL_DIR` pointing at the real ones, and copy the model files in to skip the download). Expect the "setting up" message, then `READY`, the wrappers and the spoken "ready"; a later session shows the welcome once, then nothing. Then fire the Stop hook command from `hooks/hooks.json` twice at the same moment: one copy speaks, the other logs "already spoken". Put an old-style hook in that temporary `settings.json` and check session_start.sh warns about it.

Then install it for real: `claude plugin marketplace add <this folder>` and `claude plugin install voiceover@voiceover`, start a new Claude Code session, ask something, and confirm the reply is spoken once; test `! vo p`, `! vo r`, `! vo a`, `! voice mute here`, and that typing a new message stops speech. `~/.claude/settings.json` must have no voiceover hooks. Also mute a session, ask something, and check `! vo a` reads that reply.

On Windows, in Git Bash: `git clone` the repo, `claude --plugin-dir <clone>`, and check the same: the setup message, "voiceover is ready", replies spoken (and still playing after Claude finishes), pause and resume, a new message stopping speech, and `vo status` in Command Prompt or PowerShell.
