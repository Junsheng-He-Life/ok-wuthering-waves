"""Conservative healthy-bar corroboration for the calibrated right-hand team HUD.

Ratios are approximate. Hidden, dark, coloured or broken tracks return None;
this is a second visual signal, not a replacement for numeric HP.
"""
import numpy as np


def portrait_health(frame):
    if frame is None:
        return [None] * 3
    h, w = frame.shape[:2]
    left, right = round(w - h*.1486), round(w - h*.0792)
    readings = []
    for center in (.2674, .3903, .5118):
        y = round(h*center)
        rows = frame[max(0,y-2):y+3, left:right].astype(float)
        if rows.size == 0 or right-left < 30:
            readings.append(None)
            continue
        bright = (rows.min(axis=2) > 155) & (np.ptp(rows, axis=2) < 55)
        filled = bright.sum(axis=0) >= 2
        # Require a continuous neutral bright segment anchored at the left.
        if not filled[:5].mean() >= .8:
            readings.append(None)
            continue
        end = len(filled)
        for x in range(3, len(filled)-2):
            if not filled[x:x+3].any():
                end = x
                break
        if filled[:end].mean() < .9 or filled[end+3:].sum() > 3:
            readings.append(None)
            continue
        readings.append(round(end / len(filled), 3))
    return readings
