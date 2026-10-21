#!/usr/bin/env python3
"""Make today's Reel and put it in site/ ready to publish.

If you've dropped your own video in queue/, that one goes out first.
Otherwise a brand-new Chai Bot episode is written, voiced and rendered.

Writes site/<video>.mp4 and site/reel.json (file name + caption).
"""
import json
import pathlib
import shutil
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import make_voices  # noqa: E402
import render_reel  # noqa: E402
import write_episode  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
QUEUE = ROOT / "queue"
SITE = ROOT / "site"


def from_queue():
    videos = sorted(p for p in QUEUE.glob("*") if p.suffix.lower() in (".mp4", ".mov"))
    if not videos:
        return None
    video = videos[0]
    caption_file = video.with_suffix(".txt")
    caption = caption_file.read_text(encoding="utf-8").strip() if caption_file.exists() else ""
    target = SITE / video.name.replace(" ", "-")
    shutil.copy2(video, target)
    video.unlink()
    if caption_file.exists():
        caption_file.unlink()
    print(f"Using your queued video: {video.name}")
    return {"video": target.name, "caption": caption, "source": "queue"}


def new_episode():
    folder = write_episode.main()
    episode = json.loads((folder / "episode.json").read_text(encoding="utf-8"))
    print("Making voices...")
    make_voices.make_voices(folder)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    name = f"chai-bot-{episode['number']:03d}-{stamp}.mp4"
    print("Rendering video...")
    seconds = render_reel.render(folder, SITE / name)
    for wav in folder.glob("line_*.wav"):
        wav.unlink()
    caption = episode["caption"].strip() + "\n\n" + " ".join(episode["hashtags"])
    return {"video": name, "caption": caption[:2200], "source": "generated",
            "episode": episode["number"], "title": episode["title"], "seconds": round(seconds, 1)}


def main():
    if SITE.exists():
        shutil.rmtree(SITE)
    SITE.mkdir()
    reel = from_queue() or new_episode()
    (SITE / "reel.json").write_text(json.dumps(reel, ensure_ascii=False, indent=2), encoding="utf-8")
    (SITE / "index.html").write_text("<!doctype html><title>Chai Bot 3000</title><p>Chai Bot 3000</p>")
    print(json.dumps(reel, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
