"""Select owned characters by preview name, then use game-linked material rows."""
import re
from ok import Box


class NoCurrentMaterialNeed(RuntimeError):
    """The complete cultivation list explicitly has no row for this category."""


def viewport(task, left, top, right, bottom):
    w, h = task.width, task.height
    return Box(round(left*w), round(top*h), round((right-left)*w), round((bottom-top)*h))


def select_owned_target(task, desired):
    normalize = task._normalize_material_text
    opened = False
    for attempt in range(3):
        if task.wait_ocr(0, 0, .4, .13, match=re.compile('选择培养目标'), time_out=.5):
            opened = True
            break
        task.focus_material_menu()
        if not task.menu_text(r'培养目标', (.05, .10, .25, .19), timeout=1):
            break
        # The selector is the double arrow at the right edge of the
        # viewport-anchored card (about 0.318 of the game width). Clicking
        # the card body no longer opens the picker in the current UI.
        task.move(task.width * .318, task.height * .167)
        task.sleep(.8)
        task.click(task.width * .318, task.height * .170, name="培养目标右侧双箭头", after_sleep=.8)
        if task.wait_ocr(0, 0, .4, .13, match=re.compile('选择培养目标'), time_out=3):
            opened = True
            break
    if not opened:
        import cv2
        cv2.imwrite('logs/cultivation-picker-open-failed.png', task.frame)
        raise RuntimeError('培养目标列表未打开；前台恢复与三次确认重试后仍失败')
    preview = viewport(task, .69, .08, .94, .26)
    def name_matches():
        readings = task.ocr(box=preview, target_height=task.height * 3)
        names = [normalize(b.name.replace('当期', '')) for b in readings]
        task._cultivation_preview_names = names
        task.log_info(f'cultivation preview: desired={desired!r}; observed={names!r}')
        if normalize(desired) in names:
            return True
        if not any(names):
            import cv2
            cv2.imwrite('logs/cultivation-empty-preview.png', task.frame)
        return False
    from src.task.CultivationAvatarCache import select_cached_avatar, remember_avatar, scroll_roster
    found = name_matches()
    if not found:
        found = select_cached_avatar(task, desired, name_matches)
    if not found:
        # Cache files are only hints: display or roster changes can invalidate
        # them. Relearn from observed owned cards and their preview names;
        # no target is committed until the requested name is verified.
        task.log_info(f'cultivation avatar unavailable; verify visible roster cards: {desired}')
        scroll_roster(task, 100)
        featured = [b for b in task.ocr(box=viewport(task, .01, .10, .63, .30))
                    if normalize(b.name) == normalize(desired)]
        if len(featured) == 1:
            task.click_box(featured[0], after_sleep=.6)
            found = name_matches()
    for page in range(32):
        if found:
            break
        # Owned cards display levels; unreleased previews at the top do not.
        cards = [b for b in task.ocr(box=viewport(task, .01, .11, .63, .88))
                 if re.fullmatch(r'Lv[.．]?\s*\d{1,2}', b.name, re.I)]
        for card in sorted(cards, key=lambda b: (round(b.y / (task.height*.05)), b.x)):
            task.click_box(card, after_sleep=.4)
            if name_matches():
                remember_avatar(task, desired, card, page)
                found = True
                break
        if not found:
            scroll_roster(task)
    if not found:
        raise RuntimeError(f'角色列表中未核对到{desired}；不修改培养目标')
    confirm = task.wait_ocr(box=viewport(task, .74, .85, .99, .97),
                            match=re.compile('^设为培养目标$'), time_out=5)
    if not confirm:
        # Selecting the already active target can expose no Set button.
        # Return only from the verified picker, then verify the actual target.
        if task.wait_ocr(0, 0, .4, .13, match=re.compile('选择培养目标'), time_out=1):
            task.send_key('esc', after_sleep=.7)
            if task.wait_until(lambda: task.material_target_matches(desired),
                               time_out=3, raise_if_not_found=False):
                task.log_info(f'cultivation target already active: {desired}')
                return
        import cv2
        cv2.imwrite('logs/cultivation-selection-failed.png', task.frame)
        raise RuntimeError('设置培养目标按钮未确认，返回后目标也未核对成功')
    task.click_box(confirm, after_sleep=1)
    if not task.wait_until(lambda: task.material_target_matches(desired), time_out=4,
                           raise_if_not_found=False):
        raise RuntimeError('培养目标设置结果未确认')


