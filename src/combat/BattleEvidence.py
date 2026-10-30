"""Persist decision evidence synchronously, before recovery changes the screen."""
import json
import time
from pathlib import Path


class BattleEvidence:
    def fail_battle(self, reason):
        from src.task.VerifiedDomainCombat import DomainBattleFailed
        try:
            self.save_battle_trigger(reason)
        except Exception as exc:
            # A full disk must not suppress recovery, but never hide lost evidence.
            reason += f' [触发证据保存失败: {exc}]'
        raise DomainBattleFailed(reason)

    def save_battle_trigger(self, reason):
        import cv2
        executor = getattr(self, '_executor', None)
        frame = executor.nullable_frame() if executor is not None else None
        frame_source = 'executor_cache'
        if frame is None:
            frame = getattr(self, '_battle_decision_frame', None)
            frame_source = 'last_decision_frame'
        hp_frame = getattr(self, '_hp_observation_frame', None)
        if frame is None and hp_frame is None:
            return None
        folder = Path(getattr(self, 'battle_evidence_root', 'logs/battle-triggers')) / str(time.time_ns())
        folder.mkdir(parents=True, exist_ok=False)
        now = time.monotonic()
        report = {'reason': reason, 'wall_time_ns': time.time_ns(), 'monotonic': now,
                  'hp_observation': getattr(self, '_hp_observation', None),
                  'healing': getattr(self, '_boss_healing', False),
                  'boss': getattr(getattr(self, 'boss_profile', None), 'key', None),
                  'trigger_frame_source': frame_source,
                  'images': {}}
        for label, image in (('trigger', frame), ('hp_source', hp_frame)):
            if image is not None:
                name = label + '.png'
                if not cv2.imwrite(str(folder / name), image):
                    raise RuntimeError(f'cannot write {name}')
                report['images'][label] = name
        for name in ('_boss_heal_deadline', '_battle_deadline', '_boss_acquire_deadline'):
            value = getattr(self, name, None)
            report[name] = value
            if isinstance(value, (int, float)):
                report[name + '_remaining'] = value - now
        observation = report['hp_observation']
        if observation:
            report['hp_age_seconds'] = now - observation['monotonic']
        (folder / 'decision.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        result = getattr(self, 'result', None)
        if isinstance(result, dict):
            result.setdefault('trigger_evidence', []).append(str(folder))
        return folder
