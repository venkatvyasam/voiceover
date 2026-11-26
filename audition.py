"""Hear every voice say the same text. Usage: audition.py [prefix ...]  e.g. audition.py af_ bm_"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import soundfile as sf
from kokoro_onnx import Kokoro

DATA = Path(os.environ.get("VOICEOVER_DATA", Path.home() / ".claude" / "voiceover"))
TEXT = "The agent reads the reply, runs the tool, and sends back an observation. Does this voice sound natural to you?"
ENGLISH = ("af_", "am_", "bf_", "bm_")

kokoro = Kokoro(str(DATA / "models/kokoro-v1.0.onnx"), str(DATA / "models/voices-v1.0.bin"))
prefixes = tuple(sys.argv[1:]) or ENGLISH
voices = sorted(v for v in kokoro.get_voices() if v.startswith(prefixes))
lang = {"a": "en-us", "b": "en-gb"}

player = None
for n, voice in enumerate(voices, 1):
    name = voice.split("_", 1)[1]
    samples, rate = kokoro.create(f"{name}. {TEXT}", voice=voice, speed=1.1, lang=lang.get(voice[0], "en-us"))
    wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
    sf.write(wav, samples, rate)
    if player:
        player.wait()
    print(f"{n:2}/{len(voices)}  {voice}", flush=True)
    player = subprocess.Popen(["afplay", wav])
if player:
    player.wait()
