"""Reward interaction and verified single/double settlement, independent of travel."""
import re
import time
import cv2


class MaterialRewardUI:
    @staticmethod
    def weekly_reward_orb(frame):
        """Locate the observed blue reward orb after the objective confirms victory."""
        from pathlib import Path
        from ok import Box
        path = Path(__file__).resolve().parents[2] / 'assets/images/leviathan-reward-orb-1920.png'
        template = cv2.imread(str(path))
        if template is None:
            return None
        height, width = frame.shape[:2]
        x, y = round(width*.15), round(height*.15)
        region = frame[y:round(height*.8), x:round(width*.85)]
        best = None
        for scale in (.6, .8, 1., 1.3, 1.7, 2.2, 3., 4.):
            patch = cv2.resize(template, None, fx=scale*height/1080, fy=scale*height/1080)
            if patch.shape[0] >= region.shape[0] or patch.shape[1] >= region.shape[1]:
                continue
            _, score, _, position = cv2.minMaxLoc(cv2.matchTemplate(region, patch, cv2.TM_CCOEFF_NORMED))
            if score >= .65 and (best is None or score > best.confidence):
                best = Box(position[0]+x, position[1]+y, patch.shape[1], patch.shape[0],
                           confidence=score, name='weekly_reward_orb')
        return best

    def find_material_reward_marker(self):
        icon = self.find_treasure_icon()
        if icon:
            return icon
        victory = getattr(self, 'material_victory_visible', None)
        if getattr(self, '_plan_boss', False) and victory and victory():
            return self.weekly_reward_orb(self.frame)
        return None

    def reward_text(self, pattern, region=(0, 0, 1, 1), timeout=4):
        return self.menu_text(pattern, region, timeout, viewport=True)

    def reward_dialog_visible(self, timeout=1):
        """The world F prompt shares the title, but never has claim controls."""
        def visible():
            title = self.reward_text(r'领取奖励|ClaimRewards?', (.2, .2, .8, .7), timeout=.2)
            if not title:
                return False
            control = self.reward_text(r'(40|60|80|120)?单倍领取|ClaimOnce',
                                     (.2, .5, .5, .75), timeout=.2)
            if control:
                return True
            sentence = self.reward_text(
                r'领取奖励需消耗60点结晶波片[，,]请确认是否领取[？?]',
                (.2, .35, .8, .6), timeout=.2)
            return bool(sentence and self.reward_text(r'确认|Confirm',
                                                    (.5, .5, .8, .8), timeout=.2))
        return bool(self.wait_until(visible, time_out=timeout, raise_if_not_found=False))

    def open_verified_reward(self):
        """Retry only opening the dialog, before any waveplate spending."""
        for attempt in range(3):
            self.focus_material_menu()
            if self.reward_dialog_visible(timeout=1):
                return
            victory = getattr(self, 'material_victory_visible', None)
            if not self.find_treasure_icon() and not (victory and victory()):
                raise RuntimeError('reward chest not visible')
            self.walk_to_claim_prompt()
            if self.settlement_batch_allowed():
                self.capture_settlement_health()
            # Health capture advances the frame. Recheck the actual interaction
            # instead of silently accepting pick_f returning without a keypress.
            self.next_frame()
            if self.find_f_with_claim_text():
                self.send_key('f', after_sleep=1)
                if self.reward_dialog_visible(timeout=5):
                    return
            self.log_info(f'reward opening retry {attempt + 1}/3; no spending input sent')
        cv2.imwrite('logs/reward-opening-failed.png', self.frame)
        raise RuntimeError('reward dialog not verified after 3 attempts')

    def restore_reward_dialog(self):
        """Unwind only identified, uncommitted refill menus back to this reward."""
        for _ in range(3):
            if self.reward_dialog_visible(timeout=.5):
                return
            if (self.refill_text(r'补充结晶波片', timeout=.5)
                    or self.refill_text(r'兑换结晶波片', timeout=.5)):
                self.send_key('esc', after_sleep=.5)
                continue
            self.open_verified_reward()
            return
        raise RuntimeError('领奖页面恢复未确认')

    def reward_option(self, budget):
        cost = budget.claim_cost
        button = self.reward_text(rf'({cost})?单倍领取|ClaimOnce', (.2, .5, .5, .75))
        cost_label = self.reward_text(str(cost), (.2, .5, .5, .75), timeout=1)
        verified = bool(button and (cost_label or str(cost) in button.name))
        if not verified and cost == 60:
            sentence = self.reward_text(
                r'领取奖励需消耗60点结晶波片[，,]请确认是否领取[？?]',
                (.2, .35, .8, .6), timeout=1)
            if sentence:
                button = self.reward_text(r'确认', (.5, .5, .8, .8), timeout=1)
                verified = bool(button)
        if not verified:
            raise RuntimeError(f'single reward cost {cost} not verified')
        if budget.can_claim(2):
            double = self.reward_text(rf'({cost*2})?双倍领取|ClaimDouble', (.5, .5, .8, .75), timeout=1)
            double_cost = self.reward_text(str(cost*2), (.5, .5, .8, .75), timeout=1)
            if double and (double_cost or str(cost*2) in double.name):
                return double, 2
        return button, 1

    def claim_one_reward(self, budget):
        if budget.claim_pending:
            raise RuntimeError('previous reward spending uncertain; no retry')
        checkpoint = getattr(self, 'checkpoint_claim', None)
        self.open_verified_reward()
        # A resource deficit does not change the desired reward multiplier.
        # Clicking it can open a verified refill panel instead of spending.
        for _ in range(4):
            before, reserve, _ = self.get_stamina()
            if before < 0:
                raise RuntimeError('reward waveplates unreadable; no spending input sent')
            button, multiplier = self.reward_option(budget)
            required = budget.claim_cost * multiplier
            set_stage = getattr(self, 'set_workflow_stage', None)
            if set_stage:
                set_stage('领奖', detail=f'{multiplier}倍 / {required}波片，当前{before}')
            # Keep the pre-input evidence available to durable checkpoint
            # owners. This does not acknowledge consumption or clear a guard.
            self._claim_observation_context = {
                'started_ns': time.time_ns(), 'stamina_before': before,
                'expected_cost': required, 'multiplier': multiplier}
            budget.begin_claim(multiplier)
            if checkpoint:
                checkpoint()
            self.click_box(button, after_sleep=1)
            if before < required and self.wait_for_claim_refill():
                # This positive observation proves the claim was rejected.
                # Persist that fact before any refill spending begins.
                budget.cancel_rejected_claim()
                if checkpoint:
                    checkpoint()
                if set_stage:
                    set_stage('补给', detail=f'领奖需要{required}波片，当前{before}')
                self.refill_at_reward(budget, before, reserve, opened=True)
                if not self.reward_dialog_visible(timeout=2):
                    self.open_verified_reward()
                continue
            return self.verify_reward_result(budget, before, checkpoint)
        raise RuntimeError('领奖补给循环达到上限；保留现场')

    def wait_for_claim_refill(self):
        """Allow capture/OCR latency after the single claim input.

        GUI capture can deliver the opening animation before the panel title.
        Keep observing the same input; never reclick an uncertain claim.
        """
        return bool(self.refill_text(r'补充结晶波片', timeout=8))

    def verify_reward_result(self, budget, before, checkpoint=None):
        """Retry observations only after confirmation; never click it again."""
        if not self.reward_text(r'挑战成功|ChallengeCompleted|ChallengeSuccess', (.2, .1, .8, .4), timeout=8):
            raise RuntimeError('settlement uncertain; claim will not be retried')
        expected = budget.claim_cost * budget.claim_multiplier
        saw_number = False
        for attempt in range(1, 4):
            remaining = self.reward_text(r'剩余\d+|Remaining\d+', (.5, .8, .8, 1), timeout=2)
            after = None
            if remaining:
                after = int(re.search(r'\d+', remaining.name).group())
                saw_number = True
            delta = before - after if after is not None else None
            matched = delta in (expected - 1, expected)
            self.record_reward_observation(
                attempt=attempt, before=before, after=after,
                raw=getattr(remaining, 'name', None), expected=expected, matched=matched)
            if matched:
                self._last_claim_stamina = (before, after)
                budget.finish_claim(before, after)
                if checkpoint:
                    checkpoint()
                self.log_info(f'claimed {budget.claim_multiplier} unit(s): stamina {before} -> {after}; units {budget.claimed}')
                return after
            # The settlement animation or OCR may briefly yield a number
            # whose debit is wrong. Observe a fresh frame; never press claim.
            if attempt < 3:
                self.next_frame()
        if saw_number:
            raise RuntimeError('reward stamina delta uncertain after 3 observations; never retry claim')
        raise RuntimeError('remaining stamina not readable; stop without retry')

    def record_reward_observation(self, *, attempt, before, after, raw, expected, matched):
        """Persist the already captured frame and numeric evidence, without input."""
        from pathlib import Path
        from src.task.MaterialActivity import _atomic_json
        record = {'attempt': attempt, 'stamina_before': before, 'stamina_after': after,
                  'raw': raw, 'expected_cost': expected,
                  'observed_delta': before - after if after is not None else None,
                  'matched': matched, 'observed_ns': time.time_ns()}
        observations = getattr(self, '_reward_result_observations', None)
        if not isinstance(observations, list):
            observations = self._reward_result_observations = []
        observations.append(record)
        result = getattr(self, 'result', None)
        if isinstance(result, dict):
            result.setdefault('reward_observations', []).append(record)
        self.log_info(f'reward result observation: {record}')
        frame = getattr(self, 'frame', None)
        if getattr(frame, 'size', 0):
            folder = Path('logs/reward-results')
            folder.mkdir(parents=True, exist_ok=True)
            image_path = folder / f'{record["observed_ns"]}.png'
            if cv2.imwrite(str(image_path), frame):
                record['image'] = str(image_path)
            _atomic_json(image_path.with_suffix('.json'), record)

    @staticmethod
    def reward_step(x, y, width, height):
        """Use projected position for direction only, never estimate distance.

        A marker below the character's feet can be behind the character.
        Probe backwards briefly and reacquire, rather than walking forwards
        indefinitely when its horizontal coordinate is already centered.
        """
        error = x / width - .5
        if abs(error) > .06:
            return ('d' if error > 0 else 'a'), .15
        return ('s', .15) if y / height > .70 else ('w', .25)

    def walk_to_claim_prompt(self):
        from pathlib import Path
        folder = Path('logs/reward-navigation') / str(time.time_ns())
        folder.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + 35
        missing = 0
        step = 0
        while time.monotonic() < deadline:
            self.next_frame()
            # Record navigation too: combat recording has already stopped.
            cv2.imwrite(str(folder / f'{step:04d}.jpg'), self.frame,
                        [cv2.IMWRITE_JPEG_QUALITY, 80])
            step += 1
            if self.find_f_with_claim_text():
                return
            if not self.in_team()[0]:
                raise RuntimeError('reward navigation lost team HUD')
            icon = self.find_material_reward_marker()
            if not icon:
                missing += 1
                if missing >= 3:
                    self.center_camera()
                    missing = 0
                else:
                    self.sleep(.2)
                continue
            missing = 0
            x, y = icon.center()
            direction, duration = self.reward_step(
                x, y, self.width_of_screen(1), self.height_of_screen(1))
            self.log_info(f'reward navigation: marker=({x},{y}), step={direction}')
            self.send_key(direction, down_time=duration, after_sleep=.1)
        raise RuntimeError(f'reward navigation timed out; no reward input sent; frames={folder}')
