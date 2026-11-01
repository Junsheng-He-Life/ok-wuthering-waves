"""Analyze saved backend timings and profiles offline; no game connection."""
import argparse
import json
from pathlib import Path
import pstats
import statistics


def input_summary(events):
    events = sorted(events, key=lambda e: e['start'])
    groups = {}
    gaps = []
    previous_end = None
    previous = None
    held = set()
    for event in events:
        duration = event['end'] - event['start']
        groups.setdefault(event['action'], []).append(duration)
        if previous_end is not None and event['start'] > previous_end and not held:
            gaps.append({'seconds': event['start'] - previous_end,
                'after': previous, 'before': event})
        if previous_end is None or event['end'] > previous_end:
            previous_end, previous = event['end'], event
        action = event['action']
        if action in ('mouse_down', 'mouse_up', 'send_key_down', 'send_key_up'):
            family = 'mouse' if action.startswith('mouse') else 'key'
            key = (event.get('key') or 'left') if family == 'mouse' else event['args'][0]
            control = (family, str(key))
            if action.endswith('_down'):
                held.add(control)
            else:
                held.discard(control)
    return {
        'span_seconds': events[-1]['end'] - events[0]['start'] if events else 0,
        'actions': {key: {'count': len(values), 'sum_seconds': sum(values),
                         'median_seconds': statistics.median(values), 'max_seconds': max(values)}
                    for key, values in groups.items()},
        'gaps_over_800ms': sorted((g for g in gaps if g['seconds'] >= .8),
                                  key=lambda g: g['seconds'], reverse=True),
        'note': 'Gaps exclude backend call duration. Backend calls do not prove game acceptance; '
                'a gap may be an intentional animation wait. Compare saved frames and profile.'}


def analyze(folder, frames=None):
    folder = Path(folder)
    data = json.loads((folder / 'inputs.json').read_text())
    report = input_summary(data['events'])
    report['dropped'] = data.get('dropped', 0)
    rows = []
    if (folder / 'profile.pstats').exists():
        stats = pstats.Stats(str(folder / 'profile.pstats'))
        for (file, line, name), (primitive, calls, own, cumulative, callers) in stats.stats.items():
            rows.append({'file': file, 'line': line, 'name': name, 'calls': calls,
                         'own_seconds': own, 'cumulative_seconds': cumulative})
    if (folder / 'calls.json').exists():
        calls = json.loads((folder / 'calls.json').read_text())
        report['call_timings'] = {}
        for name in sorted({c['name'] for c in calls}):
            durations = [c['end']-c['start'] for c in calls if c['name'] == name]
            report['call_timings'][name] = {'count': len(durations), 'sum_seconds': sum(durations),
                'median_seconds': statistics.median(durations), 'max_seconds': max(durations)}
        for gap in report['gaps_over_800ms']:
            lo, hi = gap['after']['end'], gap['before']['start']
            gap['overlapping_calls'] = sorted([
                {'name': c['name'], 'overlap_seconds': min(hi,c['end'])-max(lo,c['start'])}
                for c in calls if c['end'] > lo and c['start'] < hi],
                key=lambda c: c['overlap_seconds'], reverse=True)[:8]
    report['top_own_time'] = sorted(rows, key=lambda r: r['own_seconds'], reverse=True)[:35]
    report['top_cumulative_time'] = sorted(rows, key=lambda r: r['cumulative_seconds'], reverse=True)[:45]
    if frames:
        saved = sorted((int(p.stem), p) for p in Path(frames).glob('*.jpg') if p.stem.isdigit())
        for gap in report['gaps_over_800ms']:
            for label in ('after', 'before'):
                stamp = gap[label]['wall_ns']
                if saved:
                    distance, path = min((abs(ns-stamp), p) for ns, p in saved)
                    if distance < 1_000_000_000:
                        gap[label + '_frame'] = str(path.resolve())
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder')
    parser.add_argument('--frames')
    args = parser.parse_args()
    result = analyze(args.folder, args.frames)
    destination = Path(args.folder) / 'analysis.json'
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(destination)
    print(json.dumps({k: result[k] for k in ('span_seconds', 'actions', 'dropped')}, indent=2))
