"""绑定阶段的可解释动作冲突检查，不修改排序，不读取参考或运行结果。"""
from __future__ import annotations

import re
from pathlib import Path
from bspforge.source_syntax import SourceIndex, text


def without_comments(value):
    return re.sub(r'/\*.*?\*/|//[^\n]*', '', value, flags=re.S)


class BindingContractGuard:
    def __init__(self, source: Path, ir):
        self.index = SourceIndex(source, ir)

    def check(self, operation, entity, *, required_gpio_direction=None):
        node, resolved, relative = self.index.locate({**entity, 'entity_id': entity['id'],
                                                     'symbol': entity['name']})
        body = without_comments(text(node)) if node else ''
        symbol = re.sub(r'[^a-z0-9]', '', entity['name'].lower())
        code = body.lower()
        reasons = []
        if operation not in {'interrupt.register','gpio.attach_irq'} and any(term in symbol for term in ['irqhandler','interrupt_handler','isrhandler']):
            reasons.append('callback-entry-is-not-an-operation-command')
        if not node:
            return {'accepted': True, 'status': 'unknown-no-body', 'reasons': [],
                    'source_file': relative, 'reference_read': False}
        implementation = body.partition('{')[2].rpartition('}')[0].strip()
        if not implementation:
            reasons.append('empty-implementation')
        if operation in {'interrupt.enable', 'interrupt.disable'}:
            action = operation.split('.')[1]
            if 'pending' in symbol or 'priority' in symbol or 'vector' in symbol:
                reasons.append('irq-pending-priority-vector-is-not-mask-control')
            opposite = 'disable' if action == 'enable' else 'enable'
            if opposite in symbol and action not in symbol:
                reasons.append('opposite-irq-control-action')
        if operation in {'timer.start', 'timer.stop'}:
            if any(term in symbol for term in ['intenable', 'intdisable', 'intregister',
                                               'intunregister', 'preload', 'updatedisable']):
                reasons.append('timer-irq-event-or-preload-is-not-counter-run-state')
            if re.search(r'\b(?:TIM_DIER_|TIM_CR1_UDIS|TIM_CCMR\w*)', body) and not re.search(r'\bTIM_CR1_CEN\b', body):
                reasons.append('timer-body-does-not-change-run-enable')
        if operation == 'timer.set_interval':
            if any(term in symbol for term in ['intregister', 'intunregister', 'setcounter', 'setcount']) and not any(term in symbol for term in ['compare', 'period', 'reload']):
                reasons.append('current-count-or-isr-is-not-period')
            if re.search(r'->\s*(?:CNT|CV)\s*=', body) and not re.search(r'->\s*(?:ARR|RC|CCR\w*)\s*=', body):
                reasons.append('writes-current-count-without-period-target')
            if re.search(r'->\s*(?:TC_CMR|CMR)\s*=', body) and not re.search(r'->\s*(?:TC_RC|ARR|RC)\s*=', body):
                reasons.append('configures-timer-mode-without-period-target')
        if operation == 'gpio.write' and any(term in symbol for term in ['writeprotect', 'writeprotection', 'lock', 'direction', 'mode', 'outputwrite', 'pullup', 'pulldown', 'debounce', 'filter']):
            reasons.append('gpio-protection-or-mode-is-not-output-value')
        if operation == 'gpio.read' and any(term in symbol for term in ['output', 'latch', 'direction', 'intflag', 'pending']):
            reasons.append('gpio-output-state-or-irq-status-is-not-input-sample')
        if operation == 'gpio.configure' and any(term in symbol for term in ['toggle', 'pinread', 'pinwrite', 'getlevel']):
            reasons.append('gpio-data-action-is-not-direction-configuration')
        if operation == 'gpio.configure' and required_gpio_direction == 'output' and re.search(r'\b\w*DIR_INPUT\b', body):
            reasons.append('fixed-input-configuration-conflicts-with-output-slot')
        if operation == 'gpio.configure' and required_gpio_direction == 'output' and re.search(r'INPUT_?(?:Connect|Disconnect|Msk|Pos)',body,re.I) and not re.search(r'DIR_|DIRECTION|OUTPUT',body):
            reasons.append('input-buffer-only-does-not-establish-output-direction')
        if operation in {'clock.enable', 'clock.disable'}:
            if 'calibrationtimer' in symbol:
                reasons.append('calibration-timer-is-not-target-clock-state')
            if re.search(r'(?:IRQ_ENABLE|IRQ_DISABLE|irq_init|irq_enabled|clock_int_disable)', body) and not re.search(r'(?:task_trigger\s*\(|[hl]fclk_(?:start|stop)\s*\(|TASKS_\w+\s*=)', body):
                reasons.append('clock-api-only-enables-controller-irq')
            if re.search(r'(?:clock|clk)set$', symbol) and not re.search(r'(?:enable|disable|start|stop|control)', symbol):
                reasons.append('clock-tree-setting-is-not-instance-gate-control')
        return {'accepted': not reasons, 'status': 'verified-conflict' if reasons else 'no-proven-conflict',
                'reasons': reasons, 'source_file': relative, 'line': resolved.get('line'),
                'body_excerpt': implementation[:1000], 'reference_read': False}
