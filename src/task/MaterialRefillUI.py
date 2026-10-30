"""In-place waveplate exchanges with a durable guard around resource spending."""
import json
import re
import time
from pathlib import Path


class MaterialResourceLimit(RuntimeError):
    pass


class RefillOutcomeUncertain(RuntimeError):
    pass


class MaterialRefillUI:
    refill_pending_path = Path('logs/refill-use-pending.json')

    def refill_text(self, pattern, region=(0, 0, 1, 1), timeout=4):
        if pattern in (r'补充结晶波片', r'兑换结晶波片'):
            # Only the left header: exclude the animated item cards and the
            # instruction underneath, reducing OCR latency in the GUI.
            region = (.15, .15, .45, .28)
        return self.menu_text(pattern, region, timeout, viewport=True)

    def refill_click(self, pattern, region=(0, 0, 1, 1), timeout=4):
        box = self.refill_text(pattern, region, timeout)
        if not box:
            raise RuntimeError(f'refill action not uniquely verified: {pattern}')
        self.click_box(box, after_sleep=.6)

    def assert_no_pending_refill(self):
        if Path('logs/echo-claim-pending.json').exists():
            raise RefillOutcomeUncertain('上次声骸领奖结果未核对；禁止开始新一轮')
        if self.refill_pending_path.exists() or Path("logs/solvent-use-pending.json").exists():
            raise RefillOutcomeUncertain("上次补给结果未核对；禁止开始新一轮")

    def refill_for_claim(self, budget, required=None):
        """Optional cultivation-page refill; never navigate to the map."""
        required = required or budget.claim_cost * budget.claim_multiplier
        for _ in range(4):
            before, reserve, _ = self.get_stamina()
            if before < 0:
                raise RuntimeError('补充前波片未识别')
            if before >= required:
                return before
            self.refill_at_reward(budget, before, reserve, opened=False)
        raise MaterialResourceLimit(f'补给次数已达上限，仍不足{required}波片')

    def refill_at_reward(self, budget, before, reserve, opened=True):
        """Exchange once, close only the refill panel, return to its caller."""
        # The second dialog selects a partial reserve exchange.
        allowance = reserve if budget.max_reserve == -1 else budget.max_reserve - budget.reserve_used
        amount = min(reserve, allowance, 240 - before)
        if amount > 0 and (budget.max_reserve == -1 or budget.reserve_used + amount <= budget.max_reserve):
            return self._exchange_waveplates(budget, before, reserve, 'reserve', amount, opened)
        if budget.max_solvents == -1 or budget.solvents_used < budget.max_solvents:
            return self._exchange_waveplates(budget, before, reserve, 'solvent', 60, opened)
        raise MaterialResourceLimit('储备和溶剂额度不足；保留领奖现场')

    def refill_reserve(self, budget):
        before, reserve, _ = self.get_stamina()
        return self._exchange_waveplates(budget, before, reserve, 'reserve', reserve, False)

    def refill_solvent(self, budget, before, reserve):
        return self._exchange_waveplates(budget, before, reserve, 'solvent', 60, False)

    def _exchange_waveplates(self, budget, before, reserve, source, amount, opened):
        pending = self.refill_pending_path
        if pending.exists() or Path('logs/solvent-use-pending.json').exists():
            raise RefillOutcomeUncertain('上次补给结果未核对；禁止重复兑换')
        if before < 0 or reserve < 0 or amount <= 0:
            raise RuntimeError('补给前数量未核对')
        if source == 'solvent' and budget.max_solvents != -1 and budget.solvents_used >= budget.max_solvents:
            raise MaterialResourceLimit('溶剂额度不足')
        if source == 'reserve' and (budget.max_reserve != -1 and budget.reserve_used + amount > budget.max_reserve):
            raise MaterialResourceLimit('储备额度不足')
        self.focus_material_menu()
        if not opened:
            self.click_relative(.839, .059, after_sleep=.5)
        if not self.refill_text(r'补充结晶波片'):
            raise RuntimeError('补给窗口未确认')
        x = .405 if source == 'reserve' else .497
        self.click(self.width_of_screen(1)*x, self.height_of_screen(1)*.44, after_sleep=.5)
        label = r'提取等量结晶单质' if source == 'reserve' else r'消耗1结晶溶剂补充60结晶波片'
        if not self.refill_text(label, (.3, .45, .7, .62)):
            raise RuntimeError('reserve source not verified' if source == 'reserve' else '单个溶剂来源未确认')
        if source == 'solvent':
            self.refill_click(r'确认', (.5, .66, .75, .8))
            count = self.verify_solvent_exchange()
            if (budget.max_solvents != -1
                    and budget.solvents_used + count > budget.max_solvents):
                raise MaterialResourceLimit('溶剂兑换次数超过本次剩余额度；禁止确认')
            amount = 60 * count
            if before + amount > 240:
                raise RuntimeError('溶剂兑换会超过240波片上限；禁止确认')
        else:
            self.refill_click(r'确认', (.5, .66, .75, .8))
            amount = self.verify_reserve_exchange()
            if amount > reserve or before + amount > 240:
                raise MaterialResourceLimit('储备兑换数量超出余额或波片容量；禁止确认')
            if budget.max_reserve != -1 and budget.reserve_used + amount > budget.max_reserve:
                raise MaterialResourceLimit('储备兑换数量超过本次额度；禁止确认')
        record = {'source': source, 'before': before, 'reserve': reserve, 'amount': amount}
        if source == 'solvent':
            record['solvent_count'] = count
        pending.parent.mkdir(parents=True, exist_ok=True)
        pending.write_text(json.dumps(record))
        if source == 'reserve':
            budget.record_refill(amount)
        else:
            for _ in range(count):
                budget.record_solvent()
        update = getattr(self, 'update_activity', None)
        if update:
            update()
        try:
            for attempt in range(3 if source == 'solvent' else 1):
                self.refill_click(r'确认', (.5, .66, .75, .8))
                if self.refill_text(r'获得', (.35, .18, .65, .35), timeout=8):
                    break
                if (source != 'solvent' or attempt == 2
                        or not self.refill_text(r'兑换结晶波片', timeout=.5)
                        or self.verify_solvent_exchange() != count):
                    raise RuntimeError('补给获得窗口未确认')
            self.refill_click(r'点击空白处继续', (.3, .8, .7, .95))
            if self.refill_text(r'补充结晶波片', timeout=.5):
                self.send_key('esc', after_sleep=.6)
            elif not self.reward_dialog_visible(timeout=1):
                raise RuntimeError('补给结果窗口未确认')
            after, remaining, _ = self.get_stamina()
            expected = reserve - amount if source == 'reserve' else reserve
            if after-before not in (amount, amount+1) or remaining != expected:
                raise RuntimeError('补给数量变化未确认')
        except Exception as exc:
            raise RefillOutcomeUncertain(f'{exc}；保留补给待核对记录') from exc
        pending.unlink()
        self.log_info(f'in-place refill {source}: stamina {before} -> {after}; reserve {reserve} -> {remaining}')
        return after

    def verify_reserve_exchange(self):
        region = (.2, .5, .5, .65)
        box = self.refill_text(r'兑换次数[：:]\d+', region)
        if not box:
            raise RuntimeError('储备兑换次数未识别；禁止确认')
        count = int(re.search(r'\d+', box.name).group())
        if not 1 <= count <= 240:
            raise RuntimeError('储备兑换次数超出范围；禁止确认')
        checks = ((r'兑换结晶波片', (.2, .1, .75, .3)),
                  (rf'结晶单质[x×X]{count}', (.3, .35, .48, .53)),
                  (rf'结晶波片[x×X]{count}', (.52, .35, .7, .53)))
        if not all(self.refill_text(pattern, region) for pattern, region in checks):
            raise RuntimeError('储备和波片兑换数量不一致；禁止确认')
        return count

    def verify_solvent_exchange(self):
        count_region = (.2, .5, .5, .65)
        count_box = self.refill_text(r'兑换次数[：:]\d+', count_region)
        if not count_box:
            raise RuntimeError('溶剂兑换次数未识别，禁止确认')
        count = int(re.search(r'\d+', count_box.name).group())
        if not 1 <= count <= 3:
            raise RuntimeError('溶剂兑换次数超出可核对范围，禁止确认')
        checks = ((r'兑换结晶波片', (.2, .1, .75, .3)),
                  (rf'结晶溶剂[x×X]{count}', (.3, .35, .48, .53)),
                  (rf'结晶波片[x×X]{count * 60}', (.52, .35, .7, .53)),
                  (rf'兑换次数[：:]{count}', count_region))
        if not all(self.refill_text(pattern, region) for pattern, region in checks):
            raise RuntimeError('溶剂数量、波片数量或兑换次数不一致，禁止确认')
        return count

    def reconcile_solvent(self):
        if self.refill_pending_path.exists():
            return self.reconcile_current_refill()
        import json
        from pathlib import Path
        pending = Path('logs/solvent-use-pending.json')
        record = json.loads(pending.read_text())
        self.focus_material_menu()
        if not self.refill_text(r'获得', (.35, .18, .65, .35), timeout=3):
            raise RuntimeError('未确认溶剂获得窗口，保留待核对记录')
        self.refill_click(r'点击空白处继续', (.3, .8, .7, .95))
        if not self.refill_text(r'补充结晶波片', (.2, .1, .75, .3)):
            raise RuntimeError('补充窗口未确认')
        self.send_key('esc', after_sleep=.6)
        after, reserve, _ = self.get_stamina()
        if after - record['before'] not in (60, 61) or reserve != record['reserve']:
            raise RuntimeError(f'补充结果仍不明确: {after}, {reserve}')
        record.update(after=after, verified=True)
        pending.write_text(json.dumps(record, ensure_ascii=False))
        pending.rename(Path('logs') / f'solvent-reconciled-{time.time_ns()}.json')
        self.return_to_world()
        return after

    def reconcile_current_refill(self):
        """Finish one recorded exchange only from the exact same game popup."""
        record = json.loads(self.refill_pending_path.read_text())
        if record.get('source') != 'solvent' or record.get('solvent_count') != 1:
            raise RefillOutcomeUncertain('待核对补给不是单个溶剂；保留记录')
        before, reserve = record['before'], record['reserve']
        self.focus_material_menu()
        if self.refill_text(r'兑换结晶波片', timeout=.5):
            # This popup shows the solvent inventory beside waveplates; the
            # generic two-number HUD reader would mistake it for reserve.
            waveplate_badge = rf'{before}\s*/\s*240'
            if (not self.refill_text(waveplate_badge, (.68, 0, .9, .12))
                    or self.verify_solvent_exchange() != 1):
                raise RefillOutcomeUncertain('补给确认窗口数量与原记录不一致')
            for _ in range(3):
                self.refill_click(r'确认', (.5, .66, .75, .8))
                if self.refill_text(r'获得', (.35, .18, .65, .35), timeout=3):
                    break
                if not self.refill_text(r'兑换结晶波片', timeout=.5):
                    raise RefillOutcomeUncertain('确认后页面未知；保留待核对记录')
            else:
                raise RefillOutcomeUncertain('三次确认未生效；保留待核对记录')
        elif not self.refill_text(r'获得', (.35, .18, .65, .35), timeout=2):
            raise RefillOutcomeUncertain('补给结果页面未知；保留待核对记录')
        self.refill_click(r'点击空白处继续', (.3, .8, .7, .95))
        if self.refill_text(r'补充结晶波片', timeout=.5):
            self.send_key('esc', after_sleep=.6)
        elif not self.reward_dialog_visible(timeout=1):
            raise RefillOutcomeUncertain('补给后领奖窗口未确认；保留待核对记录')
        after, remaining, _ = self.get_stamina()
        if after - before not in (60, 61) or remaining != reserve:
            raise RefillOutcomeUncertain('波片变化未确认；保留待核对记录')
        self.refill_pending_path.unlink()
        self.log_info(f'reconciled in-place solvent: {before} -> {after}')
        return after
