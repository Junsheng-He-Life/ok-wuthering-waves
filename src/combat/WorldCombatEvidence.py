"""Read positive combat evidence from supplied BGR pixels without game access.

Templates identify candidates, not victory. Only explicit challenge completion
text or a claim objective paired with a treasure marker has encounter scope.
The caller must gate these events with fresh HUD/enemy observations and temporal
novelty; an old drop, unrelated challenge or occluded enemy remains ambiguous.
This module never accesses a task, executor, capture device or input controller.
"""
import json
from pathlib import Path
import re
import time

import cv2
import numpy as np


TEMPLATE_REGIONS = {
    'treasure_icon': (.03, .10, .97, .81),
    'absorb_zh_CN': (.45, .35, .86, .72),
    'absorb_en_US': (.45, .35, .86, .72),
}
TEXT_REGIONS = ((.20, .15, .80, .55), (0., .20, .28, .34),
                (0., .35, .40, .85))


def _pixel_box(frame, roi):
    h, w = frame.shape[:2]
    return tuple(round(v * size) for v, size in zip(roi, (w, h, w, h)))


class StaticWorldTemplates:
    """Preload COCO crops; match at 720-pixel height with no runtime file I/O.

    ``root`` is the repository directory. Calls accept a uint8 BGR image of
    shape (height, width, 3), an asset label, and a normalized xyxy search ROI.
    Return None or {confidence, box}; box is integer xywh in the original frame.
    Scores are normalized correlation, not calibrated probabilities. The .80
    treasure threshold follows BaseWWTask.find_treasure_icon; .85 absorption
    is conservative candidate detection and may miss changed fonts/HUD scale.
    """

    def __init__(self, root):
        assets = Path(root) / 'assets'
        data = json.loads((assets / 'coco_annotations.json').read_text())
        names = {item['id']: item['name'] for item in data['categories']}
        images = {item['id']: item for item in data['images']}
        self.templates = {}
        loaded = {}
        for annotation in data['annotations']:
            label = names[annotation['category_id']]
            if label not in TEMPLATE_REGIONS:
                continue
            info = images[annotation['image_id']]
            path = assets / info['file_name']
            if path not in loaded:
                loaded[path] = cv2.imread(str(path))
            source = loaded[path]
            if source is None:
                raise ValueError(f'Unreadable world evidence asset: {path}')
            x, y, w, h = annotation['bbox']
            crop = source[round(y):round(y + h), round(x):round(x + w)]
            scale = 720 / source.shape[0]
            self.templates[label] = cv2.resize(crop, (max(1, round(w * scale)),
                max(1, round(h * scale))), interpolation=cv2.INTER_AREA)
        if set(self.templates) != set(TEMPLATE_REGIONS):
            raise ValueError('Missing world evidence template assets')

    def __call__(self, frame, label, roi):
        x1, y1, x2, y2 = _pixel_box(frame, roi)
        scale = 720 / frame.shape[0]
        search = cv2.resize(frame[y1:y2, x1:x2], None, fx=scale, fy=scale,
                            interpolation=cv2.INTER_AREA)
        template = self.templates[label]
        h, w = template.shape[:2]
        if search.shape[0] < h or search.shape[1] < w:
            return None
        scores = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(scores)
        if not np.isfinite(score) or score < (.80 if label == 'treasure_icon' else .85):
            return None
        return {'confidence': float(score), 'box': (x1 + round(loc[0] / scale),
            y1 + round(loc[1] / scale), round(w / scale), round(h / scale))}


def make_onnx_text_reader():
    """Create one independent CPU OCR instance; initialization can be slow.

    Uses the installed onnxocr package and its local bundled models, not the
    task's shared OCR instance. Construct before starting input, then call only
    on an evidence worker. The returned callable accepts (BGR frame, xyxy ROI)
    and returns text/confidence/absolute xywh dictionaries. It owns no thread.
    """
    import onnxruntime as ort
    from onnxocr.onnx_paddleocr import ONNXPaddleOcr
    engine = ONNXPaddleOcr(use_angle_cls=False, use_npu=False, use_openvino=False)
    # onnxocr 0.0.18 ignores cpu_threads when creating its CPU sessions. Replace
    # only this private engine's sessions; never patch the process-wide factory.
    # One non-spinning thread keeps the capture and fast evidence workers free.
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.add_session_config_entry('session.intra_op.allow_spinning', '0')
    options.add_session_config_entry('session.inter_op.allow_spinning', '0')
    for predictor, model in ((engine.text_detector, engine.args.det_model_dir),
                             (engine.text_recognizer, engine.args.rec_model_dir)):
        predictor.session = ort.InferenceSession(model, sess_options=options,
                                                 providers=['CPUExecutionProvider'])

    def read_text(frame, roi):
        x1, y1, x2, y2 = _pixel_box(frame, roi)
        # Bounded OCR resolution controls cost without resizing the source.
        scale = min(1., 720 / frame.shape[0])
        crop = cv2.resize(frame[y1:y2, x1:x2], None, fx=scale, fy=scale,
                          interpolation=cv2.INTER_AREA)
        result = engine.ocr(crop, cls=False)
        output = []
        for polygon, (text, score) in (result[0] if result and result[0] else []):
            points = np.asarray(polygon) / scale
            left, top = points.min(axis=0)
            right, bottom = points.max(axis=0)
            output.append({'text': text, 'confidence': float(score),
                'box': (x1 + round(left), y1 + round(top),
                        round(right - left), round(bottom - top))})
        return output

    return read_text


