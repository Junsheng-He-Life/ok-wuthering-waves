"""An unavailable slot should trigger beacon healing only from verified world UI."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from src.task.MaterialRunUI import MaterialRunUI


class TestMaterialBeaconRecovery(unittest.TestCase):
    def test_materials_and_terminal_pages_close_before_world_check(self):
        task = MaterialRunUI()
        task.focus_material_menu = Mock()
        task.send_key = Mock()
        task.ensure_main = Mock()
        task.in_team_and_world = Mock(side_effect=[False, False, True])
        task.read_material_entry_warning = Mock(return_value=None)
        task.wait_guidebook_page = Mock(return_value=None)
        task.menu_text = Mock(side_effect=lambda pattern, *args, **kwargs:
                              object() if '素材获取' in pattern else None)
        task.return_to_world()
        self.assertEqual(2, task.send_key.call_count)
        task.ensure_main.assert_not_called()

    def test_unknown_page_has_bounded_world_wait(self):
        task = MaterialRunUI()
        task.focus_material_menu = Mock()
        task.ensure_main = Mock()
        task.log_info = Mock()
        task.in_team_and_world = Mock(return_value=False)
        task.read_material_entry_warning = Mock(return_value=None)
        task.wait_guidebook_page = task.menu_text = Mock(return_value=None)
        task.ocr = Mock(return_value=[])
        task.frame = None
        with patch('src.task.MaterialRunUI.cv2.imwrite'):
            task.return_to_world()
        task.ensure_main.assert_called_once_with(time_out=15)

    def task(self, *, world=True, revive=False):
        task = MaterialRunUI()
        task.send_key = task.log_info = task.next_frame = Mock()
        task.wait_until = Mock(return_value=False)
        task.in_team_and_world = Mock(return_value=world)
        task.menu_text = Mock(side_effect=[True, False] if revive else [False])
        return task

    def test_unavailable_slot_in_world_requests_beacon_instead_of_throwing(self):
        self.assertFalse(self.task().verify_team_health())

    def test_known_revive_prompt_is_dismissed_without_consuming_item(self):
        task = self.task(revive=True)
        self.assertFalse(task.verify_team_health())
        self.assertIn(('esc',), [call.args for call in task.send_key.call_args_list])

    def test_unknown_page_still_stops_before_map_input(self):
        task = self.task(world=False)
        with self.assertRaisesRegex(RuntimeError, 'world HUD missing'):
            task.verify_team_health()
        self.assertNotIn(('m',), [call.args for call in task.send_key.call_args_list])

    def test_persistent_revive_prompt_is_not_treated_as_world(self):
        task = self.task()
        task.menu_text = Mock(return_value=True)
        with self.assertRaisesRegex(RuntimeError, '复苏窗口未关闭'):
            task.verify_team_health()

    def test_failed_slot_check_reaches_beacon_and_verifies_health_again(self):
        task = self.task()
        task.verify_team_health = Mock(side_effect=[False, True])
        task.in_realm = Mock(return_value=False)
        task.ensure_main = task.click_box = task.sleep = task.wait_in_team_and_world = Mock()
        task.stable_map_waypoint = Mock(return_value=object())
        task.menu_text = Mock(return_value=True)
        task.menu_click = Mock()
        task.frame = None
        with patch('src.task.MaterialRunUI.cv2.imwrite'):
            task.heal_at_beacon()
        task.menu_click.assert_called_once_with(r'快速旅行|FastTravel', (.65, .7, 1, 1))
        self.assertEqual(2, task.verify_team_health.call_count)

    def beacon_task(self, *, world=True, realm=False):
        task = MaterialRunUI()
        task.in_realm = Mock(return_value=realm)
        task.in_team_and_world = Mock(return_value=world)
        task.ensure_main = Mock()
        task.focus_material_menu = Mock(side_effect=AssertionError('recovery must not reclaim focus'))
        task.verify_team_health = Mock(return_value=True)
        task.send_key = Mock()
        task.log_info = Mock()
        task.click_box = Mock()
        task.sleep = Mock()
        task.next_frame = Mock()
        task.wait_in_team_and_world = Mock()
        task.stable_map_waypoint = Mock(return_value='verified beacon')
        task.menu_text = Mock(return_value='verified fast travel')
        task.frame = None
        return task

    def test_default_healthy_team_keeps_existing_no_teleport_behavior(self):
        task = self.beacon_task()
        task.heal_at_beacon()
        task.ensure_main.assert_called_once_with()
        task.verify_team_health.assert_called_once_with()
        task.send_key.assert_not_called()
        task.stable_map_waypoint.assert_not_called()

    def test_force_teleport_does_not_return_early_for_healthy_team(self):
        task = self.beacon_task()
        with patch('src.task.MaterialRunUI.cv2.imwrite'):
            task.heal_at_beacon(force_teleport=True)
        task.ensure_main.assert_called_once_with()
        self.assertEqual(task.verify_team_health.call_count, 2)
        task.send_key.assert_called_once_with('m', after_sleep=1)
        task.wait_in_team_and_world.assert_called_once_with(time_out=60)

    def test_direct_forced_retreat_checks_health_only_after_teleport(self):
        task = self.beacon_task()
        events = []
        task.send_key.side_effect = lambda key, **kwargs: events.append(key)
        task.wait_in_team_and_world.side_effect = lambda **kwargs: events.append('world restored')
        task.verify_team_health.side_effect = lambda: events.append('health verified') or True
        with patch('src.task.MaterialRunUI.cv2.imwrite'):
            task.heal_at_beacon(force_teleport=True, verify_before=False)
        self.assertEqual(events, ['m', 'world restored', 'health verified'])
        task.ensure_main.assert_not_called()
        task.focus_material_menu.assert_not_called()
        task.in_team_and_world.assert_called_once_with()
        task.verify_team_health.assert_called_once_with()

    def test_direct_recovery_without_world_hud_or_inside_domain_never_sends_input(self):
        for world, realm in ((False, False), (True, True)):
            with self.subTest(world=world, realm=realm):
                task = self.beacon_task(world=world, realm=realm)
                with self.assertRaises(RuntimeError):
                    task.heal_at_beacon(force_teleport=True, verify_before=False)
                task.send_key.assert_not_called()
                task.click_box.assert_not_called()
                task.ensure_main.assert_not_called()
                task.verify_team_health.assert_not_called()

    def test_direct_recovery_without_verified_beacon_never_clicks_the_map(self):
        task = self.beacon_task()
        task.stable_map_waypoint.return_value = None
        with self.assertRaisesRegex(RuntimeError, 'no verified waypoint'):
            task.heal_at_beacon(force_teleport=True, verify_before=False)
        task.send_key.assert_called_once_with('m', after_sleep=1)
        task.click_box.assert_not_called()
        task.menu_text.assert_not_called()
        task.verify_team_health.assert_not_called()

    def test_missing_fast_travel_never_falls_back_to_an_unknown_click(self):
        for visible_label in (None, 'verified beacon label'):
            with self.subTest(visible_label=visible_label):
                task = self.beacon_task()
                # No travel button: select only a verified beacon label if one
                # exists, then stop unless the final travel button is verified.
                task.menu_text.side_effect = [None, visible_label, None]
                with patch('src.task.MaterialRunUI.cv2.imwrite'):
                    with self.assertRaisesRegex(RuntimeError, 'not uniquely verified'):
                        task.heal_at_beacon(force_teleport=True, verify_before=False)
                expected = ['verified beacon'] + ([visible_label] if visible_label else [])
                self.assertEqual([call.args[0] for call in task.click_box.call_args_list], expected)
                task.wait_in_team_and_world.assert_not_called()
                task.verify_team_health.assert_not_called()

    def test_direct_retreat_still_requires_verified_healing_after_teleport(self):
        task = self.beacon_task()
        task.verify_team_health.return_value = False
        with patch('src.task.MaterialRunUI.cv2.imwrite'):
            with self.assertRaisesRegex(RuntimeError, 'healing not verified after teleport'):
                task.heal_at_beacon(force_teleport=True, verify_before=False)
        task.wait_in_team_and_world.assert_called_once_with(time_out=60)
        task.verify_team_health.assert_called_once_with()

    def test_live_beacon_detection_keeps_full_icon_below_old_map_crop(self):
        # A 52px-high reference icon starting at y=912 used to be truncated at
        # y=918 by the 85% crop. The bottom toolbar remains outside the search.
        template_path = Path(__file__).resolve().parents[1] / 'assets/images/map-beacon-huanglong-1920.png'
        template = cv2.imread(str(template_path))
        self.assertIsNotNone(template)
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        height, width = template.shape[:2]
        frame[912:912 + height, 890:890 + width] = template
        box = MaterialRunUI.live_map_beacon(frame)
        self.assertIsNotNone(box)
        self.assertEqual((box.x, box.y), (890, 912))
        self.assertEqual(box.name, 'map_beacon_huanglong')
        self.assertGreater(box.confidence, .99)

    def test_nexus_template_detects_complete_lower_map_icon(self):
        template_path = Path(__file__).resolve().parents[1] / 'assets/images/map-nexus-huanglong-1920.png'
        template = cv2.imread(str(template_path))
        self.assertIsNotNone(template)
        self.assertEqual(template.shape[:2], (52, 56))
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        frame[912:964, 881:937] = template
        box = MaterialRunUI.live_map_beacon(frame)
        self.assertIsNotNone(box)
        self.assertEqual((box.x, box.y, box.width, box.height), (881, 912, 56, 52))
        self.assertEqual(box.name, 'map_nexus_huanglong')
        self.assertGreater(box.confidence, .99)
        self.assertTrue(MaterialRunUI.waypoint_has_active_color(frame, box))

    def test_blank_map_has_no_verified_beacon_or_nexus(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        self.assertIsNone(MaterialRunUI.live_map_beacon(frame))

    def test_fallback_map_search_includes_full_lower_beacon(self):
        task = self.beacon_task()
        point = SimpleNamespace(x=880, y=912, width=57, height=53, confidence=.9,
                                name='map_way_point_big')
        task.live_map_beacon = Mock(return_value=None)
        task.box_of_screen = lambda *bounds, **kwargs: bounds
        task.find_feature = lambda name, box, **kwargs: (
            [point] if name == 'map_way_point_big' and point.y + point.height <= 1080 * box[3] else [])
        task.waypoint_has_active_color = Mock(return_value=True)
        def wait_until(predicate, **kwargs):
            self.assertIsNone(predicate())
            return predicate()
        task.wait_until = wait_until
        with patch('src.task.MaterialRunUI.time.monotonic', side_effect=[100., 100.5]):
            self.assertIs(MaterialRunUI.stable_map_waypoint(task), point)

    def test_actual_nexus_label_is_verified_before_travel_click(self):
        task = self.beacon_task()
        task.menu_text.side_effect = [None, '中枢信标', 'verified fast travel']
        with patch('src.task.MaterialRunUI.cv2.imwrite'):
            task.heal_at_beacon(force_teleport=True, verify_before=False)
        label_expression = task.menu_text.call_args_list[1].args[0]
        self.assertIn('中枢信标', label_expression.split('|'))
        self.assertEqual([call.args[0] for call in task.click_box.call_args_list],
                         ['verified beacon', '中枢信标', 'verified fast travel'])
