import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
import cv2
import numpy as np
from src.combat.BattleEvidence import BattleEvidence
from src.task.VerifiedDomainCombat import DomainBattleFailed


class TestBattleEvidence(unittest.TestCase):
    def test_failure_saves_exact_ocr_source_even_if_current_frame_changed(self):
        with tempfile.TemporaryDirectory() as directory:
            task = BattleEvidence()
            task.battle_evidence_root = directory
            source = np.full((8, 10, 3), 73, np.uint8)
            current = np.full((8, 10, 3), 192, np.uint8)
            task._hp_observation_frame = source.copy()
            task._executor = SimpleNamespace(nullable_frame=lambda: current)
            task._hp_observation = {'monotonic':time.monotonic(), 'raw':['2B549/33398'],
                                    'parsed':None, 'slot_at_decision':2}
            task.result = {}
            task._boss_heal_deadline = time.monotonic()+12
            with self.assertRaisesRegex(DomainBattleFailed, 'critical'):
                task.fail_battle('critical')
            folder = Path(task.result['trigger_evidence'][0])
            report = json.loads((folder/'decision.json').read_text())
            np.testing.assert_array_equal(source, cv2.imread(str(folder/'hp_source.png')))
            np.testing.assert_array_equal(current, cv2.imread(str(folder/'trigger.png')))
            self.assertEqual(['2B549/33398'], report['hp_observation']['raw'])
            self.assertGreater(report['_boss_heal_deadline_remaining'], 0)

    def test_write_failure_does_not_hide_original_battle_failure(self):
        task = BattleEvidence()
        def fail(reason):
            raise OSError('disk full')
        task.save_battle_trigger = fail
        with self.assertRaisesRegex(DomainBattleFailed, 'original.*disk full'):
            task.fail_battle('original')
