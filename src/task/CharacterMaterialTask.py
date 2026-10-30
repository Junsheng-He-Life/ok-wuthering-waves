import threading
import time

from qfluentwidgets import FluentIcon

from ok import Logger
from src.Labels import Labels
from src.task.BaseWWTask import MATERIALS_TITLE_BOX, MATERIALS_TITLE_TEXT
from src.task.DomainTask import DomainTask

logger = Logger.get_logger(__name__)

CULTIVATION_TARGET = 'Cultivation Target'
CHARACTER_MATERIAL_TYPE = 'Character Material Type'
FALLBACK_STAGE_NAME = 'Fallback Stage Name'
SAVE_COMBAT_DEBUG_FRAMES = 'Save Combat Frames for Debug'
LEGACY_TARGET_DOMAIN_NAME = 'Target Domain Name'

AUTO_MATERIAL = 'Auto (Target Avatar)'
LEGACY_AUTO_MATERIAL = 'Auto (Character Profile)'
RESONATOR_EXP = 'Resonator EXP'
WEAPON_AND_SKILL = 'Weapon & Skill'

USE_CURRENT_TARGET = 'Use current in-game target'

CHARACTER_MATERIAL_PROFILES = {
    '秧秧玄翎': {
        'display_name': '秧秧·玄翎',
        'default_material': WEAPON_AND_SKILL,
    },
    '爱弥斯': {
        'display_name': '爱弥斯',
        'default_material': WEAPON_AND_SKILL,
        'team_hints': (
            Labels.char_aemeath,
            Labels.chang_changli,
            Labels.char_moning,
        ),
        # Verified on the live 1920x1080 material list. This is consulted only
        # when the cultivation-target avatar row cannot be read reliably.
        'fallback_stage_name': '荒萋旧殿',
        'material_snapshot': {
            'captured_at': '2026-07-25',
            'materials': (
                {
                    'name': '我们的选择',
                    'category': 'Resonator Ascension',
                    'owned': 11,
                    'required': 16,
                },
                {
                    'name': '叠翼偏振体',
                    'category': WEAPON_AND_SKILL,
                    'owned': 3,
                    'required': 71,
                },
                {
                    'name': '忆中沉金',
                    'category': 'Skill Upgrade',
                    'owned': 0,
                    'required': 14,
                },
                {
                    'name': '时苔茸',
                    'category': 'Resonator Ascension',
                    'owned': 0,
                    'required': 20,
                },
                {
                    'name': '高频啸花声核',
                    'category': WEAPON_AND_SKILL,
                    'owned': 1,
                    'required': 3,
                },
                {
                    'name': '全频啸花声核',
                    'category': WEAPON_AND_SKILL,
                    'owned': 1,
                    'required': 45,
                },
                {
                    'name': '全频锐棱声核',
                    'category': WEAPON_AND_SKILL,
                    'owned': 2,
                    'required': 12,
                },
            ),
        },
    },
}