def material_action(boxes, kind, width, height):
    labels = {'武器/技能': '武器与技能素材', '突破': '共鸣者突破材料',
              '周本': '技能升级材料', '角色经验': '共鸣者经验材料',
              '武器经验': '武器经验材料', '贝币': '贝币'}
    label = labels.get(kind)
    rows = sorted((b for b in boxes if b.name.strip() == label and b.x > .25*width), key=lambda b:b.y)
    if not rows:
        if kind in ('突破', '周本') and any(b.name.strip() == '声骸培养' for b in boxes):
            raise NoCurrentMaterialNeed(f'{kind}不在当前培养需求中，已看到材料列表末尾')
        raise RuntimeError(f'培养目标没有可见的{kind}材料行')
    # The first weapon/skill row is the domain material; later identically
    # named rows are overworld drops. Verify the resulting challenge separately.
    row = rows[0]
    buttons = [b for b in boxes if b.name.strip() == '前往' and b.x > .8*width
               and abs((b.y+b.height/2)-(row.y+row.height/2)) < .055*height]
    if len(buttons) != 1:
        raise RuntimeError(f'{kind}右侧前往按钮未唯一确认')
    if kind == '周本':
        counts = [re.search(r'本周剩余可收取次数[：:]\s*(\d+)/\d+', b.name) for b in boxes
                  if abs(b.y-row.y) < .08*height]
        counts = [m for m in counts if m]
        if len(counts) != 1 or int(counts[0][1]) < 1:
            raise RuntimeError('周本剩余领奖次数不足或未识别')
    return buttons[0]


def required_jobs(boxes, target, width):
    """Build only jobs actually observed in the cultivation target list.

    Repeated weapon/skill labels after the first refer to overworld materials;
    retain them as deferred jobs rather than treating them as domain rewards.
    """
    labels = {'共鸣者经验材料': ('角色经验', 'moni', 40),
              '共鸣者突破材料': ('突破', 'qiangdi', 60),
              '武器与技能素材': ('武器/技能', 'ningsu', 40),
              '技能升级材料': ('周本', 'zhange', 60),
              '武器经验材料': ('武器经验', 'moni', 40),
              '贝币': ('贝币', 'moni', 40)}
    counts = {}
    jobs = []
    for box in sorted(boxes, key=lambda b: b.y):
        label = box.name.strip()
        if label not in labels or box.x <= width * .25 or box.x >= width * .65:
            continue
        kind, category, cost = labels[label]
        occurrence = counts.get(label, 0)
        counts[label] = occurrence + 1
        job = {'target': target, 'kind': kind, 'cost': cost, 'repeat': occurrence,
               'route': {'category': category, 'fallback_stage_name': ''}}
        counts_on_row = material_counts(boxes, box, width)
        job['material_counts'] = counts_on_row
        job['satisfied'] = bool(counts_on_row) and all(a >= b for a, b in counts_on_row)
        if not counts_on_row:
            job['deferred_reason'] = '材料持有量/需求量未识别，禁止盲目重复刷取'
        if kind == '周本':
            quotas = [re.search(r'本周剩余可收取次数[：:]\s*(\d+)[/／]\d+', b.name)
                      for b in boxes if abs(b.y - box.y) < width * .08]
            quotas = [m for m in quotas if m]
            if len(quotas) == 1 and int(quotas[0][1]) == 0:
                job['deferred_reason'] = '本周周本奖励次数已用完，等待重置'
        if kind == '武器/技能' and occurrence:
            job['deferred_reason'] = '野外素材采集适配尚未完成，保留实际需求'
        from src.task.MaterialNeedsReport import describe_job
        projection = describe_job(job)['conversion_estimate']
        if projection and not any(projection['missing']) and not job['satisfied']:
            job['deferred_reason'] = '低级余量可能已足以合成补齐；先核验配方，不继续消耗体力'
            job['conversion_pending'] = True
        jobs.append(job)
    return jobs


