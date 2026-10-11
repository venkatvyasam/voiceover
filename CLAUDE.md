# speak-claude

Claude Code reads its own replies aloud with Kokoro, a free text-to-speech model that runs locally. macOS only.
The people using this repo are learning (a student, and his family). Explain changes in plain terms and keep the code simple and readable.

## How it fits together

Two Claude Code hooks, registered in `~/.claude/settings.json` by `setup_hooks.py`:

- **Stop** → `speak_reply.py`: checks the mutes, takes `last_assistant_message` from the hook input, skips replies under `MIN_CHARS`, cleans the text for speech (`speakable()` drops code blocks, tables, headings and `>` quotes), stops any older speech, starts `speak.py` detached, logs the decision to `speak.log`.
- **UserPromptSubmit** → `shush --on-prompt`: stops speech when the user sends a message, unless the message mentions shush.

`speak.py` splits text into chunks that grow by at most `GROWTH` (1.8x), generates the next chunk while the current one plays through `afplay`, and saves `last.txt` / `last.wav` for `shush -a`.
`shush` is the user's control panel (stop, pause, resume, repeat, mute, status). `shush -h` lists everything.

State outside the repo: `~/.claude/.speak-off` (mute all), `~/.claude/speak-muted/<session_id>` (mute one session).

## Rules that must not break

- **A hook must never block or fail a turn.** `speak_reply.py` detaches `speak.py` and always exits 0, even on exceptions.
- **`shush --on-prompt` must print nothing.** A UserPromptSubmit hook's output is added to Claude's context.
- **Pause is `SIGSTOP` on `afplay`.** A stopped process can't exit, so anything that kills speech must also send `SIGCONT` (see `stop_all` in `shush`).
- **Only `setup_hooks.py` edits `~/.claude/settings.json`.** It backs the file up and touches only this tool's hooks.
- **Use uv, never pip.** `onnxruntime` is pinned to 1.23.2, the last version with Intel Mac builds (it has Apple Silicon builds too). Don't upgrade it.
- The hooks point at this folder's absolute path. If the folder moves, run `./install.sh` again.

## Testing changes

```bash
# What the hook would say, without speaking or logging
echo '{"session_id":"test","last_assistant_message":"<a reply of 120+ characters>"}' | .venv/bin/python speak_reply.py --dry-run

# Speak something directly
.venv/bin/python speak.py "Testing one two three."

# Current state, and why the last reply was spoken or skipped
./shush status
tail -5 speak.log

# Stop anything left playing after a test
./shush
```

Changes to `speak.py`, `speak_reply.py` and `shush` take effect on the next reply; no restart needed.

## Working in this repo

- Replies here are read aloud by this tool. Prefer short spoken-style paragraphs, and put commands, paths and code in code blocks (the voice skips them).
- Make changes on a branch (`git checkout -b my-change`). Don't push to `main` without checking with Venkat, who owns the repo.
- If someone asks to set this up: run `./install.sh`, then `./shush status`. Prerequisites are macOS 13+, `uv`, and Claude Code. The full guide is `docs/guide.html`.
