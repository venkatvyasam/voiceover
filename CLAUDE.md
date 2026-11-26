# voiceover

Claude Code reads its own replies aloud with Kokoro, a free text-to-speech model that runs locally. macOS only.
The people using this repo are learning (a student, and his family). Explain changes in plain terms and keep the code simple and readable.

## How it fits together

voiceover is a Claude Code plugin: `.claude-plugin/plugin.json` labels it, `.claude-plugin/marketplace.json` makes this repo its own marketplace (`/plugin install voiceover --marketplace venkatvyasam/voiceover`), and `hooks/hooks.json` registers three hooks:

- **SessionStart** → `session_start.sh`: writes the current code folder to `~/.claude/voiceover/root` (the `voice` wrapper reads it; a plugin's folder changes with every update), starts `setup.sh` in the background if the voice isn't installed or `uv.lock` changed, and warns if old install.sh hooks are still in `~/.claude/settings.json`. It may print only JSON with a `systemMessage` (shown to the user); plain text would go into Claude's context.
- **Stop** → `speak_reply.py`: checks the mutes, takes `last_assistant_message` from the hook input, skips replies under `MIN_CHARS`, cleans the text for speech (`speakable()` drops code blocks, tables, headings and `>` quotes; `shorten_paths()` says a long path as the name on the end of it; `drop_foreign_scripts()` removes scripts the English voice can only spell out letter by letter, like Arabic or Chinese; `say_powers()` reads m² as "m squared"), skips a reply another copy of the hook already took (`already_taken()`: old install.sh hooks and the plugin's both fire), stops any older speech (by the number in `speak.pid`), starts `speak.py` detached, logs the decision to `speak.log`.
- **UserPromptSubmit** → `voice --on-prompt`: stops speech when the user sends a message, unless the message is itself a voice command (starts with `voice` or `vo`).

`speak.py` splits text into chunks that grow by at most `GROWTH` (1.8x), generates the next chunk while the current one plays, and saves `last.txt` / `last.wav` for `voice again`. It plays the sound itself through `sounddevice` (the `Player` class): the chunks go into one queue that the sound card reads from, so they play back to back with no gap, and pause holds the exact place. `speak.py --play FILE` plays a saved recording the same way (`voice again` uses it). `speak.state` tells `voice status` whether it's preparing, speaking or paused.
It used to play through the Mac's `afplay`, which had two problems: it runs about a second after its sound ends (a silence between every chunk), and pausing it with `SIGSTOP` skipped ahead on resume, because the Mac's sound clock kept running.
The generating happens in `voice_server.py`, the voice engine: a background process that keeps Kokoro loaded (about 500 MB, no CPU while waiting) and answers over `voice_server.sock`. `speak.py` starts it when it isn't running, and loads Kokoro itself if the engine can't be reached. The engine quits after `IDLE_MINUTES` (45) unused. A warm engine halves the wait for the first sound (about 3s instead of 6s on Venkat's Intel Mac).
`voice` is the user's control panel (stop, pause, resume, again, mute, status), installed as `voice` and `vo`. `voice help` lists everything.
`setup.sh` installs the Python packages (`uv sync` into `~/.claude/voiceover/.venv`), downloads the model into `~/.claude/voiceover/models`, writes the `voice` / `vo` wrappers in `~/.local/bin`, and writes `READY` (a checksum of `uv.lock`). `/voiceover:setup` (`commands/setup.md`) runs it on request. `install.sh` is for working on the code: it runs `setup.sh` and points `voice` at the clone. `uninstall.sh` removes old install.sh hooks.
`voice read FILE` hands off to the separate `readalong` tool (github.com/venkatvyasam/readalong); reading whole documents lives there, not here.

**Code and data are separate.** The code is the plugin folder (`HERE` / `DIR` / `ROOT`). Everything that's downloaded or changes lives in `DATA`, `~/.claude/voiceover` (override with `VOICEOVER_DATA`, e.g. for tests): `.venv`, `models/`, `speak.log`, `last.txt` / `last.wav`, `last-by-session/`, `speak.pid`, `speak.state`, `voice_server.sock` / `.lock` (the lock holds the engine's number), `root`, `READY`, `setup.log`.

Settings in `~/.claude`: `~/.claude/.speak-off` (mute all), `~/.claude/speak-muted/<session_id>` (mute one session), `~/.claude/speak-speed` (reading speed set with `vo 1.3`, `vo +.2` or `vo -.1`; `speak.py` reads it for every chunk, so a change is heard once the chunk playing now ends; without it, `SPEED` in `speak.py` is used).

## Rules that must not break

- **A hook must never block or fail a turn.** `speak_reply.py` detaches `speak.py` and always exits 0, even on exceptions.
- **`voice --on-prompt` must print nothing.** A UserPromptSubmit hook's output is added to Claude's context.
- **Pause is `SIGUSR1` to `speak.py`, resume is `SIGUSR2`.** Not `SIGSTOP`: that skips audio on resume. `speak.py` sets its signal handlers before its slow imports, because an unhandled `SIGUSR1` kills a process, and `voice pause` may arrive while it is still starting.
- **Signal processes by the number they wrote, never by name.** `speak.pid` and `voice_server.lock` hold the numbers, and every user checks with `ps` that the number still belongs to `speak.py` / `voice_server.py` before signalling. Names change with plugin versions, and a stale number may belong to another program.
- **Write nothing that changes into the plugin folder.** It is replaced with every update; use `DATA`.
- **The Stop hook's command must fail quietly until setup is done** (`... 2>/dev/null || true`), because `DATA/.venv` doesn't exist yet.
- **Speech must still work without the engine.** Every engine failure in `speak.py` falls back to loading Kokoro directly.
- **Only `setup_hooks.py` edits `~/.claude/settings.json`**, and now only to remove old install.sh hooks. It backs the file up and touches only this tool's hooks.
- **Use uv, never pip.** `onnxruntime` is pinned to 1.23.2, the last version with Intel Mac builds (it has Apple Silicon builds too). Don't upgrade it.

## Testing changes

```bash
# What the hook would say, without speaking or logging
echo '{"session_id":"test","last_assistant_message":"<a reply of 120+ characters>"}' | ~/.claude/voiceover/.venv/bin/python speak_reply.py --dry-run

# Speak something directly
~/.claude/voiceover/.venv/bin/python speak.py "Testing one two three."

# Current state, and why the last reply was spoken or skipped
./voice status
tail -5 ~/.claude/voiceover/speak.log

# Stop anything left playing after a test
./voice stop

# Check the plugin files, and load this folder as the plugin for one session
claude plugin validate .
claude --plugin-dir .
```

Changes to `speak.py`, `speak_reply.py` and `voice` take effect on the next reply; no restart needed.
Changes to `voice_server.py` need the running engine stopped first: `kill $(cat ~/.claude/voiceover/voice_server.lock)` (the next reply starts the new one). Changes to `hooks/hooks.json` need `/reload-plugins` or a new session.

## Working in this repo

- Replies here are read aloud by this tool. Prefer short spoken-style paragraphs, and put commands, paths and code in code blocks (the voice skips them).
- Make changes on a branch (`git checkout -b my-change`). Don't push to `main` without checking with Venkat, who owns the repo.
- If someone asks to set this up: install the plugin (`/plugin install voiceover --marketplace venkatvyasam/voiceover`), start a new session, then `! voice status`. Prerequisites are macOS 13+, git (`xcode-select --install` on a new Mac; the plugin install fails without it), `uv`, and Claude Code. The full guide is `docs/guide.html`.
