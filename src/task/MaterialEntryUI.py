"""Recognize the non-spending low-waveplate warning during material entry."""
import re

from src.task.CultivationTargetUI import viewport
from src.task.MaterialRefillUI import MaterialResourceLimit


ENTRY_WARNING = re.compile(r'结晶波片不足[，,]无法获取奖励[，,]请确认是否继续进入[？?]')
ENTRY_COST_WARNING = re.compile(
    r'领取奖励需要消耗(40|60)点结晶波片[，,]当前拥有(\d+)点[，,]是否继续[？?]')


def entry_warning_buttons(boxes, width, height, expected_cost=None):
    """Require the observed sentence, title, and two buttons in one frame.

    All coordinates are capture pixels in the live viewport. A generic
    confirmation or a refill dialog must never qualify as this entry warning.
    """
    def matches(pattern, area):
        left, top, right, bottom = area
        return [box for box in boxes
                if left <= (box.x + box.width / 2) / width <= right
                and top <= (box.y + box.height / 2) / height <= bottom
                and re.fullmatch(pattern, re.sub(r'\s+', '', box.name))]

    title = matches('提示', (.20, .28, .40, .40))
    sentence = []
    for box in boxes:
        x = (box.x + box.width / 2) / width
        y = (box.y + box.height / 2) / height
        if not (.23 <= x <= .78 and .40 <= y <= .52):
            continue
        words = re.sub(r'\s+', '', box.name)
        cost_notice = ENTRY_COST_WARNING.fullmatch(words)
        if ENTRY_WARNING.fullmatch(words) or (cost_notice
                and (expected_cost is None or int(cost_notice[1]) == expected_cost)
                and int(cost_notice[2]) < int(cost_notice[1])):
            sentence.append(box)
    cancel = matches('取消', (.23, .56, .46, .67))
    confirm = matches('确认', (.54, .56, .78, .67))
    if all(len(items) == 1 for items in (title, sentence, cancel, confirm)):
        return cancel[0], confirm[0]
    return None


class MaterialEntryUI:
    def read_material_entry_warning(self):
        self.next_frame()
        boxes = self.ocr(box=viewport(self, .20, .28, .80, .70))
        budget = getattr(self, '_run_budget', None) or getattr(self, 'shared_budget', None)
        return entry_warning_buttons(boxes, self.width, self.height,
                                     expected_cost=budget.claim_cost if budget else None)

    def handle_material_entry_notice(self, timeout=1):
        buttons = self.wait_until(self.read_material_entry_warning,
                                  time_out=timeout, raise_if_not_found=False)
        if not buttons:
            return False
        # Only the explicitly non-claiming practice phase can enter without a
        # spending allowance. This confirmation itself spends no resources.
        budget = getattr(self, '_run_budget', None) or getattr(self, 'shared_budget', None)
        refill_allowed = budget and budget.can_claim() and (
            budget.max_reserve == -1 or budget.reserve_used < budget.max_reserve
            or budget.max_solvents == -1 or budget.solvents_used < budget.max_solvents)
        allowed = getattr(self, 'phase', None) == 'practice' or refill_allowed
        if getattr(self, '_entry_warning_accepted', False):
            raise RuntimeError('低波片入场提示重复出现；不重复确认')
        self.focus_material_menu()
        # Focus changes can replace the page; never click the old OCR box.
        buttons = self.read_material_entry_warning()
        if not buttons:
            raise RuntimeError('低波片入场提示在点击前发生变化；停止输入')
        self.click_box(buttons[1 if allowed else 0], after_sleep=.5)
        if not allowed:
            raise MaterialResourceLimit('波片不足且无可用补给额度；已取消入场')
        self._entry_warning_accepted = True
        self.log_info('verified low-waveplate entry warning accepted; refill remains at reward')
        if not self.wait_until(lambda: not self.read_material_entry_warning(),
                               time_out=4, raise_if_not_found=False):
            raise RuntimeError('低波片入场提示未关闭；不重复确认')
        return True
