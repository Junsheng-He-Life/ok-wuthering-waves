import time
import unittest
from pathlib import Path
from unittest import mock
from config import config
from ok.feature.Box import Box
from ok.test.TaskTestCase import TaskTestCase
from src.char.BaseChar import BaseChar
from src.Labels import Labels
from src.char.CharFactory import get_char_by_hint, get_char_by_pos
from src.combat.CombatCheck import CombatCheck
from src.task.AutoCombatTask import AutoCombatTask
from src.task.BaseCombatTask import BaseCombatTask
from src.task.DomainTask import (
    DomainTask,
    ManualDomainExitRequested,
    manual_domain_exit_override_active,
    set_manual_domain_exit_override,
)

config['debug'] = True


def return_true():
    return True


class TestCombatCheck(TaskTestCase):
    task_class = AutoCombatTask
    config = config

    def test_in_combat_check(self):
        self.task.ensure_levitator = return_true
        self.task.do_reset_to_false()
        self.set_image('tests/images/in_combat.png')
        in_combat = self.task.in_combat()
        # self.task.screenshot('in_combat.png', show_box=True)
        # time.sleep(1)
        self.assertTrue(in_combat)

    @unittest.skipUnless(Path('ok_templates/57d8d801-BitBlt_True_3840x2160_1759986393607.1733_original.png').is_file(),
                         'Optional historical 4K capture is not distributed')
    def test_4k_combat_check(self):
        self.task.ensure_levitator = return_true
        self.task.do_reset_to_false()
        self.set_image("ok_templates/57d8d801-BitBlt_True_3840x2160_1759986393607.1733_original.png")
        in_combat = self.task.in_combat()
        # self.task.screenshot('in_combat4k.png', show_box=True)
        # time.sleep(1)
        self.assertTrue(in_combat)

    def test_not_in_combat_check(self):
        self.task.ensure_levitator = return_true
        self.task.do_reset_to_false()
        self.set_image('tests/images/in_combat3.png')
        in_combat = self.task.in_combat()
        self.assertFalse(in_combat)

    def test_in_combat_cloud(self):
        self.task.ensure_levitator = return_true
        self.task.do_reset_to_false()
        self.task.is_browser = return_true
        self.set_image('tests/images/cloud_game_combat.png')
        in_combat = self.task.in_combat()
        self.assertTrue(in_combat)

    @unittest.skipUnless(Path('ok_templates/browser_in_combat.png').is_file(),
                         'Optional historical browser capture is not distributed')
    def test_in_combat_cloud2(self):
        self.task.ensure_levitator = return_true
        self.task.do_reset_to_false()
        self.task.is_browser = return_true
        self.set_image('ok_templates/browser_in_combat.png')
        in_combat = self.task.in_combat()
        self.assertTrue(in_combat)

    @unittest.skipUnless(Path('ok_templates/25.png').is_file(),
                         'Optional historical target capture is not distributed')
    def test_target_box_short(self):
        self.set_image('ok_templates/25.png')
        self.task.chars = [BaseChar(self.task, 0)]
        self.task.chars[0].is_current_char = True
        self.assertFalse(self.task.has_target())

        self.task.chars[0].target_box_short_combat_check = True
        self.assertTrue(self.task.has_target())
        self.assertTrue(BaseChar(self.task, 0).has_short_action())

    def test_lucilla_enables_target_box_short_combat_check_from_char_factory(self):
        class Box:
            def __init__(self, name):
                self.name = name

        class Match:
            def __init__(self, name):
                self.name = name
                self.confidence = 0.95

        class Task:
            char_config = {}

            def find_one(self, name, box=None, threshold=0.6):
                return Match(name) if name == Labels.char_lucilla else None

            def find_best_match_in_box(self, box, names, threshold=0.6):
                return Match(Labels.char_lucilla)

            def log_info(self, *args, **kwargs):
                pass

        lucilla = get_char_by_pos(Task(), Box('box_char_1'), 0, None)

        self.assertTrue(lucilla.target_box_short_combat_check)

    def test_enter_combat_loads_chars_before_target_check(self):
        task = AutoCombatTask.__new__(AutoCombatTask)
        task._in_combat = False
        task.in_liberation = False
        task.chars = [None, None, None]
        task.config = {'Auto Target': True}
        task.target_enemy_error_notified = False
        task.find_one = lambda *args, **kwargs: False
        task.log_info = lambda *args, **kwargs: None
        order = []

        class Char:
            is_current_char = True

        def load_chars():
            order.append('load_chars')
            task.chars = [Char()]
            return True

        def has_target():
            order.append(('has_target', task.get_current_char() is not None))
            return True

        task.load_chars = load_chars
        task.has_target = has_target

        self.assertTrue(task.do_check_in_combat(False))
        self.assertEqual(order, ['load_chars', ('has_target', True)])


