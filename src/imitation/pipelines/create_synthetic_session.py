"""Exercise storage and action alignment without observing a real application."""

import numpy as np

from src.imitation.pipelines.record_segments import RecordingController


def create_synthetic_session(writer):
    """Write two synthetic episodes (one success, one failure) with short taps.

    This fixture tests the recorder/exporter contract only. Images are artificial
    and the manifest must say ``source=synthetic`` to prevent accidental training
    claims. All event/frame timestamps share a synthetic monotonic nanosecond axis.
    """
    if writer.manifest.get('source') != 'synthetic':
        raise ValueError('Synthetic fixtures require source=synthetic')
    now = [1_000_000_000]
    control = RecordingController(writer, clock=lambda: now[0])
    sequence = 0
    for outcome in ('success', 'failure'):
        control.command('toggle')
        control.maybe_start({'keys': [], 'buttons': []}, True)
        for index in range(12):
            now[0] += 66_666_667
            if index == 3:
                control.event({'t_ns': now[0] - 40_000_000, 'kind': 'key', 'code': 13, 'down': True})
                control.event({'t_ns': now[0] - 10_000_000, 'kind': 'key', 'code': 13, 'down': False})
            control.event({'t_ns': now[0] - 1, 'kind': 'mouse_move', 'dx': 2.0, 'dy': -1.0})
            frame = np.zeros((180, 320, 3), dtype=np.uint8)
            frame[60:90, 20 + index * 10:50 + index * 10] = (60, 210, 240)
            control.frame({'image': frame, 't_ns': now[0], 'sequence': sequence,
                           'source_t_ns': now[0] - 2_000_000, 'clock': 'synthetic'})
            sequence += 1
        now[0] += 10_000_000
        control.command(outcome)
        now[0] += 500_000_000
