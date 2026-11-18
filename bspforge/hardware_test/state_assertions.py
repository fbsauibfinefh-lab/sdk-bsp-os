"""对补测观察量实施状态断言；不生成观察、不替代设备端探针或真实性核查。"""
from __future__ import annotations

import argparse
from pathlib import Path
from statistics import median
from typing import Any

from bspforge.common import read_json, write_json


FIELDS = {
    'clock-gate': ('before', 'disabled', 'restored', 'access_after_restore'),
    'irq-mask-restore': ('before', 'after_trigger', 'after_masked_trigger', 'after_restored_trigger', 'pending_cleared'),
    'timer-stop-restart-update': ('before_stop', 'after_stop_wait', 'after_restart', 'stop_wait_ms', 'old_period_ms', 'requested_period_ms', 'measured_periods_ms', 'relative_tolerance'),
    'gpio-direction': ('output_low_read', 'output_high_read', 'input_mode_readback', 'output_mode_restored'),
}


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    name=case.get('case')
    if name not in FIELDS:
        return {'case':name,'status':'unverified','reason':'unknown assertion; not counted as pass'}
    observations=case.get('observations') or {}
    missing=[key for key in FIELDS[name] if observations.get(key) is None]
    provenance=case.get('provenance') or {}
    missing += ['provenance.'+key for key in ('firmware_sha256','raw_trace_path','request_id') if not provenance.get(key)]
    if missing:
        return {'case':name,'status':'unverified','missing':missing}
    o=observations
    try:
        if name=='clock-gate':
            checks={'initially_enabled':o['before']==1,'disabled_readback':o['disabled']==0,'restored_readback':o['restored']==1,'access_restored':o['access_after_restore'] is True}
        elif name=='irq-mask-restore':
            checks={'trigger_increased_count':o['after_trigger']>o['before'],'masked_no_increment':o['after_masked_trigger']==o['after_trigger'],'restored_increased_count':o['after_restored_trigger']>o['after_masked_trigger'],'pending_cleared':o['pending_cleared'] is True}
        elif name=='gpio-direction':
            checks={'low':o['output_low_read']==0,'high':o['output_high_read']==1,'input_mode':o['input_mode_readback']=='input','output_restored':o['output_mode_restored'] is True}
        else:
            periods=o['measured_periods_ms']
            checks={'stopped_no_increment':o['after_stop_wait']==o['before_stop'],'wait_exceeds_two_periods':o['old_period_ms']>0 and o['stop_wait_ms']>2*o['old_period_ms'],'restart_progress':o['after_restart']>o['after_stop_wait'],'at_least_three_intervals':len(periods)>=3,'period_tolerance':o['requested_period_ms']>0 and 0<=o['relative_tolerance']<=.25 and bool(periods) and abs(median(periods)-o['requested_period_ms'])<=o['relative_tolerance']*o['requested_period_ms']}
        return {'case':name,'status':'pass' if all(checks.values()) else 'fail','checks':checks,'evidence_authenticity_verified':False}
    except (TypeError,ValueError):
        return {'case':name,'status':'unverified','reason':'invalid observation types'}


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    data=read_json(a.input)
    rows=[evaluate_case(c) for c in data['cases']]
    write_json(a.output,{'cases':rows,'summary':{status:sum(r['status']==status for r in rows) for status in ('pass','fail','unverified')},'note':'Offline assertion checking only; no hardware commands executed and no authenticity claim.'})
    return 0 if all(r['status']=='pass' for r in rows) and rows else 1


if __name__=='__main__':
    raise SystemExit(main())
