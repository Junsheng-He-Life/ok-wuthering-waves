"""Human-readable observed shortages and explicitly labelled conversion estimates."""
import html
import json
from datetime import datetime
from pathlib import Path


def conversion_projection(counts, ratio=3):
    """Reserve each lower tier's own demand before upgrading its surplus.

    Input is one confirmed family ordered from low to high. Output does not
    imply that synthesis has been performed or that currency costs are met.
    """
    if ratio < 2 or any(a < 0 or b < 0 for a, b in counts):
        raise ValueError('invalid conversion input')
    stock = [a for a, _ in counts]
    crafted = [0] * len(counts)
    for i in range(len(counts) - 1):
        surplus = max(0, stock[i] - counts[i][1])
        made = surplus // ratio
        stock[i] -= made * ratio
        stock[i + 1] += made
        crafted[i + 1] += made
    return {'after_conversion': stock, 'crafted': crafted,
            'missing': [max(0, need - stock[i]) for i, (_, need) in enumerate(counts)]}


def describe_job(job):
    counts = job.get('material_counts', [])
    raw = [max(0, b-a) for a, b in counts]
    projection = None
    # These two previously captured first rows visibly show a single family
    # in blue/purple/gold order. Until the in-game recipe is verified, this is
    # a planning estimate only and must not mark a farming job as complete.
    if (job.get('kind') == '武器/技能' and job.get('repeat') == 0
            and ((job.get('target') in ('秧秧·玄翎', '弗洛洛') and len(counts) == 3)
                 or (job.get('target') == '心' and len(counts) == 4))):
        projection = conversion_projection(counts)
    return {**job, 'raw_missing': raw, 'conversion_estimate': projection,
            'conversion_verified': False,
            'observation_status': '未知' if not counts else ('库存已足' if not any(raw) else '仍有缺口')}


def write_needs_report(progress, status='paused', budget=None, directory='logs/material-status', activity=None):
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    jobs = [describe_job(job) for job in progress.get('jobs', [])]
    data = {'updated_at': datetime.now().astimezone().isoformat(timespec='seconds'),
            'observed_at': progress.get('observed_at', '旧记录，扫描时间未记录'),
            'status': status, 'budget': budget, 'activity': activity, 'jobs': jobs}
    def atomic(name, text):
        target = folder / name
        tmp = target.with_suffix(target.suffix + '.tmp')
        tmp.write_text(text, encoding='utf-8')
        tmp.replace(target)
    atomic('status.json', json.dumps(data, ensure_ascii=False, indent=2))
    rows = []
    for job in jobs:
        counts = ' · '.join(f'{a}/{b}' for a,b in job.get('material_counts', [])) or '未识别'
        missing = ' · '.join(map(str, job['raw_missing'])) or '未知'
        estimate = job['conversion_estimate']
        projected = (' · '.join(map(str, estimate['missing'])) + '（3:1估算，配方待核验）') if estimate else '系列/等级未核验，不混合折算'
        note = job.get('deferred_reason') or ('周本尚未适配' if job.get('kind') == '周本' else job['observation_status'])
        cells = [job['target'], f"{job['kind']} · 第{job.get('repeat',0)+1}行", counts, missing, projected, note]
        rows.append('<tr>' + ''.join('<td>'+html.escape(str(c))+'</td>' for c in cells) + '</tr>')
    status_text = {'paused':'已暂停','interrupted':'已暂停','running':'运行中','stopped':'已停止'}.get(status,status)
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta http-equiv="refresh" content="5">
<title>队伍材料缺口</title><style>body{font:16px system-ui;background:#111827;color:#e5e7eb;margin:32px}h1{font-size:26px}p{color:#cbd5e1;line-height:1.7}table{border-collapse:collapse;width:100%;background:#1f2937}td,th{text-align:left;padding:14px;border-bottom:1px solid #374151}th{color:#93c5fd}small{color:#9ca3af}</style>
<h1>队伍材料缺口 · '''+html.escape(status_text)+'''</h1><p>库存来自最近一次培养目标扫描；领奖后的准确库存将在下轮扫描更新。各行按画面从左到右排列。合成估算先保留低级材料需求，不代表已经合成。</p><p>不同角色可能共享库存，不能将逐角色可合成数量直接相加。周本、野外和无法识别的项目继续显示为未完成。</p>'''
    if activity:
        from src.task.MaterialActivity import format_duration
        current = activity.get('current_job') or {}
        current_text = ' / '.join(x for x in (current.get('target'), current.get('kind'),
                                                current.get('resolved_stage', '')) if x) or '当前无材料任务'
        page += ('<section><h2>本次运行概况</h2><p>状态：'+html.escape(str(activity.get('status', status)))+
                 '　当前：'+html.escape(current_text)+'<br>累计活跃时间：'+
                 html.escape(format_duration(activity.get('elapsed_seconds', 0)))+
                 '　累计波片：'+str(activity.get('waveplates_spent', 0))+
                 '　备用结晶：'+str(activity.get('reserve_waveplates_used', 0))+
                 '　领奖：'+str(activity.get('claim_units', 0))+
                 '　结晶溶剂：'+str(activity.get('solvents_used', 0))+'</p></section>')
        if activity.get('baseline_note'):
            page += '<small>'+html.escape(activity['baseline_note'])+'</small>'
        events = activity.get('events', [])[-10:]
        if events:
            page += '<h3>最近领取</h3><table><thead><tr>'+''.join(
                '<th>'+s+'</th>' for s in ('时间','角色','材料类别','关卡','次数','波片'))+'</tr></thead><tbody>'
            for event in reversed(events):
                cells = (event.get('at', ''), event.get('target', ''), event.get('kind', ''),
                         event.get('stage', ''), event.get('claim_units', 0), event.get('waveplates_spent', 0))
                page += '<tr>'+''.join('<td>'+html.escape(str(c))+'</td>' for c in cells)+'</tr>'
            page += '</tbody></table>'
        material_totals = activity.get('materials', {})
        if material_totals:
            from src.task.MaterialActivity import format_duration
            page += '<h3>角色材料累计</h3><table><thead><tr>'+''.join(
                '<th>'+s+'</th>' for s in ('角色','类别','关卡','领奖次数','波片','活跃用时'))+'</tr></thead><tbody>'
            for totals in sorted(material_totals.values(), key=lambda item: (item['target'], item['kind'])):
                cells = (totals.get('target', ''), totals.get('kind', ''), totals.get('stage', ''),
                         totals.get('claim_units', 0), totals.get('waveplates_spent', 0),
                         format_duration(totals['active_seconds'])
                         if totals.get('active_seconds') is not None else '历史未记录')
                page += '<tr>'+''.join('<td>'+html.escape(str(c))+'</td>' for c in cells)+'</tr>'
            page += '</tbody></table>'
    page += '<small>扫描时间：'+html.escape(str(data['observed_at']))+'　报告更新时间：'+html.escape(data['updated_at'])+'</small>'
    if budget:
        page += '<p>当前进程账本：'+html.escape(json.dumps(budget,ensure_ascii=False))+'</p>'
    page += '<table><thead><tr>'+''.join('<th>'+s+'</th>' for s in ('角色','材料类别','持有/需要','原始缺口','合成后缺口估算','状态'))+'</tr></thead><tbody>'+''.join(rows)+'</tbody></table></html>'
    atomic('index.html', page)
    return data
