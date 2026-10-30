"""Absorb interactions isolated from every waveplate reward handler."""
import time
from pathlib import Path

import cv2


class EchoPickupUI:
    def pick_f(self, handle_claim=True):
        # OKWW's YOLO walker calls pick_f, rather than pick_echo. Route that
        # branch through the same absorb-only gate as a stationary pickup.
        if handle_claim:
            return self.pick_echo()
        return super().pick_f(handle_claim=False)

    def handle_claim_button(self):
        raise RuntimeError('声骸任务不使用通用领奖处理；须走限额结算')

    def pick_echo(self):
        self.next_frame()
        absorb = self.absorb_echo_text(ignore_config=True)
        if absorb is None:
            raise RuntimeError('当前语言的吸收提示未适配；不发送通用 F')
        if not self.find_f_with_text(target_text=absorb):
            return False
        for key in ('w', 'a', 's', 'd'):
            self.send_key_up(key)
        folder = Path('logs/echo-pickup')
        folder.mkdir(parents=True, exist_ok=True)
        stamp = str(time.time_ns())
        cv2.imwrite(str(folder / f'{stamp}-before.png'), self.frame)
        self.send_key('f', after_sleep=.8)

        def cleared():
            return (self.in_team()[0] and not self.find_f_with_text(
                target_text=absorb))

        if not self.wait_until(cleared, time_out=5, raise_if_not_found=False):
            raise RuntimeError('吸收交互结果未确认；不重复发送 F')
        cv2.imwrite(str(folder / f'{stamp}-after.png'), self.frame)
        self.result.setdefault('absorb_interactions', []).append({
            'evidence': str(folder / stamp), 'prompt_cleared': True,
            'inventory_verified': False})
        # This counts a cleared absorb prompt, not a verified inventory delta.
        self.info_set('吸收交互已确认', len(self.result['absorb_interactions']))
        return True

    def search_echo(self):
        if self.pick_echo():
            return True
        # Reuse OKWW's bounded visual navigation with the strict pick_echo
        # override above. Never call its generic pick_f/claim handler.
        absorbed, multiple = self.yolo_find_echo(
            turn=True, use_color=False, time_out=12, threshold=.5)
        self.result.setdefault('echo_searches', []).append({
            'absorbed_prompt_cleared': bool(absorbed), 'multiple_seen': bool(multiple)})
        return bool(absorbed)
