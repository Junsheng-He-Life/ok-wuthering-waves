"""Read waveplate counters using their ordering, allowing dialog HUD shifts."""
import re


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
