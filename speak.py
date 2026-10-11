"""Speak text with Kokoro (local, free). Usage: speak.py "text"  or  echo text | speak.py"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

HERE = Path(__file__).parent
VOICE = "af_heart"  # Venkat's picks, in order: af_heart, am_fenrir, bm_fable (hear them: audition.py af_heart am_fenrir bm_fable)
SPEED = 1.1
FIRST_CHUNK_CHARS = 80  # short first chunk = quick first sound
CHUNK_CHARS = 250  # largest chunk
GROWTH = 1.8       # each chunk is generated while the previous one plays, and generation runs
                   # ~2.2x faster than speech, so a chunk under ~2x the previous one is ready in time
MIN_CHUNK = 40     # don't end a chunk on a tiny sentence like "Done." (too short to cover the next)


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


def speak(text):
    # For `shush -a`: last.txt always; last.wav only once every chunk is generated,
    # so an interrupted reply never leaves a partial or mismatched recording.
    (HERE / "last.wav").unlink(missing_ok=True)
    (HERE / "last.txt").write_text(text)
    kokoro = Kokoro(str(HERE / "models/kokoro-v1.0.onnx"), str(HERE / "models/voices-v1.0.bin"))
    subprocess.run(["pkill", "-x", "afplay"])  # stop the previous reply if it's still talking
    subprocess.run(["pkill", "-CONT", "-x", "afplay"])  # ...even if it was paused (a stopped process can't die)
    player = None
    recording = []
    for chunk in chunks(text):
        samples, sample_rate = kokoro.create(chunk, voice=VOICE, speed=SPEED, lang="en-us")
        recording.append(samples)
        wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        sf.write(wav, samples, sample_rate)
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
