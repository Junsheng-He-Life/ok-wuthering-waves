import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import numpy as np
from ok import Box
from src.task.CultivationAvatarCache import cache_paths, locate_avatar
from src.task.CultivationTargetUI import select_owned_target


class TestCultivationAvatarCache(unittest.TestCase):
    def setUp(self):
        self.patch = np.random.default_rng(71).integers(0, 256, (38, 38, 3), dtype=np.uint8)
        self.frame = np.zeros((360, 640, 3), dtype=np.uint8)

    def test_matches_portrait_after_position_changes(self):
        self.frame[150:188, 220:258] = self.patch
        point, score = locate_avatar(self.frame, self.patch)
        self.assertEqual((239, 169), point)
        self.assertGreater(score, .99)

    def test_identical_visible_portraits_require_name_scan(self):
        self.frame[150:188, 50:88] = self.patch
        self.frame[150:188, 220:258] = self.patch
        self.assertIsNone(locate_avatar(self.frame, self.patch))

    def test_preview_pane_cannot_match_as_roster(self):
        self.frame[150:188, 500:538] = self.patch
        self.assertIsNone(locate_avatar(self.frame, self.patch))

    def test_render_blur_does_not_hide_visible_avatar(self):
        import cv2
        self.frame[150:188, 220:258] = self.patch
        blurred = cv2.GaussianBlur(self.frame, (0, 0), 1.2)
        point, score = locate_avatar(blurred, self.patch)
        self.assertEqual((239, 169), point)
        self.assertGreater(score, .89)


class TestCultivationCacheRecovery(unittest.TestCase):
    def picker(self, desired='新目标', selectable_name='新目标', final_matches=True):
        """Simulate observed picker cards and the separately verified target."""
        task = SimpleNamespace(width=1000, height=600)
        task._normalize_material_text = lambda text: text.strip()
        task.preview_name = '原目标'
        task.log_info = Mock()
        task.card = Box(100, 180, 40, 20, name='Lv.80')
        task.confirm = Box(800, 540, 150, 30, name='设为培养目标')
        task.wait_ocr = Mock(side_effect=lambda *a, **kw:
            task.confirm if kw['match'].pattern == '^设为培养目标$' else True)

        task.frame = np.zeros((task.height, task.width, 3), dtype=np.uint8)
        def ocr(box=None, frame=None, **kwargs):
            if frame is not None:
                return [Box(20, 20, 100, 30, name=task.preview_name)]
            # The top featured row has no matching text. Only the observed
            # owned-card level label is available as a click candidate.
            return [task.card] if box.y == 66 else []
        task.ocr = Mock(side_effect=ocr)

        def click_box(box, **kwargs):
            if box is task.card:
                task.preview_name = selectable_name
            elif box is not task.confirm:
                raise AssertionError('unobserved card must never be clicked')
        task.click_box = Mock(side_effect=click_box)
        task.material_target_matches = Mock(return_value=final_matches)
        task.wait_until = Mock(side_effect=lambda callback, **kw: callback())
        return task

    def test_corrupt_existing_cache_relearns_from_observed_card_and_name(self):
        with tempfile.TemporaryDirectory() as root:
            with patch('src.task.CultivationAvatarCache.CACHE_DIR', Path(root)):
                picture, metadata = cache_paths('新目标')
                picture.write_bytes(b'old portrait')
                metadata.write_text('{invalid metadata')
                task = self.picker()
                with patch('src.task.CultivationAvatarCache.scroll_roster') as scroll, \
                        patch('src.task.CultivationAvatarCache.remember_avatar') as remember:
                    select_owned_target(task, '新目标')
                scroll.assert_called_once_with(task, 100)
                remember.assert_called_once_with(task, '新目标', task.card, 0)
                self.assertEqual([task.card, task.confirm],
                                 [call.args[0] for call in task.click_box.call_args_list])
                task.material_target_matches.assert_called_once_with('新目标')

    def test_cache_miss_does_not_commit_any_unmatched_preview(self):
        task = self.picker(selectable_name='其他角色')
        with patch('src.task.CultivationAvatarCache.select_cached_avatar', return_value=False), \
                patch('src.task.CultivationAvatarCache.scroll_roster'), \
                patch('src.task.CultivationAvatarCache.remember_avatar') as remember:
            with self.assertRaisesRegex(RuntimeError, '未核对到新目标'):
                select_owned_target(task, '新目标')
        self.assertTrue(task.click_box.called)
        self.assertTrue(all(call.args[0] is task.card
                            for call in task.click_box.call_args_list))
        remember.assert_not_called()
        task.material_target_matches.assert_not_called()

    def test_relearned_preview_still_requires_result_target_verification(self):
        task = self.picker(final_matches=False)
        with patch('src.task.CultivationAvatarCache.select_cached_avatar', return_value=False), \
                patch('src.task.CultivationAvatarCache.scroll_roster'), \
                patch('src.task.CultivationAvatarCache.remember_avatar'):
            with self.assertRaisesRegex(RuntimeError, '培养目标设置结果未确认'):
                select_owned_target(task, '新目标')
        task.material_target_matches.assert_called_once_with('新目标')
