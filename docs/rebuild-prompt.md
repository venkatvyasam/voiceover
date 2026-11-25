# Prompt: rebuild "voiceover" from scratch

Paste everything below the line into Claude Code (in an empty folder, on a Mac).

---

Build a small macOS tool called **voiceover** in the current (empty) folder. It makes Claude Code read its own replies aloud using **Kokoro**, a free text-to-speech model that runs locally via `kokoro-onnx`. Follow this spec exactly: file names, constants, regexes, messages and behaviors all matter. Keep the code simple and readable; the users are a student and their family. Use **uv**, never pip. Do not edit `~/.claude/settings.json` by hand: only the `setup_hooks.py` script you write may touch it, and only when `install.sh` runs it.

## Files to create

```
.gitignore  .python-version  pyproject.toml  install.sh  uninstall.sh
setup_hooks.py  speak.py  voice_server.py  speak_reply.py  voice  audition.py
README.md  CLAUDE.md  docs/guide.html
```

`install.sh`, `uninstall.sh`, `voice` must be executable (`chmod +x`).

## Load-bearing rules (never break these)

1. A hook must never block or fail a Claude Code turn. `speak_reply.py` starts speech in a detached process and **always exits 0**, even on exceptions (`try: main() except Exception: pass; sys.exit(0)`).
2. `voice --on-prompt` must **print nothing** (UserPromptSubmit hook output is added to Claude's context).
3. Pause is `SIGUSR1` to `speak.py` and resume is `SIGUSR2`; `speak.py` plays the sound itself and holds its exact place. Never `SIGSTOP`: on macOS the sound clock keeps running, so a stopped player skips ahead on resume. `speak.py` must set its signal handlers before its slow imports (an unhandled `SIGUSR1` kills a process).
4. Only `setup_hooks.py` edits `~/.claude/settings.json`; it backs the file up first and touches only this tool's hooks.
5. `onnxruntime` is pinned to `==1.23.2` (last version with Intel Mac wheels; has Apple Silicon wheels too). Never upgrade it.
6. Hooks use this folder's **absolute path**. If the folder moves, `./install.sh` must be re-run.
7. The voice engine's file name (`voice_server.py`) must **not contain `speak.py`**: `voice stop` kills processes matching `speak.py`, and the engine must survive a stop.
8. Speech must **still work without the engine**. Every engine failure in `speak.py` falls back to loading Kokoro directly.

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
    "sounddevice>=0.5.6",
    "soundfile>=0.14.0",
]
```
Run `uv lock` to produce `uv.lock`.

## .gitignore
Standard Python ignores (`__pycache__/`, `*.py[oc]`, `build/`, `dist/`, `wheels/`, `*.egg-info`, `.venv`) plus:
`last.txt`, `last.wav`, `last-by-session/`, `last.tmp.wav`, `voice_server.sock`, `voice_server.lock`, `speak.state`, `models/` (comment: Kokoro model files ~337 MB, downloaded by setup), `speak.log`.

## install.sh (bash, `set -euo pipefail`, idempotent: "Safe to run again: it updates in place")
- `DIR` = absolute folder of the script. Helper `step()` prints `\n==> <msg>`.
- Exit with a friendly message unless `uname` is `Darwin`.
- If `uv` is missing: print how to install it (`curl -LsSf https://astral.sh/uv/install.sh | sh`), tell them to open a new terminal and re-run, exit 1.
- Step "Installing Python packages (first time: about a minute)": `(cd "$DIR" && uv sync --quiet)`.
- Step "Downloading the Kokoro voice model (about 340 MB, first time only)": into `$DIR/models/`, from base URL `https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0`, files `kokoro-v1.0.onnx` and `voices-v1.0.bin`. Skip a file if it exists and is non-empty (print "already downloaded"); otherwise `curl -fL --progress-bar` to `<file>.part` then `mv` into place (so an interrupted download never looks complete).
- Step "Making the 'voice' command (and its short form 'vo') available": `mkdir -p ~/.local/bin`; for `voice` and `vo`, symlink `~/.local/bin/<name>` -> `$DIR/voice` with `ln -sf`, unless that path exists and points somewhere else (then print "skipped <name>: ... belongs to something else"). Also remove a legacy `~/.local/bin/shush` symlink if it is dangling or points at `$DIR/shush`. If `~/.local/bin` is not in `$PATH`, print the one-liner to add `export PATH="$HOME/.local/bin:$PATH"` to `~/.zshrc`.
- Step "Registering the Claude Code hooks": `"$DIR/.venv/bin/python" "$DIR/setup_hooks.py" install`.
- Then `pkill -f "$DIR/voice_server.py" 2>/dev/null || true` (an engine left running uses the old code; the test below starts a fresh one).
- Step "Testing the voice (you should hear a short sentence)": `speak.py "Hello! The Claude Code voice-over is installed."`
- Finish with: "Done. Start a new Claude Code session and ask something: the reply will be read aloud." and "Controls: run 'voice help'."

