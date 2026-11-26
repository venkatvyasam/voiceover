# voiceover

Claude Code reads its replies aloud in a natural voice. It's free, works offline, and runs entirely on your Mac using the [Kokoro](https://github.com/thewh1teagle/kokoro-onnx) text-to-speech model.

**Full guide:** open [`docs/guide.html`](docs/guide.html) in a browser. It covers setup, daily use, how it works, and ideas for extending it.

## Requirements

- macOS (Apple Silicon or Intel)
- [Claude Code](https://code.claude.com)
- git, which Claude Code uses to download plugins. A new Mac doesn't have it: run `xcode-select --install` and click Install
- [uv](https://docs.astral.sh/uv/): `curl -LsSf https://astral.sh/uv/install.sh | sh`
- About 500 MB of free disk space (the voice model is 340 MB)

## Install

voiceover is a Claude Code plugin. In Claude Code, type:

```
/plugin install voiceover --marketplace venkatvyasam/voiceover
```

Then start a new session. The first time, it sets up the voice by itself in the background (about 340 MB, a minute or two) and says "voiceover is ready" when it's done. From then on, every reply is read aloud. If setup needs anything (usually uv), a message at the start of the session says so. You can repeat setup any time with `/voiceover:setup`.

Everything it downloads lives in `~/.claude/voiceover`, and the `voice` / `vo` commands go in `~/.local/bin`.

**Used the older `install.sh` version?** Run `./uninstall.sh` in that folder once, so its hooks are removed. Until you do, the plugin makes sure each reply is still read only once, and reminds you at the start of each session.

**Working on the code:** run `./install.sh` in a clone to set up the voice and point `voice` at your clone, then try your changes with `claude --plugin-dir /path/to/your/clone`.

## Controls

Type these in a terminal, or in Claude Code with a `!` in front (`! voice pause`). `vo` is a short form, and each word has a one-letter shortcut (`vo p`). Dashes are optional (`voice -stop` works too).

| Command | Does |
|---|---|
| `voice stop` (`vo s`) | stop speaking |
| `voice pause` / `voice resume` (`vo p` / `vo r`) | pause / resume |
| `voice again` (`vo a`) | say this session's last reply again (outside Claude Code: the last reply from any session) |
| `vo +.2` / `vo -.1` | speak faster / slower by that much; remembered, and heard once the chunk playing now ends |
| `vo 1.3` | set the speed directly (0.5 to 2) |
| `vo reset` | speed back to the default (1.1) |
| `voice status` | what's muted or playing, and why the last reply was spoken or skipped |
| `voice mute` / `voice unmute` | mute / unmute every session |
| `voice mute here` / `voice unmute here` | mute / unmute only the current Claude Code session |
| `voice read FILE` | read a document aloud with [readalong](https://github.com/venkatvyasam/readalong), if it's installed (optional; readalong is private for now, so the link only works if you have access) |
| `voice help` | help |

Speech stops by itself when you send your next message. Start a silent session with `SPEAK=0 claude`.

## Change the voice

Listen to the options with `.venv/bin/python audition.py af_ am_` (American) or `bf_ bm_` (British), then set `VOICE` at the top of `speak.py`.

## Uninstall

```
/plugin uninstall voiceover@voiceover
```

Then delete what it downloaded: `rm -rf ~/.claude/voiceover ~/.local/bin/voice ~/.local/bin/vo`. Your settings (speed, mutes) are the files `~/.claude/speak-speed`, `~/.claude/.speak-off` and the folder `~/.claude/speak-muted`.

## Files

| File | Role |
|---|---|
| `.claude-plugin/` | the plugin's label (`plugin.json`) and its one-plugin marketplace (`marketplace.json`) |
| `hooks/hooks.json` | the plugin's three hooks: session start, reply finished (Stop), message sent |
| `session_start.sh` | **SessionStart hook**: starts the setup in the background if needed, warns about old install.sh hooks |
| `setup.sh` | sets up the voice in `~/.claude/voiceover` and the `voice` / `vo` commands; `/voiceover:setup` runs it too |
| `commands/setup.md` | the `/voiceover:setup` command |
| `speak_reply.py` | Claude Code **Stop hook**: picks the text to read and starts `speak.py` |
| `speak.py` | turns text into speech with Kokoro and plays it in chunks |
| `voice_server.py` | the voice engine: keeps the voice loaded so replies start in about half the time; quits after 45 minutes unused |
| `voice` | the controls (installed as `voice` and `vo`), plus the **UserPromptSubmit hook** that stops speech when you send a message |
| `setup_hooks.py` | removes the hooks an older install.sh added to `~/.claude/settings.json` (backs it up first) |
| `install.sh` / `uninstall.sh` | for working on the code: set up the voice for a clone / remove the old install.sh hooks |
| `audition.py` | plays voices so you can pick one |
| `~/.claude/voiceover/speak.log` | one line per reply: spoken, or skipped and why |

## License

[MIT](LICENSE): use, change and share it freely; keep the copyright notice.
The Kokoro voice model, downloaded by `install.sh`, has its own license (Apache 2.0).
