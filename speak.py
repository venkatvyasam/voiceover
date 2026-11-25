"""Speak text with Kokoro (local, free). Usage: speak.py "text"  or  echo text | speak.py
                                                speak.py --play FILE.wav   (used by `voice again`)

The voice model stays loaded in a background voice engine (voice_server.py), so speech
starts in about 3 seconds instead of 6. This starts the engine when it isn't running.
If the engine can't be reached, this loads the model itself, the slower way.

The sound is played here, through `sounddevice`, one chunk straight after another with no
gap. `voice pause` sends this process SIGUSR1 and `voice resume` SIGUSR2; playback holds
its exact place in between. STATE tells `voice status` what's happening.
"""
import signal
from pathlib import Path

HERE = Path(__file__).parent
STATE = HERE / "speak.state"   # "preparing", "speaking" or "paused"; removed when done
paused = False
started = False                # has any sound been queued yet?


def set_state():
    STATE.write_text("paused" if paused else "speaking" if started else "preparing")


def on_pause(*_):
    global paused
    paused = True
    set_state()


def on_resume(*_):
    global paused
    paused = False
    set_state()


# Before the slow imports below: a SIGUSR1 that arrives with no handler kills the process,
# and `voice pause` can be sent while this is still starting up.
signal.signal(signal.SIGUSR1, on_pause)
signal.signal(signal.SIGUSR2, on_resume)
if __name__ == "__main__":
    set_state()   # so `voice pause` sees us from the start

import collections
import json
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time

import numpy as np
import sounddevice as sd
import soundfile as sf

VOICE = "af_heart"  # Venkat's picks, in order: af_heart, am_fenrir, bm_fable (hear them: audition.py af_heart am_fenrir bm_fable)
SPEED = 1.1        # the default; `vo 1.3`, `vo +.2` or `vo -.1` saves a different one in SPEED_FILE
SPEED_FILE = Path.home() / ".claude" / "speak-speed"
FIRST_CHUNK_CHARS = 80  # short first chunk = quick first sound
CHUNK_CHARS = 250  # largest chunk
GROWTH = 1.8       # each chunk is generated while the previous one plays, and generation runs
                   # ~2.2x faster than speech, so a chunk under ~2x the previous one is ready in time
MIN_CHUNK = 40     # don't end a chunk on a tiny sentence like "Done." (too short to cover the next)
LEAD = 0.3         # hand the next chunk to the player when this many seconds of sound are left
SOCKET = HERE / "voice_server.sock"
local_kokoro = None  # set only when the engine can't be used


class Player:
    """Plays chunks of audio one after another, with no gap between them.

    The sound card asks for audio in small blocks; `fill` copies them from the queue.
    While paused it sends silence and keeps its place, so resume carries on exactly there.
    """

    def __init__(self, sample_rate):
        self.rate = sample_rate
        self.queue = collections.deque()   # arrays of samples; the first one is playing
        self.pos = 0                       # how far into queue[0] we are
        self.lock = threading.Lock()
        self.stream = sd.OutputStream(samplerate=sample_rate, channels=1, dtype="float32", callback=self.fill)
        self.stream.start()

    def fill(self, out, frames, _time, _status):
        out.fill(0)
        if paused:
            return
        with self.lock:
            done = 0
            while done < frames and self.queue:
                cur = self.queue[0]
                n = min(frames - done, len(cur) - self.pos)
                out[done:done + n, 0] = cur[self.pos:self.pos + n]
                done += n
                self.pos += n
                if self.pos == len(cur):
                    self.queue.popleft()
                    self.pos = 0

    def add(self, samples):
        with self.lock:
            self.queue.append(samples)

    def seconds_left(self):
        with self.lock:
            return (sum(len(c) for c in self.queue) - self.pos) / self.rate

    def wait(self, until=0.0):
        """Wait until at most `until` seconds of sound are left (paused time doesn't count)."""
        while self.seconds_left() > until:
            time.sleep(0.05)

    def finish(self):
        self.wait()
        self.stream.stop()   # returns once the sound card has played the last block
        self.stream.close()


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


def speed():
    """The speed set with `vo`, else SPEED. Read for every chunk, so a change is heard once the current chunk ends."""
    try:
        return min(2.0, max(0.5, float(SPEED_FILE.read_text())))
    except (OSError, ValueError):
        return SPEED


def make_wav(chunk, rate):
    """Turn one chunk of text into a WAV file at speed `rate`, through the engine when possible."""
    global local_kokoro
    if local_kokoro is None:
        try:
            with socket.socket(socket.AF_UNIX) as s:
                s.settimeout(60)
                s.connect(str(SOCKET))
                s.sendall(json.dumps({"text": chunk, "voice": VOICE, "speed": rate}).encode() + b"\n")
                return json.loads(s.makefile().readline())["wav"]
        except (OSError, ValueError, KeyError):
            local_kokoro = load_kokoro()  # the engine went away: finish this reply the old way
    samples, sample_rate = local_kokoro.create(chunk, voice=VOICE, speed=rate, lang="en-us")
    wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
    sf.write(wav, samples, sample_rate)
    return wav


def make_audio(chunk, rate):
    wav = make_wav(chunk, rate)
    samples, sample_rate = sf.read(wav, dtype="float32")
    Path(wav).unlink()
    return samples, sample_rate


def load_kokoro():
    from kokoro_onnx import Kokoro  # imported only here: it takes a second, and the engine usually makes it unneeded
    return Kokoro(str(HERE / "models/kokoro-v1.0.onnx"), str(HERE / "models/voices-v1.0.bin"))


def speak(text):
    global local_kokoro, started
    # For `voice again`: last.txt always; last.wav only once every chunk is generated,
    # so an interrupted reply never leaves a partial or mismatched recording.
    (HERE / "last.wav").unlink(missing_ok=True)
    (HERE / "last.txt").write_text(text)
    if not (engine_ready() or start_engine()):
        local_kokoro = load_kokoro()
    player = None
    recording = []
    for chunk in chunks(text):
        rate = speed()
        samples, sample_rate = make_audio(chunk, rate)   # made while the previous chunk plays
        if player:
            player.wait(LEAD)
        if speed() != rate:  # `vo +.2` while the last chunk played: remake this one so the change is heard now
            samples, sample_rate = make_audio(chunk, speed())
        player = player or Player(sample_rate)
        player.add(samples)
        recording.append(samples)
        if not started:
            started = True
            set_state()
    if recording:
        sf.write(HERE / "last.tmp.wav", np.concatenate(recording), sample_rate)
        (HERE / "last.tmp.wav").rename(HERE / "last.wav")  # atomic: never play a half-written file
    if player:
        player.finish()


def play(wav):
    """Play a saved recording (`voice again`), with the same pause and resume."""
    global started
    samples, sample_rate = sf.read(wav, dtype="float32")
    player = Player(sample_rate)
    player.add(samples)
    started = True
    set_state()
    player.finish()


if __name__ == "__main__":
    try:
        if sys.argv[1:2] == ["--play"]:
            play(sys.argv[2])
        else:
            text = " ".join(sys.argv[1:]) or sys.stdin.read()
            if text.strip():
                speak(text)
    finally:
        STATE.unlink(missing_ok=True)
