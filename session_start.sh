#!/bin/bash
# SessionStart hook of the voiceover plugin. Runs as every Claude Code session starts, so it
# must be quick:
#   - records where the plugin's code is now, for the `voice` wrapper (the folder changes
#     with every plugin update);
#   - starts setup.sh in the background if the voice isn't installed yet, or the packages changed;
#   - warns if the old install.sh hooks are still in ~/.claude/settings.json.
# Anything it prints must be JSON with a "systemMessage", which is shown to the user.
# Plain text would be added to Claude's context instead.
ROOT=$(cd "$(dirname "$0")" && pwd)
DATA="${VOICEOVER_DATA:-$HOME/.claude/voiceover}"
PATH="$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"   # where uv usually lives
mkdir -p "$DATA" && echo "$ROOT" > "$DATA/root"
msg=""
say() { msg="${msg:+$msg }$1"; }

if grep -qE 'speak_reply\.py|voice\\?" --on-prompt' ~/.claude/settings.json 2>/dev/null; then
  say "voiceover: the old hooks from install.sh are still in ~/.claude/settings.json. Run ./uninstall.sh in the old folder. Until then each reply is still read only once."
fi

ready() {
  [ -x "$DATA/.venv/bin/python" ] && [ -s "$DATA/models/kokoro-v1.0.onnx" ] && [ -s "$DATA/models/voices-v1.0.bin" ] \
    && [ "$(cat "$DATA/READY" 2>/dev/null)" = "$(cksum < "$ROOT/uv.lock" | cut -d' ' -f1)" ]
}
if ! ready; then
  if [ -d "$DATA/setup.lock" ] && [ -z "$(find "$DATA/setup.lock" -maxdepth 0 -mmin +30)" ]; then
    say "voiceover: still setting up the voice. Replies will be read aloud once it's ready."
  elif ! command -v uv >/dev/null; then
    say "voiceover needs uv to install its voice. Run: curl -LsSf https://astral.sh/uv/install.sh | sh   then start a new session."
  else
    rmdir "$DATA/setup.lock" 2>/dev/null   # left behind by a setup that was interrupted
    nohup "$ROOT/setup.sh" >> "$DATA/setup.log" 2>&1 < /dev/null &
    say "voiceover: setting up the voice in the background (about 340 MB, a minute or two). You'll hear it say it's ready."
  fi
fi

[ -n "$msg" ] && printf '{"systemMessage": "%s"}\n' "$msg"
exit 0