class TestTargetlessDomainCombat(unittest.TestCase):
    def test_cached_character_hint_checks_only_expected_template(self):
        calls = []

        class Match:
            confidence = 0.91

        class Task:
            char_config = {}

            def find_one(self, name, box=None, threshold=0.6):
                calls.append(name)
                return Match()

        char = get_char_by_hint(
            Task(),
            object(),
            0,
            Labels.char_aemeath,
        )

        self.assertEqual('Aemeath', type(char).__name__)
        self.assertEqual([Labels.char_aemeath], calls)

    def test_weak_cached_character_hint_is_rejected(self):
        calls = []

        class Match:
            confidence = 0.65

        class Task:
            char_config = {}

            def find_one(self, name, box=None, threshold=0.6):
                calls.append((name, threshold))
                return Match()

        char = get_char_by_hint(
            Task(),
            object(),
            0,
            Labels.char_aemeath,
        )

        self.assertIsNone(char)
        self.assertEqual(Labels.char_aemeath, calls[0][0])
        self.assertGreater(calls[0][1], 0.65)

    def test_domain_enters_combat_from_health_bar_without_lock_on(self):
        task = CombatCheck.__new__(CombatCheck)
        task._in_combat = False
        task._in_liberation = False
        task.chars = [object(), object(), object()]
        task.config = {}
        task.target_enemy_error_notified = False
        task.targetless_combat_notified = False
        task.last_targetless_target_attempt = 0
        task.last_targetless_health_probe = 0
        task.last_targetless_health_confirmed = 0
        task.last_targetless_end_probe = 0
        task.allow_combat_without_target = (
            DomainTask.allow_combat_without_target.__get__(task)
        )
        task.combat_chars_ready = lambda: False
        task.targetless_health_probe_interval = lambda: 1
        task.targetless_combat_grace_period = lambda: 3
        task.targetless_target_retry_interval = lambda: 1
        task.load_chars = lambda: True
        task.has_target = lambda: False
        task.check_health_bar = lambda: True
        task.find_one = lambda *args, **kwargs: None
        task.log_info = lambda *args, **kwargs: None
        target_attempts = []
        task.target_enemy = lambda wait=True: target_attempts.append(wait)

        class Scene:
            def set_in_combat(self):
                return True

        task.scene = Scene()

        self.assertTrue(task.do_check_in_combat(False))
        self.assertEqual([False], target_attempts)
        self.assertTrue(task._in_combat)

    def test_domain_keeps_fighting_when_lock_on_drops(self):
        task = CombatCheck.__new__(CombatCheck)
        task._in_combat = True
        task._in_liberation = False
        task.targetless_combat_notified = False
        task.last_targetless_target_attempt = 0
        task.last_targetless_health_probe = 0
        task.last_targetless_health_confirmed = 0
        task.last_targetless_end_probe = 0
        task.combat_end_condition = None
        task.allow_combat_without_target = (
            DomainTask.allow_combat_without_target.__get__(task)
        )
        task.get_current_char = lambda: None
        task.on_combat_check = lambda: True
        task.targetless_health_probe_interval = lambda: 1
        task.targetless_combat_grace_period = lambda: 3
        task.targetless_target_retry_interval = lambda: 1
        task.check_f_break = lambda: None
        task.has_target = lambda: False
        task.check_health_bar = lambda: True
        task.log_info = lambda *args, **kwargs: None
        target_attempts = []
        task.target_enemy = lambda wait=True: target_attempts.append(wait)

        class Scene:
            def in_combat(self):
                return None

            def set_in_combat(self):
                return True

        task.scene = Scene()

        self.assertTrue(task.do_check_in_combat(False))
        self.assertEqual([False], target_attempts)

    def test_targetless_grace_skips_expensive_visual_checks(self):
        task = CombatCheck.__new__(CombatCheck)
        task._in_combat = True
        task._in_liberation = False
        task.targetless_combat_notified = True
        task.last_targetless_target_attempt = 100
        task.last_targetless_health_probe = 100
        task.last_targetless_health_confirmed = 100
        task.last_targetless_end_probe = 100
        task.combat_end_condition = None
        task.allow_combat_without_target = (
            DomainTask.allow_combat_without_target.__get__(task)
        )
        task.targetless_health_probe_interval = lambda: 1
        task.targetless_combat_grace_period = lambda: 3
        task.targetless_target_retry_interval = lambda: 1
        task.check_f_break = mock.Mock()
        task.has_target = lambda: self.fail(
            'fast targetless path must not scan the lock-on indicator'
        )
        task.check_health_bar = lambda: self.fail(
            'health bar must not be scanned before the probe interval'
        )

        class Scene:
            def in_combat(self):
                return None

            def set_in_combat(self):
                return True

        task.scene = Scene()

        with mock.patch('src.combat.CombatCheck.time.time', return_value=100.2):
            self.assertTrue(task.do_check_in_combat(False))
        task.check_f_break.assert_called_once_with()

    def test_missing_health_bar_expires_after_grace_without_retargeting(self):
        task = CombatCheck.__new__(CombatCheck)
        task.allow_combat_without_target = lambda: True
        task.last_targetless_health_probe = 100
        task.last_targetless_health_confirmed = 100
        task.last_targetless_target_attempt = 102
        task.targetless_combat_notified = True
        task.targetless_health_probe_interval = lambda: .25
        task.targetless_combat_grace_period = lambda: 3
        task.targetless_target_retry_interval = lambda: 2
        task.check_health_bar = mock.Mock(return_value=False)
        task.target_enemy = mock.Mock()
        task.scene = mock.Mock()
        task.scene.set_in_combat.return_value = True
        with mock.patch('src.combat.CombatCheck.time.time', return_value=102.5):
            self.assertTrue(task.keep_targetless_combat())
        with mock.patch('src.combat.CombatCheck.time.time', return_value=103.01):
            self.assertFalse(task.keep_targetless_combat())
        task.target_enemy.assert_not_called()
        self.assertEqual(task.last_targetless_health_confirmed, 100)

    def test_domain_requires_treasure_or_death_to_finish_combat(self):
        class Task:
            treasure = None
            revive = None

            def find_treasure_icon(self):
                return self.treasure

            def find_one(self, name, threshold):
                self.assertEqual(
                    'revive_confirm_hcenter_vcenter',
                    name,
                )
                return self.revive

        task = Task()
        task.assertEqual = self.assertEqual

        self.assertFalse(DomainTask.domain_combat_finished(task))
        task.treasure = object()
        self.assertTrue(DomainTask.domain_combat_finished(task))
        task.treasure = None
        task.revive = object()
        self.assertTrue(DomainTask.domain_combat_finished(task))

    def test_combat_once_reuses_preloaded_characters(self):
        calls = []

        class Task:
            info = {}
            chars = []

            def wait_combat(self, **kwargs):
                calls.append(('wait_combat', kwargs))
                return True

            def combat_chars_ready(self):
                return True

            def load_chars(self):
                self.fail('combat_once must reuse the preloaded team')

            def in_combat(self):
                return False

            def on_combat_started(self):
                calls.append(('on_combat_started',))

            def combat_end(self):
                calls.append(('combat_end',))

            def switch_healer(self):
                calls.append(('switch_healer',))

            def wait_in_team_and_world(self, **kwargs):
                calls.append(('wait_in_team_and_world', kwargs))

        result = BaseCombatTask.combat_once(Task())

        self.assertTrue(result)
        self.assertIn(('on_combat_started',), calls)
        self.assertIn(('combat_end',), calls)

    def test_combat_once_runs_current_character_perform(self):
        calls = []

        class CurrentChar:
            def perform(self):
                calls.append(('perform',))

        class Task:
            info = {}
            chars = [CurrentChar()]
            combat_checks = 0

            def wait_combat(self, **kwargs):
                return True

            def combat_chars_ready(self):
                return True

            def on_combat_started(self):
                calls.append(('on_combat_started',))

            def in_combat(self):
                self.combat_checks += 1
                return self.combat_checks == 1

            def get_current_char(self):
                return self.chars[0]

            def combat_end(self):
                calls.append(('combat_end',))

            def switch_healer(self):
                pass

            def wait_in_team_and_world(self, **kwargs):
                return True

        BaseCombatTask.combat_once(Task())

        self.assertEqual(
            [('on_combat_started',), ('perform',), ('combat_end',)],
            calls,
        )

    def test_manual_leave_dialog_raises_out_of_character_rotation(self):
        class Task:
            _in_combat = True

            def manual_domain_exit_requested(self):
                return True

        with self.assertRaises(ManualDomainExitRequested):
            DomainTask.in_combat(Task())

    def test_manual_leave_ocr_helper_remains_available_off_hot_path(self):
        class Task:
            def find_one(self, *_args, **_kwargs):
                return None

            def ocr(self, *_args, **_kwargs):
                return [Box(700, 350, 200, 40, name='确认离开')]

        from src.task.DomainTask import domain_leave_confirmation_visible

        self.assertTrue(domain_leave_confirmation_visible(Task()))

    def test_exit_template_false_positive_does_not_latch_stop(self):
        from types import SimpleNamespace
        task = SimpleNamespace(_manual_exit_requested=False, _last_manual_exit_probe=0,
                               MANUAL_EXIT_PROBE_INTERVAL=0, find_one=mock.Mock(return_value=True),
                               ocr=mock.Mock(return_value=[]), log_info=mock.Mock())
        self.assertFalse(DomainTask.manual_domain_exit_requested(task))
        self.assertFalse(task._manual_exit_requested)
        task.ocr.assert_called_once()

    def test_verified_exit_dialog_still_stops_without_clicking(self):
        from types import SimpleNamespace
        task = SimpleNamespace(_manual_exit_requested=False, _last_manual_exit_probe=0,
                               MANUAL_EXIT_PROBE_INTERVAL=0, find_one=mock.Mock(return_value=True),
                               ocr=mock.Mock(return_value=[Box(700,350,200,40,name='确认离开')]),
                               log_info=mock.Mock())
        try:
            self.assertTrue(DomainTask.manual_domain_exit_requested(task))
            self.assertTrue(task._manual_exit_requested)
        finally:
            set_manual_domain_exit_override(False)

    def test_manual_leave_hot_path_does_not_run_ocr(self):
        class Task:
            _manual_exit_requested = False
            _last_manual_exit_probe = 0
            MANUAL_EXIT_PROBE_INTERVAL = 0

            def find_one(self, *_args, **_kwargs):
                return None

            def ocr(self, *_args, **_kwargs):
                self.fail('combat input guard must not run OCR')

            def log_info(self, _message):
                pass

        task = Task()
        task.fail = self.fail
        self.assertFalse(DomainTask.manual_domain_exit_requested(task))

    def test_domain_combat_starts_with_three_fast_attacks(self):
        clicks = []

        class Task:
            _manual_exit_requested = True
            _last_manual_exit_probe = 123

            def log_info(self, _message):
                pass

            def click(self, **kwargs):
                clicks.append(kwargs)

        DomainTask.on_combat_started(Task())

        self.assertEqual(3, len(clicks))
        self.assertTrue(all(
            click['after_sleep'] == 0.04 for click in clicks
        ))

    def test_manual_leave_dialog_blocks_next_combat_input(self):
        class Task:
            _in_combat = True
            _raise_if_manual_exit_before_input = (
                DomainTask._raise_if_manual_exit_before_input
            )

            def manual_domain_exit_requested(self):
                return True

        with self.assertRaises(ManualDomainExitRequested):
            DomainTask.click(Task())

    def test_manual_override_stops_recovery_loop_and_releases_mouse(self):
        calls = []

        class Task:
            stamina_once = 40

            def open_F2_book_and_get_stamina(self):
                return 240, 0, 240

            def back(self):
                self.fail('manual override must not return to the book')

            def sleep(self, duration):
                calls.append(('sleep', duration))

            def farm_in_domain(self, must_use):
                raise ManualDomainExitRequested()

            def mouse_up(self):
                calls.append(('mouse_up',))

            def log_info(self, message, notify=False):
                calls.append(('log', message, notify))

        task = Task()
        task.fail = self.fail
        teleports = []
        DomainTask.farm_domain_with_recovery_loop(
            task,
            must_use=0,
            teleport_into_domain_once=lambda: teleports.append(True),
        )

        self.assertEqual([True], teleports)
        self.assertIn(('mouse_up',), calls)
        self.assertTrue(any(
            call[0] == 'log' and 'manual override' in call[1]
            for call in calls
        ))

if __name__ == '__main__':
    unittest.main()
