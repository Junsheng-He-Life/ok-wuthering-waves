"""Diagnostics observe the original backend without injecting any actions."""
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from src.combat.CombatDiagnostics import combat_diagnostics


class TestCombatDiagnostics(unittest.TestCase):
    def test_analysis_does_not_count_a_held_action_as_idle(self):
        from scripts.analyze_combat_timing import input_summary
        events = [{'action': 'send_key', 'start': 0., 'end': 3.5},
                  {'action': 'click', 'start': 3.6, 'end': 3.8},
                  {'action': 'click', 'start': 5.8, 'end': 6.}]
        summary = input_summary(events)
        self.assertEqual(1, len(summary['gaps_over_800ms']))
        self.assertAlmostEqual(2., summary['gaps_over_800ms'][0]['seconds'])
        self.assertEqual(3.5, summary['actions']['send_key']['sum_seconds'])
        held_mouse = [{'action': 'mouse_down', 'start': 0., 'end': .01},
                      {'action': 'mouse_up', 'start': 3., 'end': 3.01},
                      {'action': 'click', 'start': 5., 'end': 5.2}]
        summary = input_summary(held_mouse)
        self.assertEqual(1, len(summary['gaps_over_800ms']))
        self.assertAlmostEqual(1.99, summary['gaps_over_800ms'][0]['seconds'])

    def test_disabled_diagnostics_do_not_touch_backend(self):
        task = SimpleNamespace(record_hud=False)
        with combat_diagnostics(task):
            pass
        self.assertFalse(hasattr(task, 'executor'))

    def test_exception_restores_backend_and_keeps_timing_without_extra_input(self):
        click = Mock()
        interaction = SimpleNamespace(click=click)
        task = SimpleNamespace(record_hud=True, _verified_battle=True, result={},
                               executor=SimpleNamespace(interaction=interaction))
        with self.assertRaisesRegex(RuntimeError, 'interrupted'):
            with combat_diagnostics(task):
                interaction.click(down_time=.08)
                raise RuntimeError('interrupted')
        self.assertIs(click, interaction.click)
        click.assert_called_once_with(down_time=.08)
        folder = Path(task.result['combat_timing'][0])
        self.assertTrue((folder / 'calls.json').exists())
        data = json.loads((folder / 'inputs.json').read_text())
        self.assertEqual(1, len(data['events']))
        self.assertGreaterEqual(data['events'][0]['end'], data['events'][0]['start'])
