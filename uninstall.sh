#!/bin/bash
# Removes the Claude Code voice-over hooks and the 'shush' link. Leaves this folder in place.
set -euo pipefail
DIR=$(cd "$(dirname "$0")" && pwd)

"$DIR/shush" >/dev/null 2>&1 || true            # stop anything still speaking
"$DIR/.venv/bin/python" "$DIR/setup_hooks.py" uninstall
if [ "$(readlink ~/.local/bin/shush 2>/dev/null)" = "$DIR/shush" ]; then
  rm ~/.local/bin/shush
  echo "  removed ~/.local/bin/shush"
fi
rm -f ~/.claude/.speak-off
rm -rf ~/.claude/speak-muted

echo
echo "Uninstalled. Claude Code will stop reading replies in new sessions."
echo "To delete everything (including the 340 MB model), delete this folder: $DIR"
