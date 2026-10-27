#!/usr/bin/env python3
"""Render a Chai Bot 3000 episode into a 1080x1920 Reel (MP4).

Needs: episodes/<NNN>/episode.json and line_<i>.wav (from make_voices.py),
       assets/stage.png + assets/stage.json (from prepare_assets.py).

Usage: python scripts/render_reel.py episodes/001 out.mp4
"""
import glob
import json
import math
import pathlib
import subprocess
import sys
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

W, H, FPS, SR = 1080, 1920, 30, 48000

AMBER = np.array([255, 168, 40], np.float32)
AMBER_CORE = np.array([255, 222, 140], np.float32)
COLORS = {
    "amber": (AMBER, AMBER_CORE),
    "red": (np.array([255, 60, 50], np.float32), np.array([255, 170, 160], np.float32)),
    "blue": (np.array([80, 170, 255], np.float32), np.array([190, 230, 255], np.float32)),
    "pink": (np.array([255, 80, 130], np.float32), np.array([255, 190, 210], np.float32)),
}

# Camera shots on the original picture: centre x, centre y, zoom.
WIDE = (563.0, 698.0, 1.0)
MEDIUM = (560.0, 610.0, 1.28)
CLOSE = (555.0, 487.0, 1.72)

LOADING_TEXT = "Processing… chai first, solution later"
END_TEXT_1 = "Come back tomorrow!"
END_TEXT_2 = "Chai will be ready"
END_TEXT_3 = "Follow · CHAI BOT 3000"
CUSTOMER_TAG = "CUSTOMER"
BOT_TAG = "CHAI BOT"
CUSTOMER_NUMBER = "Customer #{number}"
GAP_BETWEEN_LINES = 0.45  # seconds of silence between lines
GAP_BEFORE_PUNCHLINE = 0.8  # a beat of silence before Chai Bot's last line
SOUND_EFFECTS = False     # True = whoosh + background hum (off: cleaner, more natural)
SHOW_SUBTITLES = False    # True = show each spoken line as a subtitle box
SHOW_TITLE = False        # True = show "Customer #N" + the problem at the top (comedy episodes)
SHOW_NEWS_BANNER = True   # news bulletins: show "चाय बॉट समाचार" + the category at the top
NEWS_TAG = "चाय बॉट समाचार"
NEWS_END = ("कल फिर मिलेंगे!", "ताज़ा ख़बरों के लिए फ़ॉलो करें", "स्रोत: द हिंदू")
GAP_BETWEEN_NEWS = 0.4    # seconds between news stories


# ---------------------------------------------------------------- fonts

def find_font(patterns, what):
    for pattern in patterns:
        found = sorted(glob.glob(pattern, recursive=True))
        if found:
            return found[0]
    sys.exit(f"::error::No {what} font found. Install fonts-noto-core and fonts-dejavu-core.")


from PIL import features as _features  # noqa: E402

if not _features.check("raqm"):
    sys.exit("::error::Pillow can't shape Hindi text (libraqm missing). Install libraqm0 and libfribidi0.")

# Newer Noto Devanagari fonts have no English letters, so English text uses its own font.
HINDI_FONT = find_font([
    "/usr/share/fonts/**/NotoSansDevanagari-Bold.ttf",
    "/usr/share/fonts/**/NotoSansDevanagari-ExtraBold.ttf",
    "/usr/share/fonts/**/NotoSansDevanagari*Bold*.[ot]tf",
    "/usr/share/fonts/**/Lohit-Devanagari.ttf",
    "/usr/share/fonts/**/FreeSansBold.ttf",
], "Hindi (Devanagari)")
ENGLISH_FONT = find_font([
    "/usr/share/fonts/**/NotoSans-Bold.ttf",
    "/usr/share/fonts/**/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/**/FreeSansBold.ttf",
    "/usr/share/fonts/**/LiberationSans-Bold.ttf",
], "English")
_font_cache = {}


def is_hindi(text):
    return any("\u0900" <= ch <= "\u097f" for ch in (text or ""))


