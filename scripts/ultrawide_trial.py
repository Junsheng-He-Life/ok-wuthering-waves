"""Run bounded material/echo tasks with explicit resource limits."""

import argparse
import json
import sys
import threading
import signal
from pathlib import Path


def load_menu_steps(path, root):
    """Read a bounded operator-authored JSON queue from this repository only."""
    source = Path(path)
    source = (source if source.is_absolute() else root / source).resolve(strict=True)
    if not source.is_relative_to(root.resolve()) or not source.is_file():
        raise ValueError('menu-steps must be a JSON file inside this repository')
    if source.stat().st_size > 65536:
        raise ValueError('menu-steps JSON exceeds 64 KiB')
    return json.loads(source.read_text(encoding='utf-8'))


def final_result(task_result, capture, *, expired=False, interrupted=False, execution_error=None):
    """Preserve confirmed accounting while surfacing capture failures from every phase."""
    result = dict(task_result or {'status': 'not_started'})
    geometry_error = getattr(capture, 'geometry_error', None)
    if geometry_error:
        result.update(status='stopped', error=geometry_error)
    elif expired:
        result.update(status='timeout')
    elif interrupted:
        result.update(status='interrupted')
    elif execution_error:
        result.update(status='stopped', error=execution_error)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('inspect', 'scan', 'enter', 'combat', 'resume', 'basic', 'approach', 'team', 'heal', 'recover', 'loop', 'practice', 'claim', 'plan', 'catalog', 'echo', 'echo-catalog', 'echo-inventory', 'settlement-catalog', 'settlement-enter', 'settlement-travel', 'settlement-test', 'refill-inspect', 'solvent-reconcile', 'stamina-read', 'hud-diagnostic', 'menu-return', 'weekly-inspect', 'synthesis-inspect', 'synthesis-recipe-inspect', 'recipe-audit', 'cultivation-inspect', 'boss-record', 'material-audit', 'menu-step', 'preflight'), default='inspect')
    parser.add_argument('--desktop-session', action='store_true', help='Use desktop settings and structured progress')
    parser.add_argument('--desktop-preflight', action='store_true', help='Require fresh party and level checks before entry')
    parser.add_argument('--desktop-preflight-mode', choices=('tacet', 'boss', 'materials'))
    parser.add_argument('--desktop-experimental', action='store_true', help='Allow explicitly unverified combinations, never unknown levels')
    parser.add_argument('--menu-action', choices=('inspect', 'terminal', 'text', 'point', 'back', 'scroll'), default='inspect')
    parser.add_argument('--menu-expect', default='')
    parser.add_argument('--menu-point', nargs=2, type=float)
    parser.add_argument('--menu-scroll', type=int)
    parser.add_argument('--menu-after-expect', default='')
    parser.add_argument('--menu-steps', help='Repository-local JSON array of observed menu steps')
    parser.add_argument('--echo-mode', choices=('boss', 'tacet'), default='boss',
                        help='Boss echoes/materials or Tacet rewards, within spending caps')
    parser.add_argument('--echo-no-claim', action='store_true', help='Absorb only; no rewards or refills')
    parser.add_argument('--runs', type=int, default=2)
    parser.add_argument('--reserve-limit', type=int, default=0)
    parser.add_argument('--solvent-limit', type=int, default=0)
    parser.add_argument('--solvent-total', type=int, default=None,
                        help='Explicit cumulative solvent cap including the shared ledger used count; defaults to saved setting or 0')
    parser.add_argument('--max-stamina', type=int, default=80)
    parser.add_argument('--target', default='')
    parser.add_argument('--targets', default='', help='Three cultivation targets, comma separated')
    parser.add_argument('--stage', default='')
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--continuous', action='store_true')
    parser.add_argument('--skip-map-routes', action='store_true')
    parser.add_argument('--boss-context', action='store_true')
    parser.add_argument('--record-hud', action='store_true')
    args = parser.parse_args()
    if args.desktop_session:
        # The panel may request pause while imports are still starting. Do not let
        # the default SIGUSR action kill the process before control is ready.
        signal.signal(signal.SIGUSR1, lambda *_: None)
        signal.signal(signal.SIGUSR2, lambda *_: None)
    if args.solvent_total is not None and args.solvent_total < 0:
        parser.error('solvent-total must be a finite non-negative integer')
    if args.phase == 'echo':
        if not args.stage.strip() or not 1 <= args.runs <= 100:
            parser.error('echo requires --stage and --runs 1..100')
        if not (0 <= args.max_stamina <= 4000 and 0 <= args.reserve_limit <= 240
                and 0 <= args.solvent_limit <= 133):
            parser.error('echo resource limits must be finite and non-negative')
    if not (1 <= args.timeout <= 600 or args.timeout == 0 and args.continuous and args.phase == 'plan'):
        parser.error('timeout must be 1..600; continuous plan also accepts 0')
    sys.argv = [sys.argv[0]]
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    menu_steps = None
    if args.menu_steps:
        if args.phase != 'menu-step':
            parser.error('menu-steps requires --phase menu-step')
        try:
            menu_steps = load_menu_steps(args.menu_steps, root)
            from src.task.MenuInspectionTask import validate_menu_steps
            validate_menu_steps(menu_steps)
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
    from src.runtime.MacSession import MacSession, release_inputs
    lease = MacSession(root).acquire()
    from config import config
    if args.desktop_session:
        from src.runtime.MacSession import prepare_desktop_config
        config = prepare_desktop_config(root, config)
    from ok import OK
    from src.task.MaterialTrialTask import MaterialTrialTask
    if args.phase == 'preflight':
        from src.task.DesktopPreflightTask import DesktopPreflightTask
        MaterialTrialTask = DesktopPreflightTask
    if args.phase in ('team', 'heal', 'recover', 'loop', 'practice', 'claim', 'plan', 'refill-inspect', 'solvent-reconcile', 'stamina-read', 'hud-diagnostic', 'menu-return', 'weekly-inspect', 'synthesis-inspect', 'synthesis-recipe-inspect', 'recipe-audit', 'cultivation-inspect'):
        from src.task.SafeMaterialTask import SafeMaterialTask
        MaterialTrialTask = SafeMaterialTask
        MaterialTrialTask.run_limit = args.runs
        MaterialTrialTask.reserve_limit = args.reserve_limit
        MaterialTrialTask.record_hud = args.record_hud
        if args.phase in ('plan', 'claim'):
            from src.task.TeamMaterialTask import TeamMaterialTask
            MaterialTrialTask = TeamMaterialTask

    if args.phase == 'boss-record':
        from src.task.BossRecordingTask import BossRecordingTask
        MaterialTrialTask = BossRecordingTask

    if args.phase == 'material-audit':
        from src.task.TeamMaterialAuditTask import TeamMaterialAuditTask
        MaterialTrialTask = TeamMaterialAuditTask

    if args.phase == 'menu-step':
        from src.task.MenuInspectionTask import MenuInspectionTask
        MaterialTrialTask = MenuInspectionTask
        MaterialTrialTask.menu_action = args.menu_action
        MaterialTrialTask.menu_expect = args.menu_expect
        MaterialTrialTask.menu_point = args.menu_point
        MaterialTrialTask.menu_scroll = args.menu_scroll
        MaterialTrialTask.menu_after_expect = args.menu_after_expect
        MaterialTrialTask.menu_steps = menu_steps

    if args.phase in ('echo', 'echo-catalog', 'echo-inventory'):
        from src.task.EchoFarmTask import BossEchoTask, TacetEchoTask
        MaterialTrialTask = BossEchoTask if args.echo_mode == 'boss' else TacetEchoTask

    if args.phase in ('settlement-catalog', 'settlement-enter', 'settlement-travel', 'settlement-test'):
        from src.task.SettlementTrialTask import SettlementTrialTask
        MaterialTrialTask = SettlementTrialTask

    config['use_gui'] = False
    if args.phase == 'catalog':
        from src.task.TeamMaterialScanTask import TeamMaterialScanTask
        MaterialTrialTask = TeamMaterialScanTask
    # No trigger tasks are instantiated, even if a saved config enables one.
    config['trigger_tasks'] = []
    config['onetime_tasks'] = []
    config['check_mutex'] = False
    MaterialTrialTask.phase = 'loop' if args.phase == 'plan' else args.phase
    MaterialTrialTask.expected_target = args.target
    MaterialTrialTask.exact_stage = args.stage
    app = OK(config)
    task = None
    expired = threading.Event()
    interrupted = threading.Event()
    diagnostics_done = threading.Event()

    def report_wait_state():
        while not diagnostics_done.wait(30):
            executor = app.task_executor
            interaction = getattr(executor, 'interaction', None)
            window = getattr(interaction, 'mac_window', None)
            print('TRIAL_STATE', json.dumps({
                'paused': executor.paused,
                'task': str(executor.current_task),
                'window': {key: getattr(window, key, None) for key in
                           ('window_id', 'exists', 'visible', 'pos_valid')},
            }), flush=True)

    threading.Thread(target=report_wait_state, daemon=True).start()

    def stop_requested(*_):
        interrupted.set()
        app.exit_event.set()
        release_inputs(app)

    signal.signal(signal.SIGINT, stop_requested)
    signal.signal(signal.SIGTERM, stop_requested)

    def stop_on_deadline():
        expired.set()
        app.exit_event.set()

    timer = threading.Timer(args.timeout, stop_on_deadline)
    timer.daemon = True
    if args.timeout and not args.desktop_session:
        timer.start()
    desktop_monitor = None
    execution_error = None
    try:
        task = app.get_onetime_task(MaterialTrialTask)
        if args.desktop_preflight or args.phase == 'preflight':
            task.desktop_preflight_required = args.desktop_preflight
            task.desktop_allow_experimental = args.desktop_experimental
            task.desktop_preflight_mode = args.desktop_preflight_mode or (args.echo_mode if args.phase == 'echo' else 'tacet' if args.phase == 'preflight' else 'materials')
            if args.stage:
                task.desktop_preflight_stage = args.stage
        if args.solvent_total is not None and args.phase in ('plan', 'claim', 'echo'):
            from src.task.MaterialActivity import SOLVENT_TOTAL_CONFIG
            task.config[SOLVENT_TOTAL_CONFIG] = args.solvent_total
        if args.boss_context:
            task._plan_boss = True
        if args.phase in ('echo', 'echo-catalog', 'echo-inventory'):
            task.echo_stage_override = args.stage
            task.config['本次战斗上限'] = args.runs
            task.config.update({'战后领奖': not args.echo_no_claim,
                                '本次最多领奖': args.runs, '本次波片上限': args.max_stamina,
                                '本次储备上限': args.reserve_limit,
                                '本次溶剂上限': args.solvent_limit})
        if args.phase in ('plan', 'claim'):
            task.target_override = args.target.strip()
            if args.desktop_session and args.phase == 'plan':
                # The desktop explicitly promises the current whole party.
                # Saved single-target settings must not silently change that scope.
                task.config[task.TARGET_NAMES_CONFIG] = ''
                task.config[task.SINGLE_TARGET_CONFIG] = ''
            if args.targets:
                task.parse_target_names(args.targets)
                task.config[task.TARGET_NAMES_CONFIG] = args.targets
                task.config[task.SINGLE_TARGET_CONFIG] = ''
            task.skip_map_routes = args.skip_map_routes
            task.config['持续轮刷'] = args.continuous
            task.config['本次最多领奖'] = args.runs
            task.config['本次波片上限'] = args.max_stamina
            task.config['本次储备上限'] = args.reserve_limit
            task.config['本次溶剂上限'] = args.solvent_limit
        if args.desktop_session:
            from src.runtime.DesktopTrialMonitor import DesktopTrialMonitor
            desktop_monitor = DesktopTrialMonitor(app, task, args.timeout, expired, release_inputs)
            desktop_monitor.start()
        app.run_task(task)
    except Exception as error:
        execution_error = str(error)
    finally:
        if desktop_monitor:
            desktop_monitor.close()
        diagnostics_done.set()
        timer.cancel()
        result = final_result(task.result if task else None,
                              getattr(app.device_manager, 'capture_method', None),
                              expired=expired.is_set(), interrupted=interrupted.is_set(),
                              execution_error=execution_error)
        output = root / 'logs' / ('ultrawide-' + args.phase + '.json')
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        if args.phase == 'plan' and task is not None and hasattr(task, 'progress'):
            from src.task.MaterialNeedsReport import write_needs_report
            write_needs_report(task.progress, result['status'], result.get('budget'))
        print('TRIAL_RESULT', json.dumps(result, ensure_ascii=False))
        app.exit_event.set()
        release_inputs(app)
        app.quit()
        app.device_manager.capture_method.close()
        lease.close()
    return 0 if result['status'] not in ('timeout', 'stopped', 'not_started', 'running', 'interrupted', 'preflight_blocked') else 1


if __name__ == '__main__':
    raise SystemExit(main())
