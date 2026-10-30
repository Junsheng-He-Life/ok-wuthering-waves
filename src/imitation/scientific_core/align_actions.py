"""Align observed frames with subsequent input events without filesystem I/O.

All alignment uses Python ``monotonic_ns`` observation/callback times, not the
unverified native image presentation clock. Labels describe recorded human
inputs; neither successful input delivery nor task completion is inferred.
"""

from collections import Counter
import math


OUTCOMES = frozenset(('success', 'failure', 'unlabeled', 'interrupted'))


def _integer(value, field):
    if type(value) is not int or value < 0:
        raise ValueError(f'{field} must be a nonnegative integer')
    return value


def _validate_events(events):
    for event in events:
        if not isinstance(event, dict):
            raise ValueError('Each event must be an object')
        _integer(event.get('t_ns'), 'event.t_ns')
        kind = event.get('kind')
        if kind in ('key', 'button'):
            if type(event.get('down')) is not bool:
                raise ValueError('Input down must be a boolean')
            if kind == 'key':
                _integer(event.get('code'), 'key.code')
            elif event.get('button') not in ('left', 'right', 'middle'):
                raise ValueError('Unknown mouse button')
        elif kind in ('mouse_move', 'scroll'):
            for field in ('dx', 'dy'):
                value = event.get(field)
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise ValueError(f'{kind}.{field} must be finite')
        elif kind == 'focus':
            if type(event.get('active')) is not bool:
                raise ValueError('focus.active must be a boolean')
        elif kind not in ('reset', 'segment', 'control'):
            raise ValueError(f'Unknown event kind: {kind!r}')


def _segments(events):
    segments, active = {}, None
    for event in events:
        if event['kind'] == 'segment':
            name, action = event.get('segment_id'), event.get('action')
            if not isinstance(name, str) or not name:
                raise ValueError('segment_id must be a nonempty string')
            if action == 'start':
                if active is not None or name in segments:
                    raise ValueError('Overlapping or duplicate segment start')
                active = dict(start=event['t_ns'], end=None, outcome=None,
                              invalid_since=None, events=[], keys=set(),
                              buttons=set(), cursor=0)
                segments[name] = active
            elif action == 'end':
                if active is None or segments.get(name) is not active:
                    raise ValueError('Segment end has no matching active start')
                outcome = event.get('outcome')
                if outcome is not None and outcome not in OUTCOMES:
                    raise ValueError('Unknown segment outcome')
                active.update(end=event['t_ns'], outcome=outcome)
                active = None
            else:
                raise ValueError('Segment action must be start or end')
        elif active is not None:
            active['events'].append(event)
            invalid = event['kind'] == 'reset' or (
                event['kind'] == 'focus' and not event['active'])
            if invalid and active['invalid_since'] is None:
                active['invalid_since'] = event['t_ns']
    return segments


def _validate_frames(frames, segments):
    seen, last_time, last_sequence = set(), -1, -1
    for frame in frames:
        if not isinstance(frame, dict):
            raise ValueError('Each frame must be an object')
        ident = _integer(frame.get('frame_id'), 'frame_id')
        timestamp = _integer(frame.get('t_ns'), 'frame.t_ns')
        sequence = _integer(frame.get('sequence'), 'sequence')
        if ident in seen or timestamp <= last_time or sequence <= last_sequence:
            raise ValueError('Frame IDs must be unique; time and sequence must increase')
        name = frame.get('segment_id')
        if not isinstance(name, str) or name not in segments:
            raise ValueError('Frame references an unknown segment')
        segment = segments[name]
        if timestamp < segment['start'] or (
                segment['end'] is not None and timestamp > segment['end']):
            raise ValueError('Frame timestamp lies outside its segment')
        if not isinstance(frame.get('image'), str) or not frame['image']:
            raise ValueError('Frame image must be a nonempty path')
        seen.add(ident)
        last_time, last_sequence = timestamp, sequence


def _apply_state(segment, event):
    if event['kind'] in ('key', 'button'):
        field, value = ('keys', event['code']) if event['kind'] == 'key' else (
            'buttons', event['button'])
        if event['down']:
            segment[field].add(value)
        else:
            segment[field].discard(value)


