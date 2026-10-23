"""Claude Code Stop hook: read Claude's reply aloud with Kokoro (free, runs on your Mac).

Claude Code runs this every time a reply finishes, passing JSON on stdin that includes
`last_assistant_message` (the reply text) and `session_id`. install.sh registers it in
~/.claude/settings.json.

Design rules, all load-bearing:
  * Never block the session: speech runs in a detached process and this exits at once.
  * Never break a turn: every path exits 0, exceptions included.
  * Never read the whole transcript (it can pass 100 MB): only its tail, and only as a
    fallback for Claude Code versions that don't send `last_assistant_message`.

Every decision (spoken, or skipped and why) goes to speak.log, which `voice status` reads.
Test without speaking:  echo '{"last_assistant_message": "..."}' | .venv/bin/python speak_reply.py --dry-run
"""
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEAK = [str(HERE / ".venv/bin/python"), str(HERE / "speak.py")]
LOG = HERE / "speak.log"

MIN_CHARS = 120    # shorter replies are skipped: mostly notices like "Login expired"
MAX_CHARS = 5000   # ~4-5 minutes of speech; longer replies are cut at a sentence end
TAIL_BYTES = 4_000_000
MUTE_FLAG = os.path.expanduser("~/.claude/.speak-off")            # voice mute / unmute
SESSION_MUTE_DIR = os.path.expanduser("~/.claude/speak-muted")    # voice mute here: one file per session id
SESSION_LAST_DIR = HERE / "last-by-session"                        # voice again: each session's last spoken reply


def log(session: str, msg: str) -> None:
    if "--dry-run" in sys.argv:
        return
    with open(LOG, "a") as f:
        f.write(f"\n--- {time.ctime()} [{session[:8]}] {msg}\n")


