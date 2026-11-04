"""Replay the observed rescue and reject buffs, stale frames and other slots."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from src.combat.HealingVerification import conservative_hp_reference, verified_healing_maximum
from src.combat.MaterialBossHealing import MaterialBossHealing, BossHealRequested
from src.task.VerifiedDomainCombat import DomainBattleFailed


class TestHealingMaximumChange(unittest.TestCase):
    @staticmethod
    def observation(hp, sequence=1, slot=1, bar=None, **extra):
        bars=[1.,1.,1.];bars[slot]=hp[0]/hp[1] if bar is None else bar
        return {'team_verified':True,'slot_at_decision':slot,'parsed':list(hp),
                'portrait_ratios':bars,'capture_sequence':sequence,**extra}

    def test_recorded_gain_exceeds_the_entire_maximum_increase(self):
        reference=conservative_hp_reference((10401,17620),18697)
        self.assertEqual((11478,18697),reference)
        self.assertTrue(MaterialBossHealing.healing_progress(reference,[],(13641,18697)))

    def test_buff_only_or_maximum_reduction_cannot_establish_healing(self):
        before=(10401,17620)
        for maximum,current in ((18697,10401),(18697,11037),(18697,11478),
                                (16000,10401),(16000,9445)):
            reference=conservative_hp_reference(before,maximum)
            self.assertFalse(MaterialBossHealing.healing_progress(reference,[],(current,maximum)))

    def test_same_frame_cannot_supply_the_second_maximum_confirmation(self):
        hp=(13641,18697);samples=[];observation=self.observation(hp)
        self.assertFalse(verified_healing_maximum(hp,1,observation,samples))
        self.assertFalse(verified_healing_maximum(hp,1,observation,samples))
        self.assertTrue(verified_healing_maximum(hp,1,self.observation(hp,2),samples))
        self.assertFalse(verified_healing_maximum(hp,1,self.observation(hp,2),samples))

    def test_other_slot_coarse_or_rejected_readings_cannot_verify_a_maximum(self):
        hp=(13641,18697)
        cases=[self.observation(hp,slot=0),self.observation(hp,approximate_portrait_hp=True),
               self.observation(hp,rejected='numeric_portrait_disagreement'),
               self.observation(hp,bar=.4),self.observation(hp,capture_sequence=None),
               self.observation(hp,parsed=[13641,186971]),self.observation(hp,team_verified=False)]
        for observation in cases:
            with self.subTest(observation=observation):
                samples=[(0,hp[1])]
                self.assertFalse(verified_healing_maximum(hp,1,observation,samples))
                self.assertEqual([],samples)

    def test_changing_maximum_or_reversed_capture_resets_confirmation(self):
        hp=(13641,18697);samples=[]
        verified_healing_maximum(hp,1,self.observation(hp,2),samples)
        self.assertFalse(verified_healing_maximum(hp,1,self.observation(hp,1),samples))
        verified_healing_maximum(hp,1,self.observation(hp,3),samples)
        other=(14000,19000)
        self.assertFalse(verified_healing_maximum(other,1,self.observation(other,4),samples))

    def rescue(self, samples):
        task=MaterialBossHealing();task.result={};task.in_team=Mock(return_value=(True,1,3))
        task.chars=[SimpleNamespace(char_name='yangyang_sp',confidence=.99),
                    SimpleNamespace(char_name='char_phrolova',confidence=.99),
                    SimpleNamespace(char_name='char_suisui',confidence=.99,
                                    emergency_heal_actions=Mock(return_value=True))]
        task.mouse_up=task.healing_switch=task.next_frame=task.log_info=Mock()
        iterator=iter(samples)
        def read():
            hp,observation=next(iterator);task._hp_observation=observation;return hp
        task.read_boss_hp=read
        task.wait_until=lambda fn,**kw:any(fn() for _ in samples)
        return task

    def test_real_rescue_succeeds_only_after_two_fresh_same_slot_numeric_frames(self):
        hp=(13641,18697)
        samples=[(hp,self.observation(hp,10704,bar=.757)),
                 (hp,self.observation(hp,10705,bar=.757))]
        task=self.rescue(samples)
        task.heal_material_boss(BossHealRequested(1,(10401,17620)))
        event=task.result['healing'][0]
        self.assertEqual('verified',event['status'])
        self.assertEqual([10704,10705],event['max_hp_change']['verified_capture_sequences'])
        self.assertFalse(task._boss_healing)

    def test_malformed_maximum_portrait_fallback_is_not_healing_evidence(self):
        bad=(129570,186971);hp=(13641,18697)
        samples=[(bad,self.observation(bad,10603,approximate_portrait_hp=True)),
                 (hp,self.observation(hp,10704,bar=.757))]
        task=self.rescue(samples)
        with self.assertRaises(DomainBattleFailed):
            task.heal_material_boss(BossHealRequested(1,(10401,17620)))
        self.assertEqual('failed',task.result['healing'][0]['status'])


if __name__=='__main__':unittest.main()