def _label_window(left, right, segment):
    start, end = left['t_ns'], right['t_ns']
    events, index = segment['events'], segment['cursor']
    while index < len(events) and events[index]['t_ns'] < start:
        _apply_state(segment, events[index])
        index += 1
    segment['cursor'] = index
    sample = dict(frame_id=left['frame_id'], next_frame_id=right['frame_id'],
                  image=left['image'], next_image=right['image'],
                  segment_id=left['segment_id'], t_ns=start, duration_ns=end-start,
                  keys_start=sorted(segment['keys']),
                  buttons_start=sorted(segment['buttons']), key_transitions=[],
                  button_transitions=[], mouse_dx=0, mouse_dy=0,
                  scroll_dx=0, scroll_dy=0, outcome=segment['outcome'])
    while index < len(events) and events[index]['t_ns'] < end:
        event = events[index]
        kind = event['kind']
        if kind in ('key', 'button'):
            field = 'code' if kind == 'key' else 'button'
            sample[kind + '_transitions'].append(
                dict(offset_ns=event['t_ns']-start,
                     **{field: event[field], 'down': event['down']}))
        elif kind in ('mouse_move', 'scroll'):
            prefix = 'mouse' if kind == 'mouse_move' else 'scroll'
            sample[prefix + '_dx'] += event['dx']
            sample[prefix + '_dy'] += event['dy']
        index += 1
    return sample


def align_actions(frames, events, *, max_gap_ms=250, outcomes=('success',)):
    """Return ``(samples, quality)`` for safe, adjacent observation intervals.

    Parameters are lists of frame/event dictionaries in schema 1.0.0. Frames
    must be ordered, with unique IDs and increasing source sequence/time;
    events are stably sorted by integer nanoseconds. A sample covers [t_i,t_j):
    held state applies events strictly before t_i, while transitions at t_i
    belong to this sample and transitions at t_j belong to the next one.
    Mouse/scroll deltas retain their raw recorded units. ``max_gap_ms`` is a
    positive engineering quality cutoff, not a measured latency guarantee.

    Only explicitly ended segments with selected human outcomes are accepted.
    Reset/focus-loss events invalidate intervals from that point until a new
    neutral segment starts; preceding intervals remain eligible. Missing ends
    and labels are counted, never interpreted as successful. Invalid schemas,
    duplicate frames, or contradictory segment boundaries raise ValueError.
    Input dictionaries are not modified. Returned samples own their lists.
    """
    if type(max_gap_ms) not in (int, float) or not math.isfinite(max_gap_ms) or max_gap_ms <= 0:
        raise ValueError('max_gap_ms must be finite and positive')
    outcomes = frozenset(outcomes)
    if not outcomes or not outcomes <= OUTCOMES:
        raise ValueError('Choose at least one supported outcome')
    _validate_events(events)
    ordered = sorted(events, key=lambda event: event['t_ns'])
    segments = _segments(ordered)
    _validate_frames(frames, segments)
    samples, dropped = [], Counter()
    for left, right in zip(frames, frames[1:]):
        segment = segments[left['segment_id']]
        reason = None
        if left['segment_id'] != right['segment_id']:
            reason = 'segment_boundary'
        elif segment['end'] is None:
            reason = 'incomplete_segment'
        elif segment['outcome'] is None:
            reason = 'missing_outcome'
        elif segment['outcome'] not in outcomes:
            reason = 'outcome_filtered'
        elif right['t_ns'] - left['t_ns'] > max_gap_ms * 1_000_000:
            reason = 'frame_gap'
        elif segment['invalid_since'] is not None and segment['invalid_since'] < right['t_ns']:
            reason = 'reset_or_focus_loss'
        if reason:
            dropped[reason] += 1
        else:
            samples.append(_label_window(left, right, segment))
    return samples, dict(frames=len(frames), events=len(events),
                         event_order_corrected=events != ordered,
                         segments=len(segments), accepted=len(samples),
                         dropped_pairs=dict(dropped),
                         incomplete_segments=sum(s['end'] is None for s in segments.values()))
