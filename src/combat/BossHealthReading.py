"""Cross-check risky OCR against portrait bars and a separate captured frame."""
from src.combat.PortraitHealth import portrait_health


class BossHealthReading:
    def read_boss_hp(self):
        hp = self.read_current_hp()
        observation = getattr(self, '_hp_observation', None)
        # Isolated unit-test adapters may supply numeric HP without a capture.
        if observation is None:
            return hp
        team, slot, *_ = self.in_team()
        observation.update(slot_at_decision=slot, team_verified=team)
        bars = portrait_health(getattr(self, '_hp_observation_frame', None))
        observation['portrait_ratios'] = bars
        if not team or not 0 <= slot < 3 or hp is None:
            return None
        ratio = hp[0] / hp[1]
        bar = bars[slot]
        if bar is not None and abs(bar-ratio) > .22:
            observation['rejected'] = 'numeric_portrait_disagreement'
            self.save_battle_trigger('血量OCR与头像血条不符，读数被拒绝，未判定濒死')
            if bar >= .5:
                observation['approximate_portrait_hp'] = True
                return int((bar-.05)*hp[1]), hp[1]
            return None
        if ratio > .4:
            return hp
        first = dict(observation)
        first_sequence = observation.get('capture_sequence')
        self.next_frame()
        second = self.read_current_hp()
        second_observation = self._hp_observation
        team2, slot2, *_ = self.in_team()
        bars2 = portrait_health(getattr(self, '_hp_observation_frame', None))
        second_observation.update(slot_at_decision=slot2, team_verified=team2,
                                  portrait_ratios=bars2, previous_reading=first)
        new_sequence = second_observation.get('capture_sequence')
        if (first_sequence is not None and new_sequence == first_sequence
                or not team2 or slot2 != slot or second is None or second[1] != hp[1]):
            second_observation['rejected'] = 'fresh_same_slot_reading_not_verified'
            return None
        if bars2[slot] is not None and abs(bars2[slot]-second[0]/second[1]) > .22:
            second_observation['rejected'] = 'numeric_portrait_disagreement'
            self.save_battle_trigger('复核血量与头像血条不符，未判定濒死')
            if bars2[slot] >= .5:
                second_observation['approximate_portrait_hp'] = True
                return int((bars2[slot]-.05)*second[1]), second[1]
            return None
        if abs(second[0]/second[1]-ratio) > .12:
            second_observation['rejected'] = 'numeric_readings_disagree'
            return None
        second_observation['confirmed_low_hp'] = True
        return second
