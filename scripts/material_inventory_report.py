"""Build a named shared-stock report from the last read-only game audit."""
import html
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.task.SharedMaterialInventory import summarize_shared_inventory

from src.task.SharedMaterialPlanner import FAMILIES



def main():
    audit = json.loads(Path('logs/material-audit-latest.json').read_text())
    activity = json.loads(Path('configs/macos-desktop/team-material-activity.json').read_text())
    recipes = [(a,b,3) for family in FAMILIES.values() for a,b in zip(family,family[1:])]
    summary = summarize_shared_inventory(audit['items'], recipes)
    result = {'updated_at': datetime.now().astimezone().isoformat(timespec='seconds'),
        'audit_status': audit['status'], 'audit_folder': audit['folder'],
        'synthesis_ratio': 3, 'recipe_verified_in_game': True,
        'note': '合成是规划估算，未执行；未扫描到的低阶材料不计入可用库存。库存按物品名称只计算一次，需求按角色求和。',
        'families': FAMILIES, 'items': summary,
        'activity': {k:v for k,v in activity['materials'].items()
                     if v.get('target') in ('心','今汐','卜灵')},
        'resources': {k:activity[k] for k in ['waveplates_spent','claim_units','solvents_used','reserve_waveplates_used']}}
    folder = Path('logs/material-status');folder.mkdir(exist_ok=True, parents=True)
    (folder/'shared-inventory.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    rows=[]
    for r in summary:
        need='、'.join(f'{k} {v}' for k,v in r['by_target'].items())
        cells=[r['item_name'],r['inventory'] if r['inventory'] is not None else '未核对',
               need,r['required_total'],r['raw_missing'],r['craft_output'],r['craft_input'],
               r['missing_after_synthesis'] if r['missing_after_synthesis'] is not None else '未核对']
        rows.append('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in cells)+'</tr>')
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>三角色共用材料账本</title>
<style>body{font:15px system-ui;margin:32px;color:#ddd;background:#121a27}table{border-collapse:collapse;width:100%}td,th{padding:10px;border-bottom:1px solid #3b4655;text-align:left}th{color:#9ccaff}p{line-height:1.7}</style>
<h1>心、卜灵、今汐 · 共用库存与合成缺口</h1><p>'''+html.escape(result['note'])+'''</p><p>截至 '''+html.escape(result['updated_at'])+'''，审计状态：'''+html.escape(result['audit_status'])+'''。纯化倍率已在游戏核对为3:1；表中合成数量为计划，尚未执行。</p><table><tr>'''+''.join('<th>'+x+'</th>' for x in ['材料','库存（只算一次）','各角色需求','总需求','原始缺口','计划合成产出','计划合成投入','合成后缺口'])+'</tr>'+''.join(rows)+'</table></html>'
    (folder/'shared-inventory.html').write_text(page)
    print(json.dumps([r for r in summary if r['item_name'] in ['如歌的弦线','急板涡流','海蚀嵌合体239']],ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
