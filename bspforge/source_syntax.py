from __future__ import annotations

import re
from collections import defaultdict, OrderedDict
from pathlib import Path
from typing import Any

from tree_sitter import Language, Parser
import tree_sitter_c

from bspforge.hardware_effect_graph import identifier_tokens


def walk(node):
    if node is None:
        return
    pending = [node]
    while pending:
        current = pending.pop()
        yield current
        pending.extend(reversed(current.named_children))


def text(node):
    return node.text.decode('utf-8', errors='replace') if node else ''


def identifiers(node):
    return {text(n) for n in walk(node) if n.type in {'identifier', 'field_identifier'}} if node else set()


def field(node, name):
    return node.child_by_field_name(name) if node else None


def function_name(declarator):
    if declarator is None:
        return ''
    if declarator.type in {'identifier', 'field_identifier', 'qualified_identifier'}:
        return text(declarator)
    return function_name(field(declarator, 'declarator'))


class SourceIndex:
    """基于已存在IR定位源码；树状语法和类型提示与编译语义分别标记。"""

    def __init__(self, root: Path, ir: dict[str, Any]):
        self.root, self.ir = root, ir
        self.parser = Parser(Language(tree_sitter_c.language()))
        try:
            import tree_sitter_cpp
            self.cpp_parser = Parser(Language(tree_sitter_cpp.language()))
        except ImportError:
            self.cpp_parser = self.parser
        self.files = OrderedDict()
        self.buffers = {}
        self.by_id = {f['id']: f for f in ir['functions']}
        self.by_name = defaultdict(list)
        for function in ir['functions']:
            self.by_name[function['name']].append(function)
        self.source_hashes = {}

    def parse_file(self, relative):
        if relative in self.files:
            self.files.move_to_end(relative)
            return self.files[relative]
        path = self.root / relative
        try:
            raw = path.read_bytes()
        except OSError:
            self.files[relative] = (None, {})
            return self.files[relative]
        import hashlib
        self.buffers[relative] = raw
        self.source_hashes[relative] = hashlib.sha256(raw).hexdigest()
        parser = self.cpp_parser if path.suffix in {'.cc', '.cpp', '.cxx', '.hpp'} else self.parser
        tree = parser.parse(raw)
        functions = defaultdict(list)
        for node in walk(tree.root_node):
            if node.type == 'function_definition':
                name = function_name(field(node, 'declarator'))
                if name:
                    functions[name].append(node)
        self.files[relative] = (tree, functions)
        while len(self.files) > 24:
            self.files.popitem(last=False)
        return self.files[relative]

    def locate(self, candidate):
        original = self.by_id.get(candidate['entity_id'], candidate)
        symbol = candidate.get('symbol', original.get('name', ''))
        relative = original.get('file', candidate['file'])
        tree, nodes = self.parse_file(relative)
        if nodes.get(symbol):
            node = min(nodes[symbol], key=lambda n: abs(n.start_point.row + 1 - int(original.get('line', 1))))
            return node, original, relative
        # 声明与定义只按同符号和源码模块接近程度解析，不读取标签。
        alternatives = [f for f in self.by_name.get(symbol, []) if f.get('evidence', {}).get('kind') == 'definition']
        if alternatives:
            def prefix(path):
                count = 0
                for left, right in zip(Path(path).parts, Path(relative).parts):
                    if left != right:
                        break
                    count += 1
                return count
            nearest = max(prefix(f['file']) for f in alternatives)
            alternatives = [f for f in alternatives if prefix(f['file']) == nearest]
        if len({f['file'] for f in alternatives}) > 1:
            return None, original, relative
        alternatives = sorted(alternatives, key=lambda f: f.get('line', 1))
        for alternative in alternatives:
            _, other = self.parse_file(alternative['file'])
            if other.get(symbol):
                return other[symbol][0], alternative, alternative['file']
        return None, original, relative

    def resolve_call(self, symbol, caller_file):
        alternatives = self.by_name.get(symbol, [])
        same = [f for f in alternatives if f['file'] == caller_file]
        chosen = same or alternatives
        if not chosen:
            return None
        def common_prefix(relative):
            count = 0
            for left, right in zip(Path(relative).parts, Path(caller_file).parts):
                if left != right:
                    break
                count += 1
            return count
        best = max(common_prefix(f['file']) for f in chosen)
        chosen = [f for f in chosen if common_prefix(f['file']) == best]
        definitions = [f for f in chosen if f.get('evidence', {}).get('kind') == 'definition']
        chosen = definitions or chosen
        source = [f for f in chosen if Path(f['file']).suffix not in {'.h', '.hpp'}]
        chosen = source or chosen
        # 无目标条件证据时，不按字母顺序选另一个芯片分支的实现。
        if len({f['file'] for f in chosen}) > 1:
            return None
        return min(chosen, key=lambda f: f.get('line', 1))


