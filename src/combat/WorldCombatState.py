"""Temporal combat decisions from local, timestamped visual observations.

All times are monotonic seconds. Missing enemy bars are not evidence of a kill:
they only change an active encounter to ``occluded``. A drop or an echo belongs
to one enemy and can request confirmation, but cannot close a whole encounter.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class WorldObservation:
    sequence: int
    captured_at: float
    hud_visible: bool | None
    enemy_visible: bool
    portrait_ratios: tuple = (None, None, None)
    # Evidence is independently timestamped when a slower recognizer is used.
    events: tuple = ()
    event_sequence: int | None = None
    event_captured_at: float | None = None
    event_scan_complete: bool = True


class WorldCombatState:
    """Use hysteresis without turning uncertainty into a successful battle.

    Two distinct positive frames, at least 100 ms apart, establish start. End
    needs two fresh observations of a newly appearing encounter-wide success
    signal plus at least 500 ms of visible HUD without enemy bars or HP loss.
    ``kill_candidate`` and ``reward_candidate`` events never establish end.
    The caller serializes access; the state machine never reads pixels or acts.
    """

    def __init__(self, *, max_age=.6, start_seconds=.1, end_seconds=.5):
        self.max_age, self.start_seconds, self.end_seconds = max_age, start_seconds, end_seconds
        self.state, self.reason = 'idle', 'no_combat_observed'
        self.last_sequence, self.last_capture = -1, None
        self.started_at = self.start_candidate = self.clear_since = None
        self.last_health = (None, None, None)
        self.baseline_events, self.seen_events = set(), set()
        self.baseline_ready = False
        self.end_events = set()
        self.end_label = None
        self.kill_candidate = False
        self.observations = self.transitions = 0
        self.last_gap = self.max_gap = 0.

    def _set(self, state, reason):
        if state != self.state:
            self.transitions += 1
        self.state, self.reason = state, reason

    def _clear_end(self):
        self.clear_since = None
        self.end_events.clear()
        self.end_label = None
        self.kill_candidate = False

    def observe(self, observation, now):
        """Ignore duplicated/out-of-order/stale frames, including their events."""
        o = observation
        if (o.sequence <= self.last_sequence or not 0 <= now - o.captured_at <= self.max_age
                or self.last_capture is not None and o.captured_at <= self.last_capture):
            return self.snapshot(now)
        if self.last_capture is not None:
            self.last_gap = o.captured_at - self.last_capture
            self.max_gap = max(self.max_gap, self.last_gap)
            if self.last_gap > self.max_age:
                self.start_candidate = None
                self._clear_end()
        self.last_sequence, self.last_capture = o.sequence, o.captured_at
        self.observations += 1
        damaged = any(a is not None and b is not None and a - b >= .06
                      for a, b in zip(self.last_health, o.portrait_ratios))
        self.last_health = o.portrait_ratios
        events = self._fresh_events(o, now)
        if (events is not None and o.event_scan_complete and
                (self.started_at is None or o.event_captured_at <= self.started_at)):
            self.baseline_ready = True
            self.baseline_events.update(label for label, _ in events)
        events = events or ()
        if self.started_at is None:
            if o.hud_visible is True and o.enemy_visible:
                if self.start_candidate is None:
                    self.start_candidate = o.captured_at
                self._set('starting', 'enemy_bar_with_world_hud')
                if o.captured_at - self.start_candidate >= self.start_seconds:
                    self.started_at = o.captured_at
                    self._set('fighting', 'enemy_confirmed_on_distinct_frames')
            else:
                self.start_candidate = None
                self._set('idle', 'no_confirmed_start')
            return self.snapshot(now)
        if o.hud_visible is not True:
            self._clear_end()
            self._set('unknown', 'hud_hidden_or_unreadable')
        elif o.enemy_visible or damaged:
            self._clear_end()
            self._set('fighting', 'enemy_visible' if o.enemy_visible else 'team_hp_decreased')
        elif self.state != 'ended':
            if self.clear_since is None:
                self.clear_since = o.captured_at
            for label, scope in events:
                if label in self.baseline_events or o.event_captured_at < self.started_at:
                    continue
                if scope == 'encounter' and self.baseline_ready:
                    if self.end_label != label:
                        self.end_label, self.end_events = label, set()
                    self.end_events.add(o.event_sequence)
                elif scope in ('kill_candidate', 'reward_candidate'):
                    self.kill_candidate = True
            if self.end_events or self.kill_candidate:
                self._set('ending', 'positive_event_needs_corroboration')
            else:
                self._set('occluded', 'bars_absent_without_end_evidence')
            if len(self.end_events) >= 2 and o.captured_at - self.clear_since >= self.end_seconds:
                self._set('ended', 'new_encounter_success_with_clear_hud')
        return self.snapshot(now)

    def _fresh_events(self, o, now):
        if (o.event_sequence is None or o.event_captured_at is None
                or not 0 <= now - o.event_captured_at <= 1.5
                or o.event_captured_at > o.captured_at
                or o.event_sequence in self.seen_events):
            return None
        self.seen_events.add(o.event_sequence)
        # A bounded one-shot run should not retain every recognizer sample.
        if len(self.seen_events) > 64:
            self.seen_events = set(sorted(self.seen_events)[-32:])
        return tuple((e['label'], e['scope']) for e in o.events)

    def snapshot(self, now):
        age = None if self.last_capture is None else now - self.last_capture
        fresh = age is not None and 0 <= age <= self.max_age
        return dict(state=self.state if fresh else 'unknown',
                    reason=self.reason if fresh else 'local_observation_stale',
                    fresh=fresh, age_seconds=None if age is None else round(age, 4),
                    sequence=self.last_sequence, started=self.started_at is not None,
                    ended=fresh and self.state == 'ended',
                    needs_end_confirmation=fresh and self.state == 'ending',
                    end_baseline_verified=self.baseline_ready,
                    end_evidence=self.end_label, observations=self.observations,
                    transitions=self.transitions, max_gap_seconds=round(self.max_gap, 4))
