"""Per-encounter policies. Timing values are conservative automation budgets,
not claims about game attack timings. Unverified mechanics require recordings.
"""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class BossProfile:
    key: str
    aliases: tuple[str, ...]
    acquire_seconds: float = 8
    transition_seconds: float = 6
    approach_step: float = .3
    health_interval: float = 1
    reactive_dodge: bool = False
    supported: bool = True
    battle_seconds: float = 150
    evidence: str = 'local FarmEchoTask entry policy; material combat unverified'


PROFILES = (
    BossProfile('leviathan', ('利维亚坦', '利維亞坦', 'Leviathan'),
                acquire_seconds=15, transition_seconds=30, approach_step=.4,
                battle_seconds=600, evidence='cultivation source 深洋的咒诅; guarded weekly trial'),
    BossProfile('mourning_aix', ('哀声鸷', '哀聲鷙', 'MourningAix'),
                acquire_seconds=12, transition_seconds=10, approach_step=.4,
                battle_seconds=300, evidence='cultivation material source; direct boss teleport adapter'),
    BossProfile('false_sovereign', ('伪作的神王', '偽作的神王'),
                acquire_seconds=12, transition_seconds=12, approach_step=.4,
                battle_seconds=300, evidence='cultivation material source; direct boss teleport adapter'),
    BossProfile('fenrico', ('芬莱克', '芬萊克', 'Fenrico'),
                transition_seconds=12, approach_step=.6, reactive_dodge=True,
                evidence='local recordings 2026-09-27: approach, damage, rotations; clear and reward verified; claim required supervised confirmation'),
    BossProfile('fallacy', ('无归的谬误', '無歸的謬誤', 'FallacyofNoReturn'),
                transition_seconds=8),
    BossProfile('sentry', ('SentryConstruct',), transition_seconds=8),
    BossProfile('lioness', ('荣耀狮像', '榮耀獅像', 'LionessofGlory'), transition_seconds=8),
    BossProfile('hyvatia', ('Hyvatia',), transition_seconds=10),
    BossProfile('nameless', ('无铭探索者', '無銘探索者', 'NamelessExplorer'),
                acquire_seconds=12, approach_step=.4),
    BossProfile('lady', ('LadyoftheSea',), supported=False,
                evidence='requires separate realm interaction adapter in FarmEchoTask'),
    BossProfile('hecate', ('赫卡忒', 'Hecate'), supported=False,
                evidence='normal/nightmare variants and transitions need separate recordings'),
    BossProfile('wanelao', ('万囮牢', '萬囮牢', '万四牢·朽躯', '万@牢・朽躯',
                            '万囤牢·朽躯'),
                acquire_seconds=12, transition_seconds=10, approach_step=.4,
                reactive_dodge=True,
                battle_seconds=300,
                evidence='experimental normal encounter: bounded acquisition, team healing and damage reaction; no clear verified'),
    BossProfile('tianyansuxin', ('天演溯心',), acquire_seconds=12,
                transition_seconds=12, approach_step=.4, reactive_dodge=True,
                battle_seconds=300,
                evidence='heart weekly entry verified in game; first guarded combat trial, no clear verified'),
    BossProfile('qiankui', ('千傀重楼', '千傀重樓'), supported=False,
                evidence='team weekly candidate; attack/mechanic recordings unavailable'),
)


def resolve_boss_profile(title):
    # OCR alternates the Japanese and Chinese middle-dot separators.
    text = re.sub(r'\s+', '', title).replace('・', '·').casefold()
    matches = [p for p in PROFILES if any(a.replace('・', '·').casefold() in text for a in p.aliases)]
    # Do not apply a normal-boss policy to a nightmare variant.
    if any(word in text for word in ('梦魇', '夢魘', 'nightmare', '全息', 'hologram')):
        return None
    return matches[0] if len(matches) == 1 else None
