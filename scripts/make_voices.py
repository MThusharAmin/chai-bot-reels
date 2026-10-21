#!/usr/bin/env python3
"""Turn each line of an episode into speech.

Chai Bot gets a Hindi neural voice plus a light robot effect; the customer gets a
plain Hindi voice. Uses Microsoft Edge's free text-to-speech (edge-tts package).

Writes episodes/<NNN>/line_<i>.wav (48 kHz mono) for every line.

Usage: python scripts/make_voices.py episodes/001 [--fake]
  --fake  make placeholder "voices" without the internet (for testing the renderer)
"""
import asyncio
import json
import pathlib
import subprocess
import sys

import numpy as np

SAMPLE_RATE = 48000

VOICES = {
    # Chai Bot: male voice, a bit faster and higher, then robot effect.
    "bot": {"voice": "hi-IN-MadhurNeural", "rate": "+6%", "pitch": "+6Hz"},
    "customer_female": {"voice": "hi-IN-SwaraNeural", "rate": "+4%", "pitch": "+0Hz"},
    "customer_male": {"voice": "hi-IN-MadhurNeural", "rate": "+2%", "pitch": "-8Hz"},
}

# Gentle robot sound: slight pitch lift, metallic shimmer, a touch of bit-crush, small echo.
ROBOT_FX = (
    "asetrate=48000*1.05,aresample=48000,atempo=0.952,"
    "flanger=delay=1.5:depth=1.2:regen=10:width=60:speed=0.35,"
    "acrusher=bits=12:mix=0.25:mode=log:aa=1,"
    "aecho=0.85:0.5:18:0.18,"
    "highpass=f=110,lowpass=f=9500"
)


def fail(message):
    print(f"::error::{message}")
    sys.exit(1)


def to_wav(source, target, effects=None):
    chain = ["-af", effects] if effects else []
    result = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(source), *chain,
         "-ac", "1", "-ar", str(SAMPLE_RATE), str(target)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        fail(f"ffmpeg couldn't process {source.name}: {result.stderr.strip()}")


async def speak(text, settings, mp3_path):
    import edge_tts  # installed in the workflow

    for attempt in range(1, 4):
        try:
            communicate = edge_tts.Communicate(text, settings["voice"], rate=settings["rate"],
                                               pitch=settings["pitch"])
            await communicate.save(str(mp3_path))
            if mp3_path.exists() and mp3_path.stat().st_size > 1000:
                return
        except Exception as error:  # network hiccups happen; retry
            print(f"  voice attempt {attempt} failed: {error}")
        await asyncio.sleep(3 * attempt)
    fail(f"Text-to-speech failed for: {text}")


def fake_voice(text, path, seed):
    """Babble-like placeholder with speech-like loudness changes, ~13 chars per second."""
    rng = np.random.default_rng(seed)
    seconds = max(1.2, len(text) / 13)
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    syllables = np.clip(np.sin(2 * np.pi * 4.2 * t + rng.uniform(0, 6)) * 0.8
                        + rng.normal(0, 0.25, t.size).cumsum() / 400, 0, 1)
    pauses = (np.sin(2 * np.pi * 0.6 * t) > -0.85).astype(float)
    tone = sum(np.sin(2 * np.pi * f * t) / (i + 1) for i, f in enumerate([140, 280, 420, 700]))
    audio = (tone * syllables * pauses * 0.25).astype(np.float32)
    raw = path.with_suffix(".raw")
    raw.write_bytes(audio.tobytes())
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "f32le", "-ar", str(SAMPLE_RATE),
                    "-ac", "1", "-i", str(raw), str(path)], check=True)
    raw.unlink()


def make_voices(folder, fake=False):
    folder = pathlib.Path(folder)
    episode = json.loads((folder / "episode.json").read_text(encoding="utf-8"))
    customer = "customer_" + episode.get("customer_voice", "female")

    for i, line in enumerate(episode["lines"]):
        wav = folder / f"line_{i}.wav"
        if line["who"] == "bot":
            settings, effects = VOICES["bot"], ROBOT_FX
        else:
            settings, effects = VOICES[customer], "highpass=f=90"
        print(f"  voice {i}: {line['who']}")
        if fake:
            fake_voice(line["text"], wav, seed=i)
            continue
        mp3 = folder / f"line_{i}.mp3"
        asyncio.run(speak(line["text"], settings, mp3))
        to_wav(mp3, wav, effects)
        mp3.unlink()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        fail("Usage: make_voices.py episodes/NNN [--fake]")
    make_voices(sys.argv[1], fake="--fake" in sys.argv)