def detect_world_evidence(frame, *, match_template, read_text=None):
    """Return same-frame evidence dictionaries, without deciding battle state.

    ``frame`` is uint8 BGR (H,W,3). Both injected callables receive this exact
    frame and an xyxy ROI; the matcher also receives a template label. Each
    returned event has label, scope, confidence and original-frame xywh box.
    Scope is encounter, kill_candidate or reward_candidate. Candidate scope
    does not assert a recent kill: echoes can persist, and EXP can come from
    unrelated rewards. Empty results mean unknown, never combat ended.
    OCR rows require text/confidence/box; low confidence or partial text is
    rejected. No generic 'obtained' toast is treated as combat evidence.
    """
    if (not isinstance(frame, np.ndarray) or frame.dtype != np.uint8
            or frame.ndim != 3 or frame.shape[2] != 3 or min(frame.shape[:2]) < 2):
        raise ValueError('Expected a nonempty uint8 BGR frame')
    events = []
    for name, roi in TEMPLATE_REGIONS.items():
        hit = match_template(frame, name, roi)
        if hit:
            treasure = name == 'treasure_icon'
            events.append(dict(hit, label='treasure_marker' if treasure else
                'echo_absorb_prompt', scope='reward_candidate' if treasure else
                'kill_candidate', source='template', template=name))
    if read_text is None:
        return events
    seen = set()
    for roi in TEXT_REGIONS:
        for row in read_text(frame, roi):
            text = re.sub(r'\s+', '', row['text']).casefold()
            if (not np.isfinite(row['confidence']) or row['confidence'] < .90
                    or (text, tuple(row['box'])) in seen):
                continue
            seen.add((text, tuple(row['box'])))
            label, scope = None, 'encounter'
            if roi == TEXT_REGIONS[0] and re.fullmatch(
                    r'挑战成功|挑战完成|challenge(?:completed|complete|success)', text):
                label = 'challenge_success'
            elif (roi == TEXT_REGIONS[1] and re.fullmatch(r'领取奖励|claimrewards?', text)
                    and any(e['label'] == 'treasure_marker' for e in events)):
                label = 'challenge_reward_ready'
            elif roi == TEXT_REGIONS[2] and re.fullmatch(
                    r'(?:共鸣者经验|resonatorexp)[:：+＋]?\d+', text):
                label, scope = 'resonator_exp_toast', 'kill_candidate'
            if label:
                events.append({'label': label, 'scope': scope, 'source': 'ocr',
                    'confidence': float(row['confidence']), 'box': tuple(row['box']),
                    'text': row['text']})
    return events


class LocalWorldEvidence:
    """Single-worker callable(frame) producing fresh evidence with optional OCR.

    Construct with the repository ``root`` before combat. Default is templates
    only and cannot confirm an encounter end. Set enable_ocr=True to construct
    an independent ONNX OCR engine once, or inject read_text for offline tests.
    OCR is attempted at most once per second; results are never reused on a
    newer frame. A slow OCR call must stay off the input/control thread.
    ``last_text_checked`` is true only after the latest call completed all OCR
    regions, including an empty result; throttled calls reset it to false. The
    class has no executor references, background threads or lifecycle cleanup.
    """

    def __init__(self, root, *, enable_ocr=False, read_text=None, clock=time.monotonic):
        self.match_template = StaticWorldTemplates(root)
        self.read_text = read_text or (make_onnx_text_reader() if enable_ocr else None)
        self.clock = clock
        self.next_ocr = 0.
        self.last_text_checked = False

    def __call__(self, frame):
        self.last_text_checked = False
        reader = None
        now = self.clock()
        if self.read_text is not None and now >= self.next_ocr:
            self.next_ocr = now + 1.
            reader = self.read_text
        events = detect_world_evidence(frame, match_template=self.match_template,
                                       read_text=reader)
        self.last_text_checked = reader is not None
        return events
