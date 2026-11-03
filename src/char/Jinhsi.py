"""Build Jinhsi's attack chain with normals and positively recognized E forms."""
import time
from src.char.BaseChar import BaseChar, SwitchPriority
from src.char.JinhsiHud import enhanced_e_stage


class Jinhsi(BaseChar):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_free_intro = False

    def reset_state(self):
        super().reset_state()
        self.has_free_intro = False
        self._last_e_request = None

    def allows_opportunistic_skill(self, name):
        # R is independent. E form checks and Q's opening animation belong
        # to this module; neither Q nor R requires a successful E chain.
        return name == 'liberation'

    def get_switch_priority(self, current_char=None, has_intro=False, target_low_con=False):
        return SwitchPriority.MUST if has_intro else SwitchPriority.NO

    def switch_next_char(self, **args):
        super().switch_next_char(free_intro=self.has_free_intro, target_low_con=True)
        self.has_free_intro = False

    def do_perform(self):
        self.wait_intro(time_out=1.2, click=False)
        if self.has_intro:
            remaining = 1.1 - (time.time() - self.last_switch_in_time)
            if remaining > 0:
                self.sleep(remaining)
        self.task.next_frame()
        self.check_combat()
        if self.echo_available() and self.click_echo(time_out=0):
            # Jue retains the HUD during its animation. Input availability
            # cannot be inferred from a lit E while that animation plays.
            self.sleep(1.8)
            self.task.next_frame()
            self.check_combat()
        self.perform_attack_chain()
        self.switch_next_char()

    def perform_attack_chain(self):
        started = time.monotonic()
        event = {'status': 'building_with_normals', 'e_requests': [], 'confirmed': []}
        self.task.result.setdefault('jinhsi_attack_chains', []).append(event)
        candidate, samples = None, 0
        requested = {}
        pending = None
        try:
            while time.monotonic() - started < 14:
                self.task.next_frame()
                self.check_combat()
                stage = enhanced_e_stage(self.task.frame)
                # Native input may take several capture frames to affect the
                # HUD. Keep observing the single request instead of repeating
                # E or requiring the immediately following frame to change.
                if pending and ((stage is not None and stage != pending[0])
                                or self.has_cd('resonance')):
                    event['confirmed'].append(pending[0])
                    self.logger.info(f'Jinhsi enhanced E form consumed: {pending[0]}')
                    if pending[0] == 'finisher':
                        self.has_free_intro = True
                        event['status'] = 'finisher_confirmed'
                        self.task.use_ready_combat_skill()
                        return
                    pending = None
                elif pending and time.monotonic() - pending[1] >= 1:
                    # One spaced retry is allowed only while the exact same
                    # enhanced glyph remains visible. No ordinary-ready E
                    # fallback and no unbounded key-repeat loop.
                    pending = None
                samples = samples + 1 if stage and stage == candidate else 1
                candidate = stage
                if stage and samples == 1:
                    # Confirm the ready form on the next capture before
                    # starting normals/R. A long R cinematic must not consume
                    # the five-second enhanced-entry opportunity unchecked.
                    self.task.next_frame()
                    self.check_combat()
                    second = enhanced_e_stage(self.task.frame)
                    samples = 2 if second == stage else 1
                    stage = candidate = second
                # Neither ordinary E availability nor elapsed attack time
                # establishes an enhanced skill. Require its own icon twice.
                previous = getattr(self, '_last_e_request', None)
                blocked = previous and previous[0] == stage and time.monotonic()-previous[1] < 1
                if stage and samples >= 2 and requested.get(stage,0) < 2 and not blocked and not pending and not self.has_cd('resonance'):
                    requested[stage] = requested.get(stage,0) + 1
                    self._last_e_request = (stage, time.monotonic())
                    event['e_requests'].append(stage)
                    record = getattr(self.task, 'record_rotation_hud', None)
                    if callable(record):
                        record(f'jinhsi-{stage}-before-e')
                    # Give the E startup a short settling interval before a
                    # normal click can cancel it. This is an input interval,
                    # not a requirement that E succeed before R/Q are allowed.
                    self.send_resonance_key(down_time=.12, post_sleep=.25)
                    self.task.next_frame()
                    self.check_combat()
                    if callable(record):
                        record(f'jinhsi-{stage}-after-e')
                    pending = (stage,time.monotonic())
                elif previous and stage and previous[0] != stage:
                    self._last_e_request = None
                self.continues_normal_attack(.35)
            event['status'] = 'enhanced_chain_unconfirmed'
            self.logger.info('Jinhsi normal-attack window ended without verified finisher')
        finally:
            event['seconds'] = round(time.monotonic() - started, 2)
            self.task.mouse_up()