def last_assistant_text(path: str) -> str | None:
    """Fallback: the last long-enough assistant text, read from the tail of the transcript."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        f.seek(max(0, size - TAIL_BYTES))
        lines = f.read().split(b"\n")
    for raw in reversed(lines):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except Exception:
            continue  # a tail seek can land mid-line; skip the fragment
        if row.get("type") != "assistant":
            continue
        for block in row.get("message", {}).get("content", []) or []:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "").strip()
                if len(text) >= MIN_CHARS:
                    return text
    return None


def strip_markdown(s: str) -> str:
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)   # links -> link text
    s = re.sub(r"`([^`]*)`", r"\1", s)               # inline code
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)         # bold
    s = re.sub(r"(?<!\w)\*([^*]+)\*(?!\w)", r"\1", s)  # italic
    s = re.sub(r"\s*[—–]\s*", ", ", s)                # dashes read badly
    return re.sub(r"\s+", " ", s).strip()


def drop_foreign_scripts(s: str) -> str:
    """Remove text the English voice can't pronounce.

    Kokoro's English voice spells other scripts letter by letter ("Arabic meem,
    Arabic ra, ..."), which is meaningless to hear. Latin (including accents like
    "días") and Greek (σ is read "sigma") are kept; Arabic, Hebrew, Indic scripts,
    Chinese, Cyrillic and the rest are dropped.
    """
    def keep(ch: str) -> bool:
        cat = unicodedata.category(ch)[0]
        name = unicodedata.name(ch, "")
        if cat in "LM":                               # letters and accent marks
            return name.startswith(("LATIN", "GREEK", "COMBINING"))
        if cat == "N":                                # keep 2, ², ½; drop Arabic-Indic and other script digits
            return name.startswith(("DIGIT", "SUPERSCRIPT", "SUBSCRIPT", "VULGAR", "ROMAN"))
        return True                                   # punctuation, spaces, symbols

    s = "".join(ch for ch in s if keep(ch))
    s = re.sub(r"[(\[«“\"']\s*[)\]»”\"']", "", s)   # brackets or quotes left empty
    s = re.sub(r"\s+([.,;:!?])", r"\1", s)            # "is ." -> "is."
    s = re.sub(r"[:;,]+([.!?])", r"\1", s)            # "Hindi:." -> "Hindi."
    return re.sub(r"\s+", " ", s).strip()


def say_powers(s: str) -> str:
    """The voice reads "m²" as "m two"; say it the way people do."""
    return s.replace("²", " squared").replace("³", " cubed")


def speakable(text: str) -> str | None:
    """Everything worth hearing: prose and list items, in order.

    Skips what reads badly aloud: fenced code, tables, headings, block quotes.
    Lists are kept, because in a reply like "what are the next tasks" the list is
    the whole answer.
    """
    # Fenced code becomes a placeholder, not nothing: a block is dropped either
    # way, but the marker lets the colon pass below see that something followed.
    text = re.sub(r"```.*?```", "\n\n\x00\n\n", text, flags=re.S)

    kept: list[str | None] = []
    for block in re.split(r"\n\s*\n", text):
        b = block.strip()
        if not b or b == "\x00" or b.startswith("#") or b.startswith(">"):
            kept.append(None)
            continue
        lines = [ln for ln in b.splitlines() if not ln.lstrip().startswith("|")]
        if not lines:
            kept.append(None)                             # table-only block
            continue
        # Strip list markers so "- foo" reads as "foo", not "dash foo".
        lines = [re.sub(r"^\s*(?:[-*+]|\d+\.)\s+", "", ln) for ln in lines]
        out = say_powers(drop_foreign_scripts(strip_markdown(" ".join(lines))))
        kept.append(out if len(out) >= 15 else None)

    # A sentence ending in ":" introduces something. If what it introduced was
    # dropped (a code block, a table), the colon dangles. Drop the orphaned lead-in.
    for i, cur in enumerate(kept):
        if not cur or not cur.rstrip().endswith(":"):
            continue
        nxt = next((kept[j] for j in range(i + 1, len(kept))), None)
        if nxt is not None:
            continue                                      # it introduced real speech
        head = re.split(r"(?<=[.!?])\s+(?=[A-Z])", cur.rstrip())
        head = [h for h in head if not h.rstrip().endswith(":")]
        kept[i] = " ".join(head) if head else None

    parts = [p if p.endswith((".", "?", "!", ":")) else p + "."
             for p in kept if p]
    if not parts:
        return None
    speech = " ".join(parts)
    if len(speech) > MAX_CHARS:
        cut = speech[:MAX_CHARS]
        stop = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
        speech = cut[: stop + 1] if stop > 200 else cut.rsplit(" ", 1)[0]
    return speech


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return log("?", "skipped: unreadable hook input")
    session = payload.get("session_id") or "?"
    if os.path.exists(MUTE_FLAG):
        return log(session, "skipped: all sessions muted (voice unmute)")
    if os.environ.get("SPEAK") == "0":   # `SPEAK=0 claude` starts a silent session
        return log(session, "skipped: session started with SPEAK=0")
    if os.path.exists(os.path.join(SESSION_MUTE_DIR, session)):
        return log(session, "skipped: this session muted (! voice unmute here)")

    # Claude Code passes the final reply itself. Reading the transcript instead
    # races the write of that reply and can return the previous message.
    text = (payload.get("last_assistant_message") or "").strip()
    source = "payload"
    if len(text) < MIN_CHARS:
        if text:
            return log(session, f"skipped: reply too short ({len(text)} chars, minimum {MIN_CHARS})")
        text = None
    if text is None and "last_assistant_message" not in payload:
        path = payload.get("transcript_path")
        if not path or not os.path.exists(path):
            return log(session, "skipped: no reply text and no transcript")
        text = last_assistant_text(path)
        source = "transcript"
    if not text:
        return log(session, "skipped: no reply text found")
    line = speakable(text)
    if not line:
        return log(session, "skipped: nothing speakable (only code, tables or headings)")

    if "--dry-run" in sys.argv:
        print(line)
        return

    # A new reply replaces whatever is still being read.
    subprocess.run(["pkill", "-f", str(HERE / "speak.py")],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log(session, f"spoke {len(line)} chars ({source}): {line[:80]!r}")
    SESSION_LAST_DIR.mkdir(exist_ok=True)
    (SESSION_LAST_DIR / f"{session}.txt").write_text(line)
    with open(LOG, "ab") as out:   # speak.py errors land in the log too
        subprocess.Popen(SPEAK + [line], stdout=out, stderr=out,
                         stdin=subprocess.DEVNULL, start_new_session=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass          # a hook must never disrupt the turn
    sys.exit(0)
