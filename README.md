# speak-claude

Claude Code reads its replies aloud in a natural voice. It's free, works offline, and runs entirely on your Mac using the [Kokoro](https://github.com/thewh1teagle/kokoro-onnx) text-to-speech model.

**Full guide:** open [`docs/guide.html`](docs/guide.html) in a browser. It covers setup, daily use, how it works, and ideas for extending it.

## Requirements

- macOS (Apple Silicon or Intel)
- [Claude Code](https://code.claude.com)
- [uv](https://docs.astral.sh/uv/): `curl -LsSf https://astral.sh/uv/install.sh | sh`
- About 500 MB of free disk space (the voice model is 340 MB)

## Install

```bash
git clone <this repo's URL>
cd speak-claude
./install.sh
```

You'll hear a test sentence. Start a new Claude Code session and ask something: the reply is read aloud.

## Controls

Type these in a terminal, or in Claude Code with a `!` in front (`! shush -p`).

| Command | Does |
|---|---|
| `shush` | stop speaking |
| `shush -p` / `shush -r` | pause / resume |
| `shush -a` | say the last reply again |
| `shush status` | what's muted or playing, and why the last reply was spoken or skipped |
| `shush -m` / `shush -u` | mute / unmute every session |
| `shush -s` / `shush -s off` | mute / unmute only the current Claude Code session |
| `shush -h` | help |

Speech stops by itself when you send your next message. Start a silent session with `SPEAK=0 claude`.

## Change the voice

Listen to the options with `.venv/bin/python audition.py af_ am_` (American) or `bf_ bm_` (British), then set `VOICE` at the top of `speak.py`.

## Uninstall

```bash
./uninstall.sh
```

This removes the hooks and the `shush` command. Delete the folder to remove everything else.

## Files

| File | Role |
|---|---|
| `speak_reply.py` | Claude Code **Stop hook**: picks the text to read and starts `speak.py` |
| `speak.py` | turns text into speech with Kokoro and plays it in chunks |
| `shush` | the controls, plus the **UserPromptSubmit hook** that stops speech when you send a message |
| `setup_hooks.py` | adds or removes the two hooks in `~/.claude/settings.json` (backs it up first) |
| `install.sh` / `uninstall.sh` | setup and removal |
| `audition.py` | plays voices so you can pick one |
| `speak.log` | one line per reply: spoken, or skipped and why |