def font(size, text=""):
    """Bold font at this size; picks the Hindi font only when the text contains Hindi."""
    path = HINDI_FONT if is_hindi(text) else ENGLISH_FONT
    key = (path, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.RAQM)
    return _font_cache[key]


def fitted_font(text, size, max_width):
    """Largest font up to `size` at which `text` fits in `max_width` pixels."""
    while size > 20 and font(size, text).getlength(text) > max_width:
        size -= 2
    return font(size, text)


def wrap(text, fnt, max_width):
    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if current and fnt.getlength(trial) > max_width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


# ---------------------------------------------------------------- audio

def read_wav(path):
    with wave.open(str(path)) as wav:
        frames = wav.readframes(wav.getnframes())
        width = wav.getsampwidth()
        rate = wav.getframerate()
    if width == 2:
        audio = np.frombuffer(frames, np.int16).astype(np.float32) / 32768
    elif width == 4:
        audio = np.frombuffer(frames, np.int32).astype(np.float32) / 2**31
    else:
        sys.exit(f"::error::Unsupported wav sample width in {path}")
    if rate != SR:
        sys.exit(f"::error::{path} is {rate} Hz, expected {SR}")
    # Trim leading/trailing silence so lines follow each other snappily.
    loud = np.where(np.abs(audio) > 0.01)[0]
    if loud.size:
        audio = audio[max(0, loud[0] - 1200): loud[-1] + 2400]
    return audio


def envelope(audio):
    """Loudness per video frame, scaled 0..1 — drives the lip-sync."""
    hop = SR // FPS
    frames = max(1, math.ceil(audio.size / hop))
    padded = np.pad(audio, (0, frames * hop - audio.size))
    rms = np.sqrt((padded.reshape(frames, hop) ** 2).mean(axis=1))
    top = np.percentile(rms[rms > 0.005], 90) if (rms > 0.005).any() else 1.0
    level = np.clip(rms / max(top, 1e-4), 0, 1)
    return np.maximum(level, np.roll(level, 1) * 0.6)  # soften flicker


def tone(freq, seconds, volume, decay=8.0):
    t = np.arange(int(seconds * SR)) / SR
    env = np.exp(-decay * t) * np.clip(t / 0.005, 0, 1)
    return (np.sin(2 * np.pi * freq * t) * env * volume).astype(np.float32)


def whoosh(seconds=0.38, volume=0.22):
    rng = np.random.default_rng(7)
    n = int(seconds * SR)
    noise = rng.normal(0, 1, n).astype(np.float32)
    smooth = np.convolve(noise, np.ones(6) / 6, mode="same")
    noise = noise - smooth  # crude high-pass
    t = np.linspace(0, 1, n)
    env = np.sin(np.pi * t) ** 2
    return noise * env * volume


def ding(volume=0.32):
    return tone(1568, 1.4, volume, 3.5) + tone(2093, 1.4, volume * 0.6, 4.5) + tone(3136, 1.4, volume * 0.2, 7)


def ambience(seconds, volume=0.012):
    rng = np.random.default_rng(11)
    n = int(seconds * SR)
    brown = np.cumsum(rng.normal(0, 1, n)).astype(np.float32)
    brown -= np.convolve(brown, np.ones(4800) / 4800, mode="same")
    brown /= np.abs(brown).max() + 1e-6
    return brown * volume


def load_music(seconds):
    for name in ("music.mp3", "music.wav", "music.m4a"):
        path = ASSETS / name
        if path.exists():
            raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-f", "f32le",
                                  "-ac", "1", "-ar", str(SR), "-"], capture_output=True, check=True).stdout
            music = np.frombuffer(raw, np.float32)
            reps = math.ceil(seconds * SR / max(music.size, 1))
            return np.tile(music, reps)[: int(seconds * SR)]
    return None


# ---------------------------------------------------------------- face drawing

def bez(p0, p1, p2, n=28):
    t = np.linspace(0, 1, n)[:, None]
    a, b, c = np.array(p0), np.array(p1), np.array(p2)
    return [tuple(p) for p in ((1 - t) ** 2 * a + 2 * (1 - t) * t * b + t ** 2 * c)]


