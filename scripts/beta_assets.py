"""Export only annotated recognition pixels, excluding personal screenshot context."""
import hashlib
import json
from pathlib import Path, PurePosixPath


def safe_relative(value):
    relative = PurePosixPath(value)
    if relative.is_absolute() or '..' in relative.parts or '\\' in value:
        raise ValueError(f'Unsafe resource path: {value}')
    return relative


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def export_recognition_assets(source, destination):
    """Preserve every runtime template ROI exactly; omit other source pixels.

    Original image dimensions and annotation coordinates are retained because
    the runtime uses them for viewport scaling. The export is derived recognition
    data, not a copy of the player's full screenshots or PNG metadata.
    """
    import numpy as np
    from PIL import Image, PngImagePlugin

    source, destination = Path(source), Path(destination)
    data = json.loads((source / 'coco_annotations.json').read_text())
    images = {row['id']: row for row in data['images']}
    grouped = {}
    for row in data['images']:
        safe_relative(row['file_name'])
        grouped.setdefault(row['file_name'], [])
    for annotation in data['annotations']:
        image = images[annotation['image_id']]
        grouped[image['file_name']].append(annotation)
    evidence = []
    for relative, annotations in sorted(grouped.items()):
        path = source / relative
        if path.is_symlink() or not path.resolve().is_relative_to(source.resolve()):
            raise ValueError(f'Symlink/resource escape: {relative}')
        with Image.open(path) as original:
            pixels = np.asarray(original.convert('RGB'))
            compression_flag = original.info.get('ok_compressed')
        height, width = pixels.shape[:2]
        mask = np.zeros((height, width), dtype=bool)
        for annotation in annotations:
            x, y, w, h = annotation['bbox']
            x0, y0, x1, y1 = round(x), round(y), round(x + w), round(y + h)
            if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
                raise ValueError(f'Invalid template bounds: {relative}: {annotation["bbox"]}')
            # Existing game UID locations are outside all production ROIs. If
            # that changes, require review rather than publishing that region.
            if x1 > width * .8 and y1 > height * .975:
                raise ValueError(f'Template overlaps account-ID area; review required: {relative}')
            mask[y0:y1, x0:x1] = True
        exported = np.zeros_like(pixels)
        exported[mask] = pixels[mask]
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        metadata = PngImagePlugin.PngInfo()
        if compression_flag is not None:
            metadata.add_text('ok_compressed', str(compression_flag))
        Image.fromarray(exported).save(target, pnginfo=metadata, optimize=True)
        with Image.open(target) as check:
            actual = np.asarray(check.convert('RGB'))
        if not np.array_equal(actual[mask], pixels[mask]) or np.any(actual[~mask]):
            raise ValueError(f'Exported template pixels failed verification: {relative}')
        evidence.append({'path': 'assets/' + relative, 'source_sha256': sha256(path),
                         'sha256': sha256(target), 'recognition_pixels': int(mask.sum()),
                         'source_pixels': int(mask.size), 'roi_pixels_identical': True})
    clean = {
        'info': {'description': 'Beta recognition templates; only annotated pixels retained'},
        'licenses': data.get('licenses', []),
        'categories': [{k: row[k] for k in ('id', 'name', 'supercategory') if k in row}
                       for row in data['categories']],
        'images': [{k: row[k] for k in ('id', 'file_name', 'width', 'height', 'license') if k in row}
                   for row in data['images']],
        'annotations': [{k: row[k] for k in ('id', 'image_id', 'category_id', 'bbox', 'area', 'iscrowd') if k in row}
                        for row in data['annotations']],
    }
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'coco_annotations.json').write_text(json.dumps(clean, ensure_ascii=False, indent=2) + '\n')
    return evidence
