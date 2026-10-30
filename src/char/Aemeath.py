import time

from src.char.BaseChar import BaseChar, SwitchPriority


aemeath_mecha_forte_color = {
    'r': (0, 229),
    'g': (200, 255),
    'b': (220, 255),
}


class Aemeath(BaseChar):
    LIBERATION_COOLDOWN = 25
    LIBERATION_FORCE_DURATION = 30
    LIB2_PREPARE_WINDOW = 8
    INTRO_LIBERATION_DELAY = 14
    LIB2_GUARD_TIME_OUT = 13
    FAST_LIB2_GUARD_TIME_OUT = 5
    LIB1_FALLBACK_TIME_OUT = 10
    FAST_LIB1_FALLBACK_TIME_OUT = 1.5
    POST_LIB2_COMBO_TIME_OUT = 1.5  # lib2 收尾连招(3A+E)的硬时间上限(秒), 防卡死/异常
    ENHANCED_E_MATCH_THRESHOLD = 0.60
    ENHANCED_E_HORIZONTAL_VARIANCE = 0.025
    ENHANCED_E_VERTICAL_VARIANCE = 0.025
    ENHANCED_E_RETRY_INTERVAL = 0.45
    OPENING_NORMAL_ATTACKS = 4
    OPENING_NORMAL_ATTACK_INTERVAL = 0.12
    HEAVY_RETRY_INTERVAL = 2.0
    POST_HEAVY_RECOVERY = 0.3
    POST_HEAVY_NORMAL_ATTACKS = 4
    POST_HEAVY_NORMAL_ATTACK_INTERVAL = 0.15
    HUMAN_HEAVY_MATCH_THRESHOLD = 0.60
    MECHA_FORTE_READY_PERCENT = 0.075

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.should_wait = False
        self.intro_time = -1
        self.last_liber = -1
        self.last_enhance_e = -1
        self.intro_liberation_time = -1
        self.pending_lib2 = False
        self.last_heavy_attempt = -1
        self._lib1_cast_count = 0   # 本轮 lib1 释放次数
        self._lib2_cast_count = 0   # 本轮 lib2 释放次数

    def reset_state(self):
        super().reset_state()
        self.last_heavy_attempt = -1

    def lib2_cooldown_anchor(self):
        if self.last_liber >= 0:
            return self.last_liber
        combat_start = getattr(self.task, 'combat_start', -1)
        return combat_start if combat_start > 0 else -1

    def lib2_cooldown_left(self):
        anchor = self.lib2_cooldown_anchor()
        if anchor < 0:
            return 0
        elapsed = self.time_elapsed_accounting_for_freeze(anchor)
        return max(0, self.LIBERATION_COOLDOWN - elapsed)

    def liberation_cooldown_left(self):
        if self.last_liber < 0:
            return 0
        elapsed = self.time_elapsed_accounting_for_freeze(self.last_liber)
        return max(0, self.LIBERATION_COOLDOWN - elapsed)

    def lib1_unlock_anchor(self):
        if self.last_liber >= 0:
            return self.last_liber
        return getattr(self.task, 'combat_start', -1)

    def record_intro_liberation(self):
        self.intro_liberation_time = time.time()

    def intro_lib1_ready(self):
        return self.intro_liberation_time >= 0 and (
                self.time_elapsed_accounting_for_freeze(self.intro_liberation_time)
                <= self.INTRO_LIBERATION_DELAY)

    def lib1_unlocked(self):
        if self.intro_lib1_ready():
            return True
        anchor = self.lib1_unlock_anchor()
        return anchor >= 0 and (
                self.time_elapsed_accounting_for_freeze(anchor) >= self.LIBERATION_FORCE_DURATION)

    def can_cast_lib1(self):
        if self.liberation_cooldown_left() > 0:
            return False
        allow_immediate = getattr(
            self.task,
            'allow_immediate_visible_liberation',
            None,
        )
        return (
            callable(allow_immediate)
            and allow_immediate()
        ) or self.lib1_unlocked()

    def can_cast_liberation(self):
        return self.can_cast_lib1()

    def lib2_available(self):
        return bool(self.task.find_one('aemeath_lib2', threshold=0.7))

    def preparing_lib2(self):
        return self.lib2_cooldown_anchor() >= 0 and (
                self.lib2_cooldown_left() < self.LIB2_PREPARE_WINDOW)

    def should_wait_for_lib2(self):
        return self.pending_lib2 or self.preparing_lib2()

    def should_wait_for_enhance_e(self):
        return self.time_elapsed_accounting_for_freeze(self.last_enhance_e) > 12

    def record_enhance_e(self):
        self.last_enhance_e = time.time()

    def record_heavy_liberation(self):
        self.pending_lib2 = True

    def record_liberation(self, is_lib2):
        if is_lib2:
            self.pending_lib2 = False
            self.last_liber = time.time()
            self.last_enhance_e = self.last_liber
            self._lib2_cast_count += 1
        else:
            self.intro_liberation_time = -1
            self._lib1_cast_count += 1

    def _lib1_cast_this_turn(self):
        """本轮上场后是否已释放过 lib1（第一次解放）。"""
        return self._lib1_cast_count > 0

    def _lib2_cast_this_turn(self):
        """本轮上场后是否已释放过 lib2（第二次解放）。"""
        return self._lib2_cast_count > 0

    def _execute_lib2_guard(self, context_log: str = "") -> None:
        """
        进入等待循环以确保第二次解放（lib2）被释放。
        普通战斗保留 13 秒保护；材料本使用 5 秒快速预算。
        """
        time_out = self.rotation_timeout(
            self.LIB2_GUARD_TIME_OUT,
            self.FAST_LIB2_GUARD_TIME_OUT,
        )
        deadline = time.monotonic() + time_out
        self.logger.info(f'Aemeath [do_perform] waiting for lib2 before switching {context_log}')
        
        while not self._lib2_cast_this_turn():
            if time.monotonic() >= deadline:
                self.logger.warning(
                    f'Aemeath [do_perform] lib2 guard timed out '
                    f'({time_out:g}s) {context_log}, casting switch'
                )
                break
                
            self.task.next_frame()
            self.check_combat()
            if time.monotonic() >= deadline:
                continue
            # A visible second R is the purpose of this guard. Repeated heavy
            # prompts must not keep it behind an E/heavy branch that continues.
            if self.lib2_available() and self.lib():
                self.logger.debug(f'Aemeath [do_perform] lib2 cast, integrity guard satisfied {context_log}')
                break
            if self.cast_enhanced_e_if_ready():
                self.task.next_frame()
                continue
            if time.monotonic() >= deadline:
                continue
            if self.handle_heavy(deadline=deadline):
                self.logger.debug(f'Aemeath [do_perform] handle_heavy triggered during lib2 guard {context_log}')
                self.task.next_frame()
                continue
            if time.monotonic() >= deadline:
                continue
            self.click(after_sleep=0.01)
            self.task.next_frame()

    def _execute_lib1_or_fallback_guard(self) -> None:
        """
        处理本轮尚未释放任何解放（lib1）的情况。
        在有界窗口内尝试释放 lib1 或共鸣技能。如果成功释放
        lib1，则级联调用 lib2 守护。
        """
        lib_guard_start = time.time()
        found_action = False

        time_out = self.rotation_timeout(
            self.LIB1_FALLBACK_TIME_OUT,
            self.FAST_LIB1_FALLBACK_TIME_OUT,
        )
        while time.time() - lib_guard_start < time_out:
            self.check_combat()

            if self.cast_enhanced_e_if_ready():
                found_action = True
                break
            elif self.liberation_available() and self.can_cast_lib1():
                self.logger.debug('Aemeath [do_perform] lib available but not cast — casting lib1')
                if self.lib():
                    found_action = True
                    self._execute_lib2_guard(context_log="(after forced lib1)")
                    break
                # A failed cast must not enter the second-liberation wait.
                self.click(after_sleep=0.03)
                self.task.next_frame()
                
            else:
                if not self.handle_heavy():
                    self.click(after_sleep=0.01)
                self.task.next_frame()

        if not found_action:
            self.logger.warning(
                f'Aemeath [do_perform] {time_out:g}s window elapsed with no '
                'available skill, '
                'allowing switch without liberation'
            )

    def _execute_post_lib2_combo(self):
        """lib2 释放后的强制收尾连招: 3次普攻 + 共鸣技能(E)。

        整段受 POST_LIB2_COMBO_TIME_OUT(1.5s) 硬上限保护, 防止收尾卡死/异常拖住战斗循环。
        """
        self.logger.info('Aemeath [post-lib2 combo] starting: 3 Normal Attacks -> Resonance (E)')
        start = time.time()

        # 最多 3 次普攻; 每次前检查战斗状态与时间预算, 超时即停.
        for _ in range(3):
            if time.time() - start >= self.POST_LIB2_COMBO_TIME_OUT:
                self.logger.info('Aemeath [post-lib2 combo] time budget reached during attacks, stopping')
                return
            self.check_combat()
            self.normal_attack()
            self.sleep(0.35)

        self.check_combat()

        remaining = self.POST_LIB2_COMBO_TIME_OUT - (time.time() - start)
        if remaining <= 0:
            self.logger.info('Aemeath [post-lib2 combo] no time budget left for E, skipping')
            return
        e_available = self.enhance_e_available() or not self.task.has_cd('resonance')
        if e_available:
            self.logger.info('Aemeath [post-lib2 combo] E available, casting resonance')
            self.click_resonance(has_animation=True, send_click=True,
                                 animation_min_duration=0.5, time_out=remaining)
            self.record_enhance_e()
        else:
            self.logger.info('Aemeath [post-lib2 combo] E not available, skipping')


    def _process_end_of_turn_liberations(self) -> None:
        """根据当前回合的解放技能释放状态，进行决策路由并执行相应的收尾动作。"""
        if self._lib1_cast_this_turn() and not self._lib2_cast_this_turn():
            # ── 分支A：本轮已释放 lib1 但未释放 lib2，必须等待并释放 lib2 ───────
            self._execute_lib2_guard(context_log="(initial lib1 cast)")
            
        elif not self._lib1_cast_this_turn() and not self._lib2_cast_this_turn():
            # ── 分支B：本轮既未释放 lib1 也未释放 lib2，尝试 8 秒 fallback ──────
            self._execute_lib1_or_fallback_guard()

    def do_perform(self):
        # A deferred switch can call perform again without leaving the field.
        # Echo's skill hook may also cast R during that deferred attack chunk.
        if self._echo_liberation_enabled():
            self._sync_echo_liberation_visit()
            if self._echo_rotation_started:
                # Waiting for concerto must not restart the complete intro,
                # heavy chain and liberation guards on the same field visit.
                # This short filler retains native health/ready-skill hooks.
                self.logger.info('Aemeath deferred switch: short attack segment only')
                self.task.next_frame()
                self.check_combat()
                self.continues_normal_attack(.35)
                self.check_combat()
                self.switch_next_char()
                return
            self._echo_rotation_started = True
        else:
            self._lib1_cast_count = 0
            self._lib2_cast_count = 0

        self.intro_time = -1
        self.should_wait = False
        team_rotation = getattr(self.task, 'detonation_team_active', None)
        if callable(team_rotation) and team_rotation() is True:
            self.click_echo(time_out=0)
        
        if self.has_intro:
            self.record_intro_liberation()
            self.continues_normal_attack(1.2)
            if self.check_outro() in {'char_linnai', 'char_lupa'}:
                self.intro_time = 14
            if self.check_outro() == 'chang_changli':
                self.intro_time = 10

        self.opening_normal_attack_burst()
        self.perform_everything()

        # 处理回合末尾的技能链（lib1 -> lib2）的完整性约束
        self._process_end_of_turn_liberations()

        self.switch_next_char()

    def lib(self):
        if self._echo_liberation_enabled():
            # Echo can also request R from a normal-attack chunk. Both entry
            # points must consume the same lib1/lib2 state exactly once.
            return self.click_liberation(wait_if_cd_ready=0)
        is_lib2 = self.lib2_available()
        if not is_lib2 and not self.can_cast_lib1():
            return False
        if not self.click_liberation(wait_if_cd_ready=0):
            return False
        self.record_liberation(is_lib2)
        self.f_break()

        if is_lib2:
            self._execute_post_lib2_combo()
        return True

    def _echo_liberation_enabled(self):
        policy = getattr(self.task, 'allow_opportunistic_skills', None)
        return callable(policy) and policy() is True

    def _sync_echo_liberation_visit(self):
        visit = (self.last_switch_in_time, getattr(self.task, 'combat_start', 0))
        if getattr(self, '_echo_liberation_visit', None) != visit:
            self._echo_liberation_visit = visit
            self._lib1_cast_count = self._lib2_cast_count = 0
            self._echo_rotation_started = False

    def click_liberation(self, *args, **kwargs):
        if not self._echo_liberation_enabled():
            return super().click_liberation(*args, **kwargs)
        self._sync_echo_liberation_visit()
        # Sample the second-stage icon before R changes it. A successful base
        # cast includes cinematic/CD confirmation; failed probes change no state.
        is_lib2 = self.lib2_available()
        if not is_lib2 and not self.can_cast_lib1():
            return False
        if not super().click_liberation(*args, **kwargs):
            return False
        self.record_liberation(is_lib2)
        self.logger.info(f'Aemeath Echo liberation confirmed: lib{2 if is_lib2 else 1}')
        self.f_break()
        if is_lib2:
            self._execute_post_lib2_combo()
        return True

    def continue_in_intro(self):
        return self.time_elapsed_accounting_for_freeze(self.last_liber) < 30 and \
            self.time_elapsed_accounting_for_freeze(self.last_perform) < self.intro_time

    def perform_everything(self):
        start = time.time()
        # Skill/heavy successes may reset the short combo window, but cannot
        # renew the entire visit and starve the healer/support rotations.
        visit_deadline = time.monotonic() + self.rotation_timeout(18, 8)
        self.should_wait = self.should_wait_for_lib2() or self.should_wait_for_enhance_e()
        if not self.should_wait:
            self.should_wait = self.has_intro and self.liberation_cooldown_left() < 12
        while self.time_elapsed_accounting_for_freeze(start) < 1.2 or (
                self.should_wait and self.time_elapsed_accounting_for_freeze(start) < 3.6):
            if time.monotonic() >= visit_deadline:
                break
            self.cycle_start()
            if self.cast_enhanced_e_if_ready():
                start = time.time()
                self.task.next_frame()
                continue
            # Keep the basic string moving before the remaining visual/CD
            # checks. Those checks are useful but comparatively expensive on
            # macOS, and must not create a visible pause between attacks.
            self.click(after_sleep=0.03)
            if self.lib():
                start = time.time()
                self.should_wait = self.should_wait_for_lib2()
                self.task.next_frame()
                continue
            if self.handle_heavy():
                self.f_break()
                start = time.time()
                self.should_wait = self.should_wait_for_lib2()
                self.task.next_frame()
                continue
            self.cycle_sleep()

    def lib_cd_eminent(self):
        cd = self.task.get_cd('liberation')
        return self.lib1_unlocked() and (0 < cd < 1.5 or self.liberation_available())

    def enhance_e_available(self):
        if (
                self.last_enhance_e >= 0
                and self.time_elapsed_accounting_for_freeze(
                    self.last_enhance_e
                ) < self.ENHANCED_E_RETRY_INTERVAL):
            return False
        return self.task.find_one(
            'aemeath_e1',
            threshold=self.ENHANCED_E_MATCH_THRESHOLD,
            horizontal_variance=self.ENHANCED_E_HORIZONTAL_VARIANCE,
            vertical_variance=self.ENHANCED_E_VERTICAL_VARIANCE,
        ) or self.task.find_one(
            'aemeath_e2',
            threshold=self.ENHANCED_E_MATCH_THRESHOLD,
            horizontal_variance=self.ENHANCED_E_HORIZONTAL_VARIANCE,
            vertical_variance=self.ENHANCED_E_VERTICAL_VARIANCE,
        )

    def cast_enhanced_e_if_ready(self):
        """Press E immediately when either enhanced-E icon is visible."""
        match = self.enhance_e_available()
        if not match:
            return False
        match_name = getattr(match, 'name', 'enhanced-E')
        confidence = getattr(match, 'confidence', None)
        match_detail = (
            f' ({match_name}, confidence={confidence:.3f})'
            if isinstance(confidence, (int, float))
            else ''
        )
        self.logger.info(
            'Aemeath enhanced E visible'
            f'{match_detail}: press resonance immediately'
        )
        self.send_resonance_key(post_sleep=0.12)
        self.record_enhance_e()
        return True

    def opening_normal_attack_burst(self):
        """Start generating enhanced E without waiting for visual decisions."""
        self.logger.info(
            f'Aemeath opening: {self.OPENING_NORMAL_ATTACKS} immediate '
            'normal attacks'
        )
        burst = getattr(self.task, 'native_attack_string', None)
        if callable(burst) and burst(self.OPENING_NORMAL_ATTACKS, self.OPENING_NORMAL_ATTACK_INTERVAL):
            return
        for _ in range(self.OPENING_NORMAL_ATTACKS):
            self.check_combat()
            self.click(after_sleep=self.OPENING_NORMAL_ATTACK_INTERVAL)

    def post_heavy_normal_attack_burst(self, deadline=None):
        """Resume the basic string after a heavy instead of re-holding it."""
        self.logger.info(
            f'Aemeath heavy follow-up: '
            f'{self.POST_HEAVY_NORMAL_ATTACKS} normal attacks'
        )
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            self.sleep(min(self.POST_HEAVY_RECOVERY, remaining))
        else:
            self.sleep(self.POST_HEAVY_RECOVERY)
        burst = getattr(self.task, 'native_attack_string', None)
        if deadline is not None:
            # The native cadence can spend time in health checks or a real
            # cinematic. Re-enter it one press at a time so an expired guard
            # never starts the remainder of a four-attack queue afterwards.
            for _ in range(self.POST_HEAVY_NORMAL_ATTACKS):
                if time.monotonic() >= deadline:
                    return
                self.check_combat()
                if time.monotonic() >= deadline:
                    return
                if callable(burst) and burst(1, self.POST_HEAVY_NORMAL_ATTACK_INTERVAL):
                    continue
                self.click(after_sleep=min(
                    self.POST_HEAVY_NORMAL_ATTACK_INTERVAL,
                    max(0, deadline - time.monotonic()),
                ))
                self.task.next_frame()
            return
        if callable(burst) and burst(self.POST_HEAVY_NORMAL_ATTACKS, self.POST_HEAVY_NORMAL_ATTACK_INTERVAL):
            return
        for _ in range(self.POST_HEAVY_NORMAL_ATTACKS):
            self.check_combat()
            self.click(
                after_sleep=self.POST_HEAVY_NORMAL_ATTACK_INTERVAL,
            )

    def heavy_wait_highlight_down(self, deadline=None):
        if deadline is not None and time.monotonic() >= deadline:
            return False
        self.task.held_attack_interrupted = False
        try:
            self.task.mouse_down()
            if deadline is None:
                ret = self.task.wait_until(
                    lambda: not self.heavy_ready_state(),
                    time_out=1.2,
                )
            else:
                hold_deadline = min(deadline, time.monotonic() + 1.2)
                ret = False
                while time.monotonic() < hold_deadline:
                    self.check_combat()
                    if (getattr(self.task, 'held_attack_interrupted', False)
                            or time.monotonic() >= hold_deadline):
                        break
                    if not self.heavy_ready_state():
                        ret = True
                        break
                    self.task.next_frame()
        finally:
            self.task.mouse_up()
        self.sleep(0.01)
        return ret

    def heavy_ready_state(self):
        """Return the actual Aemeath heavy state instead of a target proxy."""
        human_heavy = self.task.find_one(
            'aemeath_human_heavy',
            threshold=self.HUMAN_HEAVY_MATCH_THRESHOLD,
            horizontal_variance=0.025,
            vertical_variance=0.025,
        )
        if human_heavy:
            return 'human'

        # The mecha form uses a different attack icon. Its reliable signal is
        # the cyan fill across the left half of Aemeath's Forte gauge.
        box = self.task.box_of_screen_scaled(
            3840,
            2160,
            1610,
            1964,
            1790,
            2016,
            name='aemeath_mecha_forte',
            hcenter=True,
        )
        cyan_percent = self.task.calculate_color_percentage(
            aemeath_mecha_forte_color,
            box,
        )
        if cyan_percent > self.MECHA_FORTE_READY_PERCENT:
            return 'mecha'
        return ''

    def handle_heavy(self, deadline=None):
        if deadline is not None and time.monotonic() >= deadline:
            return False
        if (
                self.time_elapsed_accounting_for_freeze(
                    self.last_heavy_attempt
                ) < self.HEAVY_RETRY_INTERVAL
        ):
            return False
        heavy_state = self.heavy_ready_state()
        if not heavy_state:
            return False
        if deadline is not None and time.monotonic() >= deadline:
            return False
        self.logger.info(
            f'Aemeath {heavy_state} heavy ready: hold normal attack'
        )
        prepares_lib2 = self.preparing_lib2()
        state_cleared = (self.heavy_wait_highlight_down() if deadline is None
                         else self.heavy_wait_highlight_down(deadline=deadline))
        self.last_heavy_attempt = time.time()
        if state_cleared:
            if prepares_lib2:
                self.record_heavy_liberation()
        else:
            self.logger.info(
                'Aemeath heavy signal stayed highlighted after release; '
                'continue with the basic string instead of holding again'
            )
        if not getattr(self.task, 'held_attack_interrupted', False):
            if deadline is None:
                self.post_heavy_normal_attack_burst()
            else:
                self.post_heavy_normal_attack_burst(deadline=deadline)
        return True
    def get_switch_priority(self, current_char=None, has_intro=False, target_low_con=False):
        if self.should_wait_for_lib2():
            # Mornye 离场且队里有 Linnai 时让位: Linnai 要吃 Mornye 协奏入场, 优先级最高, Aemeath 此刻
            # 不抢 MUST(否则两者都 MUST、按"最久未上场"决胜会切到 Aemeath). lib2 顺延到下次轮到 Aemeath.
            from src.char.Linnai import Linnai
            if current_char and current_char.char_name == 'char_moning' and self.task.has_char(Linnai):
                return super().get_switch_priority(current_char, has_intro, target_low_con)
            return SwitchPriority.MUST
        return super().get_switch_priority(current_char, has_intro, target_low_con)

    def on_combat_end(self, chars):
        self.switch_other_char()