def heart(cx, cy, s):
    pts = []
    for a in np.linspace(0, 2 * np.pi, 60):
        x = 16 * math.sin(a) ** 3
        y = -(13 * math.cos(a) - 5 * math.cos(2 * a) - 2 * math.cos(3 * a) - math.cos(4 * a))
        pts.append((cx + x * s / 16, cy + y * s / 16))
    return pts


EYES = {
    "happy": [("stroke", "amber", bez((-47, -4), (-33, -34), (-19, -4)), 11),
              ("stroke", "amber", bez((19, -4), (33, -34), (47, -4)), 11)],
    "neutral": [("ellipse", "amber", (-32, -12, 7, 10)), ("ellipse", "amber", (32, -12, 7, 10))],
    "confused": [("ring", "amber", (-31, -12, 11, 11), 8), ("stroke", "amber", [(20, -8), (44, -17)], 9),
                 ("text", "amber", (50, -44, "?", 34))],
    "smug": [("stroke", "amber", [(-48, -12), (-18, -12)], 8), ("stroke", "amber", bez((-46, -12), (-33, 3), (-20, -12)), 8),
             ("stroke", "amber", [(18, -12), (48, -12)], 8), ("stroke", "amber", bez((20, -12), (33, 3), (46, -12)), 8)],
    "shocked": [("ring", "amber", (-32, -14, 16, 16), 8), ("ring", "amber", (32, -14, 16, 16), 8),
                ("ellipse", "amber", (-32, -14, 5, 5)), ("ellipse", "amber", (32, -14, 5, 5))],
    "sad": [("stroke", "amber", [(-48, -20), (-20, -31)], 8), ("stroke", "amber", [(48, -20), (20, -31)], 8),
            ("ellipse", "amber", (-33, -6, 6, 8)), ("ellipse", "amber", (33, -6, 6, 8))],
    "angry": [("stroke", "red", [(-48, -31), (-18, -20)], 9), ("stroke", "red", [(48, -31), (18, -20)], 9),
              ("ellipse", "amber", (-32, -6, 7, 7)), ("ellipse", "amber", (32, -6, 7, 7))],
    "love": [("poly", "pink", heart(-33, -12, 17)), ("poly", "pink", heart(33, -12, 17))],
    "blink": [("stroke", "amber", [(-44, -10), (-21, -10)], 9), ("stroke", "amber", [(21, -10), (44, -10)], 9)],
}

MOUTHS = {
    "smile": [("stroke", "amber", bez((-36, 16), (0, 50), (36, 16)), 11)],
    "closed": [("stroke", "amber", [(-22, 25), (22, 25)], 9)],
    "open": [("ring", "amber", (0, 27, 15, 11), 8)],
    "wide": [("poly", "amber", [(-30, 14), (30, 14)] + bez((30, 14), (0, 58), (-30, 14))[1:])],
    "wavy": [("stroke", "amber", [(x, 27 + 6 * math.sin(x / 7)) for x in range(-28, 29, 2)], 8)],
    "smirk": [("stroke", "amber", bez((-22, 27), (8, 37), (34, 14)), 9)],
    "o": [("ring", "amber", (0, 31, 12, 15), 8)],
    "frown": [("stroke", "amber", bez((-26, 40), (0, 16), (26, 40)), 9)],
    "flat": [("stroke", "amber", [(-24, 31), (24, 31)], 9)],
}

DEFAULT_MOUTH = {"happy": "smile", "love": "smile", "neutral": "closed", "confused": "wavy",
                 "smug": "smirk", "shocked": "o", "sad": "frown", "angry": "flat"}

_dot_cache = {}


def led_dots(w, h):
    """Dot-matrix texture like an old LED screen."""
    key = (w, h)
    if key not in _dot_cache:
        pitch = max(3.0, w / 58)
        ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
        d = (np.cos(2 * np.pi * xs / pitch) + 1) * (np.cos(2 * np.pi * ys / pitch) + 1) / 4
        _dot_cache[key] = 0.45 + 0.55 * d
    return _dot_cache[key]


