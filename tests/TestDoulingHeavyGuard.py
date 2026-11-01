"""Never repeat an unprepared hold or leave a mouse button down after rescue."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from src.char.Douling import Douling
from src.combat.MaterialBossHealing import BossHealRequested


class TestDoulingHeavyGuard(unittest.TestCase):
    def character(self):
        char = Douling.__new__(Douling)
        char.task = SimpleNamespace(frame=None, next_frame=Mock(), find_one=Mock(return_value=True),
                                    mouse_down=Mock(), mouse_up=Mock())
        char.check_combat = Mock()
        char.flying = Mock(return_value=False)
        char.logger = Mock()
        char.sleep = Mock()
        return char

    def test_unconfirmed_prompt_never_holds(self):
        char = self.character()
        char.task.find_one.return_value = None
        self.assertFalse(char._heavy_attack_hold(2.5))
        char.task.mouse_down.assert_not_called()

    def test_healing_interrupt_releases_button(self):
        char = self.character()
        char.sleep.side_effect = BossHealRequested(0, (2000, 10000))
        with self.assertRaises(BossHealRequested):
            char._heavy_attack_hold(2.5)
        char.task.mouse_down.assert_called_once()
        char.task.mouse_up.assert_called_once()

    def test_damage_prompt_cannot_authorize_healing(self):
        char = self.character()
        self.assertFalse(char.emergency_heal_actions())
        char.task.mouse_down.assert_not_called()

    def test_ready_healing_pair_is_spent_before_e_or_plunge_can_overwrite_it(self):
        for segment in (1, 2):
            char = self.character()
            char._segment = segment
            char.heavy_prompt_ready = Mock(return_value=True)
            events = []
            char._heavy_attack_hold = Mock(side_effect=lambda *a, **k: events.append('heal'))
            char._do_segment1 = Mock(side_effect=lambda: events.append('setup'))
            char._do_segment2 = Mock(side_effect=lambda: events.append('plunge'))
            char.do_perform()
            self.assertEqual(['heal', 'setup' if segment == 1 else 'plunge'], events)

    def test_consumed_prompt_ends_hold_without_repeat(self):
        char = self.character()
        char.task.find_one.side_effect = [True, None]
        self.assertTrue(char._heavy_attack_hold(2.5))
        char.task.mouse_down.assert_called_once()
        char.task.mouse_up.assert_called_once()


class TestDoulingHealingHud(unittest.TestCase):
    def test_recorded_healing_and_nonhealing_prompts_at_native_and_scaled_sizes(self):
        import cv2
        import numpy as np
        from pathlib import Path
        from src.char.DoulingHud import healing_heavy_visible
        folder = Path(__file__).parent / 'fixtures/douling-hud'
        for name in ('burst', 'regen', 'damage', 'hidden', 'jinhsi'):
            frame = np.zeros((1080, 1920, 3), np.uint8)
            frame[870:1050, 790:1500] = cv2.imread(str(folder / f'{name}.png'))
            for height in (720, 1080):
                scaled = cv2.resize(frame, (round(1920*height/1080), height))
                for left_padding in (0, 320):
                    wide = cv2.copyMakeBorder(scaled, 0, 0, left_padding, 0, cv2.BORDER_CONSTANT)
                    with self.subTest(name=name, height=height, left_padding=left_padding):
                        self.assertEqual(name in ('burst', 'regen'), healing_heavy_visible(wide))

    def test_verified_healing_prompt_can_issue_rescue_but_does_not_claim_hp_gain(self):
        from unittest.mock import patch
        char = TestDoulingHeavyGuard().character()
        with patch('src.char.Douling.healing_heavy_visible', side_effect=[True, False]):
            self.assertTrue(char.emergency_heal_actions())
        char.task.mouse_down.assert_called_once()
        char.task.mouse_up.assert_called_once()
