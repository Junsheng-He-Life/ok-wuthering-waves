"""Recorded failure replay and action/state contracts; no live input or capture."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import cv2
import numpy as np
from ok import Box
from onnxocr.onnx_paddleocr import ONNXPaddleOcr
from src.task.MaterialRunUI import MaterialRunUI
from src.combat.MaterialBossGuard import MaterialBossGuard
from src.combat.PortraitHealth import portrait_health
from src.combat.SkillAction import SkillAction, SkillResult, ActionStatus
from src.combat.RotationSequence import run_sequence
from src.char.Aemeath import Aemeath
from src.char.BaseChar import BaseChar, SwitchPriority
from src.task.BaseCombatTask import BaseCombatTask


class RecordedHp:
    read_current_hp = MaterialRunUI.read_current_hp
    pad_hp_text = staticmethod(MaterialRunUI.pad_hp_text)
    pad_hp_text_small = staticmethod(MaterialRunUI.pad_hp_text_small)
    def __init__(self, engine):
        self.engine = engine
        self.frame = cv2.imread(str(Path(__file__).parent/'images/combat-hp-9516-20261101.png'))
        self._executor = SimpleNamespace(method=SimpleNamespace(_delivered_frame_sequence=12))
        self.log_info = Mock()
    def in_team(self):
        return True, 1, 3
    def box_of_screen(self, a,b,c,d,**kw):
        return Box(round(a*1920),round(b*1080),round((c-a)*1920),round((d-b)*1080))
    def ocr(self, *,box,frame,frame_processor,threshold):
        crop = frame[box.y:box.y+box.height,box.x:box.x+box.width]
        return [SimpleNamespace(name=name) for _,(name,score) in self.engine.ocr(frame_processor(crop))[0]
                if score >= threshold]


class TestRecordedCombatHealth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ONNXPaddleOcr(use_angle_cls=False,use_npu=False,use_openvino=False)
    def test_actual_abort_frame_reads_hp_and_blank_cannot_reuse_it(self):
        task = RecordedHp(self.engine)
        self.assertEqual((9516,16525),task.read_current_hp())
        self.assertTrue(task._hp_observation['alternate_scale'])
        task.frame[:] = 0
        self.assertIsNone(task.read_current_hp())
    def test_extra_leading_digit_uses_same_frame_small_scale_numeric_retry(self):
        task = RecordedHp(self.engine)
        task.frame = cv2.imread(str(Path(__file__).parent/'images/combat-hp-4730-20261101.png'))
        task.in_team = lambda: (True, 2, 3)
        self.assertEqual((4730, 17578), task.read_current_hp())
        self.assertEqual(['14730/17578'], task._hp_observation['raw'])
        self.assertEqual(['4730/17578'], task._hp_observation['alternate_raw'])
        self.assertTrue(task._hp_observation['alternate_scale'])
        self.assertEqual(12, task._hp_observation['capture_sequence'])

    def test_same_frame_portrait_supports_active_actor_without_fake_healing(self):
        frame = cv2.imread(str(Path(__file__).parent/'images/combat-hp-9516-20261101.png'))
        bars = portrait_health(frame)
        self.assertAlmostEqual(bars[1],.595,delta=.025)
        task = MaterialBossGuard()
        task._boss_unreadable_hp=2
        task.read_boss_hp=Mock(return_value=None)
        task.in_team=Mock(return_value=(True,1,3))
        task.check_health_bar=Mock(return_value=False)
        task.request_boss_healing=Mock()
        task.log_info=Mock()
        task.fail_battle=Mock(side_effect=RuntimeError('unknown health'))
        task._hp_observation=dict(monotonic=10,team_verified=True,slot_at_decision=1,
                                  capture_sequence=12,portrait_ratios=bars)
        with patch('src.combat.MaterialBossGuard.time.monotonic',return_value=10):
            task.check_material_boss_health()
        task.fail_battle.assert_not_called()
        task.request_boss_healing.assert_not_called()
        # Updating the observation timestamp cannot make a repeated frame fresh.
        task._hp_observation['monotonic']=12
        with patch('src.combat.MaterialBossGuard.time.monotonic',return_value=12):
            with self.assertRaisesRegex(RuntimeError,'unknown health'):
                task.check_material_boss_health()
    def test_other_actors_healthy_bar_does_not_mask_current_actor(self):
        task=MaterialBossGuard()
        task._boss_unreadable_hp=2
        task.read_boss_hp=Mock(return_value=None)
        task.in_team=Mock(return_value=(True,1,3))
        task.check_health_bar=Mock(return_value=False)
        task._hp_observation=dict(monotonic=10,team_verified=True,slot_at_decision=0,
                                  capture_sequence=12,portrait_ratios=[1.,1.,1.])
        task.fail_battle=Mock(side_effect=RuntimeError('unknown'))
        with patch('src.combat.MaterialBossGuard.time.monotonic',return_value=10):
            with self.assertRaisesRegex(RuntimeError,'unknown'):
                task.check_material_boss_health()


class TestSkillEvidence(unittest.TestCase):
    def char(self):
        char=SkillAction()
        char.index=0; char.char_name='test'; char.last_switch_in_time=1
        char.task=SimpleNamespace(combat_start=1,result={},in_team=Mock(return_value=(True,0,3)),
            _executor=SimpleNamespace(method=SimpleNamespace(_delivered_frame_sequence=1)))
        char.task.next_frame=lambda: setattr(char.task._executor.method,'_delivered_frame_sequence',2)
        char.has_cd=Mock(side_effect=[False,True])
        char.resonance_available=Mock(return_value=True)
        char.click_resonance=Mock(return_value=(True,.5,False))
        return char
    def test_press_requires_new_same_actor_cooldown_evidence(self):
        char=self.char()
        self.assertTrue(char.resonance_action().confirmed)
        for stale,changed in [(True,False),(False,True),(False,False)]:
            char=self.char()
            if stale: char.task.next_frame=lambda: None
            if changed: char.task.in_team.side_effect=[(True,0,3),(True,1,3)]
            if not stale and not changed: char.has_cd.side_effect=[False,False]
            self.assertFalse(char.resonance_action().confirmed)
    def test_unavailable_never_sends_and_exception_never_claims_success(self):
        char=self.char(); char.has_cd.side_effect=None; char.has_cd.return_value=True
        self.assertEqual(ActionStatus.UNAVAILABLE,char.resonance_action().status)
        char.click_resonance.assert_not_called()
        char=self.char(); char.click_resonance.side_effect=RuntimeError('heal')
        with self.assertRaisesRegex(RuntimeError,'heal'): char.resonance_action()
        self.assertEqual(ActionStatus.INTERRUPTED,char.last_resonance_result.status)
    def test_delayed_cooldown_confirms_original_input_without_repressing(self):
        char = self.char()
        char.has_cd.side_effect = None
        char.has_cd.return_value = False
        self.assertEqual(ActionStatus.UNCONFIRMED, char.resonance_action().status)
        char.task._executor.method._delivered_frame_sequence = 3
        char.has_cd.return_value = True
        outcome = char.resonance_action()
        self.assertTrue(outcome.confirmed)
        self.assertEqual('delayed_fresh_cooldown_transition', outcome.evidence)
        char.click_resonance.assert_called_once()
        self.assertIsNone(char._pending_resonance)

    def test_delayed_cooldown_cannot_cross_visit_expiry_or_repeated_frame(self):
        for invalid in ('visit', 'expired', 'stale', 'actor'):
            with self.subTest(invalid=invalid):
                char = self.char()
                char.has_cd.side_effect = None
                char.has_cd.return_value = False
                char.resonance_action()
                char.task._executor.method._delivered_frame_sequence = 3
                if invalid == 'visit':
                    char.last_switch_in_time += 1
                elif invalid == 'expired':
                    char._pending_resonance['deadline'] = -1
                elif invalid == 'stale':
                    char.task._executor.method._delivered_frame_sequence = 2
                else:
                    char.task.in_team.return_value = (True, 1, 3)
                char.has_cd.return_value = True
                self.assertFalse(char.resonance_action().confirmed)
                char.click_resonance.assert_called_once()
                self.assertIsNone(char._pending_resonance)
    def test_missing_ready_icon_is_unknown_not_cooldown(self):
        char=self.char(); char.resonance_available.return_value=False
        result=char.resonance_action()
        self.assertEqual(ActionStatus.UNCONFIRMED,result.status)
        char.click_resonance.assert_not_called()
    def sequence_char(self):
        return SimpleNamespace(last_switch_in_time=1,index=0,char_name='test',
            task=SimpleNamespace(combat_start=1,result={},in_team=lambda: (True,0,3)),
            continues_normal_attack=Mock(),switch_next_char=Mock())
    def test_unconfirmed_step_retries_without_replaying_opener_or_advancing(self):
        char=self.sequence_char()
        opening=Mock(return_value=SkillResult(ActionStatus.UNAVAILABLE,False,'utility'))
        skill=Mock(side_effect=[SkillResult(ActionStatus.UNCONFIRMED,True,'none'),
                               SkillResult(ActionStatus.CONFIRMED,True,'cooldown')])
        next_step=Mock(return_value=SkillResult(ActionStatus.CONFIRMED,True,'next'))
        steps=[('opening',opening),('E',skill),('next',next_step)]
        with patch('src.combat.RotationSequence.time.monotonic',return_value=0):
            for _ in range(3): run_sequence(char,steps)
            self.assertEqual(2,char._rotation_sequence.step)
            next_step.assert_not_called(); char.switch_next_char.assert_not_called()
            run_sequence(char,steps); run_sequence(char,steps)
        opening.assert_called_once(); self.assertTrue(char._detonation_chain_done)
    def test_failed_or_interrupted_sequence_is_never_complete(self):
        char=self.sequence_char()
        skill=Mock(return_value=SkillResult(ActionStatus.UNCONFIRMED,True,'none'))
        steps=[('E',skill)]
        with patch('src.combat.RotationSequence.time.monotonic',return_value=0):
            run_sequence(char,steps); run_sequence(char,steps)
        self.assertFalse(char._detonation_chain_done)
        self.assertEqual('skill_unconfirmed:E',char._rotation_sequence.ended)
        char=self.sequence_char(); skill.side_effect=RuntimeError('heal')
        with self.assertRaisesRegex(RuntimeError,'heal'): run_sequence(char,steps)
        self.assertEqual(0,char._rotation_sequence.step)
        char.switch_next_char.assert_not_called()
    def test_sequence_wall_deadline_does_not_reset_and_new_visit_starts_fresh(self):
        char=self.sequence_char()
        steps=[('E',lambda: SkillResult(ActionStatus.UNCONFIRMED,True,'none'))]
        with patch('src.combat.RotationSequence.time.monotonic',return_value=0): run_sequence(char,steps)
        with patch('src.combat.RotationSequence.time.monotonic',return_value=21): run_sequence(char,steps)
        self.assertEqual('wall_deadline_unconfirmed',char._rotation_sequence.ended)
        char.last_switch_in_time=2
        with patch('src.combat.RotationSequence.time.monotonic',return_value=22): run_sequence(char,steps)
        self.assertEqual('',char._rotation_sequence.ended)

    def test_actor_change_during_action_cannot_advance_or_switch(self):
        char=self.sequence_char()
        char.task.in_team=Mock(side_effect=[(True,0,3),(True,1,3)])
        skill=Mock(return_value=SkillResult(ActionStatus.CONFIRMED,True,'animation'))
        run_sequence(char,[('R',skill)])
        self.assertEqual(0,char._rotation_sequence.step)
        char.switch_next_char.assert_not_called()
        self.assertEqual('actor_changed',char.task.result['rotation_steps'][-1]['evidence'])


class TestPendingSkillAndSwitch(unittest.TestCase):
    def test_pending_second_r_prevents_real_perform_from_switching_or_replaying_opener(self):
        task=SimpleNamespace(combat_start=1,_verified_battle=True,check_combat=Mock(),next_frame=Mock(),
                             allow_opportunistic_skills=lambda:False)
        char=Aemeath(task,0)
        char._sync_echo_liberation_visit()
        char._lib1_cast_count=1; char._lib2_guard_pending=True
        char.opening_normal_attack_burst=Mock(); char.switch_next_char=Mock()
        char.rotation_timeout=Mock(return_value=5)
        char.lib2_available=Mock(return_value=False)
        char.cast_enhanced_e_if_ready=Mock(return_value=False)
        now=[0.]
        char.handle_heavy=Mock(side_effect=lambda **kw:now.__setitem__(0,kw['deadline']) or True)
        with patch('src.char.Aemeath.time.monotonic',side_effect=lambda:now[0]):
            char.do_perform()
            char.switch_next_char.assert_not_called()
            char.do_perform()
            char.switch_next_char.assert_not_called()
            char.do_perform()
        char.switch_next_char.assert_called_once()
        char.opening_normal_attack_burst.assert_not_called()
    def test_second_r_resumes_after_slice_without_renewing_wall_limit(self):
        task=SimpleNamespace(combat_start=1,check_combat=Mock(),next_frame=Mock())
        char=Aemeath(task,0)
        char.rotation_timeout=Mock(return_value=5)
        char.lib2_available=Mock(return_value=False)
        char.cast_enhanced_e_if_ready=Mock(return_value=False)
        now=[0.]
        char.handle_heavy=Mock(side_effect=lambda **kw: now.__setitem__(0,kw['deadline']) or True)
        with patch('src.char.Aemeath.time.monotonic',side_effect=lambda:now[0]):
            char._execute_lib2_guard(); self.assertTrue(char._lib2_guard_pending)
            self.assertEqual(5,now[0])
            deadline=char._lib2_guard_deadline
            char._execute_lib2_guard(); self.assertTrue(char._lib2_guard_pending)
            char._execute_lib2_guard(); self.assertFalse(char._lib2_guard_pending)
        self.assertEqual(deadline,now[0]); self.assertEqual(0,char._lib2_cast_count)
    def test_team_preference_cannot_override_no_or_must(self):
        task=BaseCombatTask.__new__(BaseCombatTask)
        task.chars=[BaseChar(task,i) for i in range(3)]
        current,preferred,other=task.chars
        task.preferred_switch_target=Mock(return_value=preferred)
        preferred.get_switch_priority=Mock(return_value=SwitchPriority.NO)
        self.assertIs(other,task._choose_switch_target(current,False))
        preferred.get_switch_priority.return_value=SwitchPriority.NORMAL
        other.get_switch_priority=Mock(return_value=SwitchPriority.MUST)
        self.assertIs(other,task._choose_switch_target(current,False))


class TestCharacterStepIntegration(unittest.TestCase):
    def test_support_characters_do_not_advance_burst_after_unconfirmed_e(self):
        from src.char.Chisa import Chisa
        from src.char.Denia import Denia
        for cls in (Chisa,Denia):
            task=SimpleNamespace(combat_start=1,result={},in_team=lambda:(True,0,3),
                                 detonation_team_active=lambda:True,char_config={})
            char=cls(task,0,char_name=cls.__name__)
            char.continues_normal_attack=Mock(); char.click_echo=Mock()
            char.is_forte_full=Mock(return_value=True); char.perform_forte=Mock(return_value=True)
            char.resonance_action=Mock(side_effect=[
                SkillResult(ActionStatus.UNCONFIRMED,True,'no change'),
                SkillResult(ActionStatus.CONFIRMED,True,'cooldown'),
                SkillResult(ActionStatus.CONFIRMED,True,'cooldown')])
            char.liberation_available=Mock(return_value=True)
            char.click_liberation=Mock(return_value=True)
            char.switch_next_char=Mock()
            with patch('src.combat.RotationSequence.time.monotonic',return_value=0):
                char.do_perform(); char.do_perform()
                char.click_liberation.assert_not_called()
                char.switch_next_char.assert_not_called()
                for _ in range(7): char.do_perform()
            char.click_echo.assert_called_once()
            self.assertTrue(char._detonation_chain_done)

    def test_two_healers_and_zero_healer_critical_rescue(self):
        from src.combat.MaterialBossHealing import MaterialBossHealing,BossHealRequested
        task=MaterialBossHealing()
        task.chars=[SimpleNamespace(char_name='dps',confidence=.99,index=0),
                    SimpleNamespace(char_name='new_healer_a',confidence=.99,index=1,emergency_heal_actions=Mock()),
                    SimpleNamespace(char_name='new_healer_b',confidence=.99,index=2,emergency_heal_actions=Mock())]
        task.in_team=Mock(return_value=(True,0,3))
        with self.assertRaises(BossHealRequested): task.request_boss_healing((5000,10000))
        task.chars[1].recovery_until=float('inf')
        self.assertEqual([task.chars[2]],task.healing_candidates())
        del task.chars[2].emergency_heal_actions
        with self.assertRaises(BossHealRequested): task.request_boss_healing((1000,10000))
