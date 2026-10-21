#!/usr/bin/env python3
"""Post today's Reel (described in site/reel.json) to Instagram.

Environment
-----------
IG_ACCESS_TOKEN   Instagram access token (GitHub secret).
PUBLIC_BASE_URL   Public address where site/ is published (GitHub Pages).
DRY_RUN           "true" = check the token and the video link, but don't post.
"""
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API = "https://graph.instagram.com/v25.0"
ROOT = pathlib.Path(__file__).resolve().parent.parent
REEL_INFO = ROOT / "site" / "reel.json"
LOG = ROOT / "posted.log"
STATUS_WAIT_SECONDS = 15
STATUS_MAX_WAIT_SECONDS = 15 * 60


def fail(message):
    print(f"::error::{message}")
    sys.exit(1)


def call(method, path, token, params=None):
    params = dict(params or {})
    params["access_token"] = token
    url = f"{API}/{path}"
    data = None
    if method == "GET":
        url += "?" + urllib.parse.urlencode(params)
    else:
        data = urllib.parse.urlencode(params).encode()
    request = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as reply:
            return json.load(reply)
    except urllib.error.HTTPError as error:
        fail(f"Instagram API error {error.code} on '{path}': {error.read().decode(errors='replace')}")
    except urllib.error.URLError as error:
        fail(f"Could not reach Instagram ({path}): {error.reason}")


def check_public_link(url, attempts=8):
    """Instagram downloads the video itself, so the link must work publicly."""
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=30) as reply:
                size_mb = int(reply.headers.get("Content-Length", "0")) / 1_000_000
                print(f"Video link works ({reply.headers.get('Content-Type')}, {size_mb:.1f} MB): {url}")
                return
        except (urllib.error.HTTPError, urllib.error.URLError) as error:
            print(f"  link not ready yet ({error}), waiting...")
            time.sleep(15)
    fail(f"The video link {url} isn't reachable. Check that GitHub Pages is set to 'GitHub Actions'.")


def wait_until_ready(container_id, token):
    waited = 0
    while waited <= STATUS_MAX_WAIT_SECONDS:
        info = call("GET", container_id, token, {"fields": "status_code,status"})
        code = info.get("status_code")
        print(f"  Instagram processing status: {code}")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            fail(f"Instagram could not process the video: {info.get('status', code)}")
        time.sleep(STATUS_WAIT_SECONDS)
        waited += STATUS_WAIT_SECONDS
    fail("Instagram was still processing the video after 15 minutes.")


def main():
    token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    base_url = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    dry_run = os.environ.get("DRY_RUN", "false").strip().lower() == "true"
    if not token:
        fail("IG_ACCESS_TOKEN secret is missing (Settings > Secrets and variables > Actions).")
    if not base_url:
        fail("Public video address is missing (GitHub Pages didn't report its URL).")
    if not REEL_INFO.exists():
        fail("site/reel.json not found, so there's nothing to post.")

    reel = json.loads(REEL_INFO.read_text(encoding="utf-8"))
    caption = reel.get("caption", "")
    print(f"Reel: {reel['video']}")
    print(f"Caption: {caption[:150]}{'...' if len(caption) > 150 else ''}")

    me = call("GET", "me", token, {"fields": "user_id,username"})
    user_id = me.get("user_id") or me.get("id")
    print(f"Posting as @{me.get('username')} (account {user_id})")

    video_url = f"{base_url}/{urllib.parse.quote(reel['video'])}"
    check_public_link(video_url)

    if dry_run:
        print("Dry run: everything checks out. Nothing was posted.")
        return

    container = call("POST", f"{user_id}/media", token, {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "share_to_feed": "true",
    })
    container_id = container["id"]
    print(f"Upload started (container {container_id}), waiting for Instagram to process it...")
    wait_until_ready(container_id, token)

    published = call("POST", f"{user_id}/media_publish", token, {"creation_id": container_id})
    media_id = published["id"]
    permalink = call("GET", media_id, token, {"fields": "permalink"}).get("permalink", "")
    print(f"Posted! {permalink or media_id}")

    with LOG.open("a", encoding="utf-8") as log:
        log.write(json.dumps({
            "posted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "video": reel["video"],
            "episode": reel.get("episode"),
            "title": reel.get("title"),
            "media_id": media_id,
            "permalink": permalink,
        }, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
