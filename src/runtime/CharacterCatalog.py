"""Names offered by the GUI and verified against the live combat party."""
import json
from pathlib import Path


def names_for_party(chars):
    rows=json.loads((Path(__file__).resolve().parents[2]/'profiles/characters.json').read_text())
    names={row['id']:row['name'] for row in rows}
    if len(chars)!=3 or any(not c or c.confidence<.8 for c in chars):
        raise RuntimeError('当前三人身份未完整识别，未使用缓存培养名单。')
    result=[names.get(getattr(c.char_name,'value',c.char_name)) for c in chars]
    if not all(result) or len(set(result))!=3:
        raise RuntimeError('当前队伍的培养名称尚未核实，请选择已适配的培养角色。')
    return result
