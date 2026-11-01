"""Evidence-bearing results for incremental migration of legacy skill calls.

This adapter uses the existing executor only. Its result describes a cast,
not damage dealt or a completed rotation. Unconfirmed input is never success.
"""
from dataclasses import dataclass
from enum import StrEnum
import time


class ActionStatus(StrEnum):
    CONFIRMED = 'confirmed'
    UNAVAILABLE = 'unavailable'
    UNCONFIRMED = 'unconfirmed'
    INTERRUPTED = 'interrupted'


@dataclass(frozen=True)
class SkillResult:
    status: ActionStatus
    issued: bool
    evidence: str

    @property
    def confirmed(self):
        return self.status == ActionStatus.CONFIRMED


def frame_sequence(task):
    sequence = getattr(getattr(getattr(task, '_executor', None), 'method', None),
                       '_delivered_frame_sequence', None)
    return sequence if isinstance(sequence, int) else None


class SkillAction:
    def resonance_action(self, time_out=.8):
        """Confirm a ready -> cooldown transition on a new same-actor frame.

        Skills whose cast has no cooldown transition remain unconfirmed until
        a character-specific observer is supplied. No guesses from animation
        absence or raw pixel changes, and no extra input on the observer path.
        """
        task = self.task
        before = frame_sequence(task)
        visit = (self.last_switch_in_time, getattr(task, 'combat_start', None))
        issued = False
        started = time.monotonic()

        def result(status, evidence):
            outcome = SkillResult(status, issued, evidence)
            self.last_resonance_result = outcome
            record = getattr(task, 'result', None)
            if isinstance(record, dict):
                record.setdefault('skill_actions', []).append({
                    'skill': 'resonance', 'actor': str(self.char_name), 'slot': self.index,
                    'status': str(status), 'issued': issued, 'evidence': evidence,
                    'before_frame': before, 'after_frame': frame_sequence(task),
                    'seconds': round(time.monotonic() - started, 3)})
            return outcome

        team, slot, *_ = task.in_team()
        if not team or slot != self.index:
            self._pending_resonance = None
            return result(ActionStatus.INTERRUPTED, 'actor_not_current')
        pending = getattr(self, '_pending_resonance', None)
        self._pending_resonance = None
        if (pending and pending['visit'] == visit
                and time.monotonic() <= pending['deadline']
                and before is not None and pending['frame'] is not None
                and before > pending['frame'] and self.has_cd('resonance')):
            # A delayed cooldown belongs to the earlier input in this visit.
            # Observe before issuing another E; never call an existing cooldown
            # a new cast or carry this evidence through a character switch.
            issued = True
            before = pending['before_frame']
            return result(ActionStatus.CONFIRMED, 'delayed_fresh_cooldown_transition')
        if self.has_cd('resonance'):
            return result(ActionStatus.UNAVAILABLE, 'cooldown_observed')
        if not self.resonance_available():
            return result(ActionStatus.UNCONFIRMED, 'readiness_not_observed')
        try:
            issued = bool(self.click_resonance(time_out=time_out)[0])
            task.next_frame()
            team, slot, *_ = task.in_team()
            if not team or slot != self.index or visit != (
                    self.last_switch_in_time, getattr(task, 'combat_start', None)):
                return result(ActionStatus.INTERRUPTED, 'actor_or_visit_changed')
            after = frame_sequence(task)
            if (issued and before is not None and after is not None and after > before
                    and self.has_cd('resonance')):
                return result(ActionStatus.CONFIRMED, 'fresh_cooldown_transition')
            if issued and before is not None and after is not None and after > before:
                self._pending_resonance = {
                    'visit': visit, 'frame': after, 'before_frame': before,
                    'deadline': time.monotonic() + 3,
                }
            return result(ActionStatus.UNCONFIRMED, 'cast_not_observed')
        except Exception:
            self._pending_resonance = None
            result(ActionStatus.INTERRUPTED, 'action_unwound')
            raise
