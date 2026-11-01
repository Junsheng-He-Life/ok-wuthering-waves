"""Short native attack strings that do not serialize every click behind OCR."""
import sys
import time


class NativeAttackCadence:
    def native_attack_string(self, count, interval=.1, *, duration=None):
        """Return False outside native verified combat; otherwise send a bounded string.

        Visual/health checks surround at most three presses. Pause, stop,
        foreground ownership and the player's exit dialog still gate input.
        There is no worker thread or queued input surviving a rotation.
        Count-based combos retain their press count. Duration-based filler has
        a real wall deadline, including recognition cost, not a guessed count
        multiplied by an assumed input latency.
        """
        if sys.platform != 'darwin' or not getattr(self, '_verified_battle', False):
            return False
        from ok.device.interaction_methods.macos import MacForegroundInteraction
        interaction = self.executor.interaction
        if not isinstance(interaction, MacForegroundInteraction):
            return False
        deadline = time.monotonic() + duration if duration is not None else None
        def expired():
            return deadline is not None and time.monotonic() >= deadline
        remaining = count
        result = getattr(self, 'result', None)
        metrics = (result.setdefault('native_attack_cadence', {'strings': 0, 'presses': 0,
                    'interval_samples': 0, 'interval_seconds': 0., 'max_interval_seconds': 0.})
                   if isinstance(result, dict) else None)
        if metrics is not None:
            metrics['strings'] += 1
        previous_press = None
        while remaining > 0 and not expired():
            self.check_combat()
            if expired():
                break
            ready_skill = getattr(self, 'use_ready_combat_skill', None)
            if callable(ready_skill) and ready_skill():
                # A ready skill replaces this filler segment. Return control
                # to its character module with a fresh HUD instead of replaying
                # a stale attack queue after the animation.
                self.next_frame()
                self.check_combat()
                return True
            for _ in range(min(3, remaining)):
                self.executor.check_enabled()
                self._raise_if_manual_exit_before_input()
                if self.executor.exit_event.is_set() or not interaction.clickable():
                    return True
                if expired():
                    break
                stamp = time.monotonic()
                if metrics is not None:
                    metrics['presses'] += 1
                    if previous_press is not None:
                        gap = stamp - previous_press
                        metrics['interval_samples'] += 1
                        metrics['interval_seconds'] += gap
                        metrics['max_interval_seconds'] = max(metrics['max_interval_seconds'], gap)
                previous_press = stamp
                interaction.click(down_time=.08)
                remaining -= 1
                if remaining and not expired():
                    pause = interval if deadline is None else min(interval, max(0, deadline-time.monotonic()))
                    time.sleep(pause)
            self.next_frame()
        self.check_combat()
        return True
