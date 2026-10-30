import re
import time

from qfluentwidgets import FluentIcon

from ok import Logger
from ok.task.exceptions import CannotFindException
from src.task.BaseCombatTask import BaseCombatTask, NotInCombatException, CharDeadException
from src.task.WWOneTimeTask import WWOneTimeTask

logger = Logger.get_logger(__name__)

MANUAL_EXIT_CONFIRM_BOX = (0.22, 0.18, 0.78, 0.78)
MANUAL_EXIT_CONFIRM_TEXT = [
    re.compile(r'.*确认.*离开.*'),
    re.compile(r'.*確認.*離開.*'),
    re.compile(r'.*(Confirm.*Leave|Leave.*Domain).*', re.IGNORECASE),
]
_MANUAL_DOMAIN_EXIT_OVERRIDE_ACTIVE = False


def manual_domain_exit_override_active():
    """Keep trigger combat disabled after a domain task yields to the player."""
    return _MANUAL_DOMAIN_EXIT_OVERRIDE_ACTIVE


def set_manual_domain_exit_override(active):
    global _MANUAL_DOMAIN_EXIT_OVERRIDE_ACTIVE
    _MANUAL_DOMAIN_EXIT_OVERRIDE_ACTIVE = bool(active)


def domain_leave_confirmation_visible(task):
    """Recognize the leave confirmation by template or localized title."""
    if task.find_one('gray_confirm_exit_button', threshold=0.7):
        return True
    return bool(task.ocr(
        *MANUAL_EXIT_CONFIRM_BOX,
        match=MANUAL_EXIT_CONFIRM_TEXT,
        threshold=0.2,
    ))


class ManualDomainExitRequested(Exception):
    """The player opened the leave-domain confirmation during combat."""