## uninstall.sh (bash, `set -euo pipefail`)
Run `"$DIR/voice" stop` (ignore errors), `pkill -f "$DIR/voice_server.py"` (ignore errors; unloads the voice engine), `setup_hooks.py uninstall`, remove `~/.local/bin/voice` and `vo` only if they point at `$DIR/voice`, `rm -f ~/.claude/.speak-off ~/.claude/speak-speed`, `rm -rf ~/.claude/speak-muted`. Print that the folder (with the 340 MB model) is left in place and can be deleted.

## setup_hooks.py
Usage `setup_hooks.py install|uninstall` (otherwise `sys.exit(__doc__)`).
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

It plays the sound **itself**, through `sounddevice`, not through the Mac's `afplay`. `afplay` has two problems: it keeps running about a second after its sound ends (a 1-second silence between chunks), and pausing it with `SIGSTOP` skips ahead on resume, because the Mac's sound clock keeps running.

**Pause and resume are signals:** `voice pause` sends `SIGUSR1`, `voice resume` sends `SIGUSR2`. An unhandled `SIGUSR1` kills a process, and a pause can arrive while speak.py is still starting, so the very top of the file, **before** the slow imports (numpy, sounddevice, soundfile), is only:
```python
import signal
from pathlib import Path
HERE = Path(__file__).parent
STATE = HERE / "speak.state"   # "preparing", "speaking" or "paused"; removed when done
paused = False
started = False                # has any sound been queued yet?
def set_state(): STATE.write_text("paused" if paused else "speaking" if started else "preparing")
def on_pause(*_):  set paused = True (global), set_state()
def on_resume(*_): set paused = False (global), set_state()
signal.signal(signal.SIGUSR1, on_pause)
signal.signal(signal.SIGUSR2, on_resume)
if __name__ == "__main__":
    set_state()   # so `voice pause` sees us from the start
```
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
SOCKET = HERE / "voice_server.sock"
local_kokoro = None     # set only when the engine can't be used
```

`class Player` (plays chunks one after another with no gap; while paused it sends silence and keeps its place):
- `__init__(sample_rate)`: `self.rate`, `self.queue = collections.deque()` (arrays of samples; the first is playing), `self.pos = 0` (how far into `queue[0]`), `self.lock = threading.Lock()`, then `self.stream = sd.OutputStream(samplerate=sample_rate, channels=1, dtype="float32", callback=self.fill)` and `self.stream.start()`.
- `fill(out, frames, _time, _status)` (the sound card calls it for each small block): `out.fill(0)`; if `paused`, return (silence, place kept). Otherwise, under the lock, copy samples from `queue[0][pos:]` into `out[:, 0]` until `frames` are filled or the queue is empty, popping each array once fully played and resetting `pos`. If the queue runs dry, the rest stays silent (it never skips).
- `add(samples)`: append under the lock.
- `seconds_left()`: `(sum of queued lengths - pos) / rate`, under the lock.
- `wait(until=0.0)`: sleep 0.05 s at a time while `seconds_left() > until` (paused time doesn't count, because nothing is consumed while paused).
- `finish()`: `wait()`, then `stream.stop()` (returns once the last block has played) and `stream.close()`.

Import `kokoro_onnx` **only inside `load_kokoro()`** (it takes about a second to import, and the engine usually makes it unnecessary). `load_kokoro()` returns `Kokoro("models/kokoro-v1.0.onnx", "models/voices-v1.0.bin")` (paths relative to the script folder).

`chunks(text)`: split into sentences with `re.split(r"(?<=[.!?:])\s+", text.strip())`. Start with `limit = FIRST_CHUNK_CHARS`. A sentence longer than `limit` is split further with `re.split(r"(?<=[,;])\s+", sentence)`. For each piece: if `len(cur) >= MIN_CHUNK and len(cur) + len(piece) > limit`, emit `cur`, set `limit = min(CHUNK_CHARS, max(FIRST_CHUNK_CHARS, int(len(cur) * GROWTH)))`, reset `cur`. Then `cur = f"{cur} {piece}".strip()`. Return remaining `cur` too.

`engine_ready()`: try to connect a Unix socket (`AF_UNIX`) to `SOCKET` and close it at once; return True if that worked, False on `OSError`.

`start_engine()`: `Popen([sys.executable, HERE/"voice_server.py"], stdout/stderr = speak.log opened "ab", stdin=DEVNULL, start_new_session=True)`, then poll `engine_ready()` every 0.1 s for up to 30 s (loading usually takes about 5). Return True once ready, else False.

`speed()`: return `float(SPEED_FILE.read_text())` clamped to 0.5–2.0 (Kokoro's range); on `OSError` or `ValueError` return `SPEED`. Call it for **every chunk** (never cache it).

`make_wav(chunk, rate)` (returns a WAV file path): if `local_kokoro` is None, connect to `SOCKET` with a 60 s timeout, send one line `json.dumps({"text": chunk, "voice": VOICE, "speed": rate}) + "\n"`, read one line back and return its `"wav"`. On `OSError`, `ValueError` or `KeyError`, set `local_kokoro = load_kokoro()` (the engine went away: finish this reply the old way) and continue. With `local_kokoro`: `create(chunk, voice=VOICE, speed=rate, lang="en-us")`, write to a `NamedTemporaryFile(suffix=".wav", delete=False)` with soundfile, return its path.

`make_audio(chunk, rate)`: `make_wav`, read it with `sf.read(wav, dtype="float32")`, delete the file, return `(samples, sample_rate)`.

`speak(text)`:
1. Delete `last.wav` (missing_ok), write `last.txt` = text.
2. `if not (engine_ready() or start_engine()): local_kokoro = load_kokoro()`.
3. `player = None`, `recording = []`. For each chunk: `rate = speed()`; `samples, sample_rate = make_audio(chunk, rate)` (made while the previous chunk plays); if there is a player, `player.wait(LEAD)`; if `speed() != rate` (the user changed the speed meanwhile), remake it with `make_audio(chunk, speed())` so the change is heard as soon as the current chunk ends; `player = player or Player(sample_rate)`; `player.add(samples)`; append to `recording`; the first time, set `started = True` and `set_state()`.
4. Write the concatenated recording (numpy) to `last.tmp.wav` and `rename` it to `last.wav` (atomic, so `voice again` never plays a half-written or mismatched file).
5. `player.finish()`.

`play(wav)`: read it, make a `Player`, add the samples, set `started = True` and `set_state()`, `finish()`.

Main: inside `try:` run `play(argv[2])` for `--play`, else `speak(text)`; in `finally:` delete `STATE` (missing_ok).

Measured on an Intel Mac: from the first sound to the end takes the recording's length plus about 0.3 s, and a 3 s pause adds exactly 3 s (nothing skipped).

## voice_server.py (the voice engine)
A background process that keeps Kokoro loaded between replies, so speech starts in about half the time (measured on an Intel Mac: about 3 s to the first sound instead of about 6 s). While waiting it uses no CPU and about 500 MB of memory. Its docstring must say its name must not contain `speak.py`, and why.
```python
SOCKET = HERE / "voice_server.sock"
LOCK = HERE / "voice_server.lock"
IDLE_MINUTES = 45
```
- `log(msg)`: print `f"\n=== {time.ctime()} [engine] {msg}"` with `flush=True` (stdout goes to speak.log). Use `===`, **not** `---`: `voice status` reads the last `---` line as the last reply's decision.
- `serve(conn, kokoro)`: `conn.settimeout(10)`, read one line; if it's empty, return (that's `engine_ready()` checking). Otherwise parse the JSON, run `kokoro.create(text, voice=..., speed=..., lang="en-us")`, write a temp WAV (`delete=False`) and send back `json.dumps({"wav": path}) + "\n"`. If sending fails with `OSError`, delete the WAV (speak.py was stopped; nobody will play it) and re-raise.
- `main()`: open `LOCK` and take `fcntl.flock(LOCK_EX | LOCK_NB)`; on `BlockingIOError` return (another engine is already running). Load Kokoro (do **not** run a warm-up sentence: the first real request warms it, and a warm-up only delays the first reply). Unlink a stale `SOCKET`, bind an `AF_UNIX` socket there, `listen()`, `settimeout(60)` so it wakes once a minute to check the idle clock. Log `voice engine ready (quits after 45 minutes unused)`. Loop while less than `IDLE_MINUTES` have passed since the last request: `accept()` (continue on `socket.timeout`), call `serve` inside `with conn:`, log `request failed: <repr>` on any exception, then reset the idle clock. After the loop log `voice engine quit after 45 minutes unused`. In a `finally`, unlink `SOCKET`.

## speak_reply.py (the Stop hook)
Module docstring explains: Claude Code runs it after each reply, passing JSON on stdin with `last_assistant_message` and `session_id`; never block, never break a turn, never read the whole transcript (can exceed 100 MB, only its tail as fallback). Supports `--dry-run` (prints the speech text, does not speak or log).

Constants:
```python
SPEAK = [HERE/".venv/bin/python", HERE/"speak.py"]
LOG = HERE / "speak.log"
MIN_CHARS = 120     # shorter replies are skipped (mostly notices like "Login expired")
MAX_CHARS = 5000    # ~4-5 minutes of speech; cut at a sentence end
TAIL_BYTES = 4_000_000
MUTE_FLAG = ~/.claude/.speak-off           # voice mute / unmute
SESSION_MUTE_DIR = ~/.claude/speak-muted   # one empty file per muted session id
SESSION_LAST_DIR = HERE / "last-by-session"  # each session's last spoken text, for voice again
```

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
1. Parse stdin JSON; on failure log `skipped: unreadable hook input` with session `?`.
2. `session = payload.get("session_id") or "?"`.
3. `MUTE_FLAG` exists -> `skipped: all sessions muted (voice unmute)`.
4. env `SPEAK == "0"` -> `skipped: session started with SPEAK=0` (so `SPEAK=0 claude` is a silent session).
5. `SESSION_MUTE_DIR/<session>` exists -> `skipped: this session muted (! voice unmute here)`.
6. `text = payload.last_assistant_message` stripped (use the payload, NOT the transcript: reading the transcript races the write of the reply and can return the previous message). If non-empty and shorter than `MIN_CHARS` -> `skipped: reply too short (N chars, minimum 120)`.
7. Only if the key `last_assistant_message` is absent entirely (old Claude Code versions): use `transcript_path` with `last_assistant_text`; if missing -> `skipped: no reply text and no transcript`; source = "transcript".
8. No text -> `skipped: no reply text found`. `speakable()` returns None -> `skipped: nothing speakable (only code, tables or headings)`.
9. `--dry-run`: print the line and return.
10. `pkill -f <HERE/speak.py>` (output to devnull) so a new reply replaces the old one. Log `spoke N chars (payload|transcript): <first 80 chars repr>`. Write the line to `last-by-session/<session>.txt`. Start `speak.py <line>` with `Popen(..., stdout=log, stderr=log, stdin=DEVNULL, start_new_session=True)` where log is `speak.log` opened in append-binary mode (so speak.py errors land in the log).

## voice (bash; the user's control panel, installed as `voice` and `vo`)
- `DIR=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)` (resolves through the `~/.local/bin` symlink; `readlink -f` needs macOS 12.3+). `PY=$DIR/.venv/bin/python`, `LOG=$DIR/speak.log`, `SESSION_MUTE_DIR=~/.claude/speak-muted`, `SPEED_FILE=~/.claude/speak-speed`, `NUMBER='^[+-]?([0-9]+\.?[0-9]*|\.[0-9]+)$'`.
- `current_speed`: the contents of `SPEED_FILE` if it is a plain number, else `SPEED` parsed from speak.py with sed.
- `set_speed ARG`: if ARG is `reset`, delete `SPEED_FILE` (so the default applies) and take `current_speed` as the new speed. Otherwise, with awk, a signed ARG (`+.2`, `-.1`, `+1.2`) is added to `current_speed`; an unsigned one (`1.3`) replaces it. Clamp to 0.5–2, format with `%.2f` then strip trailing zeros and a trailing dot (`1.30` -> `1.3`, `2.00` -> `2`). write it to `SPEED_FILE`. Either way, delete `last.wav` (the saved audio is at the old speed, so `voice again` makes it fresh), and print `speed 1.3x (was 1.1x)`, adding `; the range is 0.5 to 2` inside the parentheses when it was clamped. If a replay is playing (`pgrep -f "$DIR/speak.py --play"`), also print `the replay playing now keeps its speed; the next reply, or vo a, uses <new>x` (a replay plays a finished recording, so its speed is fixed).
- **Before** the dash-stripping below: if `$1` matches `NUMBER`, run `set_speed "$1"` and exit 0. This must come first, or `-.1` would become `.1`.
- `again_file`: if `$CLAUDE_CODE_SESSION_ID` is set (it is, inside Claude Code `!` commands) use `$DIR/last-by-session/$CLAUDE_CODE_SESSION_ID.txt`, else `$DIR/last.txt`.
- `saved_audio_matches FILE`: `last.wav` non-empty AND `cmp -s FILE last.txt`.
- `stop_all`: `pkill -f "$DIR/speak.py" 2>/dev/null; rm -f "$DIR/speak.state"`.
- `playback`: `pgrep -f "$DIR/speak.py" >/dev/null && cat "$DIR/speak.state" 2>/dev/null` (prints preparing, speaking or paused; nothing when idle).
- Argument parsing: command = `$1` (default `help`), lowercased, leading dashes stripped (so `stop`, `-stop`, `s` all work). Second word `$2` lowercased (`here`).
- Commands:
  - `stop|s` -> stop_all; print `stopped`.
  - `pause|p` -> if `playback` prints anything, `pkill -USR1 -f "$DIR/speak.py"` and print `paused (voice resume to continue)` (works before the first sound too); else `nothing playing`.
  - `resume|r|continue` -> if `playback` is `paused`, `pkill -USR2 -f "$DIR/speak.py"` and print `resumed`; else `nothing paused`.
  - `again|a|repeat|replay` -> if the again file is empty/missing print `nothing spoken yet to repeat`; else stop_all, then if saved audio matches `nohup $PY speak.py --play last.wav &` (instant, and pause works the same), else `nohup $PY speak.py "$(cat file)" &` (regenerates); print `saying the last reply again`.
  - `speed` -> with a second word matching `NUMBER` or equal to `reset`, `set_speed` it; otherwise print `speed <current>x  (vo +.2 faster, vo -.1 slower, vo reset for the default)`.
  - `reset` -> `set_speed reset`.
  - `status|st` -> print `Voice-over status` then lines: `All sessions:  MUTED  (voice unmute)` or `on`; `This session:` MUTED / `silent (started with SPEAK=0)` / `on`, or a hint to run `! voice status` inside Claude Code when no session id; `Playback:` from `playback`: `paused  (voice resume)`, `speaking`, `preparing speech`, or `idle` when it prints nothing; `Voice engine:` `loaded (quick start; quits after 45 minutes unused)` if `pgrep -f "$DIR/voice_server.py"` finds it, else `not loaded (the next reply takes ~6s to start)`; `Voice:` VOICE parsed from speak.py with sed, and `current_speed` (`<voice> at <speed>x speed  (vo +.2 faster, vo -.1 slower)`); `Again:` `nothing spoken yet` / `ready, instant` / `regenerates (~3s)`; `Last reply:` the last `--- ` line in speak.log for this session (match `[first 8 chars of session id]`), falling back to the most recent overall, or `nothing logged yet`.
  - `mute|m` -> with `here`: require a session id (else print `run this inside Claude Code, with ! in front:  ! voice mute here` and exit 1), stop_all, touch `~/.claude/speak-muted/<id>`, print `this session muted (! voice unmute here to undo)`. Without: stop_all, touch `~/.claude/.speak-off`, print `all sessions muted (voice unmute to undo)`.
  - `unmute|u` -> the reverse (`this session unmuted` / `all sessions unmuted`).
  - `read` -> shift; if a `readalong` command exists `exec readalong "$@"`, else print `voice read needs readalong: github.com/venkatvyasam/readalong` and exit 1. (Optional external tool; this repo does not read documents itself.)
  - `help|h` -> usage text (below).
  - `on-prompt` (invoked as `--on-prompt` by the UserPromptSubmit hook): read the hook JSON on stdin with `$PY -c`; if `prompt` matches `re.match(r"\s*!?\s*(voice|vo)\b", p, re.I)` do nothing (a voice command must not stop the speech it targets), otherwise stop_all. Print nothing, always `exit 0`.
  - anything else -> `voice: unknown command '<x>' (nothing was changed)`, blank line, usage, exit 1.
- Usage text:
```
voice: controls for the Claude Code voice-over   (vo is the short form)
Inside Claude Code, start with !   e.g.  ! voice pause

  voice stop          stop speaking now                        vo s
  voice pause         pause                                    vo p
  voice resume        continue where it paused                 vo r
  voice again         say this session's last reply again      vo a
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
Plays every voice saying `"<name>. The agent reads the reply, runs the tool, and sends back an observation. Does this voice sound natural to you?"`. Args are voice-name prefixes (default `af_ am_ bf_ bm_`). Voices from `kokoro.get_voices()`, sorted. `lang` = `en-us` for prefix `a`, `en-gb` for `b`. Speed 1.1. Pipeline generation/playback like speak.py and print `NN/total  voice` as each starts.

