"""Read waveplate counters using their ordering, allowing dialog HUD shifts."""
import re


def find_waveplate_add_box(frame, boxes):
    """Locate the actual white plus beside one readable /240 badge.

    The badge anchors a small search region; a cross-shaped connected component
    confirms the input target. Never reuse an absolute screen coordinate.
    """
    import cv2
    import numpy as np
    from ok import Box
    badges = [b for b in boxes if re.fullmatch(
        r'[0-9]{1,4}[/／]240[+＋]?', re.sub(r'\s+', '', b.name))]
    if len(badges) != 1 or frame is None:
        return None
    badge = badges[0]
    h, w = frame.shape[:2]
    left = max(0, int(badge.x + badge.width - badge.height))
    right = min(w, int(badge.x + badge.width + badge.height * 3))
    top, bottom = max(0, int(badge.y - badge.height * .5)), min(h, int(badge.y + badge.height * 1.5))
    crop = frame[top:bottom, left:right]
    if not crop.size:
        return None
    mask = ((crop.min(axis=2) > 200) & (np.ptp(crop, axis=2) < 40)).astype('uint8')
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    candidates = []
    for x, y, cw, ch, area in stats[1:]:
        if not (.45 * badge.height <= ch <= 1.8 * badge.height and .8 <= cw/ch <= 1.25
                and .12 <= area/(cw*ch) <= .65):
            continue
        shape = mask[y:y+ch, x:x+cw]
        # Resampling can move the thin cross arm off the integer centerline.
        if (shape[max(0,ch//2-1):ch//2+2, :].mean(axis=1).max() >= .85
                and shape[:, max(0,cw//2-1):cw//2+2].mean(axis=0).max() >= .85
                and shape[:max(1,ch//4), :max(1,cw//4)].mean() < .15):
            candidates.append(Box(int(left+x), int(top+y), int(cw), int(ch), name='已核对波片补给加号'))
    return candidates[0] if len(candidates) == 1 else None


def parse_waveplates(boxes, width):
    numbers, fractions = [], []
    for box in boxes:
        name = re.sub(r'\s+', '', box.name)
        x = (box.x + box.width / 2) / width
        if not .4 <= x <= .91:
            continue
        fraction = re.fullmatch(r'([0-9]{1,4})[/／]240[+＋]?', name)
        if fraction:
            fractions.append((x, int(fraction[1])))
        elif re.fullmatch(r'[0-9]{1,4}', name):
            numbers.append((x, int(name)))
    if len(fractions) == 1:
        current_x, current = fractions[0]
        reserves = [value for x,value in numbers if .02 < current_x-x < .16]
        if len(reserves) == 1:
            return current, reserves[0], current+reserves[0]
    elif not fractions and len(numbers) == 2:
        (left,reserve),(right,current) = sorted(numbers)
        if .02 < right-left < .16 and right >= .74:
            return current, reserve, current+reserve
    return -1, -1, -1
