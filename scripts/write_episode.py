#!/usr/bin/env python3
"""Write the next Chai Bot 3000 episode script (in Hindi) with an AI model.

Creates episodes/<NNN>/episode.json and records it in episodes/history.json.

Environment (set one of the two keys)
-------------------------------------
GEMINI_API_KEY      Google Gemini, free tier (used if set)
ANTHROPIC_API_KEY   Claude, paid (about 1-2 cents a script)
SCRIPT_MODEL        optional model override
                    (defaults: gemini-flash-latest / claude-sonnet-5-5)
"""
import json
import os
import pathlib
import random
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
EPISODES = ROOT / "episodes"
HISTORY = EPISODES / "history.json"

FACES = ["happy", "confused", "smug", "shocked", "sad", "angry", "love", "neutral"]

TOPICS = [
    "office and bosses", "exams and results", "college life", "job interviews",
    "salary day and money running out", "friends who never reply", "relatives' questions",
    "parents and phone use", "gym and fitness goals", "Monday mornings", "traffic and commute",
    "online shopping", "food delivery and cooking", "sleep and alarm clocks", "social media likes",
    "weddings and functions", "neighbours", "rain and weather", "group projects",
    "WiFi and phone battery", "New Year resolutions", "procrastination", "first salary",
    "hostel and PG life", "siblings", "being single", "work from home",
]

SYSTEM_PROMPT = """You write short comedy scripts for "Chai Bot 3000", an animated Instagram Reels series for teens and adults in India.

THE CHARACTER
Chai Bot 3000 is a slightly rusty turquoise robot who runs a roadside chai stall. His face is an old TV screen.
He is endlessly cheerful, very confident, and his advice is usually hilariously wrong — but sometimes accidentally wise.
He believes chai solves everything. He refuses to serve coffee. He talks like a friendly chaiwala, with occasional robot words
(प्रोसेसिंग, डेटा, सिस्टम, अपडेट, एरर).

THE FORMAT
A customer arrives with a relatable everyday problem. Chai Bot listens, "processes", and gives confident, absurd advice.
The last line is a punchline that lands. Total spoken words: 45–75 (about 20–35 seconds).

LANGUAGE
Everything spoken is natural, everyday spoken Hindi written in Devanagari script — how people actually talk, not formal or
textbook Hindi. Common English words people use in Hindi (बॉस, ऑफिस, फोन, सैलरी) are fine, written in Devanagari.
Every line must be easy for a Hindi text-to-speech voice to read: no emojis, no abbreviations, no symbols, numbers as words.

RULES — never break these
- Clean, friendly humour any family member could watch. No swearing, no double meanings.
- No politics, religion, caste, region, or community jokes. No jokes about gender roles, looks, weight, skin colour or disability.
- No real people, celebrities, brands or companies.
- No alcohol, smoking, drugs, gambling, violence or self-harm, even as a joke.
- Advice must be harmless nonsense: never suggest anything risky, illegal, unhealthy or rude to do in real life.
- Don't reuse a problem or punchline from the "already used" list.

OUTPUT
Reply with ONLY a JSON object, no other text:
{
  "title": "4–7 word Hindi hook that states the problem (Devanagari)",
  "title_en": "the same hook in short, punchy English (max 7 words), shown on screen",
  "topic": "short English label of the topic",
  "customer_voice": "male" or "female",
  "reaction": one of FACES — Chai Bot's face the moment he hears the problem,
  "lines": [
    {"who": "customer", "text": "Hindi (Devanagari)", "en": "English subtitle", "face": FACE Chai Bot shows while listening},
    {"who": "bot", "text": "Hindi (Devanagari)", "en": "English subtitle", "face": FACE while saying it},
    ...
  ],
  "caption": "Instagram caption in Hindi (Devanagari): one funny line, then a question that invites comments or tagging a friend. Max 3 short lines. Emojis allowed here.",
  "hashtags": ["#chaibot3000", ... 6–9 relevant hashtags, mix of Hindi-audience and English tags]
}
Lines: start with 1–2 customer lines, then 2–3 bot lines; optionally one short customer reply and a final bot punchline.
Every line at most 16 words. 4–6 lines in total. Keep sentences short and simple so they're easy to follow.
"en" is a natural, funny English subtitle of that exact line (not word-for-word), so non-Hindi speakers get the joke.
FACES = happy, confused, smug, shocked, sad, angry, love, neutral."""


def fail(message):
    print(f"::error::{message}")
    sys.exit(1)


def load_history():
    if HISTORY.exists():
        return json.loads(HISTORY.read_text(encoding="utf-8"))
    return []


