"""The offline regression runner must not alter installed user configuration."""
import json
import tempfile
import unittest
from pathlib import Path

from scripts.test_material_stability import isolated_test_workspace


class TestMaterialTestIsolation(unittest.TestCase):
    def test_config_and_relative_ui_writes_stay_in_scratch_directory(self):
        from config import config
        from ok.util.config import Config
        original_directory = Path.cwd()
        original_folder = Config.config_folder
        original_config_folder = config.get('config_folder')
        with tempfile.TemporaryDirectory() as folder:
            installation = Path(folder)
            user_configs = installation / 'configs'
            user_configs.mkdir()
            hint = user_configs / '_combat_team_hint.json'
            original = b'{"0":"actual-player-character"}'
            hint.write_bytes(original)
            with isolated_test_workspace(installation) as workspace:
                state = Config('_combat_team_hint', {'0': ''})
                state['0'] = 'test-character'
                Path('configs/ui_config.json').write_text('{"test":true}')
                Path('logs/test-result.json').write_text('{}')
                self.assertEqual(str(workspace / 'configs'), config['config_folder'])
                for key in ('macos', 'windows', 'adb', 'browser'):
                    self.assertNotIn(key, config)
                self.assertEqual('test-character', json.loads(
                    (workspace / 'configs/_combat_team_hint.json').read_text())['0'])
                self.assertEqual(original, hint.read_bytes())
                self.assertFalse((user_configs / 'ui_config.json').exists())
                self.assertFalse((installation / 'logs').exists())
            self.assertFalse(workspace.exists())
            self.assertEqual(original, hint.read_bytes())
        self.assertEqual(original_directory, Path.cwd())
        self.assertEqual(original_folder, Config.config_folder)
        self.assertEqual(original_config_folder, config.get('config_folder'))