## README.md
Sections: intro (natural voice, free, offline, runs on the Mac with Kokoro, link to kokoro-onnx), pointer to `docs/guide.html`, Requirements (macOS Apple Silicon or Intel, Claude Code, uv, ~500 MB disk), Install (`git clone`, `cd voiceover`, `./install.sh`), Controls table (every command above, with short forms; note dashes optional and the `!` prefix inside Claude Code), "Speech stops by itself when you send your next message. Start a silent session with `SPEAK=0 claude`.", Change the voice (`.venv/bin/python audition.py af_ am_` or `bf_ bm_`, then edit `VOICE`), Uninstall, Files table (include `voice_server.py`: "the voice engine: keeps the voice loaded so replies start in about half the time; quits after 45 minutes unused").

## CLAUDE.md
Describe how the pieces fit (the two hooks, what each function in speak_reply.py does, chunking, the voice engine and its fallback, state files `~/.claude/.speak-off`, `~/.claude/speak-muted/<session_id>` and `~/.claude/speak-speed`), list the load-bearing rules above, the testing commands below, a note that changes to `voice_server.py` need the running engine stopped first (`pkill -f voice_server.py`; the next reply starts the new one), and: replies in this repo are read aloud, so prefer short spoken-style paragraphs and put commands/paths/code in code blocks (the voice skips them). Users are learners: explain changes in plain terms.

