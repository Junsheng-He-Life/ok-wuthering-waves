"""Enlarge small material text while retaining original-frame coordinates."""
import cv2


def read_enlarged_region(task, box, *, contrast=False, frame=None):
    source = task.frame if frame is None else frame
    image = source[box.y:box.y+box.height, box.x:box.x+box.width]
    if contrast:
        image = cv2.cvtColor(image.max(axis=2), cv2.COLOR_GRAY2BGR)
    image = cv2.resize(image, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    image = cv2.copyMakeBorder(image, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=(0, 0, 0))
    # BaseTask.target_height only downsamples. Explicit enlargement must map
    # recognized boxes back; frame_processor alone cannot communicate scaling.
    rows = task.ocr(frame=image, threshold=.8)
    for row in rows:
        row.x = box.x + round((row.x - 20) / 3)
        row.y = box.y + round((row.y - 20) / 3)
        row.width = round(row.width / 3)
        row.height = round(row.height / 3)
    return rows
