"""Confirm objective changes across frames, including Tacet wave resets."""
import re


def read_objective(text):
    text = re.sub(r'\s+', '', text)
    match = re.search(r'(击败敌人|清理无音区中涌现的残象)[：:]?(\d+)/(\d+)', text)
    if not match:
        return None
    label, current, total = match.groups()
    current, total = int(current), int(total)
    if not 0 <= current <= total <= 100 or total == 0:
        return None
    return label, current, total


class EncounterProgress:
    """A new reading needs two distinct frames before it can renew a watchdog.

    Tacet counters restart for each wave; a stable denominator change is a
    wave transition, not a decrease in cumulative kills. Ordinary domains
    retain their fixed denominator. Neither signal proves victory.
    """
    def __init__(self):
        self.confirmed = self.candidate = None
        self.candidate_at = self.last_sequence = None
        self.version = self.extended_version = 0
        self.last_progress_at = None

    def observe(self, text, now, sequence=None):
        value = read_objective(text)
        if value is None:
            self.candidate = None
            return None
        if sequence is not None and sequence == self.last_sequence:
            return None
        self.last_sequence = sequence
        if value != self.candidate:
            self.candidate, self.candidate_at = value, now
            return None
        if now - self.candidate_at < .25 or value == self.confirmed:
            return None
        previous = self.confirmed
        self.confirmed = value
        if previous is None or previous[0] != value[0]:
            return None
        increased = previous[2] == value[2] and value[1] > previous[1]
        wave = value[0] == '清理无音区中涌现的残象' and (
            value[2] != previous[2] or value[1] == 0 and previous[1] > 0)
        if not (increased or wave):
            return None
        self.version += 1
        self.last_progress_at = now
        return {'previous': previous, 'current': value, 'wave_transition': wave,
                'sequence': sequence, 'version': self.version}

    def consume_extension(self, now, maximum_age=90):
        if (self.last_progress_at is None or now-self.last_progress_at > maximum_age
                or self.version <= self.extended_version):
            return False
        self.extended_version = self.version
        return True
