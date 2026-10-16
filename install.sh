#!/bin/bash
# Installs the Claude Code voice-over. Safe to run again: it updates in place.
set -euo pipefail
DIR=$(cd "$(dirname "$0")" && pwd)
step() { printf '\n==> %s\n' "$1"; }

[ "$(uname)" = "Darwin" ] || { echo "Sorry: this tool currently works on macOS only."; exit 1; }
if ! command -v uv >/dev/null; then
  echo "uv (the Python tool manager) is not installed. Install it with:"
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
  echo "then open a new terminal window and run ./install.sh again."
  exit 1
fi

step "Installing Python packages (first time: about a minute)"
(cd "$DIR" && uv sync --quiet)

step "Downloading the Kokoro voice model (about 340 MB, first time only)"
mkdir -p "$DIR/models"
BASE=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0
for f in kokoro-v1.0.onnx voices-v1.0.bin; do
  if [ -s "$DIR/models/$f" ]; then
    echo "  $f: already downloaded"
  else
    curl -fL --progress-bar -o "$DIR/models/$f.part" "$BASE/$f"
    mv "$DIR/models/$f.part" "$DIR/models/$f"
  fi
done

step "Making the 'voice' command (and its short form 'vo') available"
mkdir -p ~/.local/bin
for name in voice vo; do
  link=~/.local/bin/$name
  if [ -e "$link" ] && [ "$(readlink "$link")" != "$DIR/voice" ]; then
    echo "  skipped $name: ~/.local/bin/$name already exists and belongs to something else"
  else
    ln -sf "$DIR/voice" "$link"; echo "  linked ~/.local/bin/$name"
  fi
done
# Earlier versions called this command 'shush'; remove that old link.
if [ -L ~/.local/bin/shush ] && { [ ! -e ~/.local/bin/shush ] || [ "$(readlink ~/.local/bin/shush)" = "$DIR/shush" ]; }; then
  rm ~/.local/bin/shush; echo "  removed the old 'shush' link"
fi
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) echo "  ~/.local/bin is not on your PATH yet. Run this once, then open a new terminal:"
     echo "    echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc" ;;
esac

step "Registering the Claude Code hooks"
"$DIR/.venv/bin/python" "$DIR/setup_hooks.py" install

step "Testing the voice (you should hear a short sentence)"
"$DIR/.venv/bin/python" "$DIR/speak.py" "Hello! The Claude Code voice-over is installed."

echo
echo "Done. Start a new Claude Code session and ask something: the reply will be read aloud."
echo "Controls: run 'voice help'."
