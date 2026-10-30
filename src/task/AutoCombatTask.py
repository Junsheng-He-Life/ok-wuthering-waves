import time

from qfluentwidgets import FluentIcon

from ok import TriggerTask, Logger
from src.char.CharFactory import char_names
from src.combat.XuanlingTeam import XuanlingTeam
from src.scene.WWScene import WWScene
from src.task.BaseCombatTask import BaseCombatTask, NotInCombatException, CharDeadException

logger = Logger.get_logger(__name__)


class AutoCombatTask(XuanlingTeam, BaseCombatTask, TriggerTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_config = {'_enabled': True}
        self.trigger_interval = 0.1
        self.name = "Auto Combat"
        self.description = "Enable auto combat in Abyss, Game World etc"
        self.icon = FluentIcon.CALORIES
        self.last_is_click = False
        self.default_config.update({
            'Auto Target': True,
            'Use Liberation': True,
            'Check Levitator': True,
        })
        self.config_description = {
            'Auto Target': 'Turn off to enable auto combat only when manually target enemy using middle click',
            'Use Liberation': 'Do not use Liberation in Open World to Save Time',
            'Check Levitator': 'Toggle the levitator and verify if the character is floating',
        }
        self.op_index = 0
        self.char_features_warmed_up = False

    def warm_up_char_features(self):
        if self.char_features_warmed_up:
            return
        try:
            for char_name in char_names:
                self.get_feature_by_name(char_name)
        except Exception as e:
            logger.warning(f'warm_up_char_features failed: {e}')
            return
        self.char_features_warmed_up = True
        logger.info(f'warm_up_char_features loaded {len(char_names)} character templates')

    def run(self):
        ret = False
        from src.task.DomainTask import (
            domain_leave_confirmation_visible,
            manual_domain_exit_override_active,
        )
        if manual_domain_exit_override_active():
            self.log_info(
                'manual override: Auto Combat remains suppressed after '
                'the domain task yielded to the player'
            )
            return ret
        self.warm_up_char_features()
        if not self.scene.in_team(self.in_team_and_world):
            return ret
        raw_in_team = self.in_team()[0]
        if not raw_in_team:
            # A domain leave-confirmation overlay hides the live HUD while the
            # cached scene can still report the previous combat state. Never
            # let this trigger task resume inputs after a one-time domain task
            # has yielded to the player.
            if domain_leave_confirmation_visible(self):
                self.log_info(
                    'manual override: Auto Combat suppressed while leave '
                    'confirmation is visible'
                )
            return ret
        self.use_liberation = self.config.get('Use Liberation')
        if not self.use_liberation and not self.in_world():  # 仅大世界生效
            self.use_liberation = True
        combat_start = time.time()
        while self.in_combat():
            if any(c is None or c.char_name == 'unknown' for c in self.chars):
                self.log_error('Unrecognized team member; stop auto combat instead of using another character rotation')
                break
            ret = True
            try:
                self.get_current_char().perform()
            except CharDeadException:
                self.log_error(f'Characters dead', notify=True)
                break
            except NotInCombatException as e:
                logger.info(f'auto_combat_task_out_of_combat {int(time.time() - combat_start)} {e}')
                break
        if ret:
            self.combat_end()
        return ret

    def realm_perform(self):
        if not self.last_is_click:
            if self.op_index % 10 == 0:
                self.send_key_and_wait_animation('4', self.in_illusive_realm, enter_animation_wait=0.2)
            else:
                self.click()
        else:
            if self.available('liberation'):
                self.send_key_and_wait_animation(self.get_liberation_key(), self.in_illusive_realm)
            elif self.available('echo'):
                self.send_key(self.get_echo_key())
            elif self.available('resonance'):
                self.send_key(self.get_resonance_key())
            elif self.is_con_full() and self.in_team()[0]:
                self.send_key_and_wait_animation('2', self.in_illusive_realm)
        self.last_is_click = not self.last_is_click
        self.op_index += 1
        self.sleep(0.02)


from ok import run_task
from config import config

if __name__ == "__main__":
    run_task(config, task=AutoCombatTask, debug=True)
