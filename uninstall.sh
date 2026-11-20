#!/bin/bash
# Removes the Claude Code voice-over hooks and the 'voice' / 'vo' commands. Leaves this folder in place.
set -euo pipefail
DIR=$(cd "$(dirname "$0")" && pwd)

"$DIR/voice" stop >/dev/null 2>&1 || true       # stop anything still speaking
pkill -f "$DIR/voice_server.py" 2>/dev/null || true   # and unload the voice engine
"$DIR/.venv/bin/python" "$DIR/setup_hooks.py" uninstall
for name in voice vo; do
  if [ "$(readlink ~/.local/bin/$name 2>/dev/null)" = "$DIR/voice" ]; then
    rm ~/.local/bin/$name
    echo "  removed ~/.local/bin/$name"
  fi
done
rm -f ~/.claude/.speak-off
rm -rf ~/.claude/speak-muted

echo
echo "Uninstalled. Claude Code will stop reading replies in new sessions."
echo "To delete everything (including the 340 MB model), delete this folder: $DIR"
