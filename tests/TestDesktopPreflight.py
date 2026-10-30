"""Fresh-read preflight must reject ambiguous, stale and under-level observations."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from src.runtime.TeamReadiness import (PRIMARY_TEAM, VERIFIED_STAGE, evaluate_team_readiness,
                                      read_hud_level, read_hud_level_variants, read_world_level)
from src.task.DesktopPreflightTask import collect_team_readiness, require_desktop_preflight


def members(level=80):
    return [dict(slot=i, character=name, name=name, confidence=.95, registered=True,
                 level=level, health=[10000, 10000]) for i, name in enumerate(sorted(PRIMARY_TEAM), 1)]


def box(text, x, y, width=80, height=40):
    return dict(text=text, x=x, y=y, width=width, height=height)


class TestDesktopPreflight(unittest.TestCase):
    def test_level_requires_one_label_and_valid_range(self):
        self.assertEqual(80, read_hud_level(['Lv.80']))
        self.assertEqual(90, read_hud_level(['LV．90']))
        for words in (['80'], ['Lv.0'], ['Lv.99'], ['Lv.80', 'Lv.90'], ['Lv.80/90']):
            self.assertIsNone(read_hud_level(words))

    def test_world_rank_is_paired_to_its_own_label(self):
        rows = [box('索拉等级', 100, 700), box('8阶0', 600, 698),
                box('联觉等级', 100, 750), box('79级', 600, 750)]
        self.assertEqual(8, read_world_level(rows))
        self.assertIsNone(read_world_level([rows[0], box('8阶', 600, 750)]))
        self.assertIsNone(read_world_level(rows + [box('7阶', 500, 700)]))
        self.assertIsNone(read_world_level(rows + [box('索拉等级', 200, 700)]))

    def test_valid_crop_variants_must_not_disagree(self):
        self.assertEqual(80, read_hud_level_variants((['iv.80'], ['Lv.80'])))
        self.assertEqual(90, read_hud_level_variants((['Lv.90'], ['L.90'])))
        self.assertIsNone(read_hud_level_variants((['Lv.80'], ['Lv.90'])))

    def test_supported_combination_is_slot_independent_but_not_gear_certification(self):
        result = evaluate_team_readiness(list(reversed(members())), 8)
        self.assertTrue(result['can_start'])
        self.assertFalse(result['equipment_verified'])
        self.assertEqual('beta_candidate', result['support_level'])

    def test_experimental_option_never_bypasses_unknown_or_low_levels(self):
        for level in (None, 70, True, '90', 120):
            roster = members()
            roster[1]['level'] = level
            result = evaluate_team_readiness(roster, 8, allow_experimental=True)
            self.assertFalse(result['can_start'])

    def test_unknown_world_never_passes_experimental(self):
        for world in (None, True, 9, '8'):
            self.assertFalse(evaluate_team_readiness(members(), world,
                                                    allow_experimental=True)['can_start'])

    def test_other_world_requires_explicit_experimental_choice(self):
        self.assertFalse(evaluate_team_readiness(members(), 7)['can_start'])
        self.assertTrue(evaluate_team_readiness(members(), 7, allow_experimental=True)['can_start'])

    def test_unrecognized_or_duplicate_identity_blocks(self):
        for field, value in (('registered', False), ('confidence', .79), ('confidence', float('nan'))):
            roster = members()
            roster[0][field] = value
            self.assertFalse(evaluate_team_readiness(roster, 8, allow_experimental=True)['can_start'])
        roster = members()
        roster[0]['character'] = roster[1]['character']
        self.assertFalse(evaluate_team_readiness(roster, 8)['can_start'])

    def test_low_or_unknown_health_blocks(self):
        for hp in (None, [0, 10000], [8000, 10000], [10001, 10000], [0, 0]):
            roster = members()
            roster[0]['health'] = hp
            self.assertFalse(evaluate_team_readiness(roster, 8)['can_start'])

    def test_other_stage_and_materials_are_not_mislabeled_verified(self):
        for options in ({'stage': '其他无音区'}, {'mode': 'materials'}, {'mode': 'boss'}):
            self.assertFalse(evaluate_team_readiness(members(), 8, **options)['can_start'])

    def test_back_up_team_remains_experimental(self):
        roster = members()
        for member, name in zip(roster, ('char_aemeath', 'char_denia', 'char_chisa')):
            member['character'] = name
        result = evaluate_team_readiness(roster, 8, allow_experimental=True)
        self.assertTrue(result['can_start'])
        self.assertEqual('experimental', result['support_level'])
        self.assertTrue(any('减员' in warning for warning in result['warnings']))

    def test_product_minimum_cannot_be_lowered_by_experimental_config(self):
        for minimum in (0, 70, True, 91):
            with self.assertRaises(ValueError):
                evaluate_team_readiness(members(), 8, minimum_level=minimum)

    def task(self):
        state = {'slot': 0, 'terminal': False}
        task = SimpleNamespace(result={}, config={}, chars=[], desktop_preflight_mode='tacet',
            desktop_preflight_stage=VERIFIED_STAGE, desktop_allow_experimental=False,
            assert_no_pending_refill=Mock(), focus_material_menu=Mock(), next_frame=Mock(),
            in_team=lambda: (True, state['slot'], 3), find_world_earth_icon=Mock(return_value=True),
            in_realm=Mock(return_value=False), check_health_bar=Mock(return_value=False),
            box_of_screen=Mock(return_value='level_crop'), sleep=Mock(),
            read_current_hp=Mock(return_value=(10000, 10000)))
        def send_key(key, **_):
            if key in ('1', '2', '3'):
                state['slot'] = int(key) - 1
            elif key == 'esc':
                state['terminal'] = not state['terminal']
        task.send_key = Mock(side_effect=send_key)
        task.wait_until = lambda predicate, **_: predicate()
        task.menu_text = lambda *_, **__: state['terminal']
        def ocr(*_, **kwargs):
            if kwargs.get('box') == 'level_crop':
                return [SimpleNamespace(name='Lv.80')]
            return [SimpleNamespace(name='索拉等级', x=100, y=700, width=100, height=40),
                    SimpleNamespace(name='8阶0', x=600, y=700, width=100, height=40)]
        task.ocr = Mock(side_effect=ocr)
        return task

    def test_live_collection_reads_each_slot_and_reidentifies_after_menu(self):
        task = self.task()
        observed = members()
        for member in observed:
            member.update(level=None, health=None)
        with patch('src.task.DesktopPreflightTask._atomic_json'), \
                patch('src.task.DesktopPreflightTask.observe_members', return_value=observed) as scan:
            result = collect_team_readiness(task)
        self.assertTrue(result['can_start'])
        self.assertEqual(2, scan.call_count)
        self.assertEqual([80, 80, 80], [m['level'] for m in result['members']])
        self.assertEqual(['1', '2', '3', 'esc', 'esc', '1'],
                         [call.args[0] for call in task.send_key.call_args_list])

    def test_pending_consumption_prevents_all_inputs(self):
        task = self.task()
        task.assert_no_pending_refill.side_effect = RuntimeError('待核对消费')
        with patch('src.task.DesktopPreflightTask._atomic_json') as save, self.assertRaises(RuntimeError):
            collect_team_readiness(task)
        task.send_key.assert_not_called()
        task.focus_material_menu.assert_not_called()
        self.assertFalse(task.result['preflight']['can_start'])
        self.assertEqual('stopped', save.call_args.args[1]['status'])

    def test_battle_or_domain_refuses_menu_and_switch_inputs(self):
        for name in ('in_realm', 'check_health_bar'):
            task = self.task()
            getattr(task, name).return_value = True
            with patch('src.task.DesktopPreflightTask._atomic_json'), self.assertRaises(RuntimeError):
                collect_team_readiness(task)
            task.send_key.assert_not_called()

    def test_team_change_during_read_invalidates_result(self):
        task = self.task()
        changed = members()
        changed[0]['character'] = 'char_verina'
        with patch('src.task.DesktopPreflightTask._atomic_json'), \
                patch('src.task.DesktopPreflightTask.observe_members', side_effect=[members(), changed]), \
                self.assertRaisesRegex(RuntimeError, '队伍发生变化'):
            collect_team_readiness(task)
        self.assertFalse(task.result['preflight']['can_start'])

    def test_two_different_level_frames_remain_unknown(self):
        task = self.task()
        read = task.ocr.side_effect
        count = [0]
        def changing(*args, **kwargs):
            if kwargs.get('box') == 'level_crop':
                count[0] += 1
                return [SimpleNamespace(name='Lv.80' if (count[0] - 1) // 2 % 2 else 'Lv.90')]
            return read(*args, **kwargs)
        task.ocr.side_effect = changing
        with patch('src.task.DesktopPreflightTask._atomic_json'), \
                patch('src.task.DesktopPreflightTask.observe_members', side_effect=lambda _: members()):
            result = collect_team_readiness(task)
        self.assertFalse(result['can_start'])
        self.assertEqual([None, None, None], [m['level'] for m in result['members']])

    def test_required_preflight_does_not_accept_previous_good_report(self):
        task = self.task()
        task.result['preflight'] = {'can_start': True}
        task.check_health_bar.return_value = True
        with patch('src.task.DesktopPreflightTask._atomic_json'), self.assertRaises(RuntimeError):
            require_desktop_preflight(task)
        self.assertFalse(task.result['preflight']['can_start'])


if __name__ == '__main__':
    unittest.main()
