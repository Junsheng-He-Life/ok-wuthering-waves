"""Resumable character steps on the existing, single combat executor.

One call executes one step. Only evidence-bearing results advance required
skills; unavailable skills are explicitly skipped, never reported as casts.
This is an incremental adapter, not a second input loop or controller.
"""
from dataclasses import dataclass, field
import time
from src.combat.SkillAction import ActionStatus, SkillResult


@dataclass
class RotationSequence:
    visit: tuple
    started: float
    step: int = 0
    attempts: dict = field(default_factory=dict)
    outcomes: dict = field(default_factory=dict)
    ended: str = ''


def observed_burst(char):
    if not char.liberation_available():
        return SkillResult(ActionStatus.UNAVAILABLE, False, 'burst_not_ready')
    success = bool(char.click_liberation(wait_if_cd_ready=0))
    return SkillResult(ActionStatus.CONFIRMED if success else ActionStatus.UNCONFIRMED,
                       success, 'burst_animation_confirmed' if success else 'burst_not_confirmed')


def optional_step(action):
    """Non-gating utility step; completion does NOT assert a successful cast."""
    action()
    return SkillResult(ActionStatus.UNAVAILABLE, False, 'optional_attempt_finished')


def run_sequence(char, steps, *, wall_limit=20):
    team, slot, *_ = char.task.in_team()
    if not team or slot != char.index:
        return  # Reconcile identity in the outer loop; issue no stale action.
    visit = (char.last_switch_in_time, getattr(char.task, 'combat_start', None))
    state = getattr(char, '_rotation_sequence', None)
    if state is None or state.visit != visit:
        state = char._rotation_sequence = RotationSequence(visit, time.monotonic())
        char._detonation_chain_done = False

    def record(kind, **fields):
        logger = getattr(char.task, 'log_info', None)
        if callable(logger):
            logger(f'Rotation step {char.char_name}: {kind} {fields}')
        result = getattr(char.task, 'result', None)
        if isinstance(result, dict):
            result.setdefault('rotation_steps', []).append({
                'actor': str(char.char_name), 'slot': char.index, 'visit': visit,
                'event': kind, **fields})

    def release(reason):
        state.ended = reason
        char._detonation_chain_done = reason == 'steps_resolved'
        record('release', reason=reason, outcomes=state.outcomes.copy())
        char.switch_next_char()

    if state.ended:
        # A deferred switch is still the same visit. Do not replay the opener.
        char.continues_normal_attack(.35, until_con_full=True)
        char.switch_next_char()
        return
    if time.monotonic() - state.started >= wall_limit:
        release('wall_deadline_unconfirmed')
        return
    if state.step == len(steps):
        release('steps_resolved')
        return
    name, action = steps[state.step]
    char.task._combat_diagnostic_step = f'{char.char_name}:{name}'
    try:
        outcome = action()
    except Exception:
        record('interrupted', step=name)
        raise  # The outer combat loop owns healing/exit; no stale continuation.
    finally:
        char.task._combat_diagnostic_step = None
    if visit != (char.last_switch_in_time, getattr(char.task, 'combat_start', None)):
        record('interrupted', step=name, evidence='visit_changed')
        return
    team, slot, *_ = char.task.in_team()
    if not team or slot != char.index:
        record('interrupted', step=name, evidence='actor_changed')
        return
    record('step', step=name, status=str(outcome.status), evidence=outcome.evidence)
    state.outcomes[name] = str(outcome.status)
    if outcome.status in (ActionStatus.CONFIRMED, ActionStatus.UNAVAILABLE):
        state.step += 1
    else:
        state.attempts[name] = state.attempts.get(name, 0) + 1
        if outcome.status == ActionStatus.INTERRUPTED:
            # Let the outer loop select the actual active character next.
            return
        if state.attempts[name] >= 2:
            release('skill_unconfirmed:' + name)
            return
        char.continues_normal_attack(.4)
