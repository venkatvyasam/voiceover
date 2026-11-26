#!/bin/bash
# Sets up voiceover's voice: the Python packages and the Kokoro model (about 340 MB), in
# ~/.claude/voiceover. Safe to run again: it only fetches what's missing.
#
# The plugin runs this by itself in the background (session_start.sh), and /voiceover:setup
# runs it on request. When it's done it writes READY, so the next session doesn't start it again.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")" && pwd)                 # the code
DATA="${VOICEOVER_DATA:-$HOME/.claude/voiceover}"   # where the voice goes
step() { printf '\n==> %s\n' "$1"; }
PATH="$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"   # where uv usually lives

[ "$(uname)" = "Darwin" ] || { echo "voiceover works on macOS only."; exit 1; }
command -v uv >/dev/null || {
  echo "voiceover needs uv (the Python tool manager). Install it with:"
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
  echo "then start a new Claude Code session."
  exit 1
}
mkdir -p "$DATA"
# One setup at a time: a second session starting meanwhile leaves this one to finish.
mkdir "$DATA/setup.lock" 2>/dev/null || { echo "voiceover setup is already running"; exit 0; }
trap 'rmdir "$DATA/setup.lock" 2>/dev/null' EXIT
first_time=$([ -e "$DATA/READY" ] && echo no || echo yes)

step "Installing the Python packages (first time: about a minute)"
UV_PROJECT_ENVIRONMENT="$DATA/.venv" uv sync --project "$ROOT" --frozen --quiet

step "Downloading the Kokoro voice (about 340 MB, first time only)"
mkdir -p "$DATA/models"
BASE=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0
for f in kokoro-v1.0.onnx voices-v1.0.bin; do
  if [ -s "$DATA/models/$f" ]; then
    echo "  $f: already downloaded"
  else
    curl -fL --progress-bar -o "$DATA/models/$f.part" "$BASE/$f"
    mv "$DATA/models/$f.part" "$DATA/models/$f"
  fi
done

step "Making the 'voice' command (and its short form 'vo') available"
mkdir -p ~/.local/bin
for name in voice vo; do
  link=~/.local/bin/$name
  # Ours: a wrapper written here, or a link from an older install.sh to a voice script.
  if [ -e "$link" ] && ! grep -q "voiceover wrapper" "$link" 2>/dev/null \
     && ! { [ -L "$link" ] && [ -e "$(dirname "$(readlink "$link")")/speak.py" ]; }; then
    echo "  skipped $name: ~/.local/bin/$name already exists and belongs to something else"
    continue
  fi
  rm -f "$link"
  # The code moves with every plugin update, so the wrapper looks up where it is now.
  printf '#!/bin/bash\n# voiceover wrapper: runs the voice script of the installed version\nexec "$(cat "%s/root")/voice" "$@"\n' "$DATA" > "$link"
  chmod +x "$link"
  echo "  made ~/.local/bin/$name"
done
[ -s "$DATA/root" ] || echo "$ROOT" > "$DATA/root"
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) echo "  ~/.local/bin is not on your PATH yet. Run this once, then open a new terminal:"
     echo "    echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc" ;;
esac

cksum < "$ROOT/uv.lock" | cut -d' ' -f1 > "$DATA/READY"   # a new uv.lock (new packages) means set up again
echo
echo "voiceover is set up. Replies will be read aloud."
if [ "$first_time" = yes ] && [ ! -e ~/.claude/.speak-off ]; then
  "$DATA/.venv/bin/python" "$ROOT/speak.py" "voiceover is ready. Claude's replies will now be read aloud." || true
fi
