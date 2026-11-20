"""Speak text with Kokoro (local, free). Usage: speak.py "text"  or  echo text | speak.py

The voice model stays loaded in a background voice engine (voice_server.py), so speech
starts in about 2 seconds instead of 5. This starts the engine when it isn't running.
If the engine can't be reached, this loads the model itself, the slower way.
"""
import json
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import soundfile as sf

HERE = Path(__file__).parent
VOICE = "af_heart"  # Venkat's picks, in order: af_heart, am_fenrir, bm_fable (hear them: audition.py af_heart am_fenrir bm_fable)
SPEED = 1.1
FIRST_CHUNK_CHARS = 80  # short first chunk = quick first sound
CHUNK_CHARS = 250  # largest chunk
GROWTH = 1.8       # each chunk is generated while the previous one plays, and generation runs
                   # ~2.2x faster than speech, so a chunk under ~2x the previous one is ready in time
MIN_CHUNK = 40     # don't end a chunk on a tiny sentence like "Done." (too short to cover the next)
SOCKET = HERE / "voice_server.sock"
local_kokoro = None  # set only when the engine can't be used


def chunks(text):
    out, cur, limit = [], "", FIRST_CHUNK_CHARS
    for sentence in re.split(r"(?<=[.!?:])\s+", text.strip()):
        # A sentence longer than the current limit is split at commas/semicolons instead.
        pieces = [sentence] if len(sentence) <= limit else re.split(r"(?<=[,;])\s+", sentence)
        for piece in pieces:
            if len(cur) >= MIN_CHUNK and len(cur) + len(piece) > limit:
                out.append(cur)
                limit = min(CHUNK_CHARS, max(FIRST_CHUNK_CHARS, int(len(cur) * GROWTH)))
                cur = ""
            cur = f"{cur} {piece}".strip()
    return out + [cur] if cur else out


def engine_ready():
    try:
        with socket.socket(socket.AF_UNIX) as s:
            s.connect(str(SOCKET))
        return True
    except OSError:
        return False


def start_engine():
    with open(HERE / "speak.log", "ab") as log:
        subprocess.Popen([sys.executable, str(HERE / "voice_server.py")], stdout=log, stderr=log,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    for _ in range(300):  # wait up to 30 seconds; loading usually takes about 5
        time.sleep(0.1)
        if engine_ready():
            return True
    return False


def make_wav(chunk):
    """Turn one chunk of text into a WAV file, through the engine when possible."""
    global local_kokoro
    if local_kokoro is None:
        try:
            with socket.socket(socket.AF_UNIX) as s:
                s.settimeout(60)
                s.connect(str(SOCKET))
                s.sendall(json.dumps({"text": chunk, "voice": VOICE, "speed": SPEED}).encode() + b"\n")
                return json.loads(s.makefile().readline())["wav"]
        except (OSError, ValueError, KeyError):
            local_kokoro = load_kokoro()  # the engine went away: finish this reply the old way
    samples, sample_rate = local_kokoro.create(chunk, voice=VOICE, speed=SPEED, lang="en-us")
    wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
    sf.write(wav, samples, sample_rate)
    return wav


def load_kokoro():
    from kokoro_onnx import Kokoro  # imported only here: it takes a second, and the engine usually makes it unneeded
    return Kokoro(str(HERE / "models/kokoro-v1.0.onnx"), str(HERE / "models/voices-v1.0.bin"))


def speak(text):
    global local_kokoro
    # For `voice again`: last.txt always; last.wav only once every chunk is generated,
    # so an interrupted reply never leaves a partial or mismatched recording.
    (HERE / "last.wav").unlink(missing_ok=True)
    (HERE / "last.txt").write_text(text)
    if not (engine_ready() or start_engine()):
        local_kokoro = load_kokoro()
    subprocess.run(["pkill", "-x", "afplay"])  # stop the previous reply if it's still talking
    subprocess.run(["pkill", "-CONT", "-x", "afplay"])  # ...even if it was paused (a stopped process can't die)
    player = None
    recording = []
    for chunk in chunks(text):
        wav = make_wav(chunk)
        samples, sample_rate = sf.read(wav, dtype="float32")
        recording.append(samples)
        if player:
            player.wait()
            Path(player.args[1]).unlink()
        player = subprocess.Popen(["afplay", wav])
    if recording:
        sf.write(HERE / "last.tmp.wav", np.concatenate(recording), sample_rate)
        (HERE / "last.tmp.wav").rename(HERE / "last.wav")  # atomic: never play a half-written file
    if player:
        player.wait()
        Path(player.args[1]).unlink()


if __name__ == "__main__":
    text = " ".join(sys.argv[1:]) or sys.stdin.read()
    if text.strip():
        speak(text)
