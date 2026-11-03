"""Recognize enhanced E glyphs, distinct from the shared forte-bar key.

Entry: 2026-11-03 19:08:29 saved combat frame, box (1608,936,1655,995).
Airborne: recorded frame 1793506020283241000.jpg, same box.
Finisher: jinhsi-failed-intro.jpg, box (908,1286,955,1345).
The latter two saved HUD contact sheets retain native pixel scale.
Cooldown/identity checks belong to the caller; a match alone proves no cast.
"""
from functools import lru_cache
from pathlib import Path
import cv2
import numpy as np


def white_glyph(image):
    return np.where(np.min(image[:, :, :3], axis=2) >= 180, 255, 0).astype(np.uint8)


@lru_cache(maxsize=8)
def templates(height):
    folder = Path(__file__).resolve().parents[2] / 'assets/images'
    result = []
    for stage in ('entry', 'airborne', 'finisher'):
        source = cv2.imread(str(folder / f'jinhsi-e-{stage}-1920.png'))
        if source is not None:
            resized = cv2.resize(source, None, fx=height/1080, fy=height/1080)
            result.append((stage, white_glyph(resized)))
    return result


def enhanced_e_stage(frame):
    if frame is None:
        return None
    h, w = frame.shape[:2]
    scale = h / 1080
    region = frame[round(h-154*scale):round(h-72*scale),
                   max(0,round(w-330*scale)):max(0,round(w-250*scale))]
    if not region.size:
        return None
    region = white_glyph(region)
    scores = []
    for stage, template in templates(h):
        if all(a >= b for a, b in zip(region.shape, template.shape)):
            score = cv2.minMaxLoc(cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED))[1]
            scores.append((score, stage))
    if not scores:
        return None
    score, stage = max(scores)
    return stage if score >= .82 else None
