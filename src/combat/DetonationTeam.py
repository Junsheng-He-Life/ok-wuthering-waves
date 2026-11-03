"""Material-run rotation for the live Aemeath / Denia / Chisa roster.

Reference: user's rotation image and Kuro's Aemeath guide (item
1463260295867838464). Equipment is untouched; live gauges gate Outros.
"""
import time


ORDER = ('char_chisa', 'char_denia', 'char_aemeath')


class DetonationTeam:
    def prefer_fast_character_rotation(self):
        return self.detonation_team_active() or super().prefer_fast_character_rotation()

    def detonation_team_active(self):
        chars = getattr(self, 'chars', [])
        return (getattr(self, '_verified_battle', False) and len(chars) == 3
                and all(c and c.confidence >= .8 for c in chars)
                and {c.char_name for c in chars} == set(ORDER))

    def prepare_team_rotation(self):
        if not self.detonation_team_active():
            return
        current = self.get_current_char()
        if current.char_name == 'char_aemeath':
            current.continues_normal_attack(4)
        chisa = next(c for c in self.chars if c.char_name == ORDER[0])
        self.healing_switch(chisa)
        self.log_info('聚爆队轮转：千咲 → 达妮娅 → 爱弥斯；按实时协奏接变奏')

    def preferred_switch_target(self, current_char, candidates, has_intro):
        if self.detonation_team_active():
            for offset in (1, 2):
                name = ORDER[(ORDER.index(current_char.char_name) + offset) % 3]
                candidate = next((c for c in candidates if c.char_name == name), None)
                if candidate:
                    return candidate
            return None
        return super().preferred_switch_target(current_char, candidates, has_intro)

    def wait_for_full_con_before_switch(self):
        if not self.detonation_team_active():
            return super().wait_for_full_con_before_switch()
        char = self.get_current_char(raise_exception=False)
        if char is None:
            return False
        started = max(char.last_switch_in_time, getattr(self, 'combat_start', 0))
        # Lower recharge equipment can need more attacks. Bound a stalled or
        # unreadable ring so it cannot indefinitely exclude the healer.
        limit = 24 if char.char_name == 'char_chisa' else 20
        return started > 0 and time.time() - started < limit

    def use_sparse_con_ring_detection(self):
        return self.detonation_team_active() or super().use_sparse_con_ring_detection()

    def allow_immediate_visible_liberation(self):
        return self.detonation_team_active() or super().allow_immediate_visible_liberation()