def material_counts(boxes, row, width):
    """Read item counters at the right of a cultivation row, excluding weekly quota."""
    readings = []
    for box in boxes:
        if not .55*width < box.x < .87*width or not -.012*width < box.y-row.y < .040*width:
            continue
        match = re.fullmatch(r'([0-9]{1,7})[/／]([0-9]{1,7})', re.sub(r'\s+', '', box.name))
        if match:
            readings.append([int(match[1]), int(match[2])])
    return readings


def supplement_weekly_counts(task, boxes):
    """Verify small boss counters even when coarse OCR returns a truncated fraction."""
    import cv2
    for row in list(boxes):
        if row.name not in ('技能升级材料', '共鸣者突破材料'):
            continue
        crop = Box(round(task.width*.74), round(row.y + task.width*.010),
                   round(task.width*.06), round(task.width*.050))
        def enlarge(frame):
            frame = cv2.resize(frame, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
            return cv2.copyMakeBorder(frame, 20, 20, 20, 20, cv2.BORDER_REPLICATE)
        readings = task.ocr(box=crop, frame_processor=enlarge)
        values = [re.sub(r'\s+', '', b.name) for b in readings]
        values = [v for v in values if re.fullmatch(r'\d{1,7}[/／]\d{1,7}', v)]
        if len(values) == 1:
            boxes[:] = [b for b in boxes if not (
                .55*task.width < b.x < .87*task.width
                and -.012*task.width < b.y-row.y < .040*task.width
                and re.fullmatch(r'\d{1,7}[/／]\d{1,7}', re.sub(r'\s+', '', b.name)))]
            boxes.append(Box(round(task.width*.77), round(row.y + task.width*.033),
                             50, 20, name=values[0]))
            task.log_info(f'weekly counter verified from enlarged crop: {values[0]}')
    return supplement_material_counts(task, boxes)


def supplement_material_counts(task, boxes):
    """Read each material tile separately so a red leading digit is not dropped."""
    import cv2
    def enlarge(frame):
        # Red shortages and white denominators must have similar contrast.
        gray = frame.max(axis=2)
        gray = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        gray = cv2.copyMakeBorder(gray, 20, 20, 20, 20, cv2.BORDER_REPLICATE)
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    for row in list(boxes):
        if row.name != '武器与技能素材':
            continue
        verified = []
        for center in (1145/1920, 1255/1920, 1366/1920, 1476/1920):
            crop = Box(round(task.width*(center-.027)), round(row.y+task.width*.010),
                       round(task.width*.054), round(task.width*.050))
            values = [re.sub(r'\s+', '', b.name) for b in task.ocr(box=crop, frame_processor=enlarge)]
            values = [v for v in values if re.fullmatch(r'\d{1,7}[/／]\d{1,7}', v)]
            if len(values) == 1:
                verified.append(Box(round(task.width*center), round(row.y+task.width*.033),
                                    50, 20, name=values[0]))
        existing = material_counts(boxes, row, task.width)
        if verified and len(verified) >= len(existing):
            boxes[:] = [b for b in boxes if not (
                .55*task.width < b.x < .87*task.width
                and -.012*task.width < b.y-row.y < .040*task.width
                and re.fullmatch(r'\d{1,7}[/／]\d{1,7}', re.sub(r'\s+', '', b.name)))]
            boxes.extend(verified)
            task.log_info('material counters verified from tile crops: ' + str([b.name for b in verified]))
    return boxes
