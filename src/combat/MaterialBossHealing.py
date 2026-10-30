"""Unwind damage rotations for bounded healer actions and verified ally HP."""
import time
from src.combat.BattleEvidence import BattleEvidence
from src.combat.BossHealthReading import BossHealthReading


class BossHealRequested(Exception):
    def __init__(self, slot, hp):
        self.slot, self.hp = slot, hp


class MaterialBossHealing(BossHealthReading, BattleEvidence):
    HEALERS = ('char_suisui', 'char_chisa', 'char_verina', 'char_baizhi')
    def healthy_healing_replacement(self, injured_slot):
        now = time.monotonic()
        samples = getattr(self, '_boss_team_health', {})
        candidates = [(hp[0] / hp[1], self.chars[slot])
                      for slot, (stamp, hp) in samples.items()
                      if slot != injured_slot and 0 <= now - stamp <= 15
                      and hp[0] / hp[1] >= .7
                      and self.chars[slot].confidence >= .8]
        return max(candidates, key=lambda item: item[0])[1] if candidates else None

    def request_boss_healing(self, hp):
        from src.task.VerifiedDomainCombat import DomainBattleFailed
        team, slot, *_ = self.in_team()
        observation = getattr(self, '_hp_observation', None)
        if observation is not None:
            observation['slot_at_decision'] = slot
            observation['team_verified'] = team
        if team and 0 <= slot < len(getattr(self, 'chars', [])):
            if not hasattr(self, '_boss_team_health'):
                self._boss_team_health = {}
            self._boss_team_health[slot] = (time.monotonic(), hp)
        if getattr(self, '_boss_healing', False):
            if time.monotonic() >= self._boss_heal_deadline:
                self.fail_battle('紧急治疗超时；返回信标')
            # The switch itself advances capture frames. The injured/dead
            # character may still be shown until the new slot becomes active;
            # let the bounded switch finish instead of aborting it midway.
            return True
        healers = [c for c in getattr(self, 'chars', [])
                   if c and c.char_name in self.HEALERS and c.confidence >= .8]
        if hp[0] <= .2 * hp[1]:
            if team and slot >= 0 and len(healers) == 1:
                raise BossHealRequested(slot, hp)
            self.fail_battle('当前角色生命危急且接场角色未确认')
        if len(healers) != 1 or hp[0] > .65 * hp[1]:
            return False
        self_rescue = team and slot >= 0 and self.chars[slot] is healers[0]
        cooldown = '_boss_self_heal_last' if self_rescue else '_boss_heal_last'
        if hp[0] > .4 * hp[1] and time.monotonic() - getattr(self, cooldown, -100) < 25:
            return False
        if team and slot >= 0:
            raise BossHealRequested(slot, hp)
        return False

    def verify_healing_replacement(self, injured_slot):
        from src.task.VerifiedDomainCombat import DomainBattleFailed
        preferred = self.healthy_healing_replacement(injured_slot)
        candidates = [c for c in self.chars if c.index != injured_slot and c.confidence >= .8
                      and time.monotonic() >= getattr(c, 'recovery_until', 0)]
        if preferred is not None:
            candidates.sort(key=lambda c: c.index != preferred.index)
        for candidate in candidates:
            if not self.healing_replacement_available(candidate):
                continue
            self.healing_switch(candidate)
            hp = self.wait_until(self.read_boss_hp, time_out=1, raise_if_not_found=False)
            if hp and self.in_team()[1] == candidate.index:
                self._boss_team_health[candidate.index] = (time.monotonic(), hp)
                if hp[0] >= .7 * hp[1]:
                    return candidate
        self.fail_battle('逐一核对后无健康接场队友；返回信标')

    def healing_replacement_available(self, candidate):
        """Allow encounter adapters to require evidence before a trial switch.

        Domain tasks retain their existing numeric-HP verification after the
        switch. World encounters can reject unreadable or depleted portrait
        bars first, avoiding a blind switch into a revival item dialog.
        """
        return True

    def healing_switch(self, target):
        from src.task.VerifiedDomainCombat import DomainBattleFailed
        current = self.get_current_char()
        if current.index == target.index:
            return
        has_intro = current.get_current_con() == 1
        self.mouse_up()
        self.held_attack_interrupted = True
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            self.send_key(str(target.index + 1), down_time=.08, after_sleep=.2)
            self.next_frame()
            team, slot, *_ = self.in_team()
            if team and slot == target.index:
                current.switch_out(con_full=has_intro)
                target.is_current_char = True
                target.has_intro = has_intro
                target.last_switch_in_time = time.time()
                return
        self.fail_battle('紧急治疗切人未确认')

    @staticmethod
    def healing_progress(before, readings, hp):
        # Never infer healing from a max-HP buff or another character's bar.
        if hp[1] != before[1] or hp[0] / hp[1] < .45:
            readings.clear()
            return False
        if readings and hp[0] < readings[-1]:
            readings.clear()
        if hp[0] > before[0] and (not readings or hp[0] > readings[-1]):
            readings.append(hp[0])
        # Preserve a clear burst heal; also accept two distinct positive ticks
        # rather than rejecting real regeneration just short of a fixed 2%.
        return hp[0] >= before[0] + .02 * before[1] or len(readings) >= 2

    def heal_material_boss(self, request):
        from src.task.VerifiedDomainCombat import DomainBattleFailed
        healer = next(c for c in self.chars if c.char_name in self.HEALERS and c.confidence >= .8)
        injured = self.chars[request.slot]
        self._boss_healing = True
        self._boss_heal_last = time.monotonic()
        if injured is healer:
            self._boss_self_heal_last = time.monotonic()
        self._boss_heal_deadline = time.monotonic() + 18
        # Acquisition was interrupted too; its old deadline must not expire
        # during rescue. The next rotation will reacquire if required.
        self._boss_acquiring = False
        event = {'slot': request.slot + 1, 'before': request.hp,
                 'healer': healer.char_name, 'status': 'started'}
        self.result.setdefault('healing', []).append(event)
        try:
            self.mouse_up()
            self.held_attack_interrupted = True
            if request.hp[0] <= .2 * request.hp[1]:
                replacement = self.verify_healing_replacement(request.slot)
                injured.recovery_until = (float('inf') if request.hp[0] == 0
                                          else time.monotonic() + 30)
                event.update(status='critical_swap', resume_slot=replacement.index + 1)
                self.log_info(f'Boss critical HP: continue with healthy ally: {event}')
                return
            if injured is healer and healer.char_name == 'char_suisui':
                replacement = self.verify_healing_replacement(request.slot)
                event['replacement'] = replacement.index + 1
                # Do not expose the wounded healer again just to measure a
                # possible regeneration tick. Keep her off field and let the
                # verified healthy ally finish its rotation; no heal is claimed.
                injured.recovery_until = time.monotonic() + 30
                event.update(status='self_rescue_deferred', resume_slot=replacement.index + 1)
                self.log_info(f'Wounded Suisui remains off field: {event}')
                return
            else:
                self.healing_switch(healer)
                event['action_issued'] = bool(healer.emergency_heal_actions())
                if not event['action_issued']:
                    if healer.char_name in self.HEALERS:
                        # Healing resources may be empty after a recent rescue.
                        # Keep the wounded character off field while a verified
                        # healthy ally continues the encounter. The regular
                        # health guard still forces retreat below 20% HP.
                        replacement = self.verify_healing_replacement(request.slot)
                        injured.recovery_until = time.monotonic() + 30
                        event['status'] = 'deferred_to_healthy_ally'
                        event['resume_slot'] = replacement.index + 1
                        self.log_info(f'Boss healer rescue deferred: {event}')
                        return
                    # Do not expose the injured ally again when the healer's
                    # bounded skill attempt failed. Outer recovery leaves the
                    # encounter with the healer still active.
                    self.fail_battle('治疗技能未成功释放；保持治疗角色并返回信标')
            self.healing_switch(injured)
            readings = []
            def recovered():
                self.next_frame()
                hp = self.read_boss_hp()
                if hp and self.in_team()[1] == request.slot:
                    event['after'] = hp
                    if hp[0] <= .2 * hp[1]:
                        self.fail_battle('治疗验证期间生命危急；返回信标')
                    if getattr(self, '_hp_observation', {}).get('approximate_portrait_hp'):
                        return False  # A coarse bar cannot prove numeric healing ticks.
                    return self.healing_progress(request.hp, readings, hp)
                return False
            if not self.wait_until(recovered, time_out=4, raise_if_not_found=False):
                self.fail_battle('原受伤角色回血未确认；返回信标')
            event['status'] = 'verified'
            event['positive_hp_readings'] = readings
            self._boss_hp_samples = {}
            self.log_info(f'Boss healer rescue verified: {event}')
        except Exception:
            event['status'] = 'failed'
            raise
        finally:
            self._boss_healing = False
            self.mouse_up()