def face_ops(state, t):
    kind = state["kind"]
    if kind == "loading":
        ops = []
        spin = t * 2.2
        for i in range(8):
            a = 2 * np.pi * (i / 8) + spin * 2 * np.pi
            size = 3.0 + 4.0 * (i / 7)
            ops.append(("ellipse", "amber", (28 * math.cos(a), -8 + 28 * math.sin(a), size, size)))
        ops.append(("text", "amber", (0, 34, "LOADING…", 12)))
        return ops
    expression = state["face"]
    eyes = EYES["blink"] if state.get("blink") else EYES.get(expression, EYES["neutral"])
    mouth = state.get("mouth") or DEFAULT_MOUTH.get(expression, "closed")
    ops = list(eyes) + list(MOUTHS[mouth])
    if expression == "sad":  # falling pixel tear
        drop = (t * 22) % 34
        ops.append(("rect", "blue", (-37, 6 + drop, 7, 7)))
    return ops


def render_face(ops, w, h):
    """Return (rgb light layer, alpha) for a screen area of w x h pixels."""
    ss = 2
    cw, ch = w * ss, h * ss
    sx, sy = cw / 160, ch / 118
    masks = {}

    def canvas(color):
        if color not in masks:
            masks[color] = Image.new("L", (cw, ch), 0)
        return ImageDraw.Draw(masks[color])

    def P(x, y):
        return ((x + 80) * sx, (y + 59) * sy)

    for op in ops:
        kind, color = op[0], op[1]
        draw = canvas(color)
        if kind == "stroke":
            pts = [P(*p) for p in op[2]]
            width = max(2, int(op[3] * sx))
            draw.line(pts, fill=255, width=width, joint="curve")
            r = width / 2
            for x, y in (pts[0], pts[-1]):
                draw.ellipse((x - r, y - r, x + r, y + r), fill=255)
        elif kind == "ellipse":
            x, y, rx, ry = op[2]
            cx, cy = P(x, y)
            draw.ellipse((cx - rx * sx, cy - ry * sy, cx + rx * sx, cy + ry * sy), fill=255)
        elif kind == "ring":
            x, y, rx, ry = op[2]
            cx, cy = P(x, y)
            draw.ellipse((cx - rx * sx, cy - ry * sy, cx + rx * sx, cy + ry * sy), outline=255,
                         width=max(2, int(op[3] * sx)))
        elif kind == "poly":
            draw.polygon([P(*p) for p in op[2]], fill=255)
        elif kind == "rect":
            x, y, rw, rh = op[2]
            x0, y0 = P(x, y)
            draw.rectangle((x0, y0, x0 + rw * sx, y0 + rh * sy), fill=255)
        elif kind == "text":
            x, y, text, size = op[2]
            fnt = font(max(8, int(size * sy)), text)
            draw.text(P(x, y), text, font=fnt, fill=255, anchor="mt")

    light = np.zeros((h, w, 3), np.float32)
    alpha = np.zeros((h, w), np.float32)
    dots = led_dots(w, h)
    for color, mask in masks.items():
        mask = mask.resize((w, h), Image.LANCZOS)
        glow1 = np.asarray(mask.filter(ImageFilter.GaussianBlur(w * 0.018)), np.float32) / 255
        glow2 = np.asarray(mask.filter(ImageFilter.GaussianBlur(w * 0.06)), np.float32) / 255
        core = np.asarray(mask, np.float32) / 255
        glow_color, core_color = COLORS[color]
        light += (core * dots)[..., None] * core_color
        light += (glow1 * 0.75 + glow2 * 0.55)[..., None] * glow_color
        alpha = np.maximum(alpha, core)
    return light, alpha


# ---------------------------------------------------------------- overlays

def balanced_wrap(text, fnt, max_width):
    """Wrap into as few lines as possible, with lines of similar length (no lonely last word)."""
    words = text.split()
    count = len(wrap(text, fnt, max_width))
    if count < 2 or len(words) < 2:
        return wrap(text, fnt, max_width)
    best, best_width = None, None
    if count == 2:
        for i in range(1, len(words)):
            lines = [" ".join(words[:i]), " ".join(words[i:])]
            widest = max(fnt.getlength(l) for l in lines)
            if widest <= max_width and (best_width is None or widest < best_width):
                best, best_width = lines, widest
    return best or wrap(text, fnt, max_width)


