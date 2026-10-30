import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from src.runtime.MacSession import MacSession, prepare_desktop_config, release_inputs


class TestMacSession(unittest.TestCase):
    def test_second_controller_is_rejected_until_first_closes(self):
        with tempfile.TemporaryDirectory() as root:
            first = MacSession(root).acquire()
            try:
                with self.assertRaises(RuntimeError):
                    MacSession(root).acquire()
            finally:
                first.close()
            second = MacSession(root).acquire()
            second.close()

    def test_launch_preserves_bindings_but_disables_auto_combat(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'configs'
            source.mkdir()
            (source / 'Game Hotkey.json').write_text('{"Liberation Key": "r"}')
            original = {'trigger_tasks': ['old'], 'update_pyappify': {}}
            config = prepare_desktop_config(root, original)
            folder = Path(config['config_folder'])
            self.assertEqual({'Liberation Key': 'r'}, json.loads((folder / 'Game Hotkey.json').read_text()))
            combat = folder / 'AutoCombatTask.json'
            combat.write_text('{"_enabled": true, "Auto Target": false}')
            prepare_desktop_config(root, original)
            self.assertEqual({'_enabled': False, 'Auto Target': False}, json.loads(combat.read_text()))
            self.assertEqual(['old'], original['trigger_tasks'])
            self.assertNotIn('update_pyappify', config)
            self.assertEqual(7, len(config['onetime_tasks']))
            self.assertIn(['src.task.EchoFarmTask', 'BossEchoTask'], config['onetime_tasks'])
            self.assertIn(['src.task.EchoFarmTask', 'TacetEchoTask'], config['onetime_tasks'])
            self.assertFalse(json.loads((folder / 'Basic Options.json').read_text())['Auto Resize Game Window'])

    def test_failed_mouse_release_does_not_prevent_key_release(self):
        interaction = SimpleNamespace(mouse_up=Mock(side_effect=RuntimeError()), send_key_up=Mock())
        release_inputs(SimpleNamespace(task_executor=SimpleNamespace(interaction=interaction)))
        interaction.send_key_up.assert_any_call('w')
        interaction.send_key_up.assert_any_call('lshift')
