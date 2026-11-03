"""Run bounded material/echo tasks with explicit resource limits."""

import argparse
import json
import sys
import threading
import signal
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('inspect', 'scan', 'enter', 'combat', 'resume', 'basic', 'approach', 'team', 'heal', 'recover', 'loop', 'practice', 'claim', 'plan', 'catalog', 'echo', 'echo-catalog', 'echo-inventory', 'settlement-catalog', 'settlement-enter', 'settlement-travel', 'settlement-test', 'refill-inspect', 'solvent-reconcile', 'stamina-read', 'hud-diagnostic', 'menu-return', 'weekly-inspect', 'synthesis-inspect', 'synthesis-recipe-inspect', 'recipe-audit', 'cultivation-inspect', 'boss-record', 'material-audit', 'stage-catalog'), default='inspect')
    parser.add_argument('--echo-mode', choices=('boss', 'tacet', 'material'), default='boss',
                        help='Boss echoes/materials or Tacet rewards, within spending caps')
    parser.add_argument('--echo-no-claim', action='store_true', help='Absorb only; no rewards or refills')
    parser.add_argument('--runs', type=int, default=2)
    parser.add_argument('--reserve-limit', type=int, default=0)
    parser.add_argument('--solvent-limit', type=int, default=0)
    parser.add_argument('--max-stamina', type=int, default=80)
    parser.add_argument('--target', default='')
    parser.add_argument('--targets', default='', help='Three cultivation targets, comma separated')
    parser.add_argument('--stage', default='')
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--continuous', action='store_true')
    parser.add_argument('--skip-map-routes', action='store_true')
    parser.add_argument('--boss-context', action='store_true')
    parser.add_argument('--record-hud', action='store_true')
    parser.add_argument('--desktop-session', action='store_true')
    parser.add_argument('--solvent-total', type=int, default=None)
    parser.add_argument('--stop-request', type=Path)
    parser.add_argument('--current-team-targets', action='store_true')
    args = parser.parse_args()
    if args.solvent_total is not None and args.solvent_total < 0:
        parser.error('solvent total must be non-negative')
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
    from src.runtime.MacSession import MacSession, release_inputs
    lease = MacSession(root).acquire()
    from config import config
    from ok import OK
    from src.task.MaterialTrialTask import MaterialTrialTask
    if args.phase in ('team', 'heal', 'recover', 'loop', 'practice', 'claim', 'plan', 'refill-inspect', 'solvent-reconcile', 'stamina-read', 'hud-diagnostic', 'menu-return', 'weekly-inspect', 'synthesis-inspect', 'synthesis-recipe-inspect', 'recipe-audit', 'cultivation-inspect'):
        from src.task.SafeMaterialTask import SafeMaterialTask
        MaterialTrialTask = SafeMaterialTask
        MaterialTrialTask.run_limit = args.runs
        MaterialTrialTask.reserve_limit = args.reserve_limit
        MaterialTrialTask.max_stamina_limit = args.max_stamina
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

    if args.phase in ('echo', 'echo-catalog', 'echo-inventory'):
        from src.task.EchoFarmTask import BossEchoTask, TacetEchoTask, MaterialStageTask
        MaterialTrialTask = {'boss':BossEchoTask,'tacet':TacetEchoTask,'material':MaterialStageTask}[args.echo_mode]

    if args.phase in ('settlement-catalog', 'settlement-enter', 'settlement-travel', 'settlement-travel', 'settlement-test'):
        from src.task.SettlementTrialTask import SettlementTrialTask
        MaterialTrialTask = SettlementTrialTask

    config['use_gui'] = False
    if args.phase == 'catalog':
        from src.task.TeamMaterialScanTask import TeamMaterialScanTask
        MaterialTrialTask = TeamMaterialScanTask
    if args.phase == 'stage-catalog':
        from src.task.StageCatalogTask import StageCatalogTask
        MaterialTrialTask = StageCatalogTask
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
    monitor = None

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
    if args.timeout:
        timer.start()
    try:
        task = app.get_onetime_task(MaterialTrialTask)
        if args.solvent_total is not None:
            task.config['累计溶剂授权上限'] = args.solvent_total
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
            if args.current_team_targets:
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
        if args.phase == 'catalog' and args.targets:
            task.target_names_override = args.targets
        if args.desktop_session:
            import time
            from src.runtime.DesktopTrialMonitor import DesktopTrialMonitor
            task.desktop_recording_id = str(time.time_ns())
            task.stop_after_current = False
            monitor = DesktopTrialMonitor(app, task, args.timeout, expired, release_inputs)
            monitor.stop_request = args.stop_request
            timer.cancel()
            monitor.start()
        app.run_task(task)
    finally:
        if monitor:
            monitor.close()
        diagnostics_done.set()
        timer.cancel()
        result = (task.result if task else None) or {'status': 'not_started'}
        if expired.is_set():
            result.update(status='timeout')
        elif interrupted.is_set():
            result.update(status='interrupted')
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
    return 0 if result['status'] not in ('timeout', 'stopped', 'not_started', 'running', 'interrupted') else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        import traceback
        traceback.print_exc()
        print('TRIAL_RESULT', json.dumps({'status':'not_started', 'error':str(error),
              'diagnostic_code':type(error).__name__}, ensure_ascii=False), flush=True)
        raise SystemExit(1)
