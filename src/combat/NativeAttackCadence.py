"""Short native attack strings that do not serialize every click behind OCR."""
import sys
import time


class NativeAttackCadence:
    def native_bounded_heavy(self, duration):
        """Let the native helper release a short hold before any slow OCR.

        Health/stop checks run before the hold; the caller refreshes health
        after release. The helper's synchronous click owns both edges, so a
        multi-second combat check cannot prolong a requested 0.65 s press.
        """
        if sys.platform != 'darwin' or not getattr(self, '_verified_battle', False):
            return None
        from ok.device.interaction_methods.macos import MacForegroundInteraction
        interaction = self.executor.interaction
        if not isinstance(interaction, MacForegroundInteraction):
            return None
        self.check_combat()
        self.executor.check_enabled()
        self._raise_if_manual_exit_before_input()
        if self.executor.exit_event.is_set() or not interaction.clickable():
            return {'status': 'interrupted', 'held_seconds': 0}
        start = time.monotonic()
        try:
            interaction.click(down_time=min(.65, max(0, duration)))
        finally:
            self.mouse_up()
        return {'status': 'released', 'held_seconds': round(time.monotonic()-start,4)}

    def native_attack_string(self, count, interval=.1):
        """Return False outside native verified combat; otherwise send a bounded string.

        Visual/health checks surround at most three presses. Pause, stop,
        foreground ownership and the player's exit dialog still gate input.
        There is no worker thread or queued input surviving a rotation.
        """
        if sys.platform != 'darwin' or not getattr(self, '_verified_battle', False):
            return False
        from ok.device.interaction_methods.macos import MacForegroundInteraction
        interaction = self.executor.interaction
        if not isinstance(interaction, MacForegroundInteraction):
            return False
        remaining = count
        while remaining > 0:
            self.check_combat()
            ready_skill = getattr(self, 'use_ready_combat_skill', None)
            if callable(ready_skill) and ready_skill():
                return True
            for _ in range(min(3, remaining)):
                self.executor.check_enabled()
                self._raise_if_manual_exit_before_input()
                if self.executor.exit_event.is_set() or not interaction.clickable():
                    return True
                interaction.click(down_time=.08)
                remaining -= 1
                if remaining:
                    time.sleep(interval)
            self.next_frame()
        self.check_combat()
        return True
