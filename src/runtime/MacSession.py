"""One foreground controller per workspace, independent of its launcher."""
import fcntl
import json
from pathlib import Path
import shutil


class MacSession:
    def __init__(self, root):
        self.path = Path(root) / 'logs' / 'macos-controller.lock'
        self.handle = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open('a+')
        try:
            fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.handle.close()
            self.handle = None
            raise RuntimeError('已有 OK-WW 控制器运行，请先停止或关闭它。') from None
        return self

    def close(self):
        if self.handle:
            self.handle.close()
            self.handle = None


def release_inputs(app):
    executor = getattr(app, 'task_executor', None)
    interaction = getattr(executor, 'interaction', None)
    if interaction:
        for button in ('left', 'right', 'middle'):
            try:
                interaction.mouse_up(key=button)
            except Exception:
                pass
        for key in ('w', 'a', 's', 'd', 'shift', 'lshift', 'alt', 'ctrl', 'space'):
            try:
                interaction.send_key_up(key)
            except Exception:
                pass


def prepare_desktop_config(root, source):
    config = dict(source)
    folder = Path(root) / 'configs' / 'macos-desktop'
    folder.mkdir(parents=True, exist_ok=True)
    profile_path = Path(root) / 'profiles' / 'macos-native-screen.json'
    profile = json.loads(profile_path.read_text()) if profile_path.exists() else {}
    # Retain device selection and the player's bindings on first use only.
    # Task enablement and scheduled jobs are deliberately not migrated.
    for name in ('devices.json', 'Game Hotkey.json'):
        source_file = Path(root) / 'configs' / name
        if name == 'Game Hotkey.json' and profile.get('game_hotkeys'):
            hotkeys_path = folder / name
            hotkeys = dict(profile['game_hotkeys'])
            # Saved GUI edits remain authoritative; the named profile supplies
            # native defaults without importing another screen's key guesses.
            if hotkeys_path.exists():
                hotkeys.update(json.loads(hotkeys_path.read_text()))
            hotkeys_path.write_text(json.dumps(hotkeys, ensure_ascii=False, indent=2))
            continue
        if source_file.exists() and not (folder / name).exists():
            shutil.copyfile(source_file, folder / name)
    basic_path = folder / 'Basic Options.json'
    basic = json.loads(basic_path.read_text()) if basic_path.exists() else {}
    basic.update({'Auto Start Game When App Starts': False,
                  'Minimize Window to System Tray when Closing': False,
                  'Auto Resize Game Window': False})
    basic.setdefault('Start/Stop', profile.get('start_stop_key', 'F9'))
    basic_path.write_text(json.dumps(basic, ensure_ascii=False, indent=2))
    # Each launch starts with auto combat OFF. The player enables it explicitly.
    combat_path = folder / 'AutoCombatTask.json'
    combat = json.loads(combat_path.read_text()) if combat_path.exists() else {
        'Auto Target': True, 'Use Liberation': True, 'Check Levitator': True}
    combat['_enabled'] = False
    combat_path.write_text(json.dumps(combat, ensure_ascii=False, indent=2))
    config.update(use_gui=True, config_folder=str(folder),
                  gui_title='OK-WW macOS · 素材与战斗（试用）', check_mutex=False)
    if profile.get('name'):
        config['gui_title'] += ' · ' + profile['name']
    config['onetime_tasks'] = [
        ['src.task.DesktopMaterialTasks', 'MaterialPracticeTask'],
        ['src.task.DesktopMaterialTasks', 'DesktopMaterialTask'],
        ['src.task.TeamMaterialTask', 'TeamMaterialTask'],
        ['src.task.TeamMaterialScanTask', 'TeamMaterialScanTask'],
        ['src.task.EchoFarmTask', 'BossEchoTask'],
        ['src.task.EchoFarmTask', 'TacetEchoTask'],
        ['src.task.DesktopMaterialTasks', 'MaterialRecoveryTask'],
    ]
    config['trigger_tasks'] = [['src.task.AutoCombatTask', 'AutoCombatTask']]
    config.pop('update_pyappify', None)  # Windows binary updater is not a macOS launcher.
    return config
