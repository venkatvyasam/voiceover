"""Claude Code Stop hook: read Claude's reply aloud with Kokoro (free, runs on your Mac).

Claude Code runs this every time a reply finishes, passing JSON on stdin that includes
`last_assistant_message` (the reply text) and `session_id`. The voiceover plugin registers
it (hooks/hooks.json).

Design rules, all load-bearing:
  * Never block the session: speech runs in a detached process and this exits at once.
  * Never break a turn: every path exits 0, exceptions included.
  * Never read the whole transcript (it can pass 100 MB): only its tail, and only as a
    fallback for Claude Code versions that don't send `last_assistant_message`.

Every decision (spoken, or skipped and why) goes to speak.log in DATA, which `voice status` reads.
Test without speaking:  echo '{"last_assistant_message": "..."}' | ~/.claude/voiceover/.venv/bin/python speak_reply.py --dry-run
"""
import fcntl
import hashlib
import json
import os
import signal
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent   # the code
DATA = Path(os.environ.get("VOICEOVER_DATA", Path.home() / ".claude" / "voiceover"))  # the voice, log and saved replies
SPEAK = [str(DATA / ".venv/bin/python"), str(HERE / "speak.py")]
LOG = DATA / "speak.log"

MIN_CHARS = 120    # shorter replies are skipped: mostly notices like "Login expired"
MAX_CHARS = 5000   # ~4-5 minutes of speech; longer replies are cut at a sentence end
TAIL_BYTES = 4_000_000
MUTE_FLAG = os.path.expanduser("~/.claude/.speak-off")            # voice mute / unmute
SESSION_MUTE_DIR = os.path.expanduser("~/.claude/speak-muted")    # voice mute here: one file per session id
SESSION_LAST_DIR = DATA / "last-by-session"                        # voice again: each session's last spoken reply


def log(session: str, msg: str) -> None:
    if "--dry-run" in sys.argv:
        return
    with open(LOG, "a") as f:
        f.write(f"\n--- {time.ctime()} [{session[:8]}] {msg}\n")


def already_taken(session: str, text: str) -> bool:
    """True if another copy of this hook already took this reply in the last minute.

    The old install.sh hooks in ~/.claude/settings.json and the plugin's hooks both fire
    if both are installed; without this, every reply would be read twice.
    """
    key = hashlib.sha1(f"{session}\n{text}".encode()).hexdigest()
    mark = SESSION_LAST_DIR / f"{session}.taken"
    with open(DATA / "hook.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)   # the two copies run at the same moment: one at a time here
        if mark.exists() and mark.read_text() == key and time.time() - mark.stat().st_mtime < 60:
            return True
        mark.write_text(key)
    return False


def stop_old_speech() -> None:
    """A new reply replaces whatever is still being read."""
    try:
        pid = int((DATA / "speak.pid").read_text())
    except (OSError, ValueError):
        return
    command = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True).stdout
    if "speak.py" in command:   # the number could belong to some other program by now
        os.kill(pid, signal.SIGTERM)


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


PATH_RE = re.compile(
    r"""(?<![\w/:~.-])                                       # not already inside a URL or token
        (?P<path>(?:~|\.{1,2})?/[\w.~+-]+(?:/[\w.~+-]+)+/?    # /a/b/c, ~/a/b, ./a/b
                 |[\w+-]+(?:/[\w.+-]+)+/?)                    # a/b, a/b/c
        (?<![.-])                                            # leave a sentence's full stop behind
        (?::(?P<line>\d+(?:-\d+)?))?                          # file.py:120, file.py:120-125
    """,
    re.X,
)
EXT_RE = re.compile(r"\.[A-Za-z]\w{0,4}$")


def shorten_paths(s: str) -> str:
    """A path read out in full is unlistenable; say the name on the end of it instead.

    "/Users/x/claude_projects/iceberg-internals/spec/notes/_TEMPLATE.md:12" becomes
    "the file template, line 12". A name that is a hash, or otherwise nothing a
    voice can say, becomes "this path". Anything that only looks like a path, such
    as "and/or" or "24/7/365", is left exactly as it was.
    """
    def spoken(m: re.Match) -> str:
        path = m.group("path")
        name = path.rstrip("/").rsplit("/", 1)[-1]
        parts = path.strip("/").split("/")
        looks_like_one = path[0] in "~./" or len(parts) > 2 or EXT_RE.search(name)
        kind = "the file" if EXT_RE.search(name) or name.startswith(".") else "the folder"
        name = EXT_RE.sub("", name.lstrip("."))               # watch.py -> watch
        name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)      # RootManifestFile -> Root Manifest File
        name = re.sub(r"_+|(?<!\d)-|-(?!\d)", " ", name)      # spec__main -> spec main, 2026-10-22 kept
        name = re.sub(r"\s+", " ", name).strip()
        name = " ".join(w.lower() if w.isupper() and len(w) > 1 else w
                        for w in name.split())      # DIRECTION -> direction, said not spelled
        if not looks_like_one or not re.search(r"[A-Za-z]", name):
            return m.group(0)                                 # not a path at all; say it as written
        sayable = len(name.split()) <= 6 and not re.fullmatch(r"[0-9a-f]{8,}", name)
        said = f"{kind} {name}" if sayable else "this path"
        return f"{said}, line {m.group('line')}" if m.group("line") else said

    return PATH_RE.sub(spoken, s)


def say_powers(s: str) -> str:
    """The voice reads "m²" as "m two"; say it the way people do."""
    return s.replace("²", " squared").replace("³", " cubed")


LIST_MARKER = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")


def join_lines(lines: list[str]) -> str:
    """Join a block's lines into one run of text, ending each list item with a full stop.

    Without the stop, "- Run the build" and "- Tell me the result" are spoken as one
    breath: "Run the build Tell me the result". Wrapped lines of a paragraph or of one
    item are joined with a space, as before.
    """
    pieces: list[list] = []                        # [text, is_list_item]
    for ln in lines:
        if LIST_MARKER.match(ln):
            pieces.append([LIST_MARKER.sub("", ln).strip(), True])
        elif pieces:
            pieces[-1][0] += " " + ln.strip()      # a wrapped line continues the item or paragraph
        else:
            pieces.append([ln.strip(), False])
    # Look past trailing markdown marks: "**Label:**" already ends in a colon.
    return " ".join(
        text + "." if is_item and text and not text.rstrip("*_` ").endswith((".", "!", "?", ":", ";", ",")) else text
        for text, is_item in pieces
    )


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
        # Strip list markers so "- foo" reads as "foo", not "dash foo", and end each
        # item with a full stop so the items don't run together when spoken.
        out = say_powers(drop_foreign_scripts(shorten_paths(strip_markdown(join_lines(lines)))))
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
    DATA.mkdir(parents=True, exist_ok=True)
    SESSION_LAST_DIR.mkdir(exist_ok=True)
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

    if already_taken(session, line):
        return log(session, "skipped: already spoken by the other copy of this hook (run ./uninstall.sh in the old folder)")
    stop_old_speech()
    log(session, f"spoke {len(line)} chars ({source}): {line[:80]!r}")
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
