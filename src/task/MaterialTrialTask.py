"""Bounded material-domain checks with no reward, refill, or repeat clicks."""

from src.task.CharacterMaterialTask import CharacterMaterialTask, USE_CURRENT_TARGET


class MaterialTrialTask(CharacterMaterialTask):
    """Validate one phase; combat stops before approaching the reward chest.

    The command-line runner sets phase and the exact live target/stage. This
    deliberately bypasses the legacy repeat/reward loop and its refill path.
    """

    phase = 'inspect'
    expected_target = ''
    exact_stage = ''
    result = None
    expand_character_search = True
    character_match_threshold = 0.8

    def trust_preferred_character_hints(self):
        return False

    def sleep_check(self):
        if self.phase in ('resume', 'basic'):
            # The bounded resume loop checks HUD and completion itself. Do not
            # re-enter the low-health detector that this diagnostic isolates.
            self._raise_if_manual_exit_before_input()
            return
        return super().sleep_check()

    def run(self):
        self.result = {'phase': self.phase, 'status': 'running'}
        try:
            if self.phase == 'approach':
                if not self.in_team_and_world() or not self.find_treasure_icon():
                    raise RuntimeError('reward chest and domain HUD must both be visible')
                self.walk_to_treasure(send_f=False)
                self.result['status'] = 'reward_prompt_unclaimed'
            elif self.phase in ('combat', 'resume', 'basic'):
                if not self.in_team_and_world():
                    raise RuntimeError('domain controls are not visible; no input sent')
                import re
                if self.phase in ('combat', 'basic'):
                    self.walk_to_domain_interaction()
                    # Only a positively recognized start prompt may begin combat.
                    if not self.find_f_with_text(target_text=[re.compile(r'开始挑战|開啟挑戰|开启挑战|Start Challenge')]):
                        raise RuntimeError('start-challenge F prompt not verified')
                    self.pick_f(handle_claim=False)
                else:
                    objective = self.ocr(0, .15, .3, .4)
                    self.log_info('resume objective OCR: ' + repr([b.name for b in objective]))
                    if not any(re.search(r'击败敌人|擊敗敵人', b.name.replace(' ', '')) for b in objective) and not self.check_health_bar():
                        raise RuntimeError('active domain objective/enemy health bar not verified')
                self.combat_end_condition = self.domain_combat_finished
                if self.phase in ('resume', 'basic'):
                    # A nearly defeated enemy may have too little red health
                    # for the legacy combat detector. A verified timed-domain
                    # objective still permits a bounded normal-attack trial.
                    import time
                    self._in_combat = True
                    deadline = time.monotonic() + (90 if self.phase == 'basic' else 45)
                    next_skill = next_switch = 0
                    slot = 2
                    while time.monotonic() < deadline:
                        if self.find_treasure_icon():
                            break
                        if not self.in_team_and_world():
                            # Skill/success animations temporarily hide the HUD.
                            # Wait without sending inputs, then re-check the chest.
                            if not self.wait_until(lambda: self.find_treasure_icon() or self.in_team_and_world(),
                                                   time_out=5, raise_if_not_found=False):
                                raise RuntimeError('domain HUD disappeared; stop normal attacks')
                            if self.find_treasure_icon():
                                break
                        now = time.monotonic()
                        if self.phase == 'basic' and now >= next_switch:
                            # Only the two visually verified, healed slots.
                            slot = 1 if slot == 2 else 2
                            self.send_key(str(slot))
                            next_switch = now + 12
                        if self.phase == 'basic' and now >= next_skill:
                            for key in ('e', 'q', 'r'):
                                self.send_key(key)
                            next_skill = now + 4
                        self.click(after_sleep=.12)
                    self._in_combat = False
                else:
                    self.combat_once()
                if not self.wait_until(self.find_treasure_icon, time_out=5, raise_if_not_found=False):
                    raise RuntimeError('combat returned without a visible reward chest; completion unverified')
                self.result['status'] = 'combat_complete_reward_unclaimed'
            else:
                self.open_materials_book()
                target = self.ensure_cultivation_target(USE_CURRENT_TARGET)
                self.result['target'] = target
                self.result['stamina'] = self.get_stamina()
                if self.expected_target and self._normalize_material_text(target) != self._normalize_material_text(self.expected_target):
                    raise RuntimeError('live cultivation target differs from trial target')
                self.open_boss_book('ningsu')
                self.sleep(1)
                rows = self._visible_material_locations(0.195)
                if self.phase == 'scan':
                    rows = self.build_material_page_dictionary('ningsu', force=True)['locations']
                self.result['rows'] = [{k: v for k, v in row.items() if k != 'action_box'} for row in rows]
                if self.phase == 'enter':
                    if not self.expected_target or not self.exact_stage:
                        raise RuntimeError('entry requires an exact verified target and stage')
                    route = {'category': 'ningsu', 'fallback_stage_name': self.exact_stage}
                    if not self.enter_character_material_domain(route):
                        raise RuntimeError('verified material domain is unavailable')
                    self.result['status'] = 'entered_no_reward_claimed'
                else:
                    self.result['status'] = 'inspected_no_stamina_spent'
            self.screenshot('ultrawide_trial_' + self.phase)
        except Exception as exc:
            self.result.update(status='stopped', error=str(exc))
            self.screenshot('ultrawide_trial_stopped')
            raise
        finally:
            import cv2
            frame = self.executor.nullable_frame()
            if frame is not None:
                cv2.imwrite('screenshots/ultrawide-trial-latest.png', frame)
            self._stop_combat_debug_frame_recorder(log_result=False)