## docs/guide.html
A single self-contained, friendly HTML guide for a beginner (light/dark aware, readable on a phone). Sections: Setup (which kind of Mac do you have; install uv; get the code; run install.sh), Daily use (the controls), How it works (hooks: your code runs at moments Claude Code chooses; what the Stop hook receives; what speak_reply.py decides, in order; why the first sound comes so quickly; how pause and stop work; the log; the files), Customize (pick a voice; other settings: SPEED, MIN_CHARS, MAX_CHARS, chunk sizes).

## When you're done, verify
```bash
./install.sh                     # hear "Hello! The Claude Code voice-over is installed."
echo '{"session_id":"test","last_assistant_message":"Here is a longer reply about /Users/me/project/src/RootManifestFile.py:42 and some numbers like 5 m² so that it passes the 120 character minimum easily."}' | .venv/bin/python speak_reply.py --dry-run
# expect: "... the file Root Manifest File, line 42 ... 5 m squared ..."
printf '%s' '{"session_id":"test","last_assistant_message":"Here are the next steps for the project, in the order I would do them this week:\n\n- Run the build\n- Tell me the result\n- **Then:** merge it"}' | .venv/bin/python speak_reply.py --dry-run
# expect: "Here are the next steps ... this week: Run the build. Tell me the result. Then: merge it."
.venv/bin/python speak.py "First test starts the voice engine."     # about 6 s to the first sound
.venv/bin/python speak.py "Second test uses the loaded engine."     # about 3 s
./voice status                    # "Voice engine:  loaded ..."
./voice +.2; ./voice -.1; ./voice +5; ./voice reset   # 1.3x, 1.2x, 2x (clamped, says the range), back to 1.1x
pkill -f voice_server.py; .venv/bin/python speak.py "Still speaks with no engine."   # fallback works (it restarts the engine)
./voice help
tail -5 speak.log
./voice stop
```
Then open a new Claude Code session, ask something, and confirm the reply is spoken; test `! vo p`, `! vo r`, `! vo a`, `! voice mute here`, and that typing a new message stops speech.
Show me `~/.claude/settings.json`'s `hooks` section after install so I can confirm only the two hooks were added.