def rounded_panel(size, radius, fill):
    panel = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(panel).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius, fill=fill)
    return panel


def caption_card(text_lines, who):
    """Subtitle box with a speaker tag, as an RGBA image."""
    body = font(60, " ".join(text_lines))
    line_h = 84
    widths = [body.getlength(line) for line in text_lines]
    box_w = int(min(960, max(widths + [300]) + 80))
    box_h = int(line_h * len(text_lines) + 56)
    card = Image.new("RGBA", (box_w, box_h + 34), (0, 0, 0, 0))
    card.alpha_composite(rounded_panel((box_w, box_h), 30, (18, 12, 8, 205)), (0, 34))
    draw = ImageDraw.Draw(card)
    if who == "bot":
        tag_text, tag_fill, tag_ink, text_ink = BOT_TAG, (255, 176, 50, 255), (35, 22, 10, 255), (255, 226, 160, 255)
    else:
        tag_text, tag_fill, tag_ink, text_ink = CUSTOMER_TAG, (245, 240, 232, 255), (35, 30, 25, 255), (255, 255, 255, 255)
    tag_font = font(34, tag_text)
    tag_w = int(tag_font.getlength(tag_text) + 44)
    draw.rounded_rectangle((28, 0, 28 + tag_w, 62), 31, fill=tag_fill)
    draw.text((28 + tag_w / 2, 31), tag_text, font=tag_font, fill=tag_ink, anchor="mm")
    for i, line in enumerate(text_lines):
        draw.text((box_w / 2, 34 + 34 + line_h * i + line_h / 2), line, font=body, fill=text_ink,
                  anchor="mm", stroke_width=2, stroke_fill=(0, 0, 0, 255))
    return card


