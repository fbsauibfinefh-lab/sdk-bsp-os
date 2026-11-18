from bspforge.build_diagnoser import BuildDiagnoser
from bspforge.closure_solver import ClosureSolver
from bspforge.hardware_test.host import HardwareTestRunner
from scripts.record_engineering_session import summarize


def fixture():
    return {
        'sdk': {'id': 'fixture', 'digest': 'frozen', 'root': '/tmp/sdk'},
        'files': [
            {'id': 'a', 'path': 'arm/a.c', 'kind': 'source', 'asset_metadata': {'architectures': ['arm']}},
            {'id': 'b', 'path': 'riscv/b.c', 'kind': 'source', 'asset_metadata': {'architectures': ['riscv']}},
        ],
        'functions': [
            {'id': 'fa', 'name': 'provider', 'file': 'arm/a.c', 'signature': 'int provider(void)'},
            {'id': 'fb', 'name': 'provider', 'file': 'riscv/b.c', 'signature': 'int provider(void)'},
        ],
        'edges': [], 'build_rules': [],
    }


def test_diagnoser_rejects_ambiguous_providers():
    ir = fixture()
    diagnosis = BuildDiagnoser().diagnose("undefined reference to `provider'", 1)
    proposal = BuildDiagnoser().propose_repairs(ir, diagnosis, {'selected_files': []})
    assert not proposal['repairs']
    assert proposal['unresolved'][0]['risk'] == 'manual'


def test_diagnoser_uses_unique_target_compatible_provider():
    ir = fixture()
    diagnosis = BuildDiagnoser().diagnose("undefined reference to `provider'", 1)
    proposal = BuildDiagnoser().propose_repairs(ir, diagnosis, {'selected_files': [], 'target_context': {'architecture': 'arm'}})
    assert [r['path'] for r in proposal['repairs']] == ['arm/a.c']


def test_diagnoser_rejects_ambiguous_headers():
    ir = fixture()
    ir['files'] += [{'id': 'h1', 'path': 'a/config.h', 'kind': 'header'}, {'id': 'h2', 'path': 'b/config.h', 'kind': 'header'}]
    diagnosis = BuildDiagnoser().diagnose('fatal error: config.h: No such file or directory', 1)
    proposal = BuildDiagnoser().propose_repairs(ir, diagnosis, {'selected_files': []})
    assert not proposal['repairs']


def test_component_baseline_does_not_follow_calls_or_include_other_architecture():
    ir = fixture()
    closure = ClosureSolver().solve(ir, {'mappings': []}, {'architecture': 'arm'}, strategy='target-components', component_roots=['arm'])
    assert closure['repair_sources'] == ['arm/a.c']
    assert not closure['seed_entities']
    assert closure['strategy'] == 'target-components'


def test_component_baseline_rejects_escaping_paths():
    import pytest
    with pytest.raises(ValueError):
        ClosureSolver().solve(fixture(), {'mappings': []}, {'architecture': 'arm'}, strategy='target-components', component_roots=['../outside'])


def test_engineering_timer_counts_only_closed_nonoverlapping_intervals():
    result = summarize([
        {'time': '2026-11-11T00:00:00+00:00', 'mode': 'active'},
        {'time': '2026-11-11T00:01:00+00:00', 'mode': 'wait'},
        {'time': '2026-11-11T00:03:00+00:00', 'mode': 'pause'},
        {'time': '2026-11-11T00:05:00+00:00', 'mode': 'finish'},
    ])
    assert result['closed_intervals_seconds'] == {'active': 60., 'wait': 120.}
    assert result['completed']


def test_engineering_timer_never_invents_an_open_interval():
    assert summarize([{'time':'2026-11-11T00:00:00+00:00','mode':'active'}])['closed_intervals_seconds']['active'] == 0


def test_engineering_primary_excludes_validation_and_repair():
    result=summarize([
        {'time':'2026-11-13T00:00:00+00:00','mode':'active','stage':'initial-build'},
        {'time':'2026-11-13T00:01:00+00:00','mode':'wait','stage':'initial-build'},
        {'time':'2026-11-13T00:03:00+00:00','mode':'active','stage':'first-validation','milestone':'first-build'},
        {'time':'2026-11-13T00:04:00+00:00','mode':'active','stage':'repair'},
        {'time':'2026-11-13T00:06:00+00:00','mode':'finish','stage':'repair','milestone':'accepted'},
    ])
    assert result['primary_first_build_active_seconds']==60
    assert result['primary_first_build_net_wall_seconds']==180
    assert result['secondary_engineering_active_seconds']==180
    assert result['secondary_acceptance_net_wall_seconds']==360
    assert result['stage_seconds']['first-validation']['net_wall']==60


