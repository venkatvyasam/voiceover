---
description: Install or repair voiceover's voice (Python packages and the 340 MB Kokoro model)
---

Run this command with the Bash tool, and wait for it to finish (the first time it downloads about 340 MB, so allow up to 10 minutes):

```bash
"${CLAUDE_PLUGIN_ROOT}/setup.sh"
```

Then tell the user in two or three plain sentences what happened: whether the voice is set up, and if not, what the output says to do (for example, install uv). Don't show the whole output unless it failed.
