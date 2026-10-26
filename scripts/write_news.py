#!/usr/bin/env python3
"""Write today's Chai Bot news bulletin in formal Hindi, using only The Hindu.

Each run covers ONE category, rotating through:
  sports -> tech & gadgets -> science & space -> feel-good & unusual -> entertainment -> ...

Steps: read The Hindu's RSS feeds for the category, drop sensitive or already-used
stories, have the AI write a 3-story bulletin from those headlines only, then have
the AI fact-check the bulletin against the headlines before it's accepted.

Creates episodes/<NNN>/episode.json (format "news") and records it in episodes/history.json.

Environment: GEMINI_API_KEY (free) or ANTHROPIC_API_KEY, optional SCRIPT_MODEL.
"""
import html
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import write_episode as common  # noqa: E402  (shared AI helpers + history)

ROOT = pathlib.Path(__file__).resolve().parent.parent
EPISODES = ROOT / "episodes"
HISTORY = EPISODES / "history.json"

HINDU = "https://www.thehindu.com"
CATEGORIES = [
    {
        "key": "sports", "hi": "खेल समाचार", "en": "Sports News",
        "feeds": [f"{HINDU}/sport/cricket/feeder/default.rss", f"{HINDU}/sport/feeder/default.rss"],
        "tags": ["#sportsnews", "#cricket", "#खेल", "#indiansports"],
        "focus": "match results, records, big wins, tournaments, notable performances by Indian players",
    },
    {
        "key": "tech", "hi": "तकनीक और गैजेट्स", "en": "Tech & Gadgets",
        "feeds": [f"{HINDU}/sci-tech/technology/gadgets/feeder/default.rss",
                  f"{HINDU}/sci-tech/technology/feeder/default.rss"],
        "tags": ["#technews", "#gadgets", "#तकनीक", "#smartphone"],
        "focus": "new phones and gadgets, launches, useful apps, AI and internet developments",
    },
    {
        "key": "science", "hi": "विज्ञान और अंतरिक्ष", "en": "Science & Space",
        "feeds": [f"{HINDU}/sci-tech/science/feeder/default.rss"],
        "tags": ["#sciencenews", "#space", "#विज्ञान", "#isro"],
        "focus": "space missions, discoveries, research breakthroughs, nature and environment science",
    },
    {
        "key": "feelgood", "hi": "अच्छी और अनोखी ख़बरें", "en": "Good & Unusual News",
        "feeds": [f"{HINDU}/life-and-style/feeder/default.rss", f"{HINDU}/news/feeder/default.rss"],
        "tags": ["#goodnews", "#positivenews", "#अनोखी_ख़बर", "#inspiring"],
        "focus": "uplifting, inspiring, heart-warming or surprising-but-harmless stories only",
    },
    {
        "key": "entertainment", "hi": "मनोरंजन समाचार", "en": "Entertainment News",
        "feeds": [f"{HINDU}/entertainment/movies/feeder/default.rss", f"{HINDU}/entertainment/feeder/default.rss"],
        "tags": ["#entertainmentnews", "#movies", "#मनोरंजन", "#newrelease"],
        "focus": "big film and series releases, trailers, box office milestones, music launches, awards",
    },
]

# Stories mentioning any of these are skipped before the AI ever sees them.
BLOCKED_WORDS = [
    "death", "dead", "dies", "died", "killed", "murder", "suicide", "rape", "sexual", "assault",
    "terror", "terrorist", "blast", "bomb", "riot", "violence", "gunman", "shot dead", "stabbed",
    "accident", "crash", "flood", "earthquake", "cyclone", "landslide", "victim", "arrest", "arrested",
    "police", "supreme court", "high court", "custody", "probe", "scam", "fraud", "war", "missile",
    "military", "army", "election", "elections", "poll", "polls", "vote", "voting", "minister", "bjp",
    "congress", "parliament", "assembly", "government", "modi", "gandhi", "religion", "religious",
    "temple", "mosque", "church", "caste", "communal", "muslim", "christian", "protest", "obituary",
    "condolence", "controversy", "slams", "lashes out", "abuse", "harassment", "drugs", "betting",
    "gambling", "doping",
]

MAX_AGE_HOURS = 48
STORIES_PER_BULLETIN = 3

