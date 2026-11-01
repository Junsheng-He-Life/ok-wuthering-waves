"""Alternate healers retain bounded inputs and observed-HP rescue decisions."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from src.char.Baizhi import Baizhi
from src.char.Verina import Verina
from src.combat.MaterialBossHealing import BossHealRequested, MaterialBossHealing
from src.task.VerifiedDomainCombat import DomainBattleFailed


class TestAlternateHealerActions(unittest.TestCase):
    def character(self, cls):
        char = cls.__new__(cls)
        char.task = SimpleNamespace(
            _verified_battle=True, _plan_boss=False,
            use_bounded_liberation_retry=lambda: True,
            next_frame=Mock(), mouse_up=Mock())
        char.check_combat = Mock()
        char.liberation_available = Mock(return_value=False)
        char.resonance_available = Mock(return_value=False)
        char.is_mouse_forte_full = Mock(return_value=False)
        char.click_liberation = Mock(return_value=False)
        char.click_resonance = Mock(return_value=(False, 0, False))
        char.heavy_attack = Mock()
        return char

    def test_ready_r_does_not_wait_for_concerto_or_run_whole_rotation(self):
        for cls in (Verina, Baizhi):
            with self.subTest(cls=cls):
                char = self.character(cls)
                char.liberation_available.return_value = True
                char.click_liberation.return_value = True
                self.assertTrue(char.emergency_heal_actions())
                char.click_liberation.assert_called_once_with(wait_if_cd_ready=0)
                char.click_resonance.assert_not_called()
                char.heavy_attack.assert_not_called()

    def test_empty_r_never_enters_cast_wait(self):
        for cls in (Verina, Baizhi):
            char = self.character(cls)
            self.assertFalse(char.emergency_heal_actions())
            char.click_liberation.assert_not_called()
            char.click_resonance.assert_not_called()

    def test_no_legacy_unbounded_r_in_unverified_task(self):
        for cls in (Verina, Baizhi):
            char = self.character(cls)
            char.task._verified_battle = False
            char.liberation_available.return_value = True
            self.assertFalse(char.emergency_heal_actions())
            char.click_liberation.assert_not_called()

    def test_no_legacy_unbounded_r_without_retry_policy(self):
        for cls in (Verina, Baizhi):
            char = self.character(cls)
            char.task.use_bounded_liberation_retry = None
            char.liberation_available.return_value = True
            self.assertFalse(char.emergency_heal_actions())
            char.click_liberation.assert_not_called()

    def test_baizhi_failed_e_tuple_is_not_truthy_success(self):
        char = self.character(Baizhi)
        char.resonance_available.return_value = True
        self.assertFalse(char.emergency_heal_actions())
        char.click_resonance.assert_called_once_with(send_click=False, time_out=.6)

    def test_baizhi_can_request_e_after_unconfirmed_r(self):
        char = self.character(Baizhi)
        char.liberation_available.return_value = True
        char.resonance_available.return_value = True
        char.click_resonance.return_value = (True, .4, False)
        self.assertTrue(char.emergency_heal_actions())
        self.assertEqual(2, char.task.next_frame.call_count)

    def test_verina_e_without_explicit_heavy_prompt_is_not_healing_action(self):
        char = self.character(Verina)
        char.resonance_available.return_value = True
        char.click_resonance.return_value = (True, .4, False)
        self.assertFalse(char.emergency_heal_actions())
        char.heavy_attack.assert_not_called()

    def test_verina_uses_fresh_prompt_after_e_for_short_heavy(self):
        char = self.character(Verina)
        char.resonance_available.return_value = True
        char.click_resonance.side_effect = lambda **kw: (True, .4, False)
        char.is_mouse_forte_full.side_effect = lambda: char.task.next_frame.call_count == 3
        self.assertTrue(char.emergency_heal_actions())
        char.heavy_attack.assert_called_once_with(.7)
        self.assertEqual(3, char.check_combat.call_count)

    def test_guard_abort_never_leaves_mouse_held_or_attempts_skill(self):
        for cls in (Verina, Baizhi):
            char = self.character(cls)
            char.check_combat.side_effect = DomainBattleFailed('stop')
            with self.assertRaises(DomainBattleFailed):
                char.emergency_heal_actions()
            self.assertEqual(2, char.task.mouse_up.call_count)
            char.click_resonance.assert_not_called()
            char.click_liberation.assert_not_called()


class TestAlternateHealerHPVerification(unittest.TestCase):
    def task(self, healer_name, hp=(6000, 10000), observed_slot=0):
        task = MaterialBossHealing()
        task.chars = [SimpleNamespace(char_name='char_changli', confidence=.99, index=0),
                      SimpleNamespace(char_name='char_encore', confidence=.99, index=1),
                      SimpleNamespace(char_name=healer_name, confidence=.99, index=2,
                                      emergency_heal_actions=Mock(return_value=True))]
        task.in_team = Mock(return_value=(True, observed_slot, 3))
        task.result = {}
        task.mouse_up = task.next_frame = task.log_info = Mock()
        task.healing_switch = Mock()
        task.read_current_hp = Mock(return_value=hp)
        task.wait_until = lambda predicate, **kw: predicate()
        return task

    def test_alternate_healers_are_requested_for_injured_ally(self):
        for name in ('char_verina', 'char_baizhi'):
            with self.assertRaises(BossHealRequested):
                self.task(name).request_boss_healing((5000, 10000))

    def test_actual_original_ally_hp_gain_required(self):
        for name in ('char_verina', 'char_baizhi'):
            task = self.task(name)
            task.heal_material_boss(BossHealRequested(0, (5000, 10000)))
            self.assertEqual('verified', task.result['healing'][0]['status'])
            self.assertIs(task.chars[0], task.healing_switch.call_args.args[0])

    def test_cast_without_gain_or_wrong_slot_never_verifies_healing(self):
        for name in ('char_verina', 'char_baizhi'):
            for hp, slot in [((5000, 10000), 0), ((9000, 10000), 2)]:
                task = self.task(name, hp, slot)
                with self.assertRaises(DomainBattleFailed):
                    task.heal_material_boss(BossHealRequested(0, (5000, 10000)))
                self.assertEqual('failed', task.result['healing'][0]['status'])

    def test_no_healing_resource_still_requires_healthy_replacement(self):
        for name in ('char_verina', 'char_baizhi'):
            task = self.task(name)
            task.chars[2].emergency_heal_actions.return_value = False
            task.verify_healing_replacement = Mock(return_value=task.chars[1])
            task.heal_material_boss(BossHealRequested(0, (3800, 10000)))
            task.verify_healing_replacement.assert_called_once_with(0)
            self.assertEqual('deferred_to_healthy_ally', task.result['healing'][0]['status'])


if __name__ == '__main__':
    unittest.main()
