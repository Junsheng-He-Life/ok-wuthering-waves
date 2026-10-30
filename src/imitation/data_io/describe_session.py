"""Record reproducibility metadata without importing the game controller."""

from datetime import datetime, timezone
import hashlib
import platform
from pathlib import Path
import subprocess
import sys

from src.imitation import SCHEMA_VERSION


def describe_session(root, task, source, config):
    """Return JSON metadata for a recording, including source hashes and Git state.

    Parameters are the repository path, a nonempty task string, source category
    (``human``, ``synthetic``, ``diagnostic``, or ``agent``), and a JSON-serializable
    configuration dict. Agent outcomes are visual reviews by the acting agent,
    not human annotations or automatically measured task rewards.
    Hashes cover available recording/export entry points and library sources.
    Diagnostic recordings hash the input-injection probe; agent recordings
    hash the bounded step-control entry point. This makes both action sources
    traceable. Git failures are recorded as unavailable; this function does
    not modify repositories.
    """
    root = Path(root).resolve()
    paths = [root / 'requirements.txt', root / 'profiles/macos-native-screen.json']
    paths += [root / 'scripts/record_imitation.py', root / 'scripts/export_imitation.py']
    if source == 'diagnostic':
        paths.append(root / 'scripts/probe_imitation_controls.py')
    elif source == 'agent':
        paths.append(root / 'scripts/step_imitation_game.py')
    paths += sorted((root / 'src/imitation').rglob('*.py'))
    paths += [root.parent / 'ok-script/ok/platform/macos/native_helper.swift']
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in paths if p.is_file()}
    repositories = {}
    for repository in (root, root.parent / 'ok-script'):
        def git(*args):
            try:
                return subprocess.check_output(
                    ['git', '-C', str(repository), *args], text=True,
                    stderr=subprocess.DEVNULL, timeout=5).strip()
            except (OSError, subprocess.SubprocessError):
                return None
        status = git('status', '--porcelain')
        repositories[str(repository)] = {
            'commit': git('rev-parse', 'HEAD'), 'dirty': bool(status) if status is not None else None,
            'status': status,
        }
    return {
        'schema_version': SCHEMA_VERSION, 'task': task, 'source': source,
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'python': sys.version, 'platform': platform.platform(), 'command': sys.argv,
        'config': config, 'repositories': repositories, 'source_sha256': hashes,
        'clock': 'Python time.monotonic_ns; observation availability and input callback time',
        'timing_limit': 'Frame receipt includes capture/transport latency; source timestamps are diagnostic.',
        'result_annotation': {'human': 'human_hotkey', 'synthetic': 'synthetic_fixture',
                              'diagnostic': 'integration_test_control',
                              'agent': 'agent_visual_review'}[source],
        'reserved_modifiers': ['control', 'option'],
        'mouse_units': 'Quartz event delta units; not screen pixels or calibrated camera degrees',
    }
