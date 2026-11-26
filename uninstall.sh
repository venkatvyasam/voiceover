#!/bin/bash
# Removes what an older install.sh set up: its two hooks in ~/.claude/settings.json and its
# links to this folder's `voice`. Run it once when you switch to the plugin, so each reply
# isn't handled twice. It leaves the plugin and the voice in ~/.claude/voiceover alone.
set -euo pipefail
DIR=$(cd "$(dirname "$0")" && pwd)
DATA="${VOICEOVER_DATA:-$HOME/.claude/voiceover}"

"$DIR/voice" stop >/dev/null 2>&1 || true
PY="$DATA/.venv/bin/python"; [ -x "$PY" ] || PY="$DIR/.venv/bin/python"; [ -x "$PY" ] || PY=python3
"$PY" "$DIR/setup_hooks.py" uninstall
for name in voice vo; do
  if [ -L ~/.local/bin/$name ] && [ "$(readlink ~/.local/bin/$name)" = "$DIR/voice" ]; then
    rm ~/.local/bin/$name
    echo "  removed the old link ~/.local/bin/$name"
  fi
done

echo
echo "The old hooks are gone. If the voiceover plugin is installed, it carries on as before."
echo "To remove voiceover completely:"
echo "  claude plugin uninstall voiceover@voiceover"
echo "  rm -rf ~/.claude/voiceover ~/.local/bin/voice ~/.local/bin/vo ~/.claude/speak-speed ~/.claude/.speak-off ~/.claude/speak-muted"
