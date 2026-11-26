#!/bin/bash
# For working on voiceover's code. Sets up the voice (the same setup the plugin runs by itself)
# and points the `voice` command at this folder. It no longer adds hooks to
# ~/.claude/settings.json: the plugin provides them. To use voiceover day to day, install the
# plugin; see the README. Safe to run again.
set -euo pipefail
DIR=$(cd "$(dirname "$0")" && pwd)
DATA="${VOICEOVER_DATA:-$HOME/.claude/voiceover}"
mkdir -p "$DATA"

# Older versions kept the voice model in this folder: move it rather than download it again.
if [ -d "$DIR/models" ] && [ ! -e "$DATA/models" ]; then
  mv "$DIR/models" "$DATA/models"
  echo "moved the voice model to $DATA/models"
fi

echo "$DIR" > "$DATA/root"   # `voice` runs this folder's code
"$DIR/setup.sh"

echo
echo "To try this folder as the plugin, for one session:  claude --plugin-dir \"$DIR\""
