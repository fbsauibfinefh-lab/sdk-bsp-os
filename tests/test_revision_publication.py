"""公开代码与版本契约检查，使用合成函数，不代表重新上板。"""
import importlib.util
import json
from pathlib import Path

import pytest
from bspforge.binding_contract_guard import BindingContractGuard, without_comments
from scripts.replacement_sdk_binding import canonical, public_scope
from scripts.verify_revision_publication import equal

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / 'reproduction/mdpi-r1'


def guard(tmp_path, name, body, operation):
    (tmp_path / 'driver.c').write_text(body)
    entity = {'id': 'f', 'name': name, 'file': 'driver.c', 'line': 1,
              'signature': body.split('{')[0], 'evidence': {'kind': 'definition'}}
    return BindingContractGuard(tmp_path, {'functions': [entity]}).check(operation, entity)


def test_irq_pending_is_not_irq_enable(tmp_path):
    assert not guard(tmp_path, 'SetPendingIRQ', 'void SetPendingIRQ(int n){NVIC->ISPR[0]=1u<<n;}', 'interrupt.enable')['accepted']
    assert guard(tmp_path, 'EnableIRQ', 'void EnableIRQ(int n){NVIC->ISER[0]=1u<<n;}', 'interrupt.enable')['accepted']


@pytest.mark.parametrize('name,body', [('SetCounter', 't->CNT=x;'), ('tc_init', 't->TC_CMR=x;')])
def test_non_period_effects_rejected(tmp_path, name, body):
    assert not guard(tmp_path, name, f'void {name}(int x){{{body}}}', 'timer.set_interval')['accepted']


def test_body_missing_is_unknown_not_proven_conflict(tmp_path):
    result = guard(tmp_path, 'configure', 'void configure(int x);', 'timer.initialize')
    assert result['accepted'] and result['status'] == 'unknown-no-body'


def test_comment_does_not_supply_hardware_evidence():
    assert 'ISER' not in without_comments('void f(void){/* ISER=1; */ // ISER=1;\n}')


def test_gpio_read_is_not_output_latch(tmp_path):
    assert not guard(tmp_path, 'ReadOutputData', 'int ReadOutputData(void){return p->ODR;}', 'gpio.read')['accepted']
    assert guard(tmp_path, 'ReadInputData', 'int ReadInputData(void){return p->IDR;}', 'gpio.read')['accepted']


def test_clock_setting_is_not_gate_enable(tmp_path):
    assert not guard(tmp_path, 'SysCtlClockSet', 'void SysCtlClockSet(int x){p->RCC=x;}', 'clock.enable')['accepted']


def test_canonical_function_pointer_and_target_scope():
    assert canonical('void (*handler)(void)') == 'void(*)(void)'
    assert public_scope('stm32f4-stdperiph', 'clock.enable', {'file': 'a/stm32f4xx_rcc.c', 'name': 'RCC_AHB1PeriphClockCmd'})
    assert not public_scope('stm32f4-stdperiph', 'clock.enable', {'file': 'a/stm32f4xx_rcc.c', 'name': 'RCC_APB2PeriphClockCmd'})


def test_scope_fixed_before_runtime():
    rows = []
    for cohort in ['revision-r1-replacements', 'revision-r1-expanded']:
        rows += json.loads((PUBLIC / 'config' / cohort / 'operation-scope.json').read_text())['rows']
    assert len(rows) == 95 and sum(r['eligible'] for r in rows) == 91
    assert len({r['sdk'] for r in rows}) == 5


def test_model_and_feature_schema_are_frozen():
    data = json.loads((PUBLIC / 'model-contract.json').read_text())
    assert data['source_dimension'] == 83 and len(data['deployment_feature_names']) == 91
    assert not data['new_retrained_models_in_this_release']


def test_expected_runtime_results_keep_failures():
    data = json.loads((PUBLIC / 'expected-integration-results.json').read_text())
    assert data['operation_outcomes'] == {'pass': 168, 'fail': 14}
    assert len(data['configurations']) == 10
    assert sum(r['boots'] for r in data['configurations']) == 100
    assert not data['new_runtime_measurements_in_this_publication']


def test_frozen_metric_checker_rejects_changed_values():
    equal({'value': .8}, {'value': .8})
    with pytest.raises(ValueError):
        equal({'value': .9}, {'value': .8})


def test_current_evaluator_does_not_relabel_or_train():
    spec = importlib.util.spec_from_file_location('current_audit', PUBLIC / 'audit_h03_evaluation.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.metrics(['a', 'b'], {'a': 3, 'missing': 2})['recall_at_5'] == .5
    assert module.metrics(['a', 'b'], {'a': 3, 'missing': 2}, 3)['recall_at_5'] == 1