class CharacterMaterialTask(DomainTask):
    """Farm a waveplate domain associated with a cultivation target.

    The target is selected or verified before a material row is considered.
    The cultivation-target avatar identifies the recommended stage row. The
    icons after the universal experience reward form the material fingerprint.
    Stage names are navigation labels and are never treated as material names.
    """

    DOMAIN_ENTRY_READY_DELAY = 3
    DOMAIN_ENTRY_FORWARD_TIME = 8
    DOMAIN_ENTRY_KEY_PULSE = 0.25
    COMBAT_DEBUG_FRAME_HZ = 5
    COMBAT_DEBUG_FRAME_FOLDER = 'character_material_combat_frames'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.icon = FluentIcon.PEOPLE
        self.name = 'Character Material Farming'
        self.description = (
            'Select a cultivation target and farm its configured material '
            'domain until waveplates are exhausted.'
        )
        self.support_schedule_task = True
        self.default_config = {
            CULTIVATION_TARGET: '秧秧·玄翎',
            CHARACTER_MATERIAL_TYPE: AUTO_MATERIAL,
            FALLBACK_STAGE_NAME: '',
            SAVE_COMBAT_DEBUG_FRAMES: False,
        }
        self.config_description = {
            CULTIVATION_TARGET: (
                'Exact character name shown in Material Acquisition. Use '
                f'"{USE_CURRENT_TARGET}" to keep the current in-game target.'
            ),
            CHARACTER_MATERIAL_TYPE: (
                'Auto uses the cultivation-target avatar. Resonator EXP is '
                'universal; Weapon & Skill is character-specific.'
            ),
            FALLBACK_STAGE_NAME: (
                'Optional stage name used only when the cultivation-target '
                'avatar marker cannot be detected. This is not a material name.'
            ),
            SAVE_COMBAT_DEBUG_FRAMES: (
                'Save the latest combat frame at 5 Hz for debugging. Files '
                'are timestamped under screenshots/'
                f'{self.COMBAT_DEBUG_FRAME_FOLDER}.'
            ),
        }
        self.config_type[CHARACTER_MATERIAL_TYPE] = {
            'type': 'drop_down',
            'options': [AUTO_MATERIAL, RESONATOR_EXP, WEAPON_AND_SKILL],
        }
        self.stamina_once = 40
        self._preferred_farming_team_hints = ()
        self._save_combat_debug_frames_enabled = False
        self._combat_debug_frame_stop = None
        self._combat_debug_frame_thread = None
        self._combat_debug_frame_count = 0
        self.add_exit_after_config()

    def run(self):
        super().run()
        self.make_sure_in_world()
        self.farm_character_materials()

    def on_combat_started(self):
        """Start the optional 5 Hz recorder for the confirmed combat only."""
        self._start_combat_debug_frame_recorder()
        try:
            super().on_combat_started()
        except BaseException:
            self._stop_combat_debug_frame_recorder()
            raise

    def combat_end(self):
        """Stop recording before leaving the completed combat context."""
        try:
            super().combat_end()
        finally:
            self._stop_combat_debug_frame_recorder()

    def _start_combat_debug_frame_recorder(self):
        self._stop_combat_debug_frame_recorder(log_result=False)
        if not self._save_combat_debug_frames_enabled:
            return
        self._combat_debug_frame_stop = threading.Event()
        self._combat_debug_frame_count = 0
        self._combat_debug_frame_thread = threading.Thread(
            target=self._combat_debug_frame_recording_loop,
            name='character-material-combat-frames',
            daemon=True,
        )
        self._combat_debug_frame_thread.start()
        self.log_info(
            'combat debug frame recording started: '
            f'{self.COMBAT_DEBUG_FRAME_HZ} Hz -> screenshots/'
            f'{self.COMBAT_DEBUG_FRAME_FOLDER}'
        )

    def _combat_debug_frame_recording_loop(self):
        interval = 1 / self.COMBAT_DEBUG_FRAME_HZ
        stop_event = self._combat_debug_frame_stop
        while stop_event is not None and not stop_event.is_set():
            started_at = time.monotonic()
            try:
                self._capture_combat_debug_frame()
            except Exception:
                logger.exception(
                    'failed to save character material combat frame'
                )
            remaining = interval - (time.monotonic() - started_at)
            if stop_event.wait(max(0, remaining)):
                break

    def _capture_combat_debug_frame(self):
        """Queue a safe copy of the executor's latest frame for PNG writing."""
        frame = self.executor.nullable_frame()
        if frame is None:
            return False
        if getattr(self, 'record_hud', False):
            # Headless runs have no GUI screenshot signal receiver. Write on
            # this recorder thread instead of emitting a signal nobody saves.
            import cv2
            from pathlib import Path
            folder = Path('logs') / self.COMBAT_DEBUG_FRAME_FOLDER
            folder.mkdir(parents=True, exist_ok=True)
            if not cv2.imwrite(str(folder / f'{time.time_ns()}.jpg'), frame.copy(),
                               [cv2.IMWRITE_JPEG_QUALITY, 85]):
                raise RuntimeError('combat debug frame write failed')
            self._combat_debug_frame_count += 1
            return True
        self.screenshot(
            f'{self.COMBAT_DEBUG_FRAME_FOLDER}/frame',
            frame=frame.copy(),
        )
        self._combat_debug_frame_count += 1
        return True

    def _stop_combat_debug_frame_recorder(self, log_result=True):
        stop_event = getattr(self, '_combat_debug_frame_stop', None)
        thread = getattr(self, '_combat_debug_frame_thread', None)
        if stop_event is not None:
            stop_event.set()
        if (
                thread is not None
                and thread.is_alive()
                and thread is not threading.current_thread()
        ):
            thread.join(timeout=0.5)
        count = getattr(self, '_combat_debug_frame_count', 0)
        self._combat_debug_frame_stop = None
        self._combat_debug_frame_thread = None
        if log_result and (thread is not None or count):
            self.log_info(
                f'combat debug frame recording stopped: {count} frame(s)'
            )

    def prefer_fast_character_rotation(self):
        """Use bounded farming variants of each character's own rotation."""
        return True

    def allow_immediate_visible_liberation(self):
        """Do not hold a visibly ready R behind long encounter timers."""
        return True

    def preferred_switch_target(self, current_char, candidates, has_intro):
        """Cycle the recorded farming team instead of starving a second DPS."""
        if not self._preferred_farming_team_hints or not candidates:
            return None
        by_index = {char.index: char for char in candidates}
        team_size = len(self._preferred_farming_team_hints)
        for offset in range(1, team_size + 1):
            next_index = (current_char.index + offset) % team_size
            if next_index in by_index:
                return by_index[next_index]
        return None

    def attack_while_waiting_to_switch(self):
        """Do not keep a character animation-locked during fast rotation."""
        return False

    def wait_for_full_con_before_switch(self):
        """Allow a bounded Concerto buildup for any freshly identified team."""
        char = self.get_current_char(raise_exception=False)
        if char is None:
            return False
        # Low recharge or an unreadable ring must not hold an unfamiliar team
        # on one character for the entire encounter.
        limit = 18 if char.is_healer else 12
        started = max(char.last_switch_in_time, getattr(self, 'combat_start', 0))
        return started > 0 and time.time() - started < limit

    def use_sparse_con_ring_detection(self):
        """Support the current thin segmented Concerto ring used by this team."""
        return True

    def trust_cached_character_hints(self):
        """Identify the live farming team instead of trusting stale UI hints."""
        return False

    def trust_preferred_character_hints(self):
        """The selected material profile records this farming team's slots."""
        return bool(self._preferred_farming_team_hints)

    def preferred_character_hint(self, index):
        if 0 <= index < len(self._preferred_farming_team_hints):
            return self._preferred_farming_team_hints[index]
        return ''

    @classmethod
    def profile_for_target(cls, target_name):
        normalized = cls._normalize_material_text(target_name)
        for profile_key, profile in CHARACTER_MATERIAL_PROFILES.items():
            if profile_key in normalized or normalized in profile_key:
                return profile
        return None

    @classmethod
    def material_snapshot_for_target(cls, target_name):
        """Return saved material quantities with a calculated shortage."""
        profile = cls.profile_for_target(target_name)
        if not profile or not profile.get('material_snapshot'):
            return None
        snapshot = profile['material_snapshot']
        return {
            'captured_at': snapshot['captured_at'],
            'materials': tuple({
                **material,
                'shortage': max(
                    0,
                    material['required'] - material['owned'],
                ),
            } for material in snapshot['materials']),
        }

    @classmethod
    def resolve_material_route(cls, config, actual_target_name=None):
        target_name = (
            actual_target_name
            or config.get(CULTIVATION_TARGET, USE_CURRENT_TARGET)
        )
        requested_type = config.get(CHARACTER_MATERIAL_TYPE, AUTO_MATERIAL)
        profile = cls.profile_for_target(target_name)

        if requested_type in (AUTO_MATERIAL, LEGACY_AUTO_MATERIAL):
            requested_type = (
                profile['default_material']
                if profile
                else WEAPON_AND_SKILL
            )

        fallback_stage_name = str(
            config.get(FALLBACK_STAGE_NAME)
            or config.get(LEGACY_TARGET_DOMAIN_NAME)
            or (profile or {}).get('fallback_stage_name')
            or ''
        ).strip()
        category = 'moni' if requested_type == RESONATOR_EXP else 'ningsu'
        return {
            'material_type': requested_type,
            'category': category,
            'fallback_stage_name': fallback_stage_name,
        }

    @staticmethod
    def fingerprint_distance(first, second):
        """Return the Hamming distance between two hexadecimal image hashes."""
        if not first or not second or len(first) != len(second):
            return None
        return (int(first, 16) ^ int(second, 16)).bit_count()

    @classmethod
    def icon_fingerprint_distance(cls, first, second):
        """Compare the ordered material icons, excluding universal EXP."""
        if not first or not second:
            return None
        distances = [
            cls.fingerprint_distance(left, right)
            for left, right in zip(first, second)
        ]
        distances = [
            distance for distance in distances
            if distance is not None
        ]
        if not distances:
            return None
        return sum(distances) / len(distances)

    @classmethod
    def equivalent_material_locations(
            cls,
            locations,
            fallback_stage_name='',
            max_fingerprint_distance=24):
        """Find the target row, then expand only to identical drop previews."""
        locations = [
            location for location in locations
            if cls._valid_material_location_name(location.get('name', ''))
        ]
        normalized_stage = cls._normalize_material_text(
            fallback_stage_name
        )
        if normalized_stage:
            # A configured or live-verified stage name is a safety anchor, not
            # a loose hint. Do not let a noisy avatar marker or a same-drop
            # stage substitute another row.
            return [
                location for location in locations
                if (
                    location.get('normalized_name') == normalized_stage
                )
            ]

        stable_locations = [
            location for location in locations
            if location.get('observation_count', 2) >= 2
        ]
        target_rows = [
            location for location in stable_locations
            if location.get('is_target_row')
        ]
        if not target_rows and stable_locations:
            best_marker = max(
                stable_locations,
                key=lambda location: location.get('target_marker_score', 0),
            )
            if best_marker.get('target_marker_score', 0) >= 0.05:
                target_rows = [best_marker]
        if not target_rows:
            return []

        target_fingerprints = [
            location.get('drop_fingerprint')
            for location in target_rows
            if location.get('drop_fingerprint')
        ]
        target_icon_fingerprints = [
            location.get('material_icon_fingerprints')
            for location in target_rows
            if location.get('material_icon_fingerprints')
        ]
        if not target_fingerprints and not target_icon_fingerprints:
            return target_rows

        equivalent = []
        for location in locations:
            fingerprint = location.get('drop_fingerprint')
            icon_fingerprints = location.get('material_icon_fingerprints')
            icon_distances = [
                cls.icon_fingerprint_distance(icon_fingerprints, target)
                for target in target_icon_fingerprints
            ]
            distances = [
                cls.fingerprint_distance(fingerprint, target)
                for target in target_fingerprints
            ]
            if any(
                    distance is not None
                    and distance <= max_fingerprint_distance
                    for distance in icon_distances):
                equivalent.append(location)
            elif not target_icon_fingerprints and any(
                    distance is not None
                    and distance <= max_fingerprint_distance
                    for distance in distances):
                equivalent.append(location)
        return equivalent or target_rows

    @classmethod
    def select_visible_direct_material_location(
            cls,
            visible_locations,
            indexed_locations,
            fallback_stage_name=''):
        """Select a visible direct row only after the material is verified."""
        has_target_marker = any(
            location.get('is_target_row')
            for location in indexed_locations
        )
        normalized_fallback = cls._normalize_material_text(
            fallback_stage_name
        )
        has_fallback_reference = bool(
            normalized_fallback
            and any(
                normalized_fallback
                == location.get('normalized_name', '')
                for location in indexed_locations
            )
        )
        if not has_target_marker and not has_fallback_reference:
            return None

        equivalent_locations = cls.equivalent_material_locations(
            indexed_locations,
            fallback_stage_name,
        )
        equivalent_keys = {
            (
                location.get('normalized_name'),
                location.get('is_direct'),
            )
            for location in equivalent_locations
        }
        return next(
            (
                location
                for location in visible_locations
                if (
                    location.get('is_direct')
                    and (
                        location.get('normalized_name'),
                        location.get('is_direct'),
                    ) in equivalent_keys
                )
            ),
            None,
        )

    def material_target_matches(self, desired_target):
        if desired_target == USE_CURRENT_TARGET:
            return True
        current_target = self.current_material_target_name()
        desired = self._normalize_material_text(desired_target)
        current = self._normalize_material_text(current_target)
        if len(desired) == 1:
            return desired == current
        return bool(desired and current and (desired in current or current in desired))

    def _visible_target_choice(self, desired_target):
        desired = self._normalize_material_text(desired_target)
        boxes = self.ocr(0.04, 0.10, 0.96, 0.92, threshold=0.2) or []
        matching = [
            box for box in boxes
            if desired
            and desired in self._normalize_material_text(box.name)
        ]
        if not matching:
            # OCR can split a decorated name such as "秧秧·玄翎" into two
            # adjacent boxes. Rebuild visible text lines and use any box on
            # the matching line as the click target.
            lines = []
            for box in sorted(boxes, key=lambda item: (item.y, item.x)):
                line = next(
                    (
                        candidate
                        for candidate in lines
                        if abs(candidate[0].y - box.y)
                        <= max(candidate[0].height, box.height)
                    ),
                    None,
                )
                if line is None:
                    lines.append([box])
                else:
                    line.append(box)
            for line in lines:
                joined = ''.join(
                    box.name for box in sorted(line, key=lambda item: item.x)
                )
                if desired and desired in self._normalize_material_text(joined):
                    matching.append(line[-1])
        if not matching:
            return None

        # Prefer a selector entry away from the original header. The header can
        # remain visible behind a modal on some UI versions.
        header_right = self.width_of_screen(MATERIALS_TITLE_BOX[2] + 0.20)
        return max(matching, key=lambda box: box.x > header_right)

    def ensure_cultivation_target(self, desired_target):
        """Select the configured target, or stop if it cannot be verified."""
        if desired_target == USE_CURRENT_TARGET:
            current = self.current_material_target_name() or 'current'
            self.log_info(f'use in-game cultivation target: {current}')
            return current
        if self.wait_until(lambda: self.material_target_matches(desired_target),
                           time_out=2, raise_if_not_found=False):
            self.log_info(f'cultivation target verified: {desired_target}')
            return desired_target

        from src.task.CultivationTargetUI import select_owned_target
        select_owned_target(self, desired_target)
        self._material_page_dictionary.clear()
        self.log_info(f'cultivation target selected: {desired_target}')
        return desired_target

    def enter_character_material_domain(self, route):
        """Enter an unlocked location for one already-resolved material."""
        self.open_boss_book(route['category'])
        fallback_stage_name = route.get('fallback_stage_name', '')
        if fallback_stage_name:
            self.log_info(
                f'exact material stage required: {fallback_stage_name}; '
                'do not substitute another avatar or drop match'
            )

        def select_visible_direct(visible_locations, indexed_locations):
            return self.select_visible_direct_material_location(
                visible_locations,
                indexed_locations,
                fallback_stage_name,
            )

        catalog = self.build_material_page_dictionary(
            route['category'],
            force=True,
            visible_selector=select_visible_direct,
        )
        selected_visible = catalog.get('selected_visible_location')
        if selected_visible is not None:
            self.info_set(
                'Character material stage',
                selected_visible['name'],
            )
            self.log_info(
                f"verified visible direct challenge "
                f"{selected_visible['name']}; enter immediately"
            )
            return self.enter_visible_material_location(selected_visible)

        equivalent_locations = self.equivalent_material_locations(
            catalog['locations'],
            fallback_stage_name,
        )
        ordered_locations = self.order_material_locations(equivalent_locations)
        if not ordered_locations:
            if fallback_stage_name:
                raise RuntimeError(
                    f'exact material stage "{fallback_stage_name}" was not '
                    'found; stop without selecting another location'
                )
            raise RuntimeError(
                'no row matched the cultivation-target avatar or fallback '
                'stage name; '
                'stop before selecting a different material'
            )

        for attempt, location in enumerate(ordered_locations):
            if attempt:
                self.open_boss_book(route['category'])
                self.log_info(
                    f"retry the same material at {location['name']}"
                )
            self.info_set('Character material stage', location['name'])
            if self.enter_material_location(location):
                return True
            self.log_info(
                f"material location {location['name']} is unavailable"
            )
            if not self.leave_unavailable_domain_page():
                raise RuntimeError(
                    'could not leave unavailable material location safely'
                )
        return False

    def farm_character_materials(self, daily=False, used_stamina=0, config=None):
        if config is None:
            config = self.config
        self._save_combat_debug_frames_enabled = bool(
            config.get(SAVE_COMBAT_DEBUG_FRAMES, False)
        )
        route = self.resolve_material_route(config)
        desired_target = config.get(CULTIVATION_TARGET, USE_CURRENT_TARGET)
        must_use = max(0, 180 - used_stamina) if daily else 0

        self.info_set('Cultivation target', desired_target)
        self.info_set('Character material type', route['material_type'])

        def teleport_once():
            actual_target = self.ensure_cultivation_target(desired_target)
            profile = self.profile_for_target(actual_target) or {}
            self._preferred_farming_team_hints = tuple(
                profile.get('team_hints', ())
            )
            runtime_route = self.resolve_material_route(
                config,
                actual_target_name=actual_target,
            )
            self.info_set(
                'Character material type',
                runtime_route['material_type'],
            )
            if not self.enter_character_material_domain(runtime_route):
                raise RuntimeError(
                    'no unlocked location was found for the selected material'
                )

        try:
            self.farm_domain_with_recovery_loop(must_use, teleport_once)
        finally:
            self._stop_combat_debug_frame_recorder()
