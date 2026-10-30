"""Append JPEG observations and JSONL actions to one new demonstration session."""

import hashlib
import json
from pathlib import Path
import time

from src.imitation import SCHEMA_VERSION


class SessionLimitReached(RuntimeError):
    """The configured disk budget would be exceeded by another record."""


class SessionWriter:
    """Write one session from a single consumer thread; never overwrite a run.

    ``directory`` must not exist. ``manifest`` contains task/source/config.
    Frames are uint8 BGR arrays (height, width, 3), optionally downscaled to
    ``max_width`` pixels. JSONL times are absolute host monotonic nanoseconds.
    ``max_bytes`` bounds the JPEG/JSONL payload, excluding small metadata files.
    Only explicit segment-end events describe outcomes; saving a frame or an
    input event is never evidence of successful gameplay.
    """

    def __init__(self, directory, manifest, *, max_width=1280, quality=85,
                 max_bytes=2 * 1024 ** 3):
        if max_width < 64 or not 1 <= quality <= 100 or max_bytes < 1024:
            raise ValueError('Invalid image settings or recording byte budget')
        # Load the image backend before a live segment starts. Its first import
        # can otherwise delay the first observation enough to mimic a stream stall.
        import cv2
        self._cv2 = cv2
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=False)
        (self.directory / 'frames').mkdir()
        self.manifest = dict(manifest, schema_version=SCHEMA_VERSION,
                             session_id=self.directory.name, status='recording')
        self.max_width, self.quality, self.max_bytes = max_width, quality, max_bytes
        self.bytes_written = 0
        self.frame_count = 0
        self.event_count = 0
        self.closed = False
        self._events = (self.directory / 'events.jsonl').open('x', encoding='utf-8')
        self._frames = (self.directory / 'frames.jsonl').open('x', encoding='utf-8')
        self._save_manifest()

    def _save_manifest(self):
        path = self.directory / 'manifest.json'
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.manifest, ensure_ascii=False, indent=2) + '\n',
                             encoding='utf-8')
        temporary.replace(path)

    def _append(self, handle, record):
        if self.closed:
            raise RuntimeError('Session is closed')
        line = json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n'
        size = len(line.encode('utf-8'))
        if self.bytes_written + size > self.max_bytes:
            raise SessionLimitReached('Recording reached its byte budget')
        handle.write(line)
        handle.flush()
        self.bytes_written += size

    def event(self, event):
        """Append a JSON event with a nonnegative integer ``t_ns`` timestamp."""
        timestamp = event.get('t_ns')
        if type(timestamp) is not int or timestamp < 0 or not event.get('kind'):
            raise ValueError('Events require kind and a nonnegative integer t_ns')
        self._append(self._events, event)
        self.event_count += 1

    def frame(self, sample, segment_id):
        """Save a fresh frame and its geometry; return its JSON index record.

        ``sample`` supplies image/t_ns/sequence and optional native timing and
        crop metadata. Timestamp assignment precedes encoding, so JPEG latency
        cannot move action labels. This writer does not infer a segment.
        """
        cv2 = self._cv2
        import numpy as np
        image = sample['image']
        if (not isinstance(image, np.ndarray) or image.dtype != np.uint8
                or image.ndim != 3 or image.shape[2] != 3 or min(image.shape[:2]) < 1):
            raise ValueError('Expected a nonempty uint8 BGR image')
        if type(sample['t_ns']) is not int or sample['t_ns'] < 0:
            raise ValueError('Frame t_ns must be a nonnegative integer')
        source_h, source_w = image.shape[:2]
        if source_w > self.max_width:
            image = cv2.resize(image, (self.max_width, max(1, round(source_h * self.max_width / source_w))),
                               interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, self.quality])
        if not ok:
            raise OSError('JPEG encoding failed')
        payload = encoded.tobytes()
        record = {k: v for k, v in sample.items() if k != 'image'}
        record.update(frame_id=self.frame_count, segment_id=segment_id,
                      image=f'frames/{self.frame_count:08d}.jpg',
                      source_size=[source_w, source_h], saved_size=[image.shape[1], image.shape[0]],
                      image_sha256=hashlib.sha256(payload).hexdigest())
        index_size = len((json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8'))
        if self.bytes_written + len(payload) + index_size > self.max_bytes:
            raise SessionLimitReached('Recording reached its byte budget')
        if self.closed:
            raise RuntimeError('Session is closed')
        (self.directory / record['image']).write_bytes(payload)
        self.bytes_written += len(payload)
        self._append(self._frames, record)
        self.frame_count += 1
        return record

    def close(self, status='complete', reason=''):
        """Flush indexes and atomically finalize metadata, idempotently."""
        if self.closed:
            return
        if status not in ('complete', 'error', 'interrupted'):
            raise ValueError('Invalid final session status')
        self._events.close()
        self._frames.close()
        self.closed = True
        self.manifest.update(status=status, reason=reason, ended_ns=time.monotonic_ns(),
                             frame_count=self.frame_count, event_count=self.event_count,
                             payload_bytes=self.bytes_written)
        self.manifest['index_sha256'] = {
            name: hashlib.sha256((self.directory / name).read_bytes()).hexdigest()
            for name in ('frames.jsonl', 'events.jsonl')}
        self._save_manifest()
