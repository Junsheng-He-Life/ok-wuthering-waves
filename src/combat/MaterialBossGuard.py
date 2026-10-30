"""Bounded target acquisition and health checks for material boss runs."""
import time
from src.combat.MaterialBossHealing import MaterialBossHealing


class MaterialBossGuard(MaterialBossHealing):
    def configure_material_boss(self):
        from src.combat.MaterialBossProfiles import resolve_boss_profile
        from src.task.CultivationTargetUI import viewport
        from src.task.VerifiedDomainCombat import DomainBattleFailed
        title = ''.join(b.name for b in self.ocr(box=viewport(self, .28, 0, .73, .12)))
        profile = resolve_boss_profile(title)
        if profile is None or not profile.supported:
            self.fail_battle(f'Boss 专属策略未核实：{title}；保存画面后返回')
        self.boss_profile = profile
        expected = getattr(self, '_material_boss_source', None)
        if expected and expected['boss_key'] != profile.key:
            self.fail_battle('材料详情来源与当前 Boss 不一致；停止挑战')
        self._battle_deadline = self._battle_hard_deadline = time.monotonic() + profile.battle_seconds
        self._boss_hp_samples = {}
        self._boss_last_dodge = 0
        self._boss_healing = False
        self._boss_heal_last = -100
        self._boss_self_heal_last = -100
        self._boss_team_health = {}
        self.log_info(f'Boss policy: {profile.key}; {profile.evidence}')
        if self.result is not None:
            self.result['boss_policy'] = {'name': profile.key, 'title': title,
                                          'evidence': profile.evidence}

    def boss_policy_value(self, name, default):
        return getattr(getattr(self, 'boss_profile', None), name, default)

    def boss_target_locked(self):
        # Use the target indicator directly: has_target() has a legacy Escape
        # recovery path that must not open menus during this guarded battle.
        yes, no = self.get_target_names()
        from src.task.CultivationTargetUI import viewport
        # The attack-target HUD moves with the right HUD on ultrawide screens.
        # Search the actual viewport instead of legacy 16:9 template boxes.
        for region in (viewport(self, .70, .85, .84, .96),):
            match = self.find_best_match_in_box(region, [yes, no], threshold=.6)
            if match and match.name == yes:
                return True
        return False

    def acquire_material_boss(self):
        self._boss_acquiring = True
        self._boss_acquire_deadline = time.monotonic() + self.boss_policy_value('acquire_seconds', 8)
        try:
            return self._acquire_material_boss()
        finally:
            self._boss_acquiring = False

    def _acquire_material_boss(self):
        from src.task.VerifiedDomainCombat import DomainBattleFailed
        self.mouse_up()
        self.held_attack_interrupted = True
        # Forward movement is allowed only with a visible boss encounter HUD.
        # Never walk indefinitely towards an off-screen or vanished enemy.
        movement_attempts = 0
        while movement_attempts < 12:
            self.check_boss_acquire_deadline()
            self.next_frame()
            frame = getattr(self, 'frame', None)
            if frame is not None:
                self._battle_decision_frame = frame.copy()
            treasure = getattr(self, 'material_victory_visible', None) or getattr(self, 'find_treasure_icon', None)
            if treasure is not None and treasure():
                self._battle_end_seen = True
                return
            if not self.in_team()[0] or not self.check_health_bar():
                # Boss transitions and liberation cameras can hide the bar.
                # Pause input; the acquisition deadline bounds this grace.
                self.sleep(.3)
                continue
            self.check_material_boss_health()
            self.log_info('boss acquisition: checking target HUD')
            if self.boss_target_locked():
                self.log_info('boss acquisition: target HUD confirmed')
                return
            self.log_info('boss acquisition: middle button begin')
            self.middle_click()
            self.log_info('boss acquisition: middle button end')
            self.sleep(.15)
            self.next_frame()
            if self.boss_target_locked():
                return
            movement_attempts += 1
            self.log_info('boss acquisition: forward begin')
            self.send_key('w', down_time=self.boss_policy_value('approach_step', .6), after_sleep=.1)
            self.log_info('boss acquisition: forward end')
        self.fail_battle('Boss 锁定未确认；停止空放技能并返回治疗')

    def check_boss_acquire_deadline(self):
        from src.task.VerifiedDomainCombat import DomainBattleFailed
        if (getattr(self, '_boss_acquiring', False)
                and time.monotonic() >= self._boss_acquire_deadline):
            victory = getattr(self, 'material_victory_visible', None)
            if victory and victory():
                self._battle_end_seen = True
                return
            self.fail_battle('Boss 获取目标超过时限（默认 8 秒）；停止等待并返回治疗')

    def check_material_boss_health(self):
        from src.task.VerifiedDomainCombat import DomainBattleFailed
        hp = self.read_boss_hp()
        if hp is None:
            self._boss_unreadable_hp += 1
            observation = getattr(self, '_hp_observation', {}) or {}
            bars = observation.get('portrait_ratios', ())
            age = time.monotonic() - observation.get('monotonic', float('-inf'))
            if (observation.get('team_verified') and 0 <= age <= 1
                    and len(bars) == 3 and all(bar is not None and bar >= .7 for bar in bars)):
                # A fresh, fully readable healthy team can corroborate safety
                # while damage effects hide numeric HP. This never supplies
                # numeric healing evidence or permits a low/unknown bar.
                self.log_info('numeric HP obscured; fresh healthy team portrait bars confirmed')
                return
            if self.in_team()[0] and self.check_health_bar():
                # Damage effects can obscure the active character's HP text
                # while the boss encounter is plainly still running.
                if self._boss_unreadable_hp == 3:
                    self.log_info('player HP OCR obscured; Boss bar remains, continue combat')
                return
            if self._boss_unreadable_hp >= 3:
                self.fail_battle('Boss 战斗连续无法读取血量；返回治疗')
            return
        self._boss_unreadable_hp = 0
        if self.boss_policy_value('reactive_dodge', False):
            slot = self.in_team()[1]
            now = time.monotonic()
            previous = self._boss_hp_samples.get(slot)
            self._boss_hp_samples[slot] = (now, hp[0] / hp[1])
            if (previous and 0 <= now - previous[0] <= 3
                    and previous[1] - hp[0] / hp[1] >= .12
                    and now - self._boss_last_dodge >= 3):
                # Damage reaction, not a prediction of a telegraphed attack.
                self._boss_last_dodge = now
                self.mouse_up()
                self.held_attack_interrupted = True
                self.send_key('shift', down_time=.08)
                self.log_info('Boss burst damage: release held attack and dodge once')
                result = getattr(self, 'result', None)
                if isinstance(result, dict):
                    result.setdefault('damage_dodges', []).append({'slot': slot + 1,
                        'hp_ratio': round(hp[0] / hp[1], 3)})

        if self.request_boss_healing(hp):
            return
        if hp[0] <= hp[1] * .4:
            self.fail_battle('Boss 战斗当前角色血量低于 40%；提前返回治疗')

    def guard_material_boss(self):
        # Sleep hooks run during acquisition too: enforce elapsed time there
        # while preventing recursive target acquisition.
        self.check_boss_acquire_deadline()
        if (getattr(self, 'in_liberation', False)
                or getattr(self, '_boss_acquiring', False)):
            return
        now = time.monotonic()
        if now < self._boss_guard_at:
            return
        self._boss_guard_at = now + self.boss_policy_value('health_interval', 1)
        self.check_material_boss_health()
        if getattr(self, '_boss_healing', False):
            return
        if not getattr(self, '_plan_boss', False):
            guard_target = getattr(self, 'guard_echo_target', None)
            if callable(guard_target):
                guard_target()
            return
        if self.boss_target_locked():
            self._boss_target_missing_at = None
        elif self._boss_target_missing_at is None:
            self._boss_target_missing_at = now
        elif now - self._boss_target_missing_at >= 6:
            self.acquire_material_boss()
            self._boss_target_missing_at = None
