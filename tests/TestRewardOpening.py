import unittest
from unittest.mock import Mock
from src.task.MaterialRunUI import MaterialRunUI
from src.task.MaterialRunBudget import MaterialRunBudget

class TestRewardOpening(unittest.TestCase):
    def task(self, dialogs):
        t = MaterialRunUI()
        for name in ('focus_material_menu', 'walk_to_claim_prompt', 'next_frame', 'send_key', 'log_info'):
            setattr(t, name, Mock())
        t.reward_dialog_visible = Mock(side_effect=dialogs)
        t.find_treasure_icon = Mock(return_value=True)
        t.find_f_with_claim_text = Mock(return_value=True)
        t.settlement_batch_allowed = Mock(return_value=False)
        return t

    def test_open_dialog_is_not_toggled_closed(self):
        t = self.task([True])
        t.open_verified_reward()
        t.send_key.assert_not_called()
        t.walk_to_claim_prompt.assert_not_called()

    def test_unregistered_f_retries_before_spending(self):
        t = self.task([False, False, False, True])
        t.open_verified_reward()
        self.assertEqual(2, t.send_key.call_count)
        self.assertEqual(2, t.focus_material_menu.call_count)

    def test_unknown_screen_does_not_send_input(self):
        t = self.task([False])
        t.find_treasure_icon.return_value = False
        with self.assertRaisesRegex(RuntimeError, 'chest not visible'):
            t.open_verified_reward()
        t.send_key.assert_not_called()

    def test_pending_spending_never_reopens(self):
        t = self.task([])
        b = MaterialRunBudget()
        b.begin_claim()
        with self.assertRaisesRegex(RuntimeError, 'uncertain'):
            t.claim_one_reward(b)
        t.focus_material_menu.assert_not_called()

    def test_world_reward_text_alone_is_not_a_dialog(self):
        t = MaterialRunUI()
        t.wait_until = lambda fn, **kw: fn()
        t.menu_text = Mock(side_effect=[True, None, None])
        self.assertFalse(t.reward_dialog_visible())

    def test_title_and_claim_control_confirm_dialog(self):
        t = MaterialRunUI()
        t.wait_until = lambda fn, **kw: fn()
        t.menu_text = Mock(side_effect=[True, True])
        self.assertTrue(t.reward_dialog_visible())

    def test_deficit_waits_for_refill_without_a_second_claim_input(self):
        t = self.task([])
        t.open_verified_reward = Mock()
        t.get_stamina = Mock(side_effect=[(65, 0, 65), (125, 0, 125)])
        t.reward_option = Mock(return_value=(object(), 2))
        t.refill_text = Mock(return_value=True)
        t.refill_at_reward = Mock()
        t.reward_dialog_visible = Mock(return_value=True)
        t.click_box = Mock()
        t.verify_reward_result = Mock(return_value=45)
        b = MaterialRunBudget(max_solvents=1)
        self.assertEqual(45, t.claim_one_reward(b))
        t.refill_text.assert_called_once_with(r'补充结晶波片', timeout=8)
        t.refill_at_reward.assert_called_once_with(b, 65, 0, opened=True)
        self.assertEqual(2, t.click_box.call_count)

    def test_unidentified_deficit_remains_pending(self):
        t = self.task([])
        t.open_verified_reward = Mock()
        t.get_stamina = Mock(return_value=(65, 0, 65))
        t.reward_option = Mock(return_value=(object(), 2))
        t.refill_text = Mock(return_value=None)
        t.click_box = Mock()
        t.verify_reward_result = Mock(side_effect=RuntimeError('uncertain'))
        b = MaterialRunBudget()
        with self.assertRaisesRegex(RuntimeError, 'uncertain'):
            t.claim_one_reward(b)
        self.assertTrue(b.claim_pending)
        t.click_box.assert_called_once()

    def test_double_reward_does_not_require_repeat_battle_policy(self):
        t = MaterialRunUI()
        t.settlement_batch_allowed = Mock(return_value=False)
        single, double = object(), object()
        t.reward_text = Mock(side_effect=[single, True, double, True])
        button, multiplier = t.reward_option(MaterialRunBudget(2, 80, 0))
        self.assertIs(double, button)
        self.assertEqual(2, multiplier)
