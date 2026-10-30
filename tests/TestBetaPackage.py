"""Release exports preserve recognition pixels without exporting player state."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, PngImagePlugin

from scripts.beta_assets import export_recognition_assets, safe_relative
from scripts.bootstrap_macos import check_host, verify_bundle
from scripts.build_macos_beta import APP_FILES, build


class TestBetaPackage(unittest.TestCase):
    def test_bootstrap_rejects_old_macos_before_install(self):
        with patch('scripts.bootstrap_macos.sys.platform', 'darwin'), \
             patch('scripts.bootstrap_macos.platform.machine', return_value='arm64'), \
             patch('scripts.bootstrap_macos.platform.mac_ver', return_value=('13.6', ('', '', ''), 'arm64')):
            with self.assertRaisesRegex(RuntimeError, 'macOS 14'):
                check_host()

    def assets(self, root):
        assets = root / 'assets'
        (assets / 'images').mkdir(parents=True, exist_ok=True)
        pixels = np.zeros((80, 120, 3), dtype=np.uint8)
        pixels[10:20, 20:30] = [15, 30, 80]
        pixels[78:, 100:] = 255  # Simulated account ID outside the template.
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text('Author', 'private player')
        metadata.add_text('ok_compressed', '1')
        Image.fromarray(pixels).save(assets / 'images/template.png', pnginfo=metadata)
        data = {'info': {'private': 'capture location'}, 'licenses': [],
                'images': [{'id': 1, 'file_name': 'images/template.png', 'width': 120,
                            'height': 80, 'source_capture': 'logs/private.png'}],
                'categories': [{'id': 1, 'name': 'char_example'}],
                'annotations': [{'id': 1, 'image_id': 1, 'category_id': 1,
                                 'bbox': [20, 10, 10, 10], 'area': 100}]}
        (assets / 'coco_annotations.json').write_text(json.dumps(data))
        return pixels

    def test_template_export_keeps_exact_roi_but_not_account_pixels_or_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            expected = self.assets(root)
            destination = root / 'export'
            evidence = export_recognition_assets(root / 'assets', destination)
            with Image.open(destination / 'images/template.png') as result:
                actual = np.asarray(result)
                self.assertEqual(result.size, (120, 80))
                self.assertNotIn('Author', result.info)
                self.assertEqual('1', result.info['ok_compressed'])
            np.testing.assert_array_equal(expected[10:20, 20:30], actual[10:20, 20:30])
            self.assertFalse(actual[78:, 100:].any())
            data = json.loads((destination / 'coco_annotations.json').read_text())
            self.assertNotIn('source_capture', data['images'][0])
            self.assertTrue(evidence[0]['roi_pixels_identical'])

    def test_resource_path_cannot_escape_or_publish_an_account_id_roi(self):
        for bad in ('/tmp/private.png', '../private.png', 'images/../../private.png', 'images\\private.png'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                safe_relative(bad)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assets(root)
            path = root / 'assets/coco_annotations.json'
            data = json.loads(path.read_text())
            data['annotations'][0]['bbox'] = [100, 78, 10, 2]
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'account-ID'):
                export_recognition_assets(root / 'assets', root / 'export')

    def fixture_package(self, root):
        app, framework = root / 'source-app', root / 'source-framework'
        for relative in APP_FILES:
            path = app / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('fixture')
        self.assets(app)
        for name in ('leviathan-reward-orb-1920.png', 'map-beacon-huanglong-1920.png', 'map-nexus-huanglong-1920.png'):
            Image.new('RGB', (8, 8)).save(app / 'assets/images' / name)
        for relative in ('src/actual_dirty_code.py', 'configs/account.json', 'logs/player.png'):
            path = app / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('current uncommitted content')
        framework.mkdir()
        for relative in ('setup.py', 'VERSION', 'MANIFEST.in', 'README.md', 'ok/__init__.py'):
            path = framework / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('framework source')
        return app, framework

    def test_snapshot_uses_current_files_and_excludes_player_state(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app, framework = self.fixture_package(root)
            output = root / 'release'
            with patch('scripts.build_macos_beta.git_metadata', return_value={'base_commit': 'abc', 'working_tree_dirty': True}):
                manifest = build(app, framework, output, 'test', archive=False)
            self.assertFalse((output / 'ok-wuthering-waves/configs').exists())
            self.assertFalse((output / 'ok-wuthering-waves/logs').exists())
            relative = 'ok-wuthering-waves/src/actual_dirty_code.py'
            self.assertEqual(hashlib.sha256(b'current uncommitted content').hexdigest(),
                             manifest['files'][relative]['sha256'])
            verify_bundle(output / 'ok-wuthering-waves')
            (output / relative).write_text('modified after export')
            with self.assertRaisesRegex(RuntimeError, '文件已变化'):
                verify_bundle(output / 'ok-wuthering-waves')
            with self.assertRaises(FileExistsError):
                build(app, framework, output, 'test', archive=False)

    def test_bootstrap_verification_rejects_symlink_even_with_matching_content(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app = root / 'ok-wuthering-waves'
            app.mkdir()
            secret = root / 'private'
            secret.write_text('same')
            (app / 'file').symlink_to(secret)
            (root / 'release-manifest.json').write_text(json.dumps({'files': {
                'ok-wuthering-waves/file': {'sha256': hashlib.sha256(b'same').hexdigest()}}}))
            with self.assertRaisesRegex(RuntimeError, '路径无效'):
                verify_bundle(app)


if __name__ == '__main__':
    unittest.main()
