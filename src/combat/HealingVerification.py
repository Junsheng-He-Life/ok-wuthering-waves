"""Verify changed HP maxima without mistaking a maximum buff for healing."""


def conservative_hp_reference(before, maximum):
    """Bound non-healing HP changes before measuring an additional heal.

    Retain the largest of unchanged current HP, proportional rescaling and
    adding the entire positive maximum increase to current HP. Thus neither
    a maximum decrease nor either common maximum-buff adjustment can alone
    supply a positive healing tick. The caller must separately verify this
    new maximum from fresh numeric readings of the original injured slot.
    """
    current, previous_maximum = before
    proportional = (current * maximum + previous_maximum - 1) // previous_maximum
    added_maximum = current + max(0, maximum - previous_maximum)
    return min(maximum, max(current, proportional, added_maximum)), maximum


def verified_healing_maximum(hp, slot, observation, samples):
    """Require two distinct captures of one slot, maximum and agreeing bar.

    ``samples`` contains (capture_sequence, maximum) pairs local to this one
    rescue. Approximate portrait fallbacks and rejected OCR cannot establish
    a numeric maximum or contribute healing evidence.
    """
    observation = observation or {}
    sequence = observation.get('capture_sequence')
    bars = observation.get('portrait_ratios') or []
    valid = (observation.get('team_verified') is True
             and observation.get('slot_at_decision') == slot
             and observation.get('parsed') == list(hp)
             and not observation.get('approximate_portrait_hp')
             and not observation.get('rejected')
             and isinstance(sequence, int)
             and 0 <= slot < len(bars) and bars[slot] is not None
             and abs(bars[slot] - hp[0] / hp[1]) <= .10)
    if not valid:
        samples.clear()
        return False
    if samples and samples[-1][1] != hp[1]:
        samples.clear()
    if not samples or sequence > samples[-1][0]:
        samples.append((sequence, hp[1]))
        del samples[:-2]
    elif sequence < samples[-1][0]:
        samples.clear()
        return False
    else:
        return False  # A repeated capture cannot supply a new healing tick.
    return len(samples) >= 2