SYSTEM_PROMPT = """You are the script writer for "Chai Bot 3000", a friendly robot who presents a short daily news
bulletin on Instagram Reels for an Indian audience. Chai Bot runs a roadside chai stall and reads the news to his customers.

LANGUAGE — the most important rule
Write in proper, formal, standard Hindi (मानक हिंदी), the way a respected Hindi news anchor speaks: correct grammar, clean
sentences, Hindi words instead of English where a natural Hindi word exists (प्रतियोगिता, घोषणा, वैज्ञानिक, अंतरिक्ष, फ़िल्म
is fine). Proper nouns (players, teams, products, films, places) are written in Devanagari as they are pronounced.
It must be easy for a Hindi text-to-speech voice: no emojis, no symbols, no abbreviations, no English letters,
all numbers written out as Hindi words (for example "दो सौ पैंतालीस रन", "तीन विकेट", "सन दो हज़ार छब्बीस").

ACCURACY — never break these
- Use ONLY facts that are stated in the headlines and summaries you are given. Do not add any name, number, date,
  score, quote, reason or detail that is not in them. If a detail is unclear, leave it out.
- Report facts neutrally. No jokes about the news, no opinions, no speculation, no exaggeration.
- Skip any story that involves politics, religion, caste, crime, violence, death, disasters or controversy,
  even if it appears in the list.
- Rewrite in your own words; never copy sentences.

FORMAT
Pick the {n} most interesting suitable stories from the list. The bulletin has 5 lines, all spoken by Chai Bot:
  1. A warm one-line greeting that names today's category (e.g. "नमस्कार, चाय बॉट की ख़बरों में आपका स्वागत है।
     आज की खेल ख़बरें सुनिए।").
  2–4. One line per story: two short, clear sentences each (at most 30 words per line).
  5. A short sign-off inviting viewers to follow for tomorrow's news.
Total spoken words: 70–120.

OUTPUT — reply with ONLY this JSON object:
{{
  "used_items": [index numbers of the stories you used, in order],
  "title": "short Hindi headline for the whole bulletin (max 8 words)",
  "title_en": "the same in English (max 8 words)",
  "lines": [
    {{"who": "bot", "text": "Hindi line", "en": "English translation", "face": "happy" or "neutral" or "shocked" or "love"}},
    ... exactly 5 lines ...
  ],
  "caption": "Instagram caption in formal Hindi: one line per story as a short summary (an emoji at the start of each
              line is fine), then a line inviting people to follow for daily news. Do not include hashtags or sources."
}}"""

CHECK_PROMPT = """You are a strict fact-checker for a Hindi news bulletin. Compare the bulletin with the source headlines
and summaries. Report a problem if the bulletin states ANY name, number, date, score, quote, cause or detail that is not
supported by the sources, gets something wrong, or covers politics, religion, crime, violence, death or disasters.
Also report any line that is not in proper Hindi (Devanagari) or that contains English letters or digits.
Greeting and sign-off lines don't need sources.
Reply with ONLY JSON: {"ok": true or false, "problems": ["short description", ...]}"""


def fail(message):
    print(f"::error::{message}")
    sys.exit(1)


# ---------------------------------------------------------------- feeds