def test_engineering_pause_and_preparation_are_separate():
    result=summarize([
        {'time':'2026-11-13T00:00:00+00:00','mode':'active','stage':'preparation'},
        {'time':'2026-11-13T00:10:00+00:00','mode':'active','stage':'initial-build'},
        {'time':'2026-11-13T00:11:00+00:00','mode':'pause','stage':'initial-build'},
        {'time':'2026-11-13T00:21:00+00:00','mode':'finish','stage':'initial-build'},
    ])
    assert result['primary_first_build_net_wall_seconds']==60
    assert result['secondary_acceptance_net_wall_seconds']==60
    assert result['stage_seconds']['preparation']['active']==600


def test_engineering_rejects_reverse_time_even_during_pause():
    import pytest
    with pytest.raises(ValueError):summarize([
        {'time':'2026-11-13T00:01:00+00:00','mode':'pause'},
        {'time':'2026-11-13T00:00:00+00:00','mode':'finish'},
    ])


def test_wire_evidence_preserves_bytes_and_marks_retry_uncertainty():
    import base64
    import json
    class Transport:
        def __init__(self):
            self.lines=[b'{"bspforge":true,"protocol":"1.0","event":"boot"}\n']
            self.requests=[]
        def write(self,value):
            self.requests.append(value)
            if len(self.requests)>1:
                _,rid,cmd=value.decode().split()
                self.lines.append((json.dumps({'bspforge':True,'protocol':'1.0','event':'result','request_id':rid,'command':cmd,'status':'pass'})+'\n').encode())
            return len(value)
        def readline(self):
            return self.lines.pop(0) if self.lines else b''
    transport=Transport()
    report=HardwareTestRunner(transport,'fixture','zephyr',timeout=.001,command_retries=1).run(commands=['gpio.toggle'])
    command=report['rounds'][0]['commands'][0]
    assert command['execution_multiplicity_unknown']
    assert not command['first_attempt_response_received']
    assert report['summary']['first_attempt_responses']==0
    transmitted=[base64.b64decode(e['bytes_base64']) for e in report['wire_trace'] if e['direction']=='tx']
    assert transmitted==transport.requests


def test_runtime_metrics_distinguish_hit_from_relevant_set_recall():
    from scripts.evaluate_frozen_operation_bundle import operation_metrics
    metrics=operation_metrics(['a','x','y'], {'a':3,'b':2})
    assert metrics['hit_at_5']==1
    assert metrics['recall_at_5']==.5


def test_state_assertions_do_not_pass_without_measured_observations():
    from bspforge.hardware_test.state_assertions import evaluate_case
    assert evaluate_case({'case':'clock-gate','observations':{}})['status']=='unverified'


def test_state_assertions_reject_extra_masked_interrupts():
    from bspforge.hardware_test.state_assertions import evaluate_case
    case={'case':'irq-mask-restore','observations':{'before':0,'after_trigger':1,'after_masked_trigger':2,'after_restored_trigger':3,'pending_cleared':True},'provenance':{'firmware_sha256':'fixture','raw_trace_path':'fixture','request_id':'fixture'}}
    result=evaluate_case(case)
    assert result['status']=='fail'
    assert not result['checks']['masked_no_increment']


def test_state_assertions_require_stop_and_update_not_just_final_count():
    from bspforge.hardware_test.state_assertions import evaluate_case
    case={'case':'timer-stop-restart-update','observations':{'before_stop':3,'after_stop_wait':3,'after_restart':5,'stop_wait_ms':31,'old_period_ms':10,'requested_period_ms':20,'measured_periods_ms':[19,20,21],'relative_tolerance':.1},'provenance':{'firmware_sha256':'fixture','raw_trace_path':'fixture','request_id':'fixture'}}
    assert evaluate_case(case)['status']=='pass'
    case['observations']['after_stop_wait']=4
    assert evaluate_case(case)['status']=='fail'


def test_state_assertions_never_claim_hardware_authenticity():
    from bspforge.hardware_test.state_assertions import evaluate_case
    result=evaluate_case({'case':'clock-gate','observations':{'before':1,'disabled':0,'restored':1,'access_after_restore':True},'provenance':{'firmware_sha256':'fixture','raw_trace_path':'fixture','request_id':'fixture'}})
    assert result['status']=='pass'
    assert not result['evidence_authenticity_verified']
