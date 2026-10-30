"""Bounded settlement batching; never infer missing HP bars as healthy."""
import time
from src.combat.PortraitHealth import portrait_health


class MaterialSettlement:
    def settlement_batch_allowed(self):
        job = getattr(self, 'plan_job', None)
        mode = getattr(self, 'config', {}).get('结算批次策略', '节省体力')
        return bool(mode == '效率优先' and job and job.get('material_counts')
                    and any(a < b for a, b in job['material_counts'])
                    and job.get('kind') not in ('突破', '周本')
                    and not job.get('deferred_reason'))

    def capture_settlement_health(self):
        self.next_frame()
        bars = portrait_health(self.frame)
        self._settlement_health = (time.monotonic(), bars)
        return bars

    def material_batch_battles(self):
        return max(1, min(3, int(getattr(self, 'config', {}).get('每批连续挑战场数', 2))))

    def try_repeat_material(self, budget, remaining, battles_completed):
        if (not self.settlement_batch_allowed() or battles_completed >= self.material_batch_battles()
                or not budget.can_claim()):
            return False
        stamp, bars = getattr(self, '_settlement_health', (0, []))
        # This sample is collected after verified victory, before opening the
        # reward UI. It is cleared at every battle start. Settlement/refill can
        # legitimately take >15 seconds without another combat interval.
        if (not 0 <= time.monotonic() - stamp <= 90 or len(bars) != 3
                or any(value is None or value < .85 for value in bars)):
            return False
        if not self.menu_text(r'挑战成功|ChallengeCompleted|ChallengeSuccess', (.2, .1, .8, .4), timeout=1):
            return False
        button = self.menu_text(r'重新挑战|再次挑战|ChallengeAgain|Retry', (.55, .7, 1, 1), timeout=1)
        if not button:
            return False
        self.focus_material_menu()
        self.click_box(button, after_sleep=1)
        self._entry_warning_accepted = False
        self.handle_material_entry_notice(timeout=8)
        if not self.wait_until(lambda: self.in_team()[0], time_out=30, raise_if_not_found=False):
            raise RuntimeError('重新挑战后的队伍界面未确认；停止输入')
        self._material_restarted = True
        self._settlement_health = (0, [])
        self.log_info('healthy team: restarted same material without overworld travel')
        return True
