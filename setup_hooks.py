"""Add (install) or remove (uninstall) the voice-over hooks in ~/.claude/settings.json.

Backs the file up first and touches only this tool's hooks: any older copy of them
(even from another folder) is replaced, so replies are never spoken twice.
Usage: .venv/bin/python setup_hooks.py install|uninstall
"""
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
SETTINGS = Path.home() / ".claude" / "settings.json"
STOP_CMD = f'"{HERE}/.venv/bin/python" "{HERE}/speak_reply.py"'
PROMPT_CMD = f'"{HERE}/voice" --on-prompt 2>/dev/null || true'
OURS = ("speak_reply.py", "speak-reply.py", "shush --on-prompt", 'shush" --on-prompt', 'voice" --on-prompt')


def is_ours(hook: dict) -> bool:
    return any(marker in hook.get("command", "") for marker in OURS)


def main(action: str) -> None:
    settings = json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {}
    if SETTINGS.exists():
        backup = SETTINGS.with_name(f"settings.json.bak-{datetime.now():%Y%m%d-%H%M%S-%f}")
        shutil.copy2(SETTINGS, backup)
        print(f"  backed up your settings to {backup}")

    hooks = settings.setdefault("hooks", {})
    for event in ("Stop", "UserPromptSubmit"):
        entries = []
        for entry in hooks.get(event, []):
            entry["hooks"] = [h for h in entry.get("hooks", []) if not is_ours(h)]
            if entry["hooks"]:
                entries.append(entry)          # someone else's hook: keep it
        if entries:
            hooks[event] = entries
        else:
            hooks.pop(event, None)

    if action == "install":
        hooks.setdefault("Stop", []).append({"hooks": [{"type": "command", "command": STOP_CMD}]})
        hooks.setdefault("UserPromptSubmit", []).append({"hooks": [{"type": "command", "command": PROMPT_CMD}]})
    if not hooks:
        settings.pop("hooks")

    SETTINGS.parent.mkdir(exist_ok=True)
    SETTINGS.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
    print(f"  {'registered' if action == 'install' else 'removed'} the voice-over hooks in {SETTINGS}")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("install", "uninstall"):
        sys.exit(__doc__)
    main(sys.argv[1])