class DomainTask(WWOneTimeTask, BaseCombatTask):
    DOMAIN_ENTRY_READY_DELAY = 1
    DOMAIN_ENTRY_FORWARD_TIME = 4
    DOMAIN_ENTRY_BACKWARD_TIME = 0
    DOMAIN_ENTRY_KEY_PULSE = 0
    TARGETLESS_HEALTH_PROBE_INTERVAL = 3.0
    TARGETLESS_COMBAT_GRACE_PERIOD = 300.0
    TARGETLESS_TARGET_RETRY_INTERVAL = 2.0
    TARGETLESS_END_PROBE_INTERVAL = 1.0
    MANUAL_EXIT_PROBE_INTERVAL = 0.10

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.teleport_timeout = 100
        self.stamina_once = 0
        self.group_name = "Dungeon"
        self.group_icon = FluentIcon.HOME
        self._manual_exit_requested = False
        self._last_manual_exit_probe = 0

    def allow_combat_without_target(self):
        """Domains are safe to fight when their enemy health bar is visible."""
        return True

    def targetless_health_probe_interval(self):
        return self.TARGETLESS_HEALTH_PROBE_INTERVAL

    def targetless_combat_grace_period(self):
        return self.TARGETLESS_COMBAT_GRACE_PERIOD

    def targetless_target_retry_interval(self):
        return self.TARGETLESS_TARGET_RETRY_INTERVAL

    def targetless_end_probe_interval(self):
        return self.TARGETLESS_END_PROBE_INTERVAL

    def domain_combat_finished(self):
        """Require a domain completion or death signal before ending combat."""
        return bool(
            self.find_treasure_icon()
            or self.find_one(
                'revive_confirm_hcenter_vcenter',
                threshold=0.8,
            )
        )

    def on_combat_started(self):
        """Reset manual control detection and start the current character."""
        set_manual_domain_exit_override(False)
        self._manual_exit_requested = False
        self._last_manual_exit_probe = 0
        self.log_info('domain combat: immediate opening attack')
        for _ in range(3):
            self.click(after_sleep=0.04)

    def manual_domain_exit_requested(self):
        """Detect the player's leave confirmation without clicking either choice."""
        if self._manual_exit_requested:
            return True
        now = time.time()
        if now - self._last_manual_exit_probe < self.MANUAL_EXIT_PROBE_INTERVAL:
            return False
        self._last_manual_exit_probe = now
        # This method is called before every combat input. OCR takes around two
        # seconds on macOS and used to serialize every normal attack behind that
        # delay. OCR only a positive button candidate: combat effects can
        # resemble this gray template and must not latch a manual stop alone.
        detected = bool(
            self.find_one('gray_confirm_exit_button', threshold=0.7)
        )
        if detected and self.ocr(*MANUAL_EXIT_CONFIRM_BOX,
                                 match=MANUAL_EXIT_CONFIRM_TEXT, threshold=.6):
            set_manual_domain_exit_override(True)
            self._manual_exit_requested = True
            self.log_info(
                'manual override: leave confirmation detected; '
                'stop combat immediately'
            )
            return True
        return False

    def _raise_if_manual_exit_before_input(self):
        """Block the next combat input as soon as the leave dialog is visible."""
        if (
                getattr(self, '_in_combat', False)
                and self.manual_domain_exit_requested()
        ):
            raise ManualDomainExitRequested()

    def click(self, *args, **kwargs):
        self._raise_if_manual_exit_before_input()
        return super().click(*args, **kwargs)

    def mouse_down(self, *args, **kwargs):
        self._raise_if_manual_exit_before_input()
        return super().mouse_down(*args, **kwargs)

    def send_key(self, *args, **kwargs):
        self._raise_if_manual_exit_before_input()
        return super().send_key(*args, **kwargs)

    def send_key_down(self, *args, **kwargs):
        self._raise_if_manual_exit_before_input()
        return super().send_key_down(*args, **kwargs)

    def in_combat(self, target=False):
        """Abort the combat stack when the player opens the leave dialog."""
        if (
                getattr(self, '_in_combat', False)
                and self.manual_domain_exit_requested()
        ):
            raise ManualDomainExitRequested()
        return super().in_combat(target=target)

    def revive_action(self):
        """副本内死亡恢复：关闭弹窗 → 退出副本 → 传最近传送点回血。"""

        # ① 关闭复活弹窗 (点按钮优先, esc 兜底, 与 BaseCombatTask 共用)
        self.close_revive_popup()

        # ② 打开退出菜单
        self.send_key('esc')
        self.sleep(1)

        # ③ 确认离开
        self.wait_click_feature('gray_confirm_exit_button',
                                relative_x=-1, raise_if_not_found=False,
                                time_out=3, click_after_delay=0.5, threshold=0.7)

        # ④ 必须确认已回到大世界队伍态后，再继续走 F2/传送流程
        if not self.wait_in_team_and_world(time_out=max(self.teleport_timeout, 120), raise_if_not_found=False):
            return False
        self.sleep(0.5)
        self.revive_at_tower_and_heal()
        return True

    def make_sure_in_world(self):
        if self.in_realm():
            self.send_key('esc', after_sleep=1)
            self.wait_click_feature('gray_confirm_exit_button', relative_x=-1, raise_if_not_found=False,
                                    time_out=3, click_after_delay=0.5, threshold=0.7, after_sleep=1)
            self.wait_in_team_and_world(time_out=self.teleport_timeout)
        else:
            self.ensure_main()

    def open_F2_book_and_get_stamina(self):
        self.open_materials_book()
        return self.get_stamina()

    def farm_domain_with_recovery_loop(self, must_use, teleport_into_domain_once, max_recovery_retries=3):
        """包装副本刷取循环：死亡恢复后自动从 F2 重新进入，并限制重试次数。"""
        recovery_retries = 0
        while True:
            current, _, total = self.open_F2_book_and_get_stamina()
            if total < self.stamina_once or total < must_use or (must_use == 0 and current < self.stamina_once):
                self.log_info('not enough stamina', notify=True)
                self.back()
                return
            teleport_into_domain_once()
            self.sleep(1)
            try:
                finished, must_use = self.farm_in_domain(must_use=must_use)
            except ManualDomainExitRequested:
                # Release a possible held heavy attack, but leave the player's
                # confirmation dialog and choice completely untouched.
                self.mouse_up()
                self.log_info(
                    'manual override: material farming stopped; '
                    'leave confirmation left to player',
                    notify=True,
                )
                return
            if finished:
                return
            recovery_retries += 1
            if recovery_retries >= max_recovery_retries:
                self.log_info(f'farm_domain: exceeded recovery retries ({max_recovery_retries}), stop farming',
                              notify=True)
                self.make_sure_in_world()
                return
            self.log_info('farm_domain: death recovered, re-enter from F2 book')
            self.sleep(1)

    def walk_to_domain_interaction(self):
        """Walk from the domain spawn point until its interaction prompt appears."""
        ready_delay = self.DOMAIN_ENTRY_READY_DELAY
        if ready_delay > 0:
            self.log_info(
                f'domain entry: wait {ready_delay}s for character controls'
            )
            self.sleep(ready_delay)

        pulse_duration = self.DOMAIN_ENTRY_KEY_PULSE
        if pulse_duration <= 0:
            return self.walk_until_f(
                time_out=self.DOMAIN_ENTRY_FORWARD_TIME,
                backward_time=self.DOMAIN_ENTRY_BACKWARD_TIME,
                raise_if_not_found=True,
            )

        if self.find_f_with_text():
            return True

        self.middle_click(after_sleep=0.2)
        pulse_count = max(
            1,
            round(self.DOMAIN_ENTRY_FORWARD_TIME / pulse_duration),
        )
        self.log_info(
            f'domain entry: press w {pulse_count} time(s), '
            f'{pulse_duration}s per press'
        )
        for _ in range(pulse_count):
            self.send_key(
                'w',
                down_time=pulse_duration,
                after_sleep=0.05,
            )
            if self.find_f_with_text():
                self.log_info('domain entry: forward key presses found f')
                return True

        self.screenshot('domain_entry_f_not_found')
        self.log_error(
            'domain entry: w key presses completed but f was not found'
        )
        raise CannotFindException('cant find the f to enter')

    def farm_in_domain(self, must_use=0):
        """刷本循环；返回 (是否整段正常结束, 剩余 must_use)。

        第二项在死亡提前退出时仍会带上本局内已扣过的额度，供外层恢复循环继续传参。
        """
        if self.stamina_once <= 0:
            raise RuntimeError('"self.stamina_once" must be override')
        self.info_incr('used stamina', 0)
        while True:
            self.walk_to_domain_interaction()
            self.combat_end_condition = self.domain_combat_finished
            self.pick_f(handle_claim=False)
            try:
                try:
                    self.combat_once()
                finally:
                    self._domain_chars_preloaded = False
                self.sleep(3)
                self.walk_to_treasure()
                self.pick_f(handle_claim=False)
            except (NotInCombatException, CharDeadException):
                self.log_info('farm_in_domain: death recovered, exiting domain')
                self.make_sure_in_world()
                return False, must_use
            can_continue, used = self.use_stamina(once=self.stamina_once, must_use=must_use)
            self.info_incr('used stamina', used)
            must_use -= used
            self.sleep(4)
            if not can_continue:
                self.log_info("used all stamina")
                break
            self.click(0.68, 0.84, after_sleep=1)  # farm again
            if confirm := self.wait_feature(
                    ['confirm_btn_hcenter_vcenter', 'confirm_btn_highlight_hcenter_vcenter'],
                    raise_if_not_found=False,
                    threshold=0.6,
                    time_out=2):
                self.click(0.49, 0.55, after_sleep=0.5)  # 点击不再提醒
                self.click(confirm, after_sleep=0.5)
                self.wait_click_feature(
                    ['confirm_btn_hcenter_vcenter', 'confirm_btn_highlight_hcenter_vcenter'],
                    relative_x=-1, raise_if_not_found=False,
                    threshold=0.6,
                    time_out=1)
            self.wait_in_team_and_world(time_out=self.teleport_timeout)
            self.sleep(1)
        #
        self.click(0.42, 0.84, after_sleep=2)  # back to world
        self.make_sure_in_world()
        return True, must_use
