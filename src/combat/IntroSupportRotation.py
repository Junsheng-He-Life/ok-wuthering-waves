"""Keep a verified Echo team's expired healer buff out of a two-DPS loop."""


def expired_echo_intro_healer(task, current_char, normal_targets):
    """Choose only an eligible healer after team and MUST hooks have declined.

    An Intro normally favors the next damage dealer. With two main DPS that
    rule can exclude the healer indefinitely, because every swap has an Intro.
    Refresh an expired healer buff in that specific verified Echo situation;
    active buffs and other modes retain the existing recipient priorities.
    """
    policy = getattr(task, 'allow_opportunistic_skills', None)
    chars = getattr(task, 'chars', ())
    if (not getattr(task, '_verified_battle', False)
            or not callable(policy) or policy() is not True
            or not current_char.is_main_dps
            or len(chars) != 3
            or not all(c is not None and c.confidence >= .8 for c in chars)
            or sum(c.is_main_dps for c in chars) < 2):
        return None
    # The caller has already excluded recovering and NO-priority characters.
    healers = [c for c in normal_targets
               if c.is_healer and c.buff_time > 0 and not c.has_buff()]
    return task._oldest_switch_target(healers)
