"""Short native attack strings that do not serialize every click behind OCR."""
import sys
import time


class NativeAttackCadence:
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
                interaction.click(down_time=.08)
                remaining -= 1
                if remaining:
                    time.sleep(interval)
            self.next_frame()
        self.check_combat()
        return True
