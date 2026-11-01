"""Locate complete material cards in pixels before reading their counters."""
import re
from dataclasses import dataclass

import cv2
from ok import Box

from src.task.MaterialImageOCR import read_enlarged_region


class MaterialPageReadError(RuntimeError):
    """A page observation may be retried without navigating or spending."""


@dataclass(frozen=True)
class MaterialTile:
    x: int
    y: int
    width: int
    height: int

    def icon(self, frame):
        # Keep the artwork and rarity background, excluding the changing
        # stock fraction at the bottom. OCR boxes never define this crop.
        return frame[self.y+round(self.height*.06):self.y+round(self.height*.72),
                     self.x+round(self.width*.08):self.x+round(self.width*.92)].copy()

    def counter_box(self):
        return Box(self.x, self.y+round(self.height*.73), self.width,
                   round(self.height*.27))


def material_tiles(frame):
    """Find dark square cards inside the cultivation list's light rows.

    Reject clipped or non-square components. This detector proposes card
    geometry only; a verified artwork match or item popup supplies identity.
    """
    height, width = frame.shape[:2]
    left, top = round(width*.55), round(height*.15)
    region = frame[top:round(height*.94), left:round(width*.82)]
    mask = cv2.inRange(cv2.cvtColor(region, cv2.COLOR_BGR2GRAY), 0, 150)
    size = max(1, round(height/360))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                          cv2.getStructuringElement(cv2.MORPH_RECT, (size, size)))
    result = []
    for contour in cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        x, y, w, h = cv2.boundingRect(contour)
        if (x <= 0 or y <= 0 or x+w >= region.shape[1] or y+h >= region.shape[0]):
            continue
        if (.035*width < w < .065*width and .065*height < h < .11*height
                and .75 < w/h < 1.25 and cv2.contourArea(contour)/(w*h) > .65):
            result.append(MaterialTile(x+left, y+top, w, h))
    return sorted(result, key=lambda tile: (tile.y, tile.x))


def counters_for_row(task, row, tiles, frame):
    height = frame.shape[0]
    selected = [tile for tile in tiles
                if abs(tile.y+tile.height/2-(row.y+row.height/2)) < .035*height]
    result = []
    for tile in sorted(selected, key=lambda t: t.x):
        rows = read_enlarged_region(task, tile.counter_box(), contrast=True, frame=frame)
        values = [re.sub(r'\s+', '', r.name) for r in rows]
        values = [v for v in values if re.fullmatch(r'\d{1,7}[/／]\d{1,7}', v)]
        if len(values) != 1:
            raise MaterialPageReadError(f'材料卡片数量未唯一确认：{values}')
        box = Box(tile.x+tile.width//2, row.y+round(.03*task.width), 1, 1, name=values[0])
        box.material_tile = tile
        result.append(box)
    return result


def verify_material_rows(task, boxes, tiles, labels, frame):
    """Recover a missing row heading, never skip a visible material card.

    Cards below the explicit echo-cultivation heading belong to another
    section and are intentionally excluded from material requirements.
    """
    height, width = frame.shape[:2]
    footer = min((b.y for b in boxes if b.name.strip() == '声骸培养'), default=height)
    for tile in tiles:
        if tile.y >= footer:
            continue
        if any(b.name.strip() in labels and .25*width < b.x < .65*width
               and abs(tile.y+tile.height/2-(b.y+b.height/2)) < .035*height for b in boxes):
            continue
        box = Box(round(.37*width), tile.y, round(.28*width), tile.height)
        readings = read_enlarged_region(task, box, frame=frame)
        headings = [b for b in readings if b.name.strip() in labels]
        if len(headings) != 1:
            raise MaterialPageReadError('可见材料卡片的类别未确认，禁止漏过该需求')
        boxes.extend(headings)
    return boxes
