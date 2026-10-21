#!/usr/bin/env python3
"""One-time prep: wipe the baked-in smile off Chai Bot's screen.

Reads  assets/chai-bot-original.png
Writes assets/stage.png   (same picture, blank screen)
       assets/stage.json  (where the screen and antenna bulb are)

Run again only if you replace the original picture; then re-check SCREEN_BOX.
Needs: pip install opencv-python-headless numpy
"""
import json
import pathlib

import cv2
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

# Inner glass of the screen in the original picture: left, top, right, bottom.
SCREEN_BOX = (420, 380, 690, 585)
# Where to look for the glowing antenna tip.
BULB_SEARCH = (520, 180, 680, 330)


def main():
    image = cv2.imread(str(ASSETS / "chai-bot-original.png"))
    x0, y0, x1, y1 = SCREEN_BOX
    screen = image[y0:y1, x0:x1]

    # 1. Find the glowing amber face pixels and paint over them.
    hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
    glow = (hsv[..., 2] > 70) & (hsv[..., 0] < 35) & (hsv[..., 1] > 80)
    mask = glow.astype(np.uint8) * 255
    inner = np.zeros_like(mask)
    cv2.rectangle(inner, (14, 14), (x1 - x0 - 14, y1 - y0 - 14), 255, -1)
    mask = cv2.dilate(cv2.bitwise_and(mask, inner), np.ones((9, 9), np.uint8), iterations=2)
    patched = cv2.inpaint(screen, mask, 9, cv2.INPAINT_TELEA)

    # 2. Smooth the inside of the glass so no trace of the old face is left.
    h, w = mask.shape
    glass = np.zeros((h, w), np.float32)
    cv2.rectangle(glass, (22, 22), (w - 22, h - 22), 1.0, -1)
    glass = cv2.GaussianBlur(glass, (0, 0), 9)[..., None]
    smooth = cv2.GaussianBlur(patched, (0, 0), 14).astype(np.float32)
    clean = smooth * glass + patched.astype(np.float32) * (1 - glass)
    noise = np.random.default_rng(3).normal(0, 1.6, clean.shape)
    image[y0:y1, x0:x1] = np.clip(clean + noise, 0, 255).astype(np.uint8)
    cv2.imwrite(str(ASSETS / "stage.png"), image)

    # 3. Find the antenna bulb (brightest warm spot above the head).
    bx0, by0, bx1, by1 = BULB_SEARCH
    region = cv2.GaussianBlur(cv2.cvtColor(image[by0:by1, bx0:bx1], cv2.COLOR_BGR2GRAY), (0, 0), 3)
    _, _, _, (bx, by) = cv2.minMaxLoc(region)

    info = {
        "size": [image.shape[1], image.shape[0]],
        "screen_box": list(SCREEN_BOX),
        "bulb": [bx0 + bx, by0 + by],
    }
    (ASSETS / "stage.json").write_text(json.dumps(info, indent=2))
    print(json.dumps(info))


if __name__ == "__main__":
    main()