def clean(text):
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def fetch_feed(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (ChaiBot news reader)"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as reply:
                return reply.read()
        except (urllib.error.URLError, TimeoutError) as error:
            print(f"  couldn't read {url} ({error}), retrying...")
            time.sleep(5 * (attempt + 1))
    print(f"  giving up on {url}")
    return None


def read_stories(category, used_links):
    now = datetime.now(timezone.utc)
    stories, seen = [], set()
    for url in category["feeds"]:
        raw = fetch_feed(url)
        if not raw:
            continue
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as error:
            print(f"  {url} isn't valid RSS ({error})")
            continue
        for item in root.iter("item"):
            title = clean(item.findtext("title"))
            summary = clean(item.findtext("description"))[:500]
            link = (item.findtext("link") or "").strip()
            if not title or not link or link in seen or link in used_links:
                continue
            published = item.findtext("pubDate")
            try:
                when = parsedate_to_datetime(published) if published else None
            except (TypeError, ValueError):
                when = None
            if when and when.tzinfo and now - when > timedelta(hours=MAX_AGE_HOURS):
                continue
            words = f" {title} {summary} ".lower()
            if any(re.search(rf"\b{re.escape(w.strip())}\b", words) for w in BLOCKED_WORDS):
                continue
            seen.add(link)
            stories.append({"title": title, "summary": summary, "link": link})
    return stories[:12]


# ---------------------------------------------------------------- checks

def has_latin_or_digits(text):
    return bool(re.search(r"[A-Za-z0-9]", text))


def parse_bulletin(text, stories):
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("no JSON in reply")
    data = json.loads(text[start:end + 1])
    lines = data.get("lines") or []
    if len(lines) != 5:
        raise ValueError(f"{len(lines)} lines (need 5)")
    total = 0
    for line in lines:
        line["who"] = "bot"
        spoken = (line.get("text") or "").strip()
        if not spoken or not any("ऀ" <= ch <= "ॿ" for ch in spoken):
            raise ValueError("a line is empty or not in Hindi")
        if has_latin_or_digits(spoken):
            raise ValueError(f"English letters or digits in a spoken line: {spoken}")
        if len(spoken.split()) > 34:
            raise ValueError("a line is too long")
        line["text"] = spoken
        line["en"] = (line.get("en") or "").strip()
        if line.get("face") not in ("happy", "neutral", "shocked", "love"):
            line["face"] = "neutral"
        total += len(spoken.split())
    if not 55 <= total <= 140:
        raise ValueError(f"{total} spoken words (aim 70-120)")
    used = [i for i in data.get("used_items", []) if isinstance(i, int) and 0 <= i < len(stories)]
    if not used:
        raise ValueError("didn't say which stories it used")
    for key in ("title", "caption"):
        if not (data.get(key) or "").strip():
            raise ValueError(f"missing '{key}'")
    data["used_items"] = used
    return data


def story_list(stories):
    return "\n".join(f"[{i}] {s['title']}\n    {s['summary']}" for i, s in enumerate(stories))


# ---------------------------------------------------------------- main

def next_category(history):
    done = [h.get("category") for h in history if h.get("format") == "news"]
    if not done:
        return 0
    keys = [c["key"] for c in CATEGORIES]
    last = done[-1]
    return (keys.index(last) + 1) % len(keys) if last in keys else 0


def main():
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    claude_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    model = os.environ.get("SCRIPT_MODEL", "").strip()
    if gemini_key:
        model = model or "gemini-flash-latest"
        ask = lambda p, s: common.ask_gemini(p, gemini_key, model, s)  # noqa: E731
    elif claude_key:
        model = model or "claude-sonnet-5-5"
        ask = lambda p, s: common.ask_claude(p, claude_key, model, s)  # noqa: E731
    else:
        fail("Add a GEMINI_API_KEY secret (free) or an ANTHROPIC_API_KEY secret.")

    history = common.load_history()
    number = (history[-1]["number"] + 1) if history else 1
    used_links = {link for h in history for link in h.get("links", [])}

    # Try categories in rotation until one has enough fresh, suitable stories.
    first = next_category(history)
    for step in range(len(CATEGORIES)):
        category = CATEGORIES[(first + step) % len(CATEGORIES)]
        print(f"Reading The Hindu: {category['en']}")
        stories = read_stories(category, used_links)
        print(f"  {len(stories)} suitable fresh stories")
        if len(stories) >= STORIES_PER_BULLETIN:
            break
    else:
        fail("Not enough suitable fresh stories in any category today.")

    system = SYSTEM_PROMPT.format(n=STORIES_PER_BULLETIN)
    prompt = (f"Today's category: {category['hi']} ({category['en']}). Focus on: {category['focus']}.\n\n"
              f"Source stories from The Hindu (use only these facts):\n{story_list(stories)}")

    feedback = ""
    for attempt in range(1, 4):
        reply = ask(prompt + feedback, system)
        try:
            bulletin = parse_bulletin(reply, stories)
        except (ValueError, json.JSONDecodeError) as error:
            print(f"Attempt {attempt}: script didn't pass checks ({error}), asking again...")
            feedback = f"\n\nYour previous attempt was rejected: {error}. Fix this."
            continue
        sources = story_list([stories[i] for i in bulletin["used_items"]])
        script = "\n".join(line["text"] for line in bulletin["lines"])
        verdict_text = ask(f"SOURCES:\n{sources}\n\nBULLETIN:\n{script}", CHECK_PROMPT)
        try:
            verdict = json.loads(verdict_text[verdict_text.find("{"): verdict_text.rfind("}") + 1])
        except (ValueError, json.JSONDecodeError):
            verdict = {"ok": False, "problems": ["fact-check reply unreadable"]}
        if verdict.get("ok") is True:
            print("Fact-check passed.")
            break
        problems = "; ".join(verdict.get("problems", []))[:600]
        print(f"Attempt {attempt}: fact-check found problems: {problems}")
        feedback = f"\n\nYour previous bulletin failed fact-checking: {problems}. Write it again, fixing these."
    else:
        fail("Couldn't produce a bulletin that passed fact-checking after 3 tries; skipping this post.")

    used = [stories[i] for i in bulletin["used_items"]]
    tags = ["#chaibot3000", "#hindinews", "#हिंदी_समाचार", "#news"] + category["tags"]
    caption = (f"{category['hi']} ☕🤖\n\n{bulletin['caption'].strip()}\n\n"
               f"स्रोत: द हिंदू (The Hindu)\n\n" + " ".join(tags))

    episode = {
        "number": number,
        "format": "news",
        "category": category["key"],
        "category_hi": category["hi"],
        "category_en": category["en"],
        "title": bulletin["title"].strip(),
        "title_en": (bulletin.get("title_en") or category["en"]).strip(),
        "reaction": "happy",
        "lines": bulletin["lines"],
        "caption": caption[:2200],
        "hashtags": [],
        "sources": [{"title": s["title"], "link": s["link"]} for s in used],
    }
    folder = EPISODES / f"{number:03d}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "episode.json").write_text(json.dumps(episode, ensure_ascii=False, indent=2), encoding="utf-8")
    history.append({"number": number, "format": "news", "category": category["key"],
                    "title": episode["title"], "links": [s["link"] for s in used]})
    HISTORY.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Bulletin #{number} — {category['en']}: {episode['title']}")
    for line in episode["lines"]:
        print(f"  [{line['face']}] {line['text']}")
    for s in used:
        print(f"  source: {s['link']}")
    return folder


if __name__ == "__main__":
    main()
