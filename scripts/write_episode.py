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

# Real-life situations, grouped by the time of day they fit best. Each run picks one
# that hasn't been used recently, from the group for the current posting slot.
TOPICS = {
    "morning": [  # 11 AM post: office, college, start of the day
        "Monday morning and the alarm was snoozed seven times",
        "boss calls an 'urgent' meeting that could have been a message",
        "office group chat has 200 unread messages",
        "teacher says 'this will come in the exam' about every single topic",
        "attendance is short and the semester ends next week",
        "job interview question: where do you see yourself in five years",
        "work from home but the family thinks you're free all day",
        "salary credited and already gone in two days",
        "colleague takes credit for her work in front of the boss",
        "auto driver refuses to go by the meter",
        "group project where she's doing all the work",
        "first day at a new office, doesn't know anyone",
        "laptop updates right before an important presentation",
        "packed lunch smells so good the whole office wants some",
    ],
    "afternoon": [  # 4 PM post: chai time, afternoon slump, everyday life
        "post-lunch sleepiness at the desk",
        "ordered online, the item looks nothing like the photo",
        "friend replies 'haha' to a long emotional message",
        "phone at 2 percent and the charger is at home",
        "gym membership paid for a year, went twice",
        "diet starts 'from Monday' for the fifth Monday",
        "delivery app says 'arriving in 2 minutes' for 20 minutes",
        "best friend posts the one photo where her eyes are closed",
        "WiFi stops working exactly during an online class",
        "neighbour aunty knows her business before she does",
        "started a hobby, bought all the equipment, did it once",
        "seen-zoned by a friend who is online",
        "trying to save money but sales keep happening",
        "rain ruined the plan and the new shoes",
    ],
    "evening": [  # 7 PM post: family, relatives, going home, weekend plans
        "relatives asking 'beta, shaadi kab karogi?' at every function",
        "mom compares her to Sharma ji's daughter",
        "dad forwards fake news on the family WhatsApp group",
        "stuck in traffic for an hour to travel five kilometres",
        "friends cancel the weekend plan at the last minute",
        "sibling steals her charger and denies it",
        "trying to watch a series but the family wants the TV",
        "evening walk resolution lasting one day",
        "making plans with friends that never happen",
        "parents discovering she has a social media account",
        "wedding season: three functions, one outfit",
        "dinner debate: what to eat, nobody decides",
        "grandmother insists on feeding her a fourth dinner",
        "electricity goes off right before the episode's climax",
    ],
}

SYSTEM_PROMPT = """You write short comedy scripts for "Chai Bot 3000", an animated Instagram Reels series for teens and adults in India.

THE CHARACTER
Chai Bot 3000 is a slightly rusty turquoise robot who runs a roadside chai stall. His face is an old TV screen.
He is endlessly cheerful, very confident, and his advice is usually hilariously wrong — but sometimes accidentally wise.
He believes chai solves everything. He refuses to serve coffee. He talks like a friendly chaiwala, with occasional robot words
(प्रोसेसिंग, डेटा, सिस्टम, अपडेट, एरर).

THE FORMAT
A customer — a young woman, always female (so Hindi verb endings must be feminine: "करती हूँ", "गई थी") — arrives with a
relatable everyday problem. Chai Bot listens, "processes", and gives confident, absurd advice.
The last line is a punchline that lands. Total spoken words: 45–75 (about 20–35 seconds).

MAKE IT GENUINELY FUNNY AND RELATABLE
- Start from a hyper-specific, everyday Indian moment people instantly recognise ("this is literally me / my mom / my
  office"). Specific details make it funny: the exact excuse, the exact WhatsApp message, the exact thing aunty says.
- Chai Bot's advice must be absurd but follow a weird, confident robot logic — he takes things too literally, "optimises"
  human life like a machine, or misunderstands an idiom. Example flavours (don't copy them): treating relatives' questions
  as "spam calls" to block; offering to "factory reset" the boss; prescribing "two cups of chai every 30 minutes" for heartbreak.
- Escalate: each bot line gets a bit more ridiculous than the last.
- End on a twist punchline: a callback to her first line, a surprising self-own by the bot, or an unexpectedly wise line
  hidden inside nonsense. The punchline should make people want to tag a friend.
- Before writing, silently think of three different premises and use the funniest; skip anything predictable.
- Comedy comes from the situation and the robot's logic — never from insulting anyone.

MAKE IT FEEL LIKE A REAL CONVERSATION
- The customer talks like a real person venting to a chaiwala: emotional, a bit dramatic, uses fillers and reactions
  ("यार", "अरे", "हाय", "सच में?", "मतलब...", "हम्म"), sometimes doesn't finish a sentence.
- Chai Bot answers HER specific words, not a generic speech. Short back-and-forth turns, not long monologues.
- At least one quick reaction line (e.g. customer: "सच में?!" or "भैया, ये क्या बोल रहे हो?").
- Use punctuation for natural speech rhythm: commas for small pauses, "..." for hesitation, "?!" for disbelief.
- Chai Bot is warm and friendly like a neighbourhood chaiwala who happens to be a robot — only an occasional robot word.

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
  "customer_voice": "female",
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


def time_slot():
    """morning / afternoon / evening, by the current time in India (UTC+5:30)."""
    from datetime import datetime, timedelta, timezone
    hour = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).hour
    if hour < 14:
        return "morning"
    if hour < 18:
        return "afternoon"
    return "evening"


def pick_topic(history, slot):
    """Pick a situation for this time of day that hasn't been used recently."""
    options = TOPICS[slot]
    recent = {h.get("seed_topic") for h in history[-30:]}
    fresh = [t for t in options if t not in recent] or options
    return random.choice(fresh)


