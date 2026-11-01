"""Identify material icons only from names verified in an item-detail popup."""
import hashlib
import json
import re
from pathlib import Path

import cv2
import numpy as np


def material_key(name):
    return hashlib.sha256(name.encode('utf-8')).hexdigest()[:16]


def normalize_name(value):
    return re.sub(r'\s+', '', value).strip('·:：')


def popup_identity(rows, height):
    """Require both a plausible title and an explicit inventory in the popup."""
    candidates = [(b.y, normalize_name(b.name)) for b in rows
              if .10 * height < b.y < .215 * height
              and re.search(r'[\u4e00-\u9fff]', b.name)]
    candidates = [(y, s) for y, s in candidates if not any(w in s for w in
                  ('培养', '所需', '前往', '拥有', '获取', '背包', '品质'))]
    top = min((y for y, _ in candidates), default=0)
    titles = [s for y, s in candidates if y < top + .015 * height]
    inventory = re.findall(r'拥有[：:]?(\d+)', normalize_name(''.join(b.name for b in rows)))
    if len(titles) != 1 or len(inventory) != 1:
        raise RuntimeError(f'物品详情中的名称或拥有数量未唯一确认：标题={titles}，库存={inventory}')
    return titles[0], int(inventory[0])


class MaterialIconLibrary:
    """Persist appearance/name evidence; inventory is always read live."""
    def __init__(self, folder='configs/macos-desktop/material-identities', geometry_version=None):
        self.folder = Path(folder)
        self.geometry_version = geometry_version
        self.folder.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def normalized(icon):
        if icon is None or icon.size == 0 or min(icon.shape[:2]) < 16:
            raise ValueError('材料图标裁图无效')
        return cv2.resize(icon, (64, 64), interpolation=cv2.INTER_AREA)

    def match(self, icon):
        candidate = self.normalized(icon)
        matches = []
        for path in self.folder.glob('*.json'):
            try:
                meta = json.loads(path.read_text())
                if not isinstance(meta, dict) or meta.get('source') != 'verified_item_popup' or not meta.get('name'):
                    continue
                if self.geometry_version is not None and meta.get('geometry_version') != self.geometry_version:
                    continue
                reference = cv2.imread(str(path.with_suffix('.png')))
                reference = self.normalized(reference)
            except (OSError, ValueError, TypeError):
                continue
            # Counter OCR can shift the icon crop by a few pixels between
            # pages. Align the inner image without relaxing identity thresholds.
            inner = candidate[4:-4, 4:-4]
            scores = cv2.matchTemplate(reference, inner, cv2.TM_CCOEFF_NORMED)
            _, score, _, (x, y) = cv2.minMaxLoc(scores)
            aligned = reference[y:y+inner.shape[0], x:x+inner.shape[1]]
            error = float(np.mean(np.abs(inner.astype(float) - aligned.astype(float))))
            if np.isfinite(score):
                matches.append((score, error, meta['name']))
        matches.sort(reverse=True)
        if not matches or matches[0][0] < .97 or matches[0][1] > 10:
            return None
        if len(matches) > 1 and matches[0][0] - matches[1][0] < .035:
            return None
        return matches[0][2]

    def remember(self, name, icon, evidence):
        if not name or not evidence:
            raise ValueError('材料名称必须有物品详情证据')
        key = material_key(name)
        if not cv2.imwrite(str(self.folder / (key + '.png')), self.normalized(icon)):
            raise OSError('无法保存材料识别图标')
        metadata = {'name': name, 'source': 'verified_item_popup', 'evidence': str(evidence),
                    'geometry_version': self.geometry_version}
        (self.folder / (key + '.json')).write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
        display = self.folder.parent / 'material-icons'
        display.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(display / (key + '.png')), icon)


def named_job_key(job):
    """Material names, not row positions, identify a requirement across rescans."""
    names = tuple(job.get('material_names') or [])
    return (job.get('target'), names) if names else (job.get('target'), 'unidentified', job.get('kind'), job.get('repeat', 0))


def aggregate_named_materials(jobs):
    from src.task.SharedMaterialInventory import summarize_shared_inventory
    items, unknown = [], []
    for job in jobs:
        if job.get('superseded'):
            continue
        names, counts = job.get('material_names') or [], job.get('material_counts') or []
        if not names or len(names) != len(counts) or not all(names):
            unknown.append({'target': job.get('target'), 'reason': job.get('deferred_reason') or '材料图标与名称待核对'})
            continue
        items.extend({'target': job['target'], 'item_name': name, 'inventory': count[0], 'required': count[1]}
                     for name, count in zip(names, counts))
    materials = summarize_shared_inventory(items)
    for material in materials:
        name = material['item_name']
        timestamps = [job.get('inventory_observed_at', {}).get(name) or job.get('observed_at')
                      for job in jobs if not job.get('superseded') and name in (job.get('material_names') or [])]
        material['inventory_observed_at'] = min((stamp for stamp in timestamps if stamp), default=None)
        material['notes'] = list(dict.fromkeys(job['deferred_reason'] for job in jobs
            if not job.get('superseded') and material['item_name'] in (job.get('material_names') or [])
            and job.get('deferred_reason')))
    return materials, unknown


def refresh_named_jobs(queued, fresh):
    """Keep queue indices stable while admitting newly visible material sets."""
    remaining = {named_job_key(job): job for job in fresh}
    for old in queued:
        key = named_job_key(old)
        if key in remaining:
            old.clear()
            old.update(remaining.pop(key))
        else:
            old.update(satisfied=True, superseded=True, completion_reason='本次完整扫描已无此材料组合')
    queued.extend(remaining.values())
    return queued
