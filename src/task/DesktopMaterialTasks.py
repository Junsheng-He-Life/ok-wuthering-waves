"""User-facing desktop tasks sharing the tested bounded workflow."""
from src.task.SafeMaterialTask import SafeMaterialTask


class MaterialPracticeTask(SafeMaterialTask):
    phase = 'practice'
    run_limit = 1
    reserve_limit = 0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '战斗试跑（不领奖）'
        self.description = '核对队伍与血量，打一局后退出。不领奖、不补体力。'
        self.support_schedule_task = False
        for key in ('Maximum runs', 'Maximum reserve waveplates'):
            self.default_config.pop(key, None)


class DesktopMaterialTask(SafeMaterialTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '安全素材连刷'
        self.description = '按局数单倍领奖；储备默认不补。目标、关卡或结算无法确认时停止。'
        self.support_schedule_task = False


class MaterialRecoveryTask(SafeMaterialTask):
    phase = 'recover'
    run_limit = 1
    reserve_limit = 0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '返回并治疗'
        self.description = '退出当前副本，必要时传送信标并核对三人血量。不领奖、不补体力。'
        self.support_schedule_task = False
        self.default_config.clear()
