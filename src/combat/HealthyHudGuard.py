"""Fast routine health evidence; low/unknown HP and healing retain numeric checks."""
import time

from src.combat.PortraitHealth import portrait_health
from src.combat.SkillAction import frame_sequence


def fresh_healthy_portrait(task):
    if (getattr(task, '_verified_battle', False) is not True
            or getattr(task, '_boss_healing', False)):
        return False
    frame = getattr(task, 'frame', None)
    if frame is None:
        return False
    now = time.monotonic()
    # Even a consistently bright portrait is periodically checked against the
    # numeric bar. Never substitute a ratio for HP in healing or accounting.
    if now >= getattr(task, '_routine_numeric_due', 0):
        task._routine_numeric_due = now + 3
        return False
    sequence = frame_sequence(task)
    executor = getattr(task, '_executor', None)
    if (sequence is None or frame is None
            or not 0 <= time.time() - getattr(executor, '_last_frame_time', 0) <= .5):
        return False
    team, slot, *_ = task.in_team()
    if not team or not 0 <= slot < 3:
        return False
    sample = (slot, sequence)
    if sample != getattr(task, '_routine_health_sample', None):
        task._routine_health_sample = sample
        task._routine_health_sample_at = now
    if now - task._routine_health_sample_at > .5:
        return False
    bars = portrait_health(frame)
    if bars[slot] is None or bars[slot] < .75:
        return False
    if task.boss_policy_value('reactive_dodge', False):
        # Echo encounters need the same fast healthy path. A falling bar must
        # still reach numeric confirmation and the existing damage reaction.
        samples = getattr(task, '_routine_portrait_health', {})
        previous = samples.get(slot)
        samples[slot] = (now, bars[slot])
        task._routine_portrait_health = samples
        if (previous is None or now - previous[0] > 3
                or previous[1] - bars[slot] >= .08):
            return False
    task._hp_observation_frame = frame.copy()
    task._hp_observation = {'monotonic': now, 'raw': [], 'parsed': None,
        'capture_sequence': sequence, 'team_verified': True, 'slot_at_decision': slot,
        'portrait_ratios': bars, 'health_evidence': 'fresh_healthy_portrait'}
    result = getattr(task, 'result', None)
    if isinstance(result, dict):
        result['healthy_portrait_checks'] = result.get('healthy_portrait_checks', 0) + 1
    return True
