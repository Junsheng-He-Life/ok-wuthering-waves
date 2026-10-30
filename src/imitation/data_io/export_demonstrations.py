"""Validate recorded sessions and export portable action-label metadata.

This data-I/O boundary never imports GUI, capture, or native input libraries.
Images remain in their original sessions; samples contain resolved paths and
an image hash manifest detects subsequent changes to those source files.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

from src.imitation import SCHEMA_VERSION
from src.imitation.data_io.validate_session import load_verified_session, sha256_file
from src.imitation.scientific_core.align_actions import align_actions


def _code_revision():
    root = Path(__file__).resolve().parents[3]
    try:
        commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root,
                                capture_output=True, text=True, timeout=5, check=True)
        status = subprocess.run(['git', 'status', '--porcelain'], cwd=root,
                                capture_output=True, text=True, timeout=5, check=True)
        return dict(commit=commit.stdout.strip(), dirty=bool(status.stdout))
    except (OSError, subprocess.SubprocessError):
        return dict(commit=None, dirty=None)


def session_split(session_id, seed=0):
    """Return a deterministic 80/10/10 train/val/test assignment by session.

    SHA-256 of UTF-8 ``seed + NUL + session_id`` supplies an unsigned integer;
    its remainder modulo 100 defines the bucket. Individual frames are never
    independently randomized, and the same seed/session always maps identically.
    """
    if type(seed) is not int:
        raise ValueError('seed must be an integer')
    bucket = int.from_bytes(hashlib.sha256(f'{seed}\0{session_id}'.encode()).digest()[:8], 'big') % 100
    return 'train' if bucket < 80 else ('val' if bucket < 90 else 'test')


def export_demonstrations(session_paths, output_dir, *, max_gap_ms=250, seed=0,
                          outcomes=('success',), allow_synthetic=False,
                          allow_diagnostic=False, allow_agent=False):
    """Write a new dataset directory and return its JSON-serializable summary.

    ``session_paths`` contains completed session directories matching the
    package SCHEMA_VERSION. ``output_dir`` must not exist. Declared index and
    image hashes plus record counts are verified before alignment;
    output consists of samples.jsonl, frame-hashes.jsonl, and dataset.json.
    Samples use absolute image paths, so moving source sessions requires a new
    export. Outcomes are declared annotations, not independently verified rewards.
    Native presentation timestamps are retained only in source data: alignment
    uses observation availability/callback times in Python monotonic nanoseconds.

    All sessions are validated before any output is created. Missing images,
    path escapes, duplicate session IDs, unfinished captures, or malformed
    records raise ValueError (or OSError for unreadable files). Synthetic,
    diagnostic, and agent-controlled data require separate explicit opt-ins
    and remain marked in every sample and in the summary.
    An empty export is valid but explicitly has status ``empty``.
    """
    output = Path(output_dir).expanduser().resolve()
    if output.exists():
        raise FileExistsError(f'Output already exists: {output}')
    roots = [Path(path).expanduser().resolve() for path in session_paths]
    if not roots:
        raise ValueError('At least one session is required')
    all_samples, sources, image_hashes, seen = [], [], [], set()
    outcomes = tuple(outcomes)
    for root in roots:
        manifest, frames, events, images, source_hashes = load_verified_session(
            root, allow_synthetic=allow_synthetic, allow_diagnostic=allow_diagnostic,
            allow_agent=allow_agent)
        ident = manifest['session_id']
        if ident in seen:
            raise ValueError(f'Duplicate session_id: {ident}')
        seen.add(ident)
        samples, quality = align_actions(frames, events, max_gap_ms=max_gap_ms, outcomes=outcomes)
        split = session_split(ident, seed)
        for sample in samples:
            sample.update(session_id=ident, task=manifest['task'],
                          source=manifest['source'], split=split,
                          result_annotation=manifest.get('result_annotation', 'unspecified'))
            sample['image'] = images[sample['image']]['path']
            sample['next_image'] = images[sample['next_image']]['path']
        all_samples.extend(samples)
        sources.append(dict(session_id=ident, root=str(root), split=split,
                            source=manifest['source'], task=manifest['task'],
                            result_annotation=manifest.get('result_annotation', 'unspecified'),
                            config=manifest['config'], quality=quality,
                            hashes=source_hashes))
        image_hashes.extend(dict(session_id=ident, image=relative, **details)
                            for relative, details in sorted(images.items()))
    summary = dict(schema_version=SCHEMA_VERSION, status='exported' if all_samples else 'empty',
                   created_utc=datetime.now(timezone.utc).isoformat(),
                   alignment_clock='python_monotonic_ns_observation_availability',
                   mouse_units='raw_quartz_relative_delta',
                   contains_synthetic=any(s['source'] == 'synthetic' for s in sources),
                   contains_diagnostic=any(s['source'] == 'diagnostic' for s in sources),
                   contains_agent=any(s['source'] == 'agent' for s in sources),
                   config=dict(seed=seed, max_gap_ms=max_gap_ms, outcomes=list(outcomes),
                               allow_synthetic=allow_synthetic, allow_diagnostic=allow_diagnostic,
                               allow_agent=allow_agent, split_percent=[80, 10, 10]),
                   environment=dict(python=sys.version, platform=platform.platform()),
                   exporter_revision=_code_revision(),
                   accepted=len(all_samples), sources=sources,
                   split_counts={name: sum(s['split'] == name for s in all_samples)
                                 for name in ('train', 'val', 'test')})
    output.mkdir(parents=True, exist_ok=False)
    for name, rows in (('samples.jsonl', all_samples), ('frame-hashes.jsonl', image_hashes)):
        with (output / name).open('x', encoding='utf-8') as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')
    summary['artifact_hashes'] = {name: sha256_file(output / name)
                                  for name in ('samples.jsonl', 'frame-hashes.jsonl')}
    (output / 'dataset.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    return summary
