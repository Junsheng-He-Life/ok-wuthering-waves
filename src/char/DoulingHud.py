"""Recognize Buling's two healing-heavy prompts from the current native HUD.

Source mechanics: https://wiki.kurobbs.com/mc/item/1429461100965666816
The burst (艮艮) and regeneration (震震) prompts are distinct from the
mixed-pair damage prompt. A match is a prerequisite, never proof of HP gain.
"""
from functools import lru_cache
from pathlib import Path
import cv2


@lru_cache(maxsize=8)
def healing_templates(height):
    folder = Path(__file__).resolve().parents[2] / 'assets/images'
    result = []
    for kind in ('burst', 'regen'):
        image = cv2.imread(str(folder / f'douling-heal-{kind}-1920.png'))
        if image is not None:
            result.append(cv2.resize(image, None, fx=height/1080, fy=height/1080))
    return result


def healing_heavy_visible(frame):
    if frame is None:
        return False
    h, w = frame.shape[:2]
    # Native bottom-right attack HUD; keep the search away from other skills.
    scale = h / 1080
    left, right = round(w-540*scale), round(w-430*scale)
    region = frame[round(h-165*scale):round(h-65*scale), max(0,left):max(0,right)]
    for template in healing_templates(h):
        if any(a < b for a,b in zip(region.shape[:2], template.shape[:2])):
            continue
        score = cv2.minMaxLoc(cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED))[1]
        if score >= .85:
            return True
    return False
