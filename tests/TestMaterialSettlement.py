import unittest
import time
from unittest.mock import Mock
from src.task.MaterialSettlement import MaterialSettlement
from src.task.MaterialRunBudget import MaterialRunBudget


class TestMaterialSettlement(unittest.TestCase):
    def task(self):
        t = MaterialSettlement()
        t.config = {'结算批次策略': '效率优先'}
        t.plan_job = {'kind': '武器/技能', 'material_counts': [[1,80]]}
        t._settlement_health = (time.monotonic(), [.99,.95,.90])
        t.menu_text = Mock(return_value=object())
        t.focus_material_menu = t.click_box = t.log_info = Mock()
        t.handle_material_entry_notice = Mock()
        t.wait_until = Mock(return_value=True)
        return t

    def test_double_charges_two_units_and_exact_eighty(self):
        b = MaterialRunBudget(2,80)
        b.begin_claim(2)
        with self.assertRaises(RuntimeError):
            b.finish_claim(100,60)
        self.assertTrue(b.claim_pending)
        b.finish_claim(100,20)
        self.assertEqual((2,80), (b.claimed,b.spent))
        self.assertFalse(b.can_claim())

    def test_insufficient_unit_budget_never_allows_double(self):
        self.assertFalse(MaterialRunBudget(1,80).can_claim(2))
        self.assertFalse(MaterialRunBudget(2,40).can_claim(2))

    def test_repeat_requires_health_and_separate_battle_count(self):
        t = self.task()
        self.assertTrue(t.try_repeat_material(MaterialRunBudget(), 40, 1))
        self.assertTrue(t._material_restarted)
        t=self.task()
        self.assertTrue(t.try_repeat_material(MaterialRunBudget(), 0, 1))
        for health, units, stamina in [([.9,None,.9],1,40), ([.9,.5,.9],1,40),
                                       ([.9,.9,.9],2,80)]:
            t=self.task(); t._settlement_health=(time.monotonic(),health)
            self.assertFalse(t.try_repeat_material(MaterialRunBudget(),stamina,units))
            t.click_box.assert_not_called()
        t=self.task();t._settlement_health=(time.monotonic()-91,[1,1,1])
        self.assertFalse(t.try_repeat_material(MaterialRunBudget(),40,1))

    def test_double_claim_can_repeat_but_second_battle_ends_batch(self):
        t = self.task()
        budget = MaterialRunBudget(6, 240)
        budget.begin_claim(2)
        budget.finish_claim(240, 160)
        self.assertTrue(t.try_repeat_material(budget, 160, 1))
        self.assertEqual((0, []), t._settlement_health)
        t = self.task()
        self.assertFalse(t.try_repeat_material(budget, 160, 2))
        t.click_box.assert_not_called()

    def test_delayed_verified_settlement_keeps_post_victory_health(self):
        t = self.task()
        t._settlement_health = (time.monotonic() - 45, [.99, .95, .9])
        self.assertTrue(t.try_repeat_material(MaterialRunBudget(4, 160), 80, 1))

    def test_single_battle_preference_preserves_old_recheck_frequency(self):
        t = self.task()
        t.config['每批连续挑战场数'] = 1
        self.assertFalse(t.try_repeat_material(MaterialRunBudget(4, 160), 80, 1))

    def test_satisfied_or_boss_never_batches(self):
        for job in ({'kind':'周本','material_counts':[[0,24]]},
                    {'kind':'武器/技能','material_counts':[[80,80]]}):
            t=self.task();t.plan_job=job
            self.assertFalse(t.settlement_batch_allowed())
