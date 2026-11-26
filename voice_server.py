"""The voice engine: keeps Kokoro loaded between replies so speech starts quickly.

speak.py starts this when it isn't running, then sends it one chunk of text at a time
over a Unix socket; it answers with the path of a WAV file it made. While it waits it
uses no CPU and about 500 MB of memory, and it quits by itself after IDLE_MINUTES
with no requests. The next reply after that starts it again (the slow way, once).

`voice stop` stops speech, not the engine: it signals only the number in speak.pid.
"""
import fcntl
import json
import os
import socket
import tempfile
import time
from pathlib import Path

import soundfile as sf
from kokoro_onnx import Kokoro

DATA = Path(os.environ.get("VOICEOVER_DATA", Path.home() / ".claude" / "voiceover"))  # the voice, log and saved replies
SOCKET = DATA / "voice_server.sock"
LOCK = DATA / "voice_server.lock"   # also holds the engine's process number, for `voice status`
IDLE_MINUTES = 45


def log(msg: str) -> None:
    # "===" not "---": `voice status` reads the last "---" line as the last reply's decision.
    print(f"\n=== {time.ctime()} [engine] {msg}", flush=True)


def serve(conn: socket.socket, kokoro: Kokoro) -> None:
    conn.settimeout(10)
    line = conn.makefile().readline()
    if not line:
        return  # speak.py checking whether the engine is up
    request = json.loads(line)
    samples, rate = kokoro.create(request["text"], voice=request["voice"],
                                  speed=request["speed"], lang="en-us")
    wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
    sf.write(wav, samples, rate)
    try:
        conn.sendall(json.dumps({"wav": wav}).encode() + b"\n")
    except OSError:
        Path(wav).unlink()  # speak.py was stopped while we worked; nobody will play it
        raise


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    lock = open(LOCK, "a")   # "a", not "w": opening must not erase a running engine's number
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return  # another engine is already running
    lock.truncate(0)
    lock.write(str(os.getpid()))
    lock.flush()

    kokoro = Kokoro(str(DATA / "models/kokoro-v1.0.onnx"), str(DATA / "models/voices-v1.0.bin"))

    SOCKET.unlink(missing_ok=True)
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(SOCKET))
    server.listen()
    server.settimeout(60)  # wake once a minute to check how long it's been unused
    log(f"voice engine ready (quits after {IDLE_MINUTES} minutes unused)")

    last_used = time.time()
    try:
        while time.time() - last_used < IDLE_MINUTES * 60:
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            with conn:
                try:
                    serve(conn, kokoro)
                except Exception as e:
                    log(f"request failed: {e!r}")
            last_used = time.time()
        log(f"voice engine quit after {IDLE_MINUTES} minutes unused")
    finally:
        SOCKET.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
