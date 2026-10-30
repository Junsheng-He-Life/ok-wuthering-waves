"""Verify the completed writer's checksums before trusting session records.

Checksums detect changed or truncated data relative to the recorder's finalized
manifest. They are integrity checks, not signatures authenticating who recorded
the data. Image validity originates in SessionWriter's checked JPEG encoder;
this offline reader deliberately does not import a native imaging library.
"""

import hashlib
import json
from pathlib import Path
import string

from src.imitation import SCHEMA_VERSION


def sha256_file(path):
    """Return a lowercase SHA-256 hex digest of a readable binary file."""
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _reject_constant(value):
    raise ValueError(f'Non-finite JSON constant is not permitted: {value}')


def _declared_digest(value, field):
    if not isinstance(value, str) or len(value) != 64 or any(c not in string.hexdigits for c in value):
        raise ValueError(f'{field} must declare a 64-character SHA-256 digest')
    return value.lower()


def _read_index(root, name, declared, expected_count):
    if type(expected_count) is not int or expected_count < 0:
        raise ValueError(f'{name}: manifest record count must be a nonnegative integer')
    expected_hash = _declared_digest(declared, f'manifest.index_sha256[{name}]')
    payload = (root / name).read_bytes()
    actual_hash = hashlib.sha256(payload).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError(f'{name}: SHA-256 mismatch; index changed after recording')
    rows = []
    for line_number, line in enumerate(payload.decode('utf-8').splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line, parse_constant=_reject_constant)
        except json.JSONDecodeError as exc:
            raise ValueError(f'{name}:{line_number}: invalid JSON') from exc
        if not isinstance(row, dict):
            raise ValueError(f'{name}:{line_number}: expected an object')
        rows.append(row)
    if len(rows) != expected_count:
        raise ValueError(f'{name}: record count mismatch; manifest={expected_count}, actual={len(rows)}')
    return rows, actual_hash


def _resolve_images(root, frames):
    images = {}
    for frame in frames:
        relative = frame.get('image')
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            raise ValueError('Frame image must be a relative session path')
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or '..' in Path(relative).parts:
            raise ValueError(f'Frame image escapes the session: {relative!r}')
        expected = _declared_digest(frame.get('image_sha256'), f'{relative}: image_sha256')
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f'Missing or empty frame image: {path}')
        if relative not in images:
            images[relative] = dict(path=str(path), sha256=sha256_file(path))
        if images[relative]['sha256'] != expected:
            raise ValueError(f'{relative}: SHA-256 mismatch; image changed after recording')
    return images


def load_verified_session(root, *, allow_synthetic=False, allow_diagnostic=False,
                          allow_agent=False):
    """Read and integrity-check one finalized schema-compatible recording.

    ``root`` is a session directory. Return ``(manifest, frames, events, images,
    index_hashes)``; images map relative paths to resolved paths and checked
    SHA-256 values. ``index_hashes`` also includes the exact manifest bytes read.
    All sources must declare frame/event counts, index hashes, and a hash for
    every image. Synthetic, diagnostic, and agent-controlled sessions require
    separate explicit opt-ins. Missing declarations, mismatches,
    unfinished sessions, path escapes, or malformed data raise ValueError;
    unreadable files raise OSError. No output is created by this function.
    """
    root = Path(root).expanduser().resolve()
    payload = (root / 'manifest.json').read_bytes()
    manifest = json.loads(payload, parse_constant=_reject_constant)
    if not isinstance(manifest, dict) or manifest.get('schema_version') != SCHEMA_VERSION:
        raise ValueError(f'{root}: unsupported session schema')
    if manifest.get('status') != 'complete':
        raise ValueError(f'{root}: session must be complete before export')
    for field in ('session_id', 'task'):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            raise ValueError(f'{root}: {field} must be a nonempty string')
    if not isinstance(manifest.get('config'), dict):
        raise ValueError(f'{root}: config must be an object')
    if manifest.get('source') not in ('human', 'synthetic', 'diagnostic', 'agent'):
        raise ValueError(f'{root}: source must be human, synthetic, diagnostic, or agent')
    if manifest['source'] == 'synthetic' and not allow_synthetic:
        raise ValueError('Synthetic sessions require explicit allow_synthetic=True')
    if manifest['source'] == 'diagnostic' and not allow_diagnostic:
        raise ValueError('Diagnostic sessions require explicit allow_diagnostic=True')
    if manifest['source'] == 'agent' and not allow_agent:
        raise ValueError('Agent sessions require explicit allow_agent=True')
    declared = manifest.get('index_sha256')
    if not isinstance(declared, dict):
        raise ValueError('manifest.index_sha256 must declare both index checksums')
    frames, frame_hash = _read_index(root, 'frames.jsonl', declared.get('frames.jsonl'), manifest.get('frame_count'))
    events, event_hash = _read_index(root, 'events.jsonl', declared.get('events.jsonl'), manifest.get('event_count'))
    images = _resolve_images(root, frames)
    hashes = {'manifest.json': hashlib.sha256(payload).hexdigest(),
              'frames.jsonl': frame_hash, 'events.jsonl': event_hash}
    return manifest, frames, events, images, hashes
