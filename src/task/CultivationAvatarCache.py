"""Persist verified roster portraits and use them to locate cultivation targets."""
import hashlib
import json
from pathlib import Path

import cv2


CACHE_DIR = Path('configs/macos-desktop/cultivation-avatars')


def cache_paths(name):
    key = hashlib.sha256(name.encode('utf-8')).hexdigest()[:16]
    return CACHE_DIR / f'{key}.png', CACHE_DIR / f'{key}.json'


def scroll_roster(task, amount=-4):
    """Move a small overlapping distance and wait for list inertia to settle."""
    task.scroll_relative(.40, .55, amount)
    task.sleep(.4)
    task.next_frame()
    previous = task.frame[:round(task.height*.88), :round(task.width*.63)].copy()
    for _ in range(6):
        task.sleep(.2)
        task.next_frame()
        current = task.frame[:round(task.height*.88), :round(task.width*.63)]
        if current.shape == previous.shape and cv2.absdiff(current, previous).mean() < 1.5:
            return
        previous = current.copy()


def remember_avatar(task, name, card, page):
    # The level label is aligned toward the card's right edge. Crop inside
    # the artwork, excluding the level strip, selection border and team badge.
    cx = card.x + card.width / 2 - task.width * .015
    bottom = card.y - task.height * .012
    left, top = round(cx - task.width * .030), round(bottom - task.height * .105)
    width, height = round(task.width * .060), round(task.height * .105)
    if left < 0 or top < task.height * .10:
        return
    patch = task.frame[top:top + height, left:left + width].copy()
    if patch.shape[:2] != (height, width):
        return
    picture, metadata = cache_paths(name)
    picture.parent.mkdir(parents=True, exist_ok=True)
    if cv2.imwrite(str(picture), patch):
        metadata.write_text(json.dumps({'name': name, 'screen_width': task.width,
            'page': page, 'scroll_step': 4, 'center': [(left + width / 2) / task.width,
                                   (top + height / 2) / task.height]}, ensure_ascii=False))
        task.log_info(f'verified cultivation avatar remembered: {name}; page={page}')


def locate_avatar(frame, template, threshold=.89):
    """Return a unique portrait center in the roster pane, or no match."""
    h, w = frame.shape[:2]
    left, top, right, bottom = round(w*.02), round(h*.10), round(w*.63), round(h*.88)
    area = cv2.cvtColor(frame[top:bottom, left:right], cv2.COLOR_BGR2GRAY)
    patch = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    ph, pw = patch.shape
    # Normalize render sharpness before correlation. The game may reduce
    # internal resolution while the capture dimensions remain unchanged.
    area = cv2.GaussianBlur(area, (0, 0), 2)
    patch = cv2.GaussianBlur(patch, (0, 0), 2)
    if min(ph, pw) > 24:
        patch = patch[6:-6, 6:-6]
        ph, pw = patch.shape
    if ph > area.shape[0] or pw > area.shape[1] or patch.std() < 5:
        return None
    scores = cv2.matchTemplate(area, patch, cv2.TM_CCOEFF_NORMED)
    _, score, _, point = cv2.minMaxLoc(scores)
    if score < threshold:
        return None
    x, y = point
    # Ignore adjacent correlation peaks from the same portrait.
    scores[max(0,y-ph//2):y+ph//2+1, max(0,x-pw//2):x+pw//2+1] = -1
    if float(scores.max()) > score - .035:
        return None
    return (left + x + pw/2, top + y + ph/2), score


def select_cached_avatar(task, name, verify_name):
    picture, metadata = cache_paths(name)
    if not picture.exists() or not metadata.exists():
        return False
    try:
        data = json.loads(metadata.read_text())
        template = cv2.imread(str(picture))
        if data['name'] != name or template is None:
            return False
        scale = task.width / data['screen_width']
        if scale != 1:
            template = cv2.resize(template, None, fx=scale, fy=scale)
        def attempt():
            task.next_frame()
            match = locate_avatar(task.frame, template)
            if not match:
                return False
            point, score = match
            task.click(*point, name=f'{name}缓存头像', after_sleep=.5)
            verified = verify_name()
            names = getattr(task, '_cultivation_preview_names', [])
            labels = {'', '当期', '预告', '导电', '气动', '热熔', '冷凝', '衍射', '湮灭'}
            unreadable = bool(names) and all(n in labels for n in names)
            if verified or unreadable:
                task.log_info(f'cultivation avatar cache hit: {name}; score={score:.3f}; '
                              f'preview_verified={verified}; material-card check required')
                return True
            return False
        if attempt():
            return True
        scroll_roster(task, 100)
        # Inspect every small step. Old page hints were recorded with larger
        # wheel deltas and must not be replayed as blind jumps.
        for _ in range(32):
            if attempt():
                return True
            scroll_roster(task)
    except (OSError, ValueError, KeyError, cv2.error) as exc:
        task.log_info(f'cultivation avatar cache requires relearning: {name}: {exc}')
    return False