def pick_topic(history):
    """Pick a topic not used recently, so episodes stay varied."""
    recent = [h.get("seed_topic") for h in history[-len(TOPICS) // 2:]]
    fresh = [t for t in TOPICS if t not in recent] or TOPICS
    return random.choice(fresh)


def ask_claude(prompt, api_key, model):
    body = json.dumps({
        "model": model,
        "max_tokens": 2000,
        "temperature": 1.0,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    request = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        method="POST",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as reply:
            data = json.load(reply)
    except urllib.error.HTTPError as error:
        fail(f"Claude API error {error.code}: {error.read().decode(errors='replace')}")
    return "".join(block.get("text", "") for block in data.get("content", []))


def ask_gemini(prompt, api_key, model):
    body = json.dumps({
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 1.0, "maxOutputTokens": 4000,
                             "responseMimeType": "application/json"},
    }).encode()
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=body,
        method="POST",
        headers={"x-goog-api-key": api_key, "content-type": "application/json"},
    )
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(request, timeout=120) as reply:
                data = json.load(reply)
            break
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")
            if error.code in (429, 500, 503) and attempt < 3:  # busy / free-tier limit: wait and retry
                print(f"  Gemini busy ({error.code}), retrying in {30 * attempt}s...")
                time.sleep(30 * attempt)
                continue
            fail(f"Gemini API error {error.code}: {detail}")
    parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
    return "".join(part.get("text", "") for part in parts)


def parse_episode(text):
    """Pull the JSON out of the reply and check it has everything the renderer needs."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("no JSON object in reply")
    episode = json.loads(text[start:end + 1])

    for key in ("title", "lines", "caption", "reaction", "customer_voice"):
        if not episode.get(key):
            raise ValueError(f"missing '{key}'")
    if episode["customer_voice"] not in ("male", "female"):
        episode["customer_voice"] = "female"
    if episode["reaction"] not in FACES:
        episode["reaction"] = "shocked"

    lines = episode["lines"]
    if not 3 <= len(lines) <= 7:
        raise ValueError(f"{len(lines)} lines (need 3–7)")
    if lines[0].get("who") != "customer":
        raise ValueError("first line must be the customer")
    if lines[-1].get("who") != "bot":
        raise ValueError("last line must be Chai Bot")
    total_words = 0
    for line in lines:
        if line.get("who") not in ("customer", "bot"):
            raise ValueError(f"unknown speaker {line.get('who')}")
        text = (line.get("text") or "").strip()
        if not text:
            raise ValueError("empty line")
        if not any("ऀ" <= ch <= "ॿ" for ch in text):
            raise ValueError(f"line is not in Devanagari: {text}")
        line["text"] = text
        english = (line.get("en") or "").strip()
        if not english or sum(ch.isascii() for ch in english) < len(english) * 0.9:
            raise ValueError(f"missing or non-English subtitle for: {text}")
        line["en"] = english
        if line.get("face") not in FACES:
            line["face"] = "neutral" if line["who"] == "bot" else "happy"
        total_words += len(text.split())
    title_en = (episode.get("title_en") or "").strip()
    if not title_en:
        raise ValueError("missing 'title_en'")
    episode["title_en"] = title_en
    if not 30 <= total_words <= 100:
        raise ValueError(f"{total_words} words (aim 45–75)")

    tags = [t if t.startswith("#") else f"#{t}" for t in episode.get("hashtags", [])]
    if "#chaibot3000" not in tags:
        tags.insert(0, "#chaibot3000")
    episode["hashtags"] = tags[:10]
    return episode


def main():
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    claude_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    model = os.environ.get("SCRIPT_MODEL", "").strip()
    if gemini_key:
        model = model or "gemini-flash-latest"
        ask = lambda p: ask_gemini(p, gemini_key, model)  # noqa: E731
    elif claude_key:
        model = model or "claude-sonnet-5-5"
        ask = lambda p: ask_claude(p, claude_key, model)  # noqa: E731
    else:
        fail("Add a GEMINI_API_KEY secret (free) or an ANTHROPIC_API_KEY secret.")
    print(f"Writing the script with {model}")

    history = load_history()
    number = (history[-1]["number"] + 1) if history else 1
    topic = pick_topic(history)
    used = "\n".join(f"- {h['title']}" for h in history[-60:]) or "(none yet)"
    prompt = (
        f"Write episode #{number}. Topic area: {topic}.\n"
        f"Pick a specific, relatable situation inside that topic.\n\n"
        f"Already used (don't repeat these problems):\n{used}"
    )

    last_error = None
    for attempt in range(1, 4):
        reply = ask(prompt)
        try:
            episode = parse_episode(reply)
            break
        except (ValueError, json.JSONDecodeError) as error:
            last_error = error
            print(f"Attempt {attempt}: script didn't pass checks ({error}), asking again...")
            time.sleep(2)
    else:
        fail(f"Couldn't get a valid script after 3 tries: {last_error}")

    episode["number"] = number
    folder = EPISODES / f"{number:03d}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "episode.json").write_text(json.dumps(episode, ensure_ascii=False, indent=2), encoding="utf-8")

    history.append({"number": number, "title": episode["title"], "topic": episode.get("topic", ""),
                    "seed_topic": topic})
    HISTORY.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Episode #{number}: {episode['title']}")
    for line in episode["lines"]:
        print(f"  {line['who']:>8} [{line['face']}]: {line['text']}")
    print(folder)
    return folder


if __name__ == "__main__":
    main()