def parameter_info(function, signature):
    declarator = field(function, 'declarator')
    params = next((n for n in walk(declarator) if n.type == 'parameter_list'), None) if declarator else None
    output = []
    if params:
        for node in params.named_children:
            if node.type not in {'parameter_declaration', 'optional_parameter_declaration'}:
                continue
            name = function_name(field(node, 'declarator'))
            if name:
                output.append({'name': name, 'type': text(node), 'pointer': '*' in text(node) or '[' in text(node),
                               'callback': any(n.type == 'function_declarator' for n in walk(field(node, 'declarator')))})
    if not output and signature:
        match = re.search(r'\((.*)\)', signature)
        for part in (match.group(1).split(',') if match else []):
            ids = re.findall(r'[A-Za-z_]\w*', part)
            if len(ids) > 1 and ids[-1] not in {'void', '...'}:
                output.append({'name': ids[-1], 'type': part, 'pointer': '*' in part or '[' in part,
                               'callback': bool(re.search(r'\(\s*\*', part))})
    return output


def register_roles(expression, type_context=''):
    """寄存器与位域命名的通用角色词典，不接受SDK名称或正确API列表。"""
    value = expression.lower()
    tokens = set(identifier_tokens(expression + ' ' + type_context))
    roles = set()
    is_clock = bool(tokens & {'clock', 'clk', 'rcc', 'pll', 'sysctl', 'osc', 'sysclk'})
    is_irq = bool(tokens & {'nvic', 'plic', 'irq', 'interrupt', 'intc', 'intr'})
    is_uart = bool(tokens & {'uart', 'usart', 'uarths', 'serial', 'sci', 'lpuart'})
    is_gpio = bool(tokens & {'gpio', 'gpiohs', 'port', 'pio', 'pin'})
    is_timer = bool(tokens & {'timer', 'tim', 'tmr', 'tcpwm', 'gpt', 'counter', 'ctimer', 'gptimer'})
    if is_clock:
        if tokens & {'gate', 'enable', 'en', 'ckenr', 'clken', 'ahbenr', 'apb1enr', 'apb2enr'} or re.search(r'clk_?en|clock_?enable', value):
            roles.add('clock_gate')
        if tokens & {'pll', 'freq', 'frequency', 'div', 'divider', 'cfgr', 'threshold', 'clkcfg'}:
            roles.add('clock_frequency')
    if is_irq:
        if tokens & {'iser', 'icer', 'enable', 'disable', 'mask', 'mstatus', 'mie', 'intenset', 'intenclr'}:
            roles.add('irq_enable')
        if tokens & {'ispr', 'icpr', 'pending', 'pend', 'claim', 'complete', 'mip'}:
            roles.add('irq_pending')
    if tokens & {'callback', 'handler', 'vector', 'isrtable', 'isr_table', 'isrvector'} or re.search(r'callback|handler|vector', value):
        roles.add('handler_slot')
    if is_uart:
        if tokens & {'thr', 'tdr', 'tx', 'txdata', 'txbuf', 'txdr', 'transmit'} or re.search(r'\btx(data|fifo)?\b', value):
            roles.add('uart_tx')
        if tokens & {'rbr', 'rdr', 'rx', 'rxdata', 'rxbuf', 'rxdr', 'receive'} or re.search(r'\brx(data|fifo)?\b', value):
            roles.add('uart_rx')
        if tokens & {'dr', 'data', 'fifo'}:
            roles.update({'uart_tx', 'uart_rx'})
        if tokens & {'baud', 'lcr', 'lcrh', 'brr', 'dll', 'dlh', 'fcr', 'cr1', 'cr2', 'cr3', 'config', 'format'}:
            roles.add('uart_config')
    if is_gpio:
        if tokens & {'dir', 'direction', 'mode', 'moder', 'crl', 'crh', 'pull', 'pupdr', 'input_en', 'output_en'} or re.search(r'(input|output)_?en', value):
            roles.add('gpio_direction')
        if tokens & {'idr', 'input', 'input_val', 'din', 'pdir', 'in'} or 'input_val' in value:
            roles.add('gpio_input')
        if tokens & {'odr', 'bsrr', 'brr', 'output', 'output_val', 'dout', 'pdor', 'psor', 'pcor', 'ptor', 'out'} or 'output_val' in value:
            roles.add('gpio_output')
    if is_timer:
        if tokens & {'cen', 'enable', 'run', 'start'}:
            roles.add('timer_run')
        if tokens & {'arr', 'load', 'reload', 'period', 'compare', 'cmp', 'ccr', 'ccr1', 'ccr2', 'loadcount'}:
            roles.add('timer_period')
        if tokens & {'cnt', 'count', 'current', 'currentvalue'}:
            roles.add('timer_count')
        if tokens & {'dier', 'imr', 'inten', 'intenset', 'intenclr', 'mask', 'irqmask'}:
            roles.add('timer_irq_mask')
        if tokens & {'psc', 'prescaler', 'prescale', 'mode', 'cfg', 'config', 'control', 'cr1', 'controlreg'}:
            roles.add('timer_config')
    return roles