def hook_overlay(number, title, tag=None):
    """Episode number + problem, on a dark banner at the top (clear of Instagram's top bar)."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    title_font = font(66, title)
    lines = balanced_wrap(title, title_font, 860)[:2]
    box_w = int(min(980, max(title_font.getlength(l) for l in lines) + 90))
    box_h = 40 + 86 * len(lines)
    top = 205
    layer.alpha_composite(rounded_panel((box_w, box_h), 34, (18, 12, 8, 215)), ((W - box_w) // 2, top))
    draw = ImageDraw.Draw(layer)
    for i, line in enumerate(lines):
        draw.text((W / 2, top + 22 + 86 * i + 43), line, font=title_font, fill=(255, 255, 255, 255), anchor="mm")
    tag = tag or CUSTOMER_NUMBER.format(number=number)
    tag_font = font(38, tag)
    tag_w = int(tag_font.getlength(tag) + 50)
    draw.rounded_rectangle(((W - tag_w) / 2, top - 34, (W + tag_w) / 2, top + 30), 32, fill=(255, 176, 50, 255))
    draw.text((W / 2, top - 2), tag, font=tag_font, fill=(35, 22, 10, 255), anchor="mm")
    return layer


def end_overlay(texts=None):
    line1, line2, line3 = texts or (END_TEXT_1, END_TEXT_2, END_TEXT_3)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    panel = rounded_panel((820, 330), 44, (18, 12, 8, 215))
    draw = ImageDraw.Draw(panel)
    draw.text((410, 95), line1, font=fitted_font(line1, 84, 740), fill=(255, 190, 70, 255), anchor="mm")
    draw.text((410, 190), line2, font=fitted_font(line2, 60, 740), fill=(255, 255, 255, 255), anchor="mm")
    draw.text((410, 272), line3, font=fitted_font(line3, 38, 740), fill=(200, 230, 225, 255), anchor="mm")
    layer.alpha_composite(panel, ((W - 820) // 2, 1180))
    return layer


# ---------------------------------------------------------------- timeline

def build_news_timeline(episode, audios):
    """News bulletin: Chai Bot reads every line, the camera changes shot per story."""
    shots = [WIDE, MEDIUM, CLOSE, MEDIUM, CLOSE, MEDIUM]
    segs, t = [], 0.4
    for i, line in enumerate(episode["lines"]):
        dur = audios[i].size / SR
        segs.append({"kind": "line", "start": t, "dur": dur, "line": i, "who": "bot",
                     "face": line.get("face", "neutral"), "cam": shots[i % len(shots)]})
        t += dur + GAP_BETWEEN_NEWS
    segs.append({"kind": "end", "start": t, "dur": 2.6, "face": "love", "cam": WIDE})
    first = {"kind": "intro", "start": 0.0, "dur": 0.4, "face": "happy", "cam": WIDE}
    return [first] + segs, t + 2.6


def build_timeline(episode, audios):
    if episode.get("format") == "news":
        return build_news_timeline(episode, audios)
    segs = []
    t = 0.4
    bot_count = 0
    seen_bot = False
    lines = episode["lines"]
    for i, line in enumerate(lines):
        if line["who"] == "bot" and not seen_bot:
            segs.append({"kind": "react", "start": t, "dur": 0.75, "face": episode["reaction"], "cam": CLOSE})
            t += 0.75
            segs.append({"kind": "loading", "start": t, "dur": 1.3, "cam": CLOSE})
            t += 1.3
            seen_bot = True
        dur = audios[i].size / SR
        if line["who"] == "bot":
            cam = CLOSE if (i == len(lines) - 1 or bot_count % 2 == 1) else MEDIUM
            bot_count += 1
        else:
            cam = WIDE
        segs.append({"kind": "line", "start": t, "dur": dur, "line": i, "who": line["who"],
                     "face": line["face"], "cam": cam})
        next_is_punchline = i == len(lines) - 2 and lines[-1]["who"] == "bot"
        t += dur + (GAP_BEFORE_PUNCHLINE if next_is_punchline else GAP_BETWEEN_LINES)
    segs.append({"kind": "end", "start": t, "dur": 2.6, "face": "love", "cam": WIDE})
    total = t + 2.6
    first = {"kind": "intro", "start": 0.0, "dur": 0.4, "face": "happy", "cam": WIDE}
    return [first] + segs, total


def seg_at(segs, t):
    current = segs[0]
    for s in segs:
        if s["start"] <= t:
            current = s
    return current


def ease(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def camera_at(segs, t):
    idx = 0
    for i, s in enumerate(segs):
        if s["start"] <= t:
            idx = i
    s = segs[idx]
    prev = segs[idx - 1]["cam"] if idx > 0 else s["cam"]
    blend_time = 0.2 if s["kind"] == "react" else 0.45
    k = ease((t - s["start"]) / blend_time)
    cx = prev[0] + (s["cam"][0] - prev[0]) * k
    cy = prev[1] + (s["cam"][1] - prev[1]) * k
    zoom = math.exp(math.log(prev[2]) + (math.log(s["cam"][2]) - math.log(prev[2])) * k)
    progress = (t - s["start"]) / max(s["dur"], 0.1)
    zoom *= 1 + 0.035 * min(progress, 1.5)  # slow push-in
    if s["kind"] == "react" and s.get("face") in ("shocked", "angry"):
        fade = max(0.0, 1 - (t - s["start"]) / 0.45)
        cx += math.sin(t * 90) * 6 * fade
        cy += math.cos(t * 77) * 5 * fade
    return cx, cy, zoom


def crop_box(cam, img_w, img_h):
    cx, cy, zoom = cam
    ch = img_h / zoom
    cw = ch * W / H
    cx = min(max(cx, cw / 2), img_w - cw / 2)
    cy = min(max(cy, ch / 2), img_h - ch / 2)
    return (cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2)


def subtitle(line):
    """English subtitle if the script has one, otherwise the Hindi line."""
    return (line.get("en") or line["text"]).strip()


def caption_chunks(text, duration, start):
    lines = wrap(text, font(60, text), 860)
    if len(lines) == 2:
        lines = balanced_wrap(text, font(60, text), 860)
    chunks = [lines[i:i + 2] for i in range(0, len(lines), 2)]
    total_chars = sum(len(" ".join(c)) for c in chunks) or 1
    out, t = [], start
    for chunk in chunks:
        share = duration * len(" ".join(chunk)) / total_chars
        out.append((t, t + share, chunk))
        t += share
    return out


# ---------------------------------------------------------------- main render

def render(folder, out_path):
    folder = pathlib.Path(folder)
    episode = json.loads((folder / "episode.json").read_text(encoding="utf-8"))
    stage = Image.open(ASSETS / "stage.png").convert("RGB")
    info = json.loads((ASSETS / "stage.json").read_text())
    img_w, img_h = stage.size
    sx0, sy0, sx1, sy1 = info["screen_box"]
    bulb_x, bulb_y = info["bulb"]

    audios = [read_wav(folder / f"line_{i}.wav") for i in range(len(episode["lines"]))]
    envs = [envelope(a) for a in audios]
    segs, total = build_timeline(episode, audios)
    n_frames = int(math.ceil(total * FPS))

    # ---- audio mix
    mix = np.zeros(int(total * SR) + SR, np.float32)
    speech = np.zeros_like(mix)
    for s in segs:
        at = int(s["start"] * SR)
        if s["kind"] == "line":
            a = audios[s["line"]]
            mix[at:at + a.size] += a * 0.95
            speech[at:at + a.size] = 1.0
        elif s["kind"] == "react" and SOUND_EFFECTS:
            w = whoosh()
            mix[at:at + w.size] += w
        elif s["kind"] == "loading":
            for j, f in enumerate([1180, 1480, 1180, 1760]):
                b = tone(f, 0.09, 0.07, 25)
                p = at + int((0.12 + j * 0.24) * SR)
                mix[p:p + b.size] += b
        elif s["kind"] == "end":
            d = (ding() * 0.5)[: mix.size - at]
            mix[at:at + d.size] += d
    if SOUND_EFFECTS:
        mix += ambience(mix.size / SR)[: mix.size]
    music = load_music(mix.size / SR)
    if music is not None:
        duck = np.convolve(speech, np.ones(SR // 5) / (SR // 5), mode="same")
        mix += music * (0.13 - 0.08 * duck)
    peak = np.abs(mix).max()
    if peak > 0:
        mix *= 0.89 / peak
    audio_path = folder / "mix.f32"
    mix[: int(total * SR)].astype(np.float32).tofile(audio_path)

    # ---- captions & overlays
    cards = []
    for s in segs:
        if not SHOW_SUBTITLES:
            break
        if s["kind"] == "line":
            for start, end, chunk in caption_chunks(subtitle(episode["lines"][s["line"]]), s["dur"], s["start"]):
                cards.append((start, end + 0.12, caption_card(chunk, s["who"])))
        elif s["kind"] == "loading":
            cards.append((s["start"], s["start"] + s["dur"], caption_card(wrap(LOADING_TEXT, font(60, LOADING_TEXT), 860), "bot")))
    is_news = episode.get("format") == "news"
    if is_news:
        hook = hook_overlay(episode["number"], episode.get("category_hi") or episode["title"], tag=NEWS_TAG)
        ending = end_overlay(NEWS_END)
    else:
        hook = hook_overlay(episode["number"], episode.get("title_en") or episode["title"])
        ending = end_overlay()
    show_hook = SHOW_NEWS_BANNER if is_news else SHOW_TITLE
    end_start = segs[-1]["start"]

    # Blink times (not during loading).
    rng = np.random.default_rng(episode["number"])
    blinks, bt = [], 1.6
    while bt < total:
        blinks.append(bt)
        bt += rng.uniform(2.4, 4.6)

    # ---- video frames → ffmpeg
    out_path = pathlib.Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    encoder = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", str(audio_path),
         "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-profile:v", "high",
         "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-movflags", "+faststart", "-shortest", str(out_path)],
        stdin=subprocess.PIPE,
    )
    scan = None
    for f in range(n_frames):
        t = f / FPS
        s = seg_at(segs, t)
        box = crop_box(camera_at(segs, t), img_w, img_h)
        bw, bh = box[2] - box[0], box[3] - box[1]
        view = stage.resize((W, H), Image.BICUBIC, box=box).filter(ImageFilter.UnsharpMask(2, 60, 2))
        frame = np.asarray(view, np.float32).copy()

        # Face state for this frame.
        state = {"kind": "face", "face": s.get("face", "happy")}
        if s["kind"] == "loading":
            state = {"kind": "loading"}
        elif s["kind"] == "line" and s["who"] == "bot":
            k = int((t - s["start"]) * FPS)
            env = envs[s["line"]]
            level = env[k] if k < env.size else 0.0
            state["mouth"] = "closed" if level < 0.22 else ("open" if level < 0.6 else "wide")
        if state["kind"] == "face" and s["kind"] not in ("react",):
            state["blink"] = any(0 <= t - b < 0.13 for b in blinks)

        # Screen position in this frame.
        x0 = int(round((sx0 - box[0]) / bw * W))
        y0 = int(round((sy0 - box[1]) / bh * H))
        x1 = int(round((sx1 - box[0]) / bw * W))
        y1 = int(round((sy1 - box[1]) / bh * H))
        fx0, fy0, fx1, fy1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
        if fx1 - fx0 > 4 and fy1 - fy0 > 4:
            light, _ = render_face(face_ops(state, t), x1 - x0, y1 - y0)
            light = light[fy0 - y0: fy1 - y0, fx0 - x0: fx1 - x0]
            region = frame[fy0:fy1, fx0:fx1]
            rows = np.arange(fy1 - fy0)
            scan = 1 - 0.07 * ((rows // max(2, (y1 - y0) // 90)) % 2)
            flicker = 1 + 0.03 * math.sin(t * 47) + 0.02 * math.sin(t * 13)
            region *= scan[:, None, None]
            region += light * flicker * 0.9
            frame[fy0:fy1, fx0:fx1] = region

        # Antenna bulb glow.
        talking = state.get("mouth") in ("open", "wide")
        red = s["kind"] == "react" and s.get("face") in ("shocked", "angry")
        glow = 0.35 + 0.15 * math.sin(t * 5) + (0.45 if talking else 0) + (0.6 if red else 0)
        gx = (bulb_x - box[0]) / bw * W
        gy = (bulb_y - box[1]) / bh * H
        radius = 55 * W / bw
        if -radius < gx < W + radius and -radius < gy < H + radius:
            gx0, gx1 = int(max(0, gx - radius)), int(min(W, gx + radius))
            gy0, gy1 = int(max(0, gy - radius)), int(min(H, gy + radius))
            yy, xx = np.mgrid[gy0:gy1, gx0:gx1]
            fall = np.clip(1 - np.hypot(xx - gx, yy - gy) / radius, 0, 1) ** 2.2
            colour = COLORS["red" if red else "amber"][0]
            frame[gy0:gy1, gx0:gx1] += (fall * glow)[..., None] * colour

        img = Image.fromarray(np.clip(frame, 0, 255).astype(np.uint8), "RGB").convert("RGBA")

        # Overlays.
        if show_hook and t < end_start:
            img.alpha_composite(hook)
        for start, end, card in cards:
            if start <= t < end:
                fade = min(1.0, (t - start) / 0.08)
                if fade < 1:
                    card = card.copy()
                    card.putalpha(card.getchannel("A").point(lambda a: int(a * fade)))
                img.alpha_composite(card, ((W - card.width) // 2, 1560 - card.height))
        if t >= end_start:
            fade = min(1.0, (t - end_start) / 0.3)
            layer = ending if fade >= 1 else Image.blend(Image.new("RGBA", (W, H), (0, 0, 0, 0)), ending, fade)
            img.alpha_composite(layer)

        encoder.stdin.write(img.convert("RGB").tobytes())
        if f % (FPS * 5) == 0:
            print(f"  rendering… {t:4.1f}s / {total:.1f}s")

    encoder.stdin.close()
    if encoder.wait() != 0:
        sys.exit("::error::Video encoding failed.")
    audio_path.unlink()
    print(f"Rendered {out_path} ({total:.1f}s)")
    return total


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("Usage: render_reel.py episodes/NNN out.mp4")
    render(sys.argv[1], sys.argv[2])
