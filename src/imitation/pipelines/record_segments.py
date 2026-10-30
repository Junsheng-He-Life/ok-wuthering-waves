"""Segment observations using explicit outcome annotations with source provenance."""

import time


class RecordingController:
    """Accept timestamped input and frames from one queue consumer.

    A segment starts only after ``toggle`` and a neutral input snapshot.
    Focus loss, unknown input state, geometry changes, and stream stalls end
    it as interrupted. Success/failure are declared labels, not visual proof;
    their reason identifies human, synthetic, integration-test, or agent control.
    ``clock`` returns host monotonic nanoseconds; ``report`` receives status
    strings. Neither this class nor its writer sends input to the game.
    """

    def __init__(self, writer, *, clock=time.monotonic_ns, report=print):
        self.writer, self.clock, self.report = writer, clock, report
        self.segment_id = None
        self.segment_start = None
        self.pending = False
        self.stopped = False
        self.segment_count = 0
        self.last_frame_ns = None
        self.last_sequence = None
        self.geometry = None

    def event(self, event):
        """Store only active gameplay inputs and relevant lifecycle events."""
        kind = event['kind']
        if (self.segment_id is not None and event['t_ns'] < self.segment_start
                and kind in ('key', 'button', 'mouse_move', 'scroll')):
            # A key can change between the neutral snapshot and segment start.
            # Its queued event predates the start and would otherwise disappear
            # from action alignment, falsely labeling held input as neutral.
            self.writer.event({'kind': 'reset', 'reason': 'start_input_race',
                               't_ns': self.clock()})
            self.finish('interrupted', reason='start_input_race')
            return
        lifecycle = kind in ('focus', 'reset')
        if lifecycle or self.segment_id is not None:
            self.writer.event(event)
        interrupted = (kind == 'focus' and not event['active']
                       or kind == 'reset' and event.get('reason') != 'control_hotkey')
        if interrupted:
            self.pending = False
            self.finish('interrupted', event['t_ns'], event.get('reason', 'focus_lost'))

    def command(self, action, t_ns=None):
        """Handle controls and preserve the declared annotation source.

        For success/failure, ``writer.manifest.source`` is authoritative even
        when result_annotation is missing or inconsistent. Legacy writers
        without a source default to human; unknown explicit sources are errors.
        Controls do not independently verify that gameplay succeeded.
        """
        timestamp = self.clock() if t_ns is None else t_ns
        if action == 'toggle':
            if self.segment_id is not None:
                self.finish('unlabeled', timestamp, 'paused')
            else:
                self.pending = not self.pending
                self.report('等待游戏前台且松开所有按键/鼠标。' if self.pending else '已取消开始。')
        elif action in ('success', 'failure'):
            if self.segment_id is not None:
                source = getattr(self.writer, 'manifest', {}).get('source', 'human')
                reasons = {'human': 'human_annotation', 'synthetic': 'synthetic_fixture',
                           'diagnostic': 'integration_test_control', 'agent': 'agent_visual_review'}
                if source not in reasons:
                    raise ValueError(f'Unknown recording source: {source}')
                self.finish(action, timestamp, reasons[source])
            else:
                self.report('当前没有录制片段，结果标记未保存。')
        elif action == 'stop':
            self.pending = False
            self.finish('interrupted', timestamp, 'recorder_stopped')
            self.stopped = True
        else:
            raise ValueError(f'Unknown recording control: {action}')

    def maybe_start(self, snapshot, focused):
        """Start a pending segment only from a known neutral key/button state."""
        if not self.pending or not focused or snapshot['keys'] or snapshot['buttons']:
            return False
        self.segment_count += 1
        self.segment_id = f'episode_{self.segment_count:04d}'
        self.segment_start = self.clock()
        self.last_frame_ns = self.last_sequence = self.geometry = None
        self.pending = False
        self.writer.event({'kind': 'segment', 'action': 'start',
                           'segment_id': self.segment_id, 't_ns': self.segment_start})
        self.report(f'正在录制 {self.segment_id}；完成后请标记成功或失败。')
        return True

    def frame(self, sample):
        """Save a fresh observation only within the current uninterrupted segment."""
        if self.segment_id is None or sample['t_ns'] < self.segment_start:
            return False
        timestamp, sequence = sample['t_ns'], sample['sequence']
        if self.last_sequence is not None and sequence <= self.last_sequence:
            return False
        geometry = (sample['image'].shape, str(sample.get('geometry')))
        reason = None
        if self.last_frame_ns is not None and timestamp <= self.last_frame_ns:
            reason = 'nonmonotonic_frame'
        elif self.clock() - timestamp > 1_000_000_000:
            reason = 'stale_frame'
        elif self.geometry is not None and geometry != self.geometry:
            reason = 'geometry_changed'
        if reason:
            self.event({'kind': 'reset', 'reason': reason, 't_ns': self.clock()})
            return False
        self.writer.frame(sample, self.segment_id)
        self.last_frame_ns, self.last_sequence, self.geometry = timestamp, sequence, geometry
        return True

    def check_stall(self):
        """Interrupt an active segment after one second with no fresh frame."""
        last = self.last_frame_ns or self.segment_start
        if self.segment_id is not None and self.clock() - last > 1_000_000_000:
            self.event({'kind': 'reset', 'reason': 'capture_stalled', 't_ns': self.clock()})

    def finish(self, outcome, t_ns=None, reason=''):
        """End the active segment; an unannotated stop stays interrupted/unlabeled."""
        if self.segment_id is None:
            return
        timestamp = self.clock() if t_ns is None else t_ns
        self.writer.event({'kind': 'segment', 'action': 'end', 'segment_id': self.segment_id,
                           't_ns': timestamp, 'outcome': outcome, 'reason': reason})
        self.report(f'{self.segment_id} 已结束：{outcome} ({reason})')
        self.segment_id = self.segment_start = None
