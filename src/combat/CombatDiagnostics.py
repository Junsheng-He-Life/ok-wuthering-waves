"""Opt-in timing of the existing executor; never capture or issue input here."""
from contextlib import contextmanager
import cProfile
import json
import os
from pathlib import Path
import time


@contextmanager
def combat_diagnostics(task):
    if not getattr(task, 'record_hud', False):
        yield
        return
    folder = Path('logs/combat-timing') / str(time.time_ns())
    folder.mkdir(parents=True, exist_ok=True)
    interaction = task.executor.interaction
    originals, events, calls, task_originals = {}, [], [], {}
    dropped = 0

    def wrap(name, original):
        def measured(*args, **kwargs):
            nonlocal dropped
            active = getattr(task, '_verified_battle', False)
            start, wall = time.monotonic(), time.time_ns()
            try:
                return original(*args, **kwargs)
            finally:
                if active:
                    if len(events) < 12000:
                        events.append({'action': name, 'args': [str(a) for a in args[:2]],
                            'key': kwargs.get('key'), 'down_time': kwargs.get('down_time'),
                            'wall_ns': wall, 'start': start, 'end': time.monotonic(),
                            'step': getattr(task, '_combat_diagnostic_step', None)})
                    else:
                        dropped += 1
        return measured

    # Wall timings are authoritative for inter-action latency. The optional
    # profiler may include native callback threads and is only a discovery aid.
    profile = cProfile.Profile() if os.environ.get('OKWW_PROFILE_COMBAT') == '1' else None

    def measure_call(name, original):
        def measured(*args, **kwargs):
            start, wall = time.monotonic(), time.time_ns()
            try:
                return original(*args, **kwargs)
            finally:
                if len(calls) < 20000:
                    calls.append({'name': name, 'start': start, 'end': time.monotonic(),
                                  'wall_ns': wall})
        return measured

    try:
        for name in ('click', 'send_key', 'mouse_down', 'mouse_up', 'send_key_down', 'send_key_up'):
            method = getattr(interaction, name, None)
            if callable(method):
                originals[name] = method
                setattr(interaction, name, wrap(name, method))
        for name in ('check_combat', 'next_frame', 'read_current_hp', 'refresh_cd',
                     'find_battle_reward_marker', 'in_team_and_world',
                     'manual_domain_exit_requested', 'get_current_con',
                     'native_attack_string', 'use_ready_combat_skill'):
            method = getattr(task, name, None)
            if callable(method):
                task_originals[name] = method
                setattr(task, name, measure_call(name, method))
        if profile:
            profile.enable()
        yield
    finally:
        if profile:
            profile.disable()
        for name, method in originals.items():
            setattr(interaction, name, method)
        for name, method in task_originals.items():
            setattr(task, name, method)
        if profile:
            profile.dump_stats(str(folder / 'profile.pstats'))
        (folder / 'calls.json').write_text(json.dumps(calls, indent=2))
        (folder / 'inputs.json').write_text(json.dumps(
            {'events': events, 'dropped': dropped, 'note':
             'Synchronous backend calls, not proof of game acceptance. No new input/capture thread.'},
            ensure_ascii=False, indent=2))
        result = getattr(task, 'result', None)
        if isinstance(result, dict):
            result.setdefault('combat_timing', []).append(str(folder))