def ask_claude(prompt, api_key, model, system=None):
    body = json.dumps({
        "model": model,
        "max_tokens": 2000,
        "temperature": 1.0,
        "system": system or SYSTEM_PROMPT,
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


# If the chosen Gemini model is busy or unavailable, these free models are tried next.
GEMINI_BACKUPS = ["gemini-flash-lite-latest", "gemini-3.6-flash", "gemini-3.5-flash-lite"]
GEMINI_WAITS = [20, 45, 90, 150]  # seconds to wait between retries on the same model


def gemini_request(prompt, api_key, model, system=None):
    body = json.dumps({
        "system_instruction": {"parts": [{"text": system or SYSTEM_PROMPT}]},
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
    with urllib.request.urlopen(request, timeout=120) as reply:
        data = json.load(reply)
    parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
    return "".join(part.get("text", "") for part in parts)


def ask_gemini(prompt, api_key, model, system=None):
    """Ask Gemini, waiting out busy periods and falling back to other free models."""
    models = [model] + [m for m in GEMINI_BACKUPS if m != model]
    last = ""
    for current in models:
        for attempt in range(len(GEMINI_WAITS) + 1):
            try:
                text = gemini_request(prompt, api_key, current, system)
                if text.strip():
                    if current != model:
                        print(f"  (used backup model {current})")
                    return text
                last = f"{current}: empty reply"
            except urllib.error.HTTPError as error:
                detail = error.read().decode(errors="replace")[:300]
                last = f"{current}: error {error.code} {detail}"
                if error.code in (400, 401, 403):
                    fail(f"Gemini rejected the request (check GEMINI_API_KEY): {last}")
                if error.code == 404:
                    print(f"  model {current} not available, trying the next one")
                    break
            except (urllib.error.URLError, TimeoutError) as error:
                last = f"{current}: network problem {error}"
            if attempt < len(GEMINI_WAITS):
                wait = GEMINI_WAITS[attempt]
                print(f"  Gemini busy ({last[:80]}), waiting {wait}s...")
                time.sleep(wait)
        print(f"  giving up on {current}, trying the next model")
    fail(f"Gemini stayed unavailable on every model. Last error: {last}")


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
    slot = time_slot()
    topic = pick_topic(history, slot)
    used = "\n".join(f"- {h['title']}" for h in history[-60:]) or "(none yet)"
    prompt = (
        f"Write episode #{number}. It posts in the {slot} (India time), so it should feel right for that moment.\n"
        f"Situation to build on: {topic}.\n"
        f"Make it specific, relatable and genuinely funny, with a punchline people would tag a friend for.\n\n"
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
