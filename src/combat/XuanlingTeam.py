"""Live-identity rotation for Xuanling / Phrolova / Suisui.

Suisui's team buff precedes Phrolova's recipient-only 14 s Outro. Never
insert the healer between Phrolova and Xuanling. No slot is authoritative.
"""
import time


ORDER = ('char_suisui', 'char_phrolova', 'yangyang_sp')


class XuanlingTeam:
    def xuanling_team_active(self):
        return {getattr(c, 'char_name', '') for c in self.chars} == set(ORDER)

    def preferred_switch_target(self, current_char, candidates, has_intro):
        if self.xuanling_team_active():
            for offset in (1, 2):
                name = ORDER[(ORDER.index(current_char.char_name) + offset) % len(ORDER)]
                candidate = next((c for c in candidates if c.char_name == name), None)
                if candidate and time.monotonic() >= getattr(candidate, 'recovery_until', 0):
                    return candidate
            return None
        return super().preferred_switch_target(current_char, candidates, has_intro)

    def wait_for_full_con_before_switch(self):
        if not self.xuanling_team_active():
            return super().wait_for_full_con_before_switch()
        char = self.get_current_char(raise_exception=False)
        if char is None:
            return False
        # A missing ring must not pin the team on one slot indefinitely.
        limit = 18 if char.char_name == 'char_suisui' else 12
        started = max(char.last_switch_in_time, getattr(self, 'combat_start', 0))
        return started > 0 and time.time() - started < limit

    def use_sparse_con_ring_detection(self):
        return self.xuanling_team_active() or super().use_sparse_con_ring_detection()

    def trust_cached_character_hints(self):
        return False

    def trust_preferred_character_hints(self):
        return False

    def allow_immediate_visible_liberation(self):
        return self.xuanling_team_active() or super().allow_immediate_visible_liberation()
